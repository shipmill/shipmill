"""`shipmill plugin-clean` (spec 039): remove the project- and local-scope installs of
shipmill@shipmill that shadow the user install, for a person at their terminal.

A dry run by default: it reads `claude plugin list --json` and prints one line per keyed
install, deepest folder first, and changes nothing. With --apply, and only with a terminal on
standard input and a user-scope install on the host, it runs `claude plugin uninstall
shipmill@shipmill --scope <scope>` in each folder, writes the folder's settings files back byte
for byte (the uninstall drops the plugin from enabledPlugins), and checks the listing after
each removal. It never touches a user or managed install, another plugin, or Claude Code's
~/.claude/plugins/installed_plugins.json."""

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.plugin import PLUGIN, USER_INSTALL, USER_UPDATE, Runner, Scope, latest_release, unloaded_fix
from shipmill.version import Version

LIST = ["claude", "plugin", "list", "--json"]
CLAUDE_DIR = Path(".claude")
SETTINGS = (CLAUDE_DIR / "settings.json", CLAUDE_DIR / "settings.local.json")  # restored byte for byte
# what an uninstall may leave in a folder created for it: the folder is removed only then
CREATED_ALLOWED = frozenset({CLAUDE_DIR.as_posix(), *(s.as_posix() for s in SETTINGS)})
GITDIR = re.compile(r"^gitdir: (?P<path>.+)$")

# One entry of `claude plugin list --json`, any plugin and scope, by the fields a removal may not
# change: id, scope, projectPath, version
Identity = tuple[str, str, str | None, str | None]


@dataclass(frozen=True, slots=True)
class Keyed:
    """A project- or local-scope install of the plugin: its scope, the folder it is keyed on as
    the listing names it, and its version"""

    scope: Scope
    folder: Path
    version: str

    @property
    def identity(self) -> Identity:
        return (PLUGIN, str(self.scope), str(self.folder), self.version)


@dataclass(frozen=True, slots=True)
class Listing:
    """`claude plugin list --json`, parsed: every entry's identity, the plugin's keyed
    installs, and its user install's version (None without one)"""

    identities: tuple[Identity, ...]
    keyed: tuple[Keyed, ...]
    user: str | None


def _required(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        raise ReleaseError(f"claude plugin list --json: an entry's {key} is {value!r}: {entry!r}")
    return value


def _optional(entry: dict[str, object], key: str) -> str | None:
    return None if entry.get(key) is None else _required(entry, key)


def parse(text: str) -> Listing:
    """The listing; anything but an array of objects with a string id and scope is refused"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"claude plugin list --json printed no JSON: {exc}") from None
    if not isinstance(data, list):
        raise ReleaseError("claude plugin list --json: expected a JSON array")
    identities: list[Identity] = []
    keyed: list[Keyed] = []
    user = None
    for entry in data:
        if not isinstance(entry, dict):
            raise ReleaseError(f"claude plugin list --json: an entry is {entry!r}, not an object")
        plugin, scope = _required(entry, "id"), _required(entry, "scope")
        where, version = _optional(entry, "projectPath"), _optional(entry, "version")
        identities.append((plugin, scope, where, version))
        if plugin != PLUGIN:
            continue
        if scope not in set(Scope) or version is None:
            raise ReleaseError(f"claude plugin list --json: {PLUGIN} install {entry!r}")
        if Scope(scope).keyed:
            if where is None:
                raise ReleaseError(f"claude plugin list --json: {PLUGIN} {scope} install has no projectPath: {entry!r}")
            keyed.append(Keyed(Scope(scope), Path(where), version))
        elif scope == Scope.USER:
            user = version
    order = sorted(keyed, key=lambda k: (-len(k.folder.parts), str(k.folder), str(k.scope)))
    return Listing(tuple(identities), tuple(order), user)


def linked_worktree(folder: Path) -> bool:
    """Whether the folder is a linked git worktree: its .git is a file naming a gitdir under
    the main checkout's .git/worktrees/. Claude Code resolves a `claude plugin` command run
    there to the main checkout (#417, #485), so no command reaches an install keyed on it"""
    dot = folder / ".git"
    if not dot.is_file():
        return False
    found = GITDIR.match(dot.read_text(encoding="utf-8").strip())
    return found is not None and Path(found.group("path")).parent.name == "worktrees"


@dataclass(frozen=True, slots=True)
class Step:
    """One keyed install and what plugin-clean does with it: remove it (in a folder on disk,
    or in one created for the uninstall when it is missing), or leave it to the person
    (manual: a linked worktree)"""

    install: Keyed
    missing: bool
    manual: bool

    def note(self) -> str:
        if self.manual:
            return f"a linked worktree: {unloaded_fix(self.install.folder)}"
        if self.missing:
            return "missing: created for the uninstall, then removed"
        there = [s.as_posix() for s in SETTINGS if (self.install.folder / s).is_file()]
        return f"restores {' and '.join(there)}" if there else "restores .claude/ as it was: no settings file there"


def plan(listing: Listing) -> list[Step]:
    steps = []
    for k in listing.keyed:
        missing = not k.folder.exists()
        steps.append(Step(k, missing, not missing and linked_worktree(k.folder)))
    return steps


def lines(steps: list[Step]) -> list[str]:
    """One line per keyed install, deepest folder first, its columns aligned"""
    if not steps:
        return []
    version = max(len(s.install.version) for s in steps)
    folder = max(len(str(s.install.folder)) for s in steps)
    return [
        f"{'manual' if s.manual else 'remove'}  {str(s.install.scope):<7}  {s.install.version:<{version}}"
        f"  {str(s.install.folder):<{folder}}  {s.note()}".rstrip()
        for s in steps
    ]


def after_line(listing: Listing, latest: Version) -> str | None:
    """S-039-14: the user install's update when it lags the latest release; S-039-9's install
    when the host has none and keyed ones to remove"""
    if listing.user is None:
        if not listing.keyed:
            return None
        return f"first: {USER_INSTALL}; without it, removing these leaves their folders with no install"
    if Version.parse(listing.user) < latest:
        return f"then: {USER_UPDATE}"
    return None


# -- --apply ------------------------------------------------------------------------------------


def missing_chain(folder: Path) -> list[Path]:
    """The folder and each missing parent, outermost first: what a removal creates"""
    chain = []
    at = folder
    while not at.exists():
        chain.append(at)
        if at.parent == at:
            break
        at = at.parent
    return list(reversed(chain))


def saved(folder: Path) -> dict[Path, bytes | None]:
    """The bytes of each settings file in the folder, None for one that is absent"""
    return {s: (folder / s).read_bytes() if (folder / s).is_file() else None for s in SETTINGS}


def restore(folder: Path, before: dict[Path, bytes | None], had_dir: bool) -> None:
    """Each settings file written back byte for byte, one the uninstall created deleted, and a
    .claude/ it created removed when that leaves it empty"""
    for name, data in before.items():
        path = folder / name
        if data is not None:
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        elif path.exists():
            path.unlink()
    claude = folder / CLAUDE_DIR
    if not had_dir and claude.is_dir() and not any(claude.iterdir()):
        claude.rmdir()


def remove_created(created: list[Path]) -> Path | None:
    """S-039-12: every folder created for an uninstall removed again, provided the target holds
    nothing but .claude/ and its settings files and each parent nothing but the folder below
    it; the first folder that holds more is left and returned"""
    target = created[-1]
    for path in sorted(target.rglob("*"), reverse=True):
        name = path.relative_to(target).as_posix()
        kind_ok = path.is_dir() if name == CLAUDE_DIR.as_posix() else path.is_file() and not path.is_symlink()
        if name not in CREATED_ALLOWED or not kind_ok:
            return target
    for settings in SETTINGS:
        (target / settings).unlink(missing_ok=True)
    if (target / CLAUDE_DIR).is_dir():
        (target / CLAUDE_DIR).rmdir()
    for folder in reversed(created):
        if any(folder.iterdir()):
            return folder
        folder.rmdir()
    return None


def changes(before: tuple[Identity, ...], target: Identity, after: tuple[Identity, ...]) -> str | None:
    """S-039-11: what the listing after a removal shows beyond the target entry gone: None
    when that is all"""
    expected = Counter(before)
    expected[target] -= 1
    found = Counter(after)
    if found == +expected:
        return None
    said = []
    if found[target] > 0:
        said.append("it is still listed")
    gone = +(expected - found)
    new = +(found - expected)
    if target in new:
        del new[target]
    said += [f"gone: {json.dumps(list(i))}" for i in gone.elements()]
    said += [f"new or changed: {json.dumps(list(i))}" for i in new.elements()]
    return "; ".join(said)


@dataclass(frozen=True, slots=True)
class Applied:
    """What a removal left: a created folder that held more than the uninstall wrote"""

    left: Path | None


def remove(step: Step, before: tuple[Identity, ...], run: Runner) -> Applied:
    """S-039-10 to S-039-12: one keyed install removed in its folder, the folder's settings
    files restored, then the listing checked; a missing folder is created for it and removed
    again. A failed uninstall or an unexpected listing stops the run (exit 2) once the folder
    is restored"""
    folder = step.install.folder
    created = missing_chain(folder)
    if created:
        folder.mkdir(parents=True)
    had_dir = (folder / CLAUDE_DIR).is_dir()
    kept = saved(folder)
    uninstall = ["claude", "plugin", "uninstall", PLUGIN, "--scope", str(step.install.scope)]
    try:
        run(uninstall, folder)
    except ReleaseError as exc:
        _undo(created, folder, kept, had_dir)
        raise ReleaseError(f"{' '.join(uninstall)} in {folder}: {exc}") from None
    if not created:
        restore(folder, kept, had_dir)
    try:
        after = parse(run(LIST, folder)).identities
    finally:  # a failed read still removes the folders created for the uninstall
        left = remove_created(created) if created else None
    changed = changes(before, step.install.identity, after)
    if changed is not None:
        named = "" if left is None else f"; {left} was created for the uninstall and holds more, left"
        raise ReleaseError(
            f"after {' '.join(uninstall)} in {folder}, claude plugin list --json changed beyond that entry:"
            f" {changed}; stopped, no further uninstall{named}"
        )
    return Applied(left)


def _undo(created: list[Path], folder: Path, kept: dict[Path, bytes | None], had_dir: bool) -> None:
    if created:
        remove_created(created)
    else:
        restore(folder, kept, had_dir)


Printer = Callable[[str], None]


def clean(run: Runner, cwd: Path, apply: bool, terminal: bool, say: Printer) -> int:
    """The command: 0 when no keyed install is left, 1 when some are (manual lines, or a
    created folder left behind); a refusal, a failed `claude` command, a malformed listing, or
    a check that fails is a ReleaseError (exit 2). A dry run always exits 0"""
    if apply and not terminal:
        raise ReleaseError(
            "plugin-clean --apply runs only from a person's terminal, and standard input is not one;"
            " run it without --apply to see what it would remove"
        )
    listing = parse(run(LIST, cwd))
    if apply and listing.keyed and listing.user is None:
        raise ReleaseError(
            f"no user-scope install of {PLUGIN} on this host, so removing the project- and local-scope ones"
            f" would leave their folders with none; install it first: {USER_INSTALL}"
        )
    latest = latest_release(run, cwd)
    steps = plan(listing)
    if not steps:
        say(f"no project- or local-scope install of {PLUGIN} on this host")
    if not apply:
        for line in lines(steps):
            say(line)
        last = after_line(listing, latest)
        if last is not None:
            say(last)
        return 0
    left = 0
    identities = listing.identities
    for step, line in zip(steps, lines(steps), strict=True):
        say(line)
        if step.manual:
            left += 1
            continue
        done = remove(step, identities, run)
        identities = tuple(_without(identities, step.install.identity))
        if done.left is not None:
            say(f"  left {done.left}: it holds more than the uninstall wrote; remove it by hand")
            left += 1
    last = after_line(listing, latest)
    if last is not None:
        say(last)
    return 1 if left else 0


def _without(identities: tuple[Identity, ...], target: Identity) -> list[Identity]:
    out = list(identities)
    out.remove(target)
    return out
