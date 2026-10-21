"""The gate's checks of the shipmill@shipmill plugin its sessions load (spec 031, D-44).

On every launch the gate reads the install a session in its checkout would load (loaded())
and reports, never pauses on, each install that lags the latest release (the marketplace
entry's ref), an install keyed on its linked worktree that no session loads, its own CLI when
it lags, and a config whose `requires` the version sessions load doesn't meet, each with its
fix. The one hold is PyPI answering 404 for the version sessions load (pypi()). The gate never
changes an install: `[agents] plugin_update` is deprecated and ignored (S-031-21).
"""

import enum
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.notify import Notifier, NotifyFailed
from shipmill.requires import FILE as CONFIG_FILE
from shipmill.requires import Requires
from shipmill.version import Version

PLUGIN = "shipmill@shipmill"  # the Claude Code plugin, in its marketplace
MARKETPLACE = PLUGIN.partition("@")[2]  # the marketplace Claude Code installs the plugin from
# Claude Code updates a plugin from its local copy of the marketplace, which it may not have
# refreshed since the release: `claude plugin update` alone then leaves the install behind (#477)
REFRESH = ["claude", "plugin", "marketplace", "update", MARKETPLACE]
SHIPMILL_REPO = "shipmill/shipmill"  # where shipmill releases
# The latest release is the marketplace's (spec 031): the ref its entry names on the default
# branch, which the release's stamp moves with plugin.json; never `gh release view`
MARKETPLACE_FILE = ".claude-plugin/marketplace.json"
READ_MARKETPLACE = [
    "gh",
    "api",
    "-H",
    "Accept: application/vnd.github.raw+json",
    f"repos/{SHIPMILL_REPO}/contents/{MARKETPLACE_FILE}",
]
RELEASE_REF = re.compile(r"^v\d+\.\d+\.\d+$")
# where Claude Code keeps each version of the plugin's files, under the home folder (docs/install.md)
CACHE = Path(".claude") / "plugins" / "cache" / "shipmill" / "shipmill"
# Claude Code's record of every install, which shipmill reads through `claude plugin list` and
# never writes (spec 031): an install keyed on a linked worktree is removed there by hand
INSTALLED = "~/.claude/plugins/installed_plugins.json"
PYPI = "https://pypi.org/pypi/shipmill/{version}/json"  # a release's JSON on PyPI, 404 until it is uploaded
CLI_RECORD = "cli.json"  # the gate's own CLI version, under its state directory, for doctor and status
MARKERS = Path(".cache") / "shipmill" / "plugin"  # one <version>.notified per release, under the home folder

Runner = Callable[[list[str], Path], str]  # (command, cwd) -> its stdout; ReleaseError when it fails
Fetch = Callable[[str], int]  # GET a URL -> its HTTP status; ReleaseError when no answer comes back


def marketplace_release(text: str) -> Version:
    """The latest release: the ref of the marketplace entry for the plugin, from the text of
    shipmill/shipmill's .claude-plugin/marketplace.json. An entry whose source isn't a github
    object with a ref vX.Y.Z is refused, naming the file and the entry (S-031-2)"""
    where = f"{SHIPMILL_REPO}:{MARKETPLACE_FILE}"
    name = PLUGIN.partition("@")[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"{where} is not JSON: {exc}") from None
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        raise ReleaseError(f"{where} has no plugins list")
    found = [p for p in plugins if isinstance(p, dict) and p.get("name") == name]
    if len(found) != 1:
        raise ReleaseError(f"{where} lists the plugin {name!r} {len(found)} times, want exactly 1")
    source = found[0].get("source")
    ref = source.get("ref") if isinstance(source, dict) and source.get("source") == "github" else None
    if not isinstance(ref, str) or not RELEASE_REF.match(ref):
        raise ReleaseError(
            f"{where}: the plugins entry {name!r} has source {json.dumps(source)},"
            ' not {"source": "github", "repo": ..., "ref": "vX.Y.Z"}'
        )
    return Version.of_tag(ref)


def latest_release(run: Runner, cwd: Path) -> Version:
    """The latest release, read from the marketplace on shipmill/shipmill's default branch"""
    return marketplace_release(run(READ_MARKETPLACE, cwd))


class Scope(enum.StrEnum):
    """The scopes `claude plugin list --json` gives a marketplace install"""

    LOCAL = "local"
    PROJECT = "project"
    USER = "user"
    MANAGED = "managed"

    @property
    def keyed(self) -> bool:
        """Claude Code keys a local or project install on a folder, its projectPath"""
        return self in (Scope.LOCAL, Scope.PROJECT)


# The install a session loads (D-35): the one at the most specific scope the plugin is
# installed at for the session's project, local, then project, then user, then managed. This
# is the order Claude Code's plugin docs give for `claude plugin update` without --scope
# ("the most specific scope it's installed at for your current project"), and the order its
# settings precedence gives enabledPlugins (local over project over user). A session's project
# is its folder, except in a linked git worktree, where it is the worktree's main checkout:
# `claude plugin details` in the gate's linked worktree showed the main checkout's install
# (#198), and `claude plugin update --scope local` run there changed the main checkout's
# install, not the one keyed on the worktree (#417). So an install keyed on a linked worktree's
# own folder is never the one its sessions load, and an install keyed on an enclosing folder
# that isn't the main checkout doesn't apply either.
PRECEDENCE = (Scope.LOCAL, Scope.PROJECT, Scope.USER, Scope.MANAGED)


@dataclass(frozen=True, slots=True)
class Listed:
    """One install of the plugin: its scope, the folder it is keyed on (None at user and
    managed scope), its version, and the folder its files are in when the listing names it
    (installPath; None when it doesn't)"""

    scope: Scope
    folder: Path | None
    version: Version
    path: Path | None = None

    def files(self, home: Path) -> Path:
        """The folder holding the install's files, whose hooks/ a session runs: the listing's
        installPath, else Claude Code's cache folder for its version under home"""
        if self.path is not None:
            return self.path
        return home / CACHE / str(self.version)

    def where(self) -> str:
        return f"{self.scope} scope" if self.folder is None else f"{self.scope} scope, keyed on {self.folder}"


def listed_installs(text: str) -> list[Listed]:
    """Every install of the plugin from `claude plugin list --json`, at any scope, each keyed
    install's folder resolved. Anything but the documented shape is refused"""
    try:
        entries = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"claude plugin list --json printed no JSON: {exc}") from None
    if not isinstance(entries, list):
        raise ReleaseError("claude plugin list --json: expected a JSON array")
    found = []
    for e in entries:
        if not isinstance(e, dict):
            raise ReleaseError(f"claude plugin list --json: an install is {e!r}, not an object")
        if e.get("id") != PLUGIN:
            continue
        scope, version = e.get("scope"), e.get("version")
        if not isinstance(scope, str) or scope not in set(Scope) or not isinstance(version, str):
            raise ReleaseError(f"claude plugin list --json: {PLUGIN} install {e!r}")
        where = e.get("projectPath")
        folder = None
        if Scope(scope).keyed:
            if not isinstance(where, str):
                raise ReleaseError(f"claude plugin list --json: {PLUGIN} {scope} install has no projectPath: {e!r}")
            folder = Path(where).resolve()
        files = e.get("installPath")
        if files is not None and not isinstance(files, str):
            raise ReleaseError(f"claude plugin list --json: {PLUGIN} {scope} install's installPath is {files!r}")
        found.append(Listed(Scope(scope), folder, Version.parse(version), None if files is None else Path(files)))
    return found


def session_project(checkout: Path, common_dir: str) -> Path:
    """The project Claude Code loads a session in the checkout as: a linked worktree's main
    checkout, given `git rev-parse --path-format=absolute --git-common-dir`; the checkout itself
    otherwise (a main checkout's common dir is its own .git)"""
    common = Path(common_dir.strip())
    return common.parent.resolve() if common.name == ".git" else checkout.resolve()


def effective(installs: list[Listed], project: Path) -> Listed | None:
    """The install a session in the project loads, by PRECEDENCE; None when none applies. Two
    installs at the scope that decides are refused, never guessed between"""
    for scope in PRECEDENCE:
        found = [i for i in installs if i.scope is scope and (i.folder is None or i.folder == project)]
        if len(found) > 1:
            raise ReleaseError(f"claude plugin list --json lists {PLUGIN} twice at {scope} scope for {project}")
        if found:
            return found[0]
    return None


def update_command(install: Listed, installs: list[Listed]) -> str:
    """The command that updates one install, run in its folder: github-ship-watch's fix for
    the same install (watch_state.py's plugin_fix). `claude plugin update` run in a folder picks
    an install at the same scope keyed on a folder nested in it (#233, a Claude Code bug), so
    with one nested the fix reinstalls the folder's own at that scope instead. Either way it
    refreshes the marketplace first (#477); that isn't folder-specific, so it runs there too"""
    refresh = " ".join(REFRESH)
    update = f"{refresh} && claude plugin update {PLUGIN} --scope {install.scope}"
    if install.folder is None:
        return update
    top = install.folder
    nested = sorted(
        i.folder for i in installs if i.scope is install.scope and i.folder is not None and top in i.folder.parents
    )
    if not nested:
        return f"in {top}: {update}"
    scope = install.scope
    again = (
        f"{refresh} && claude plugin uninstall {PLUGIN} --scope {scope}"
        f" && claude plugin install {PLUGIN} --scope {scope}"
    )
    return f"in {top}: {again} (`update` picks the nested install in {nested[0]}, a Claude Code bug)"


REPORTED = (Scope.LOCAL, Scope.PROJECT, Scope.USER)  # the scopes a person updates an install at


def unloaded_fix(folder: Path) -> str:
    """S-031-16: the fix for an install keyed on a linked worktree: no `claude plugin` command
    run there reaches it, and shipmill never edits Claude Code's file"""
    return f'delete the entry with "projectPath": "{folder}" under "{PLUGIN}" in {INSTALLED}'


def install_record(install: Listed, fix: str) -> dict[str, object]:
    folder = None if install.folder is None else str(install.folder)
    return {"scope": str(install.scope), "folder": folder, "version": str(install.version), "fix": fix}


@dataclass(frozen=True, slots=True)
class Lag:
    """S-031-13: an install that applies to the gate's checkout, older than the latest release,
    with the command that updates it"""

    install: Listed
    latest: Version
    fix: str

    def line(self) -> str:
        return (
            f"plugin: {PLUGIN} {self.install.version} ({self.install.where()}) lags the latest release"
            f" {self.latest}; the session starts; update it: {self.fix}"
        )


@dataclass(frozen=True, slots=True)
class GateCli:
    """S-031-17: the gate's own shipmill and how to bring it to the latest release"""

    version: Version
    fix: str

    def lags(self, latest: Version) -> bool:
        return self.version < latest

    def line(self, latest: Version) -> str:
        return f"the gate's CLI, shipmill {self.version}, lags the latest release {latest}: {self.fix}"


@dataclass(frozen=True, slots=True)
class Loaded:
    """Spec 031: the install a session in the gate's checkout would load (None: none applies)
    against the latest release (None when it wasn't read); each install that applies and lags
    it, each install keyed on the gate's linked worktree, which no session loads, the gate's
    CLI when it lags, and the config's requires when the version sessions load doesn't meet
    it, with its fix; or the failure that stopped the read. None of them holds a session"""

    project: Path
    install: Listed | None
    latest: Version | None
    lags: tuple[Lag, ...] = ()
    unloaded: tuple[Listed, ...] = ()
    cli: GateCli | None = None
    bound: Requires | None = None
    bound_fix: str | None = None
    error: str | None = None

    def lines(self) -> list[str]:
        """The tick's lines: a failed read, no install that applies, then each finding with its
        fix; a current install says nothing"""
        if self.error is not None:
            return [f"plugin check failed, the session starts anyway: {self.error}"]
        lines = []
        if self.install is None:
            lines.append(f"plugin: no {PLUGIN} install applies to {self.project}; the session loads no shipmill skills")
        lines += [lag.line() for lag in self.lags]
        lines += [
            f"plugin: {PLUGIN} {i.version} ({i.where()}) is keyed on the gate's linked worktree, which no session"
            f" loads; {unloaded_fix(i.folder)}"
            for i in self.unloaded
            if i.folder is not None
        ]
        if self.cli is not None and self.latest is not None:
            lines.append(self.cli.line(self.latest))
        if self.bound is not None and self.install is not None:
            lines.append(
                f"plugin: {CONFIG_FILE} requires shipmill {self.bound}, but sessions here load {PLUGIN}"
                f" {self.install.version} ({self.install.where()}), whose shipmill commands refuse the config;"
                f" the session starts; fix: {self.bound_fix}"
            )
        return lines

    def record(self) -> dict[str, object]:
        install = self.install
        return {
            "project": str(self.project),
            "scope": None if install is None else str(install.scope),
            "folder": None if install is None or install.folder is None else str(install.folder),
            "version": None if install is None else str(install.version),
            "latest": None if self.latest is None else str(self.latest),
            "lags": [install_record(lag.install, lag.fix) for lag in self.lags],
            "unloaded": [install_record(i, unloaded_fix(i.folder)) for i in self.unloaded if i.folder is not None],
            "cli": None if self.cli is None else {"version": str(self.cli.version), "fix": self.cli.fix},
            "requires": None if self.bound is None else {"bound": str(self.bound), "fix": self.bound_fix},
            "error": self.error,
        }


def requires_fix(bound: Requires, install: Listed, installs: list[Listed], latest: Version) -> str:
    """S-031-19: update the install sessions load when the latest release meets the bound, else
    release one that does; or lower the bound"""
    lower = f"or lower requires in {CONFIG_FILE}"
    if bound.met(latest):
        return f"{update_command(install, installs)}; {lower}"
    return f"release shipmill {bound.floor[0]}.{bound.floor[1]}.{bound.floor[2]} or later, {lower}"


def loaded(checkout: Path, project: Path, run: Runner, cli: GateCli | None, bound: Requires | None) -> Loaded:
    """Spec 031: read the installs, the one a session in the checkout (Claude Code's project
    `project`) would load, and the latest release, and find what lags it. A failed read is
    returned as the error, for the tick to report"""
    try:
        installs = listed_installs(run(["claude", "plugin", "list", "--json"], checkout))
        found = effective(installs, project)
        latest = latest_release(run, checkout)
    except ReleaseError as exc:
        return Loaded(project, None, None, error=str(exc))
    applies = sorted(
        (i for i in installs if i.scope in REPORTED and (i.folder is None or i.folder == project)),
        key=lambda i: PRECEDENCE.index(i.scope),
    )
    lags = tuple(Lag(i, latest, update_command(i, installs)) for i in applies if i.version < latest)
    here = checkout.resolve()  # the gate's --repo may be relative; Claude Code records an absolute path
    unloaded = () if here == project else tuple(i for i in installs if i.folder == here)
    unmet = bound if bound is not None and found is not None and not bound.met(found.version) else None
    fix = None if unmet is None or found is None else requires_fix(unmet, found, installs, latest)
    lagging = cli if cli is not None and cli.lags(latest) else None
    return Loaded(project, found, latest, lags, unloaded, lagging, unmet, fix)


@dataclass(frozen=True, slots=True)
class PyPI:
    """S-031-24: PyPI's answer for the version sessions load: its HTTP status, or why none came"""

    version: Version
    status: int | None
    error: str | None = None

    @property
    def url(self) -> str:
        return PYPI.format(version=self.version)

    @property
    def waits(self) -> bool:
        """404: the release's tag moved before publish uploaded it, so its pinned CLI can't run yet"""
        return self.status == 404

    def reason(self) -> str:
        return f"plugin {self.version} waits for PyPI: {self.url} answers 404; no session starts, the next tick retries"

    def lines(self) -> list[str]:
        if self.status == 200 or self.waits:
            return []
        if self.status is None:
            return [f"plugin {self.version}: PyPI didn't answer ({self.error}); the session starts anyway"]
        return [f"plugin {self.version}: PyPI answered {self.status} for {self.url}; the session starts anyway"]

    def record(self) -> dict[str, object]:
        return {"version": str(self.version), "status": self.status, "error": self.error}


def publish_fix(version: Version) -> str:
    """#569: the fix for a version PyPI doesn't serve: its publish run, else a new one"""
    tag = f"v{version}"
    return (
        f"check the publish.yml run for {tag}: gh run list --repo {SHIPMILL_REPO} --workflow publish.yml;"
        f" if none passed, publish it: gh workflow run publish.yml --repo {SHIPMILL_REPO} -f tag={tag}"
    )


def pypi(version: Version, fetch: Fetch) -> PyPI:
    try:
        return PyPI(version, fetch(PYPI.format(version=version)))
    except ReleaseError as exc:
        return PyPI(version, None, str(exc))


def notify_lags(found: Loaded, markers: Path, notifier: Notifier, dry_run: bool) -> str | None:
    """S-031-20: one desktop notification per release on the host, naming each lagging install
    and its fix: the first tick to create <markers>/<latest>.notified, an exclusive create, sends
    it, so several gates send one. None when nothing lags or the marker was there; a dry run
    creates and sends nothing"""
    if not found.lags or found.latest is None:
        return None
    marker = markers / f"{found.latest}.notified"
    if dry_run:
        return None if marker.exists() else f"would notify: {PLUGIN} lags {found.latest}"
    markers.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8"):
            pass
    except FileExistsError:
        return None
    body = "; ".join(f"{lag.install.version} ({lag.install.where()}): {lag.fix}" for lag in found.lags)
    try:
        notifier.send(f"shipmill {found.latest} is out", f"update {PLUGIN}: {body}")
    except NotifyFailed as exc:
        return f"notify failed: {exc}"
    return f"notified: {PLUGIN} lags {found.latest}"


def save_cli(path: Path, version: Version) -> None:
    """The gate's own CLI version, for doctor and status to compare with the latest release"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": str(version)}) + "\n", encoding="utf-8")


def load_cli(path: Path) -> Version | None:
    """The version the gate last ran as; None before a gate wrote one. A malformed file fails"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"{path} is malformed: {exc}") from None
    if not isinstance(data, dict) or set(data) != {"version"} or not isinstance(data["version"], str):
        raise ReleaseError(f'{path} is malformed: expected {{"version": "X.Y.Z"}}')
    return Version.parse(data["version"])


@dataclass(frozen=True, slots=True)
class PluginHost:
    """What the gate reads the plugin with: the commands (`claude plugin`, the marketplace's `gh
    api` read), its own CLI, PyPI, the folder of the notification markers, and the config's
    requires"""

    run: Runner
    cli: GateCli
    fetch: Fetch
    markers: Path
    bound: Callable[[], Requires | None]
