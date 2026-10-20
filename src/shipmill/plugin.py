"""The gate's checks of the shipmill@shipmill plugin its sessions load (D-23, D-35).

Claude Code keys a project- or local-scope plugin install on a folder, so the gate's checkout
(`tmp/shipmill-gate`) can have installs of its own, apart from the repo's. With [agents]
plugin_update = true, a tick that is about to start a session checks at most once per 24
hours whether any install keyed on the checkout, at project or local scope, is behind
shipmill's latest release and, when one is, refreshes the marketplace once (`claude plugin
marketplace update shipmill`; a failure is reported and the update still tried) and updates
it with `claude plugin update --scope <its scope>` run in the checkout. Claude Code
documents no way to name the project an update acts on, so the check reads the installs
again afterwards: an install still behind, or an install keyed on another folder that the
update changed, is reported as a failure. The last
check is recorded under the repo's git directory, beside the gate's other state. A failed
check or update is reported on the tick. A user-scope install is never updated.

Then, on every launch (D-35), the gate reads the install a session in its checkout would
load (loaded()) and starts no session while that install is older than the latest release.
"""

import datetime as dt
import enum
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.version import Version

PLUGIN = "shipmill@shipmill"  # the Claude Code plugin, in its marketplace
MARKETPLACE = PLUGIN.partition("@")[2]  # the marketplace Claude Code installs the plugin from
# Claude Code updates a plugin from its local copy of the marketplace, which it may not have
# refreshed since the release: `claude plugin update` alone then leaves the install behind (#477)
REFRESH = ["claude", "plugin", "marketplace", "update", MARKETPLACE]
SHIPMILL_REPO = "shipmill/shipmill"  # where shipmill releases
CHECKED = "plugin-check.json"  # the last check's time, under the gate's state directory
EVERY = dt.timedelta(hours=24)
SCOPES = ("project", "local")  # the scopes Claude Code keys on a folder, in the order they're updated
# where Claude Code keeps each version of the plugin's files, under the home folder (docs/install.md)
CACHE = Path(".claude") / "plugins" / "cache" / "shipmill" / "shipmill"

Runner = Callable[[list[str], Path], str]  # (command, cwd) -> its stdout; ReleaseError when it fails


@dataclass(frozen=True, slots=True)
class Install:
    """One install of the plugin keyed on a folder: its scope, folder, and version"""

    scope: str
    folder: Path
    version: str


@dataclass(frozen=True, slots=True)
class PluginUpdate:
    """What a tick's check found and did: the checkout's installs as it found them (none
    without one), the latest release (None when the check failed before it read it), the
    scopes it updated and confirmed, and the failure, if any"""

    installs: tuple[Install, ...]
    latest: str | None
    updated: tuple[str, ...]
    error: str | None = None

    def lines(self) -> list[str]:
        """The tick's lines: each update, then a failure; current installs say nothing"""
        lines = [
            f"plugin updated: {PLUGIN} {i.version} -> {self.latest} in this checkout ({i.scope} scope)"
            for i in self.installs
            if i.scope in self.updated
        ]
        if self.error is not None:
            lines.append(f"plugin update failed: {self.error}")
        return lines

    def record(self) -> dict[str, object]:
        installs = [
            {"scope": i.scope, "installed": i.version, "updated": i.scope in self.updated} for i in self.installs
        ]
        return {"latest": self.latest, "installs": installs, "error": self.error}


def load_checked(path: Path) -> dt.datetime | None:
    """The last check's time; None before the first. A malformed file fails, never reads as due"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"{path} is malformed: {exc}") from None
    if not isinstance(data, dict) or set(data) != {"checked"} or not isinstance(data["checked"], str):
        raise ReleaseError(f'{path} is malformed: expected {{"checked": <ISO time>}}')
    try:
        checked = dt.datetime.fromisoformat(data["checked"])
    except ValueError:
        raise ReleaseError(f"{path} is malformed: {data['checked']!r} is not an ISO time") from None
    if checked.tzinfo is None:
        raise ReleaseError(f"{path} is malformed: {data['checked']!r} has no time zone")
    return checked


def save_checked(path: Path, now: dt.datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked": now.isoformat()}) + "\n", encoding="utf-8")


def keyed_installs(text: str) -> list[Install]:
    """The plugin's project- and local-scope installs, from `claude plugin list --json`, each
    with its folder resolved; a user-scope install is left out. Anything but the documented
    shape is refused"""
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
        if not isinstance(e.get("scope"), str) or not isinstance(e.get("version"), str):
            raise ReleaseError(f"claude plugin list --json: {PLUGIN} install {e!r}")
        if e["scope"] not in SCOPES:
            continue
        where = e.get("projectPath")
        if not isinstance(where, str):
            raise ReleaseError(f"claude plugin list --json: {PLUGIN} {e['scope']} install has no projectPath: {e!r}")
        found.append(Install(e["scope"], Path(where).resolve(), e["version"]))
    return found


def checkout_installs(installs: list[Install], checkout: Path) -> tuple[Install, ...]:
    """The installs keyed on the checkout, project scope first; two at one scope are refused"""
    here = checkout.resolve()  # the gate's --repo may be relative; Claude Code records an absolute path
    own = [i for i in installs if i.folder == here]
    for scope in SCOPES:
        if sum(i.scope == scope for i in own) > 1:
            raise ReleaseError(f"claude plugin list --json lists {PLUGIN} twice at {scope} scope in {checkout}")
    return tuple(sorted(own, key=lambda i: SCOPES.index(i.scope)))


def check(checkout: Path, run: Runner) -> PluginUpdate:
    """Read the checkout's installs and the latest release; refresh the marketplace once and
    update each install that's behind, then read the installs again to confirm the update
    reached it and no other folder's"""
    listing = ["claude", "plugin", "list", "--json"]
    before = keyed_installs(run(listing, checkout))
    own = checkout_installs(before, checkout)
    if not own:
        return PluginUpdate((), None, ())
    tag = run(["gh", "release", "view", "-R", SHIPMILL_REPO, "--json", "tagName", "-q", ".tagName"], checkout).strip()
    latest = Version.of_tag(tag)
    behind = [i for i in own if Version.parse(i.version) < latest]
    if not behind:
        return PluginUpdate(own, str(latest), ())
    errors = []
    try:  # a failed refresh is reported; the update may still find the release
        run(REFRESH, checkout)
    except ReleaseError as exc:
        errors.append(str(exc))
    tried = []
    for install in behind:
        try:
            run(["claude", "plugin", "update", PLUGIN, "--scope", install.scope], checkout)
        except ReleaseError as exc:
            errors.append(str(exc))
            continue
        tried.append(install.scope)
    try:
        after = keyed_installs(run(listing, checkout))
    except ReleaseError as exc:
        errors.append(f"the update couldn't be confirmed: {exc}")
        return PluginUpdate(own, str(latest), (), "; ".join(errors))
    now = {i.scope: i.version for i in checkout_installs(after, checkout)}
    updated = []
    for scope in tried:
        version = now.get(scope)
        if version is not None and Version.parse(version) >= latest:
            updated.append(scope)
        else:
            left = "removed its install" if version is None else f"left its install at {version}"
            errors.append(f"`claude plugin update --scope {scope}` in {checkout} {left}")
    errors += [f"the update changed the {i.scope} install in {i.folder}" for i in changed(before, after, checkout)]
    return PluginUpdate(own, str(latest), tuple(updated), "; ".join(errors) or None)


def changed(before: list[Install], after: list[Install], checkout: Path) -> list[Install]:
    """The installs keyed on folders other than the checkout that the update changed or removed"""
    here = checkout.resolve()
    now = {(i.scope, i.folder): i.version for i in after}
    return [i for i in before if i.folder != here and now.get((i.scope, i.folder)) != i.version]


def daily_update(path: Path, checkout: Path, now: dt.datetime, run: Runner) -> PluginUpdate | None:
    """check(), at most once per EVERY: None when the last check was more recent. A check
    that read the versions is recorded, a failed update included; one that failed to read
    them is reported and not recorded, so the next launch tries again"""
    last = load_checked(path)
    if last is not None and now - last < EVERY:
        return None
    try:
        found = check(checkout, run)
    except ReleaseError as exc:
        return PluginUpdate((), None, (), str(exc))
    save_checked(path, now)
    return found


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


@dataclass(frozen=True, slots=True)
class Loaded:
    """D-35: the install a session in the gate's checkout would load (None: none applies)
    against the latest release (None when it wasn't read), with the command that updates it
    when it is behind, or the failure that stopped the check"""

    project: Path
    install: Listed | None
    latest: Version | None
    fix: str | None = None
    error: str | None = None

    @property
    def stale(self) -> bool:
        return self.install is not None and self.latest is not None and self.install.version < self.latest

    def reason(self) -> str:
        """A PLUGIN_STALE tick's reason: the install, its scope, the latest, and the fix"""
        if self.install is None or self.latest is None or self.fix is None:
            raise ReleaseError(f"{PLUGIN} isn't behind the latest release, so no session is held for it")
        return (
            f"a session here would load {PLUGIN} {self.install.version} ({self.install.where()}),"
            f" older than the latest release {self.latest}: no session starts until it is updated: {self.fix}"
        )

    def lines(self) -> list[str]:
        """The tick's lines when a session starts: a failed check, or no install that applies;
        a current install says nothing"""
        if self.error is not None:
            return [f"plugin check failed, the session starts anyway: {self.error}"]
        if self.install is None:
            return [f"plugin: no {PLUGIN} install applies to {self.project}; the session loads no shipmill skills"]
        return []

    def record(self) -> dict[str, object]:
        install = self.install
        return {
            "project": str(self.project),
            "scope": None if install is None else str(install.scope),
            "folder": None if install is None or install.folder is None else str(install.folder),
            "version": None if install is None else str(install.version),
            "latest": None if self.latest is None else str(self.latest),
            "stale": self.stale,
            "fix": self.fix,
            "error": self.error,
        }


def loaded(checkout: Path, project: Path, run: Runner) -> Loaded:
    """D-35: read the install a session in the checkout (Claude Code's project `project`)
    would load, and the latest release when there is one. A failed read is returned as the
    error, for the tick to report"""
    try:
        installs = listed_installs(run(["claude", "plugin", "list", "--json"], checkout))
        found = effective(installs, project)
        if found is None:
            return Loaded(project, None, None)
        tag = run(["gh", "release", "view", "-R", SHIPMILL_REPO, "--json", "tagName", "-q", ".tagName"], checkout)
        latest = Version.of_tag(tag.strip())
    except ReleaseError as exc:
        return Loaded(project, None, None, error=str(exc))
    return Loaded(project, found, latest, update_command(found, installs) if found.version < latest else None)
