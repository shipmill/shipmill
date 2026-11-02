"""`spec open` (spec 053): open a spec's pull request that the spec gate can follow.

Every check runs before the first write: the path, `specs.py check`, the spec's status, the
App, the feature issue, and the branch on origin. Then one commit on `spec/NNN-<slug>` from
origin's default branch and its push, the pull request whose body starts `Spec for #N`, and the
feature verdict on #N in comments.md's Feature template, whose hold line holds the issue on the
pull request until it merges. It never files the feature issue and asks no question.
"""

import functools
import importlib.util
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Protocol

from shipmill.app_gh import pull_url
from shipmill.errors import ReleaseError
from shipmill.gate import skills_dir
from shipmill.gitrepo import REMOTE, Git

_PATH = re.compile(r"docs/specs/(\d{3,})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md")
_GOAL = re.compile(r"G-[1-9][0-9]*")
_SCRIPTS = ("github-issue-triage", "scripts")
QUALITY_BAR = "quality bar"
APPROVED = "approved"
NO_ISSUE = (
    "a spec pull request needs its feature issue: pass --issue N, the issue the maintainer filed or the "
    "accepted opportunity the spec is for; spec open never files it (spec 053), and nothing was written"
)


@dataclass(frozen=True, slots=True)
class SpecPath:
    """A spec's file, docs/specs/NNN-<slug>.md, relative to the repo's root"""

    number: str  # NNN, as the file name writes it
    slug: str

    @classmethod
    def parse(cls, text: str) -> SpecPath:
        found = _PATH.fullmatch(text)
        if found is None:
            raise ReleaseError(
                "a spec's path is docs/specs/NNN-<slug>.md, relative to the repo's root, its slug lowercase words "
                f"joined by '-'; got {text!r}"
            )
        return cls(found.group(1), found.group(2))

    @property
    def path(self) -> PurePosixPath:
        return PurePosixPath(f"docs/specs/{self.number}-{self.slug}.md")

    @property
    def branch(self) -> str:
        return f"spec/{self.number}-{self.slug}"


@dataclass(frozen=True, slots=True)
class Spec:
    """What spec open reads of a spec, through specs.py: its title, its status, and the goal
    ids its `serves:` line names (none for `serves: quality bar` or without the line)"""

    title: str
    status: str
    goals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Record:
    """What GitHub holds at a number of the repo: an issue or a pull request, open or not"""

    pull: bool
    open: bool


class Checkout(Protocol):
    """The git side of spec open, on the repo's checkout and its origin"""

    def default_branch(self) -> str:
        """origin's default branch"""
        ...

    def remote_branch(self, branch: str) -> str | None:
        """The branch's commit on origin; None when origin has no such branch"""
        ...

    def publish(self, branch: str, base: str, paths: Sequence[PurePosixPath], message: str) -> None:
        """Push branch to origin: one commit on origin's base holding the working tree's paths"""
        ...


class Hub(Protocol):
    """The GitHub side of spec open; every write goes as `shipmill gh` writes"""

    def record(self, number: int) -> Record | None:
        """The issue or pull request at number; None when the repo has neither"""
        ...

    def open_pull(self, title: str, body: str, head: str, base: str) -> str:
        """Open the pull request; its URL"""
        ...

    def comment(self, number: int, body: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Request:
    """`spec open`'s arguments: the spec's path, --issue, each --with, and --body-file"""

    path: str
    issue: int | None
    with_paths: tuple[str, ...] = ()
    body_file: Path | None = None


def open_spec(top: Path, repo: str, request: Request, checkout: Checkout, hub: Hub, app: Callable[[], None]) -> str:
    """S-053-1 to S-053-7: every check, then the writes; the pull request's URL. app raises,
    as `shipmill gh` would before a write, when the App isn't available. Any failure before
    the writes raises with nothing written: no branch, commit, push, or GitHub write"""
    if request.issue is None:
        raise ReleaseError(NO_ISSUE)
    if request.issue < 1:
        raise ReleaseError(f"--issue is the feature issue's number, 1 or more; got {request.issue}")
    spec_path = SpecPath.parse(request.path)
    if not _plain_file(top / spec_path.path):
        raise ReleaseError(f"no spec file at {spec_path.path} in {top}; write it with specs.py new first")
    paths = (spec_path.path, *with_paths(top, spec_path.path, request.with_paths))
    text = _body_text(request.body_file)
    check_specs(top)
    spec = read_spec(top, spec_path.path)
    if spec.status != APPROVED:
        raise ReleaseError(
            f"{spec_path.path} is {spec.status}, and a spec pull request opens for an approved spec: set "
            f"`status: {APPROVED}` once it holds what the maintainer approves by merging it"
        )
    app()
    issue = request.issue
    found = hub.record(issue)
    if found is None:
        raise ReleaseError(f"#{issue} is no issue of {repo}; --issue names the spec's open feature issue")
    if found.pull:
        raise ReleaseError(f"#{issue} in {repo} is a pull request; --issue names the spec's open feature issue")
    if not found.open:
        raise ReleaseError(f"#{issue} in {repo} is closed; --issue names the spec's open feature issue")
    base = checkout.default_branch()
    branch = spec_path.branch
    if checkout.remote_branch(branch) is not None:
        raise ReleaseError(
            f"origin already has the branch {branch}: a pull request for this spec may be open; update that branch, "
            "or delete it once nothing needs it"
        )
    checkout.publish(branch, base, paths, f"Spec {spec_path.number}: {lowered(spec.title)}")
    body = f"Spec for #{issue}\n\n{text}" if text else f"Spec for #{issue}"
    try:
        url = hub.open_pull(f"Spec {spec_path.number}: {spec.title}", body, branch, base)
    except ReleaseError as exc:
        raise ReleaseError(f"{exc}\nthe branch {branch} is pushed, but its pull request isn't open") from None
    opened, number = pull_url(url)
    if opened.lower() != repo.lower():
        raise ReleaseError(f"gh opened the pull request {url}, not one of {repo}")
    try:
        hub.comment(issue, verdict(spec, spec_path, repo, number))
    except ReleaseError as exc:
        raise ReleaseError(f"{exc}\nthe pull request {url} is open, but #{issue} carries no verdict") from None
    return url


def verdict(spec: Spec, spec_path: SpecPath, repo: str, pull: int) -> str:
    """The feature verdict of comments.md's Feature template: the hold sentence names the spec
    pull request alone, as owner/repo#N, so the issue reads BLOCKED until it merges (#772)"""
    serves = f" Serves: {', '.join(spec.goals)}." if spec.goals else ""
    return (
        f"Triage: **feature**.{serves} The behaviour is new, so spec {spec_path.number} sets it, with its acceptance "
        "criteria, before anything is built.\n\n"
        f"The spec is in #{pull} (`{spec_path.path}`), with its acceptance criteria. Merging it is the approval, as "
        "is an answer on it that takes every recommendation, after which shipmill merges it once it is green; the "
        "build starts once it merges.\n\n"
        f"On hold: the build waits on {repo}#{pull}, the spec PR."
    )


def lowered(title: str) -> str:
    """The title with its first letter lowercased, for the commit's subject; a first word with
    another capital, an acronym or a name such as GitHub, keeps its case"""
    first = title.split(" ", 1)[0]
    if any(letter.isupper() for letter in first[1:]):
        return title
    return title[:1].lower() + title[1:]


def with_paths(top: Path, spec: PurePosixPath, given: Sequence[str]) -> tuple[PurePosixPath, ...]:
    """Each --with path: a regular file of the working tree, named relative to the repo's
    root, once, and not the spec itself"""
    found: list[PurePosixPath] = []
    for text in given:
        path = PurePosixPath(text)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] == ".git":
            raise ReleaseError(f"--with {text}: name a file inside the repo, relative to its root")
        if path == spec or path in found:
            raise ReleaseError(f"--with {text} is in the commit already; name each file once")
        if not _plain_file(top / path):
            raise ReleaseError(f"--with {text}: no such file in {top} (a symlink or folder doesn't count)")
        found.append(path)
    return tuple(found)


def _plain_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _body_text(path: Path | None) -> str:
    """--body-file's text, without leading or trailing blank lines; empty without one"""
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8").strip("\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"--body-file {path} can't be read: {exc}") from None


def _script(name: str) -> Path:
    return skills_dir().joinpath(*_SCRIPTS, name)


def check_specs(top: Path) -> None:
    """`specs.py check` in the repo's root, as CI runs it; its messages when it fails"""
    done = subprocess.run(
        [sys.executable, str(_script("specs.py")), "check"], cwd=top, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        said = "\n".join(part.strip() for part in (done.stdout, done.stderr) if part.strip())
        raise ReleaseError(f"the specs don't pass specs.py check, so nothing was written:\n{said}")


def _load(name: str, script: Path) -> ModuleType:
    found = importlib.util.spec_from_file_location(name, script)
    if found is None or found.loader is None:
        raise ReleaseError(f"can't load {script}")
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module  # its dataclasses look their module up by name
    found.loader.exec_module(module)
    return module


@functools.cache
def _specs() -> ModuleType:
    """specs.py, which the wheel ships; it imports decisions.py by that name, so that loads first"""
    _load("decisions", _script("decisions.py"))
    return _load("shipmill_specs", _script("specs.py"))


def read_spec(top: Path, path: PurePosixPath) -> Spec:
    """The spec's title, status, and goals, as specs.py parses them"""
    parsed, problems = _specs().parse(top / path)
    if parsed is None or problems:
        raise ReleaseError("\n".join(problems))
    serves: str | None = parsed.serves
    goals: tuple[str, ...] = ()
    if serves is not None and serves.strip() != QUALITY_BAR:
        goals = tuple(name.strip() for name in serves.split(","))
        odd = [name for name in goals if _GOAL.fullmatch(name) is None]
        if odd:
            raise ReleaseError(
                f"{path}'s serves: line names {', '.join(map(repr, odd))}; it names goal ids (G-n) or "
                f"'{QUALITY_BAR}' alone"
            )
    return Spec(str(parsed.title), str(parsed.status), goals)


class GitCheckout:
    """Checkout on a real checkout: the commit is built in a scratch index from origin's base,
    so the working tree, the index, and the current branch stay as they were"""

    def __init__(self, top: Path) -> None:
        self._top = top
        self._git = Git(top)

    def default_branch(self) -> str:
        return self._git.default_branch()

    def remote_branch(self, branch: str) -> str | None:
        return self._git.remote_branch(branch)

    def publish(self, branch: str, base: str, paths: Sequence[PurePosixPath], message: str) -> None:
        tracking = f"refs/remotes/{REMOTE}/{base}"
        self._git.run("fetch", "-q", REMOTE, f"+refs/heads/{base}:{tracking}")
        with tempfile.TemporaryDirectory() as folder:
            scratch = Git(self._top)
            scratch.env = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
            scratch.run("read-tree", tracking)
            for path in paths:
                mode = "100755" if os.stat(self._top / path).st_mode & stat.S_IXUSR else "100644"
                blob = self._git.run("hash-object", "-w", "--", path.as_posix()).strip()
                scratch.run("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path.as_posix()}")
            tree = scratch.run("write-tree").strip()
        if tree == self._git.run("rev-parse", f"{tracking}^{{tree}}").strip():
            listed = ", ".join(p.as_posix() for p in paths)
            raise ReleaseError(f"{listed} read the same on {REMOTE}/{base}: the spec pull request would change nothing")
        commit = self._git.run("commit-tree", tree, "-p", tracking, "-m", message).strip()
        failed = self._git.push(f"{commit}:refs/heads/{branch}")
        if failed:
            raise ReleaseError(f"git push of {branch} to {REMOTE} failed: {failed}")
