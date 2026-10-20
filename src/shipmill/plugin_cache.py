"""The plugin a gate session loads: the latest release, from a versioned cache (spec 031, D-43).

On every tick that would launch, the gate reads the latest release from the marketplace
(plugin.latest_release), checks PyPI serves it, since the plugin's commands run `uvx
shipmill==<version>`, and materializes it once into `<cache>/<version>/`, the cache being
`$XDG_CACHE_HOME/shipmill/plugin/` (`~/.cache` when XDG_CACHE_HOME is unset or empty): a
shallow clone of the tag into a temporary folder beside it (`.tmp-<random>`), its
`.claude-plugin/plugin.json` checked to hold the version, its `.git` removed, then renamed.
A folder that exists is never written again; when another gate on the host renamed its copy
first, the tick deletes its own temporary folder and uses the existing one.

A folder is only ever renamed into the cache after PyPI answered 200 for its version, so
every version in the cache is one PyPI serves. While PyPI answers 404 for the latest, the
session loads the newest cached version older than it. Any other failure (the marketplace
read, a PyPI answer other than 200 or 404, the clone, the version check, or an existing
folder whose plugin.json doesn't hold its name) falls back to the newest cached version and
reports the failure; with none cached, nothing is usable and the tick starts no session.
"""

import enum
import errno
import http.client
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.plugin import MARKETPLACE_FILE, READ_MARKETPLACE, SHIPMILL_REPO, Runner, latest_release
from shipmill.version import Version

CLONE_URL = f"https://github.com/{SHIPMILL_REPO}"
PYPI_URL = "https://pypi.org/pypi/shipmill/{version}/json"
TEMP = ".tmp-"  # a temporary folder's prefix, beside the version folders
MANIFEST = Path(".claude-plugin") / "plugin.json"
RELEASE = re.compile(r"^\d+\.\d+\.\d+$")  # a version folder's name
TIMEOUT = 30  # seconds for PyPI's answer

PyPI = Callable[[str], int]  # a URL -> the HTTP status PyPI answers; ReleaseError when it answers none


def cache_root(environ: Mapping[str, str], home: Path) -> Path:
    """`$XDG_CACHE_HOME/shipmill/plugin`, `~/.cache` when XDG_CACHE_HOME is unset or empty"""
    base = environ.get("XDG_CACHE_HOME", "")
    folder = Path(base) if base else home / ".cache"
    if not folder.is_absolute():
        raise ReleaseError(f"XDG_CACHE_HOME must be an absolute path, got {base!r}")
    return folder / "shipmill" / "plugin"


def pypi_status(url: str) -> int:
    """The status PyPI answers for url; ReleaseError when it can't be reached"""
    request = urllib.request.Request(url, headers={"User-Agent": "shipmill-gate"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as exc:  # 4xx and 5xx: an answer
        exc.close()
        return int(exc.code)
    except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts are OSErrors
        raise ReleaseError(f"{url} is unreachable: {getattr(exc, 'reason', exc)}") from None


class Step(enum.StrEnum):
    """What failed on the way to the latest release's folder"""

    MARKETPLACE = "the marketplace read"
    PYPI = "the PyPI read"
    CLONE = "the clone"
    CHECK = "the version check"


AGAIN = "the next tick tries again"


@dataclass(frozen=True, slots=True)
class Failure:
    step: Step
    error: str
    fix: str

    def line(self) -> str:
        return f"{self.step} failed: {self.error}; fix: {self.fix}"

    def record(self) -> dict[str, str]:
        return {"step": self.step.name.lower(), "error": self.error, "fix": self.fix}


class Failed(Exception):
    """A step of the materialization failed"""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.line())
        self.failure = failure


@dataclass(frozen=True, slots=True)
class PluginDir:
    """What a tick that would launch found in the cache root: the latest release (None when
    the marketplace read failed), the version sessions load and its folder (both None when no
    version is usable), whether this tick cloned it, whether the latest waits for PyPI, and
    the failure, if any"""

    root: Path
    latest: Version | None
    version: Version | None
    folder: Path | None
    cloned: bool = False
    waits: bool = False
    failure: Failure | None = None

    def __post_init__(self) -> None:
        if (self.version is None) != (self.folder is None):
            raise ReleaseError("a plugin folder needs its version, and a version its folder")
        if self.folder is None and self.failure is None:
            raise ReleaseError("no plugin folder is usable, but no failure says why")

    def reason(self) -> str:
        """A PLUGIN_FAILED tick's reason: the step, its error, and its fix"""
        if self.failure is None or self.folder is not None:
            raise ReleaseError("a plugin folder is usable, so no tick fails on it")
        f = self.failure
        return (
            f"{f.step} failed: {f.error}; the cache {self.root} holds no version PyPI serves,"
            f" so no session starts: {f.fix}"
        )

    def lines(self) -> list[str]:
        """The tick's lines when a session starts: the latest waiting for PyPI, a failure the
        session starts despite, or a version this tick cached; a cached latest says nothing"""
        lines = []
        if self.waits:
            lines.append(f"plugin: {self.latest} waits for PyPI; sessions load {self.version}")
        if self.failure is not None and self.folder is not None:
            lines.append(f"plugin: {self.failure.step} failed, sessions load {self.version}: {self.failure.line()}")
        if self.cloned:
            lines.append(f"plugin: cached {self.version} in {self.folder}")
        return lines

    def record(self) -> dict[str, object]:
        return {
            "latest": None if self.latest is None else str(self.latest),
            "version": None if self.version is None else str(self.version),
            "folder": None if self.folder is None else str(self.folder),
            "cloned": self.cloned,
            "waits_for_pypi": self.waits,
            "failure": None if self.failure is None else self.failure.record(),
        }


def manifest_version(folder: Path) -> Version:
    """The version a plugin folder's .claude-plugin/plugin.json holds; ReleaseError naming the
    file when it is missing, not JSON, or holds no X.Y.Z version"""
    path = folder / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ReleaseError(f"{path} is missing") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"{path} is not JSON: {exc}") from None
    found = data.get("version") if isinstance(data, dict) else None
    if not isinstance(found, str) or not RELEASE.match(found):
        raise ReleaseError(f"{path} holds no X.Y.Z version: {found!r}")
    return Version.parse(found)


def mismatch(folder: Path, want: str) -> str | None:
    """Why the folder's plugin.json doesn't hold want; None when it does"""
    try:
        found = str(manifest_version(folder))
    except ReleaseError as exc:
        return str(exc)
    return None if found == want else f"{folder / MANIFEST} holds {found}"


def check_cached(folder: Path) -> None:
    """An existing version folder's plugin.json must hold its name; else a failure naming it"""
    said = mismatch(folder, folder.name)
    if said is not None:
        error = f"the cache folder {folder} doesn't hold {folder.name}: {said}"
        raise Failed(Failure(Step.CHECK, error, f"rm -rf {folder}"))


def newest(root: Path, below: Version | None = None) -> Version | None:
    """The newest version in the cache whose plugin.json holds its name, older than below when
    given; None when there is none"""
    if not root.is_dir():
        return None
    found = [
        Version.parse(p.name)
        for p in root.iterdir()
        if RELEASE.match(p.name) and p.is_dir() and mismatch(p, p.name) is None
    ]
    usable = [v for v in found if below is None or v < below]
    return max(usable, default=None)


def materialize(root: Path, version: Version, run: Runner) -> tuple[Path, bool]:
    """The version's folder in the cache, and whether this call cloned it. Failed names the
    step that failed; the temporary folder never outlives the call"""
    folder = root / str(version)
    if folder.exists():
        check_cached(folder)
        return folder, False
    root.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=TEMP, dir=root))
    try:
        clone = ["git", "clone", "--quiet", "--depth", "1", "--branch", version.tag, CLONE_URL, str(temp)]
        try:
            run(clone, root)
        except ReleaseError as exc:
            reach = f"check that this host reaches {CLONE_URL} and the tag {version.tag} exists; {AGAIN}"
            raise Failed(Failure(Step.CLONE, str(exc), reach)) from None
        said = mismatch(temp, str(version))
        if said is not None:
            report = f"the tag is broken: report it at {CLONE_URL}/issues; {AGAIN}"
            raise Failed(Failure(Step.CHECK, f"the tag {version.tag} doesn't hold {version}: {said}", report))
        shutil.rmtree(temp / ".git")
        try:
            temp.rename(folder)
        except OSError as exc:
            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            check_cached(folder)  # another gate renamed its copy first: use it
            return folder, False
        return folder, True
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def fallback(root: Path, latest: Version | None, failure: Failure) -> PluginDir:
    """The newest cached version, which PyPI serves, with the failure reported"""
    found = newest(root)
    if found is None:
        return PluginDir(root, latest, None, None, failure=failure)
    return PluginDir(root, latest, found, root / str(found), failure=failure)


def resolve(root: Path, run: Runner, cwd: Path, pypi: PyPI) -> PluginDir:
    """S-031-8..10: the folder sessions load. run reads the marketplace (`gh api`, in cwd) and
    clones the tag (`git clone`); pypi answers the status of PyPI's page for the version"""
    try:
        latest = latest_release(run, cwd)
    except ReleaseError as exc:
        shown = " ".join(READ_MARKETPLACE)
        fix = f"check that `{shown}` reads {SHIPMILL_REPO}'s {MARKETPLACE_FILE}; {AGAIN}"
        return fallback(root, None, Failure(Step.MARKETPLACE, str(exc), fix))
    url = PYPI_URL.format(version=latest)
    try:
        status = pypi(url)
    except ReleaseError as exc:
        return fallback(root, latest, Failure(Step.PYPI, str(exc), f"check that this host reaches {url}; {AGAIN}"))
    if status == 404:
        found = newest(root, below=latest)
        if found is None:
            error = f"{url} answered 404: {latest} isn't on PyPI yet, and no older version is cached"
            fix = f"wait for {latest}'s publish job to upload it; {AGAIN}"
            return PluginDir(root, latest, None, None, waits=True, failure=Failure(Step.PYPI, error, fix))
        return PluginDir(root, latest, found, root / str(found), waits=True)
    if status != 200:
        failure = Failure(Step.PYPI, f"{url} answered {status}", f"check PyPI's status; {AGAIN}")
        return fallback(root, latest, failure)
    try:
        folder, cloned = materialize(root, latest, run)
    except Failed as exc:
        return fallback(root, latest, exc.failure)
    return PluginDir(root, latest, latest, folder, cloned)
