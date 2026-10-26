"""The git operations the bot needs, on a checkout whose remote is origin"""

import datetime as dt
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shipmill.config import CONFIG_PATH, branch_in
from shipmill.errors import ReleaseError
from shipmill.version import PATTERN, TAG_PREFIX, Version

REMOTE = "origin"
WORKFLOWS = ".github/workflows/"  # the CI a run resolves at its own commit, not at the tree it releases


@dataclass(frozen=True, slots=True)
class Tag:
    version: Version
    commit: str
    date: dt.datetime

    @property
    def name(self) -> str:
        return self.version.tag


class Git:
    def __init__(self, root: Path, name: str = "", email: str = "") -> None:
        self.root = root
        self._identity = ("-c", f"user.name={name}", "-c", f"user.email={email}") if name else ()
        self.env: dict[str, str] = {}  # extra environment for git, such as GIT_COMMITTER_DATE

    def _proc(self, args: tuple[str, ...], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(self.root), *self._identity, *args],
            input=stdin,
            capture_output=True,
            env={**os.environ, **self.env} if self.env else None,
        )

    def run(self, *args: str, stdin: bytes | None = None) -> str:
        proc = self._proc(args, stdin)
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace").strip()
            raise ReleaseError(f"git {' '.join(args)} failed: {err}")
        return proc.stdout.decode()

    def run_bytes(self, *args: str) -> bytes:
        proc = self._proc(args)
        if proc.returncode != 0:
            raise ReleaseError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc.stdout

    def apply(self, patch: bytes) -> str:
        """Apply a patch to the index and work tree with a 3-way merge; the error, or ''"""
        proc = self._proc(("apply", "--3way", "--index", "-"), patch)
        return "" if proc.returncode == 0 else proc.stderr.decode(errors="replace").strip()

    def ok(self, *args: str) -> bool:
        return self._proc(args).returncode == 0

    def sha(self, rev: str = "HEAD") -> str:
        return self.run("rev-parse", "--verify", f"{rev}^{{commit}}").strip()

    def show(self, rev: str, path: str) -> str | None:
        proc = self._proc(("show", f"{rev}:{path}"))
        return proc.stdout.decode() if proc.returncode == 0 else None

    def is_ancestor(self, ancestor: str, rev: str) -> bool:
        return self.ok("merge-base", "--is-ancestor", ancestor, rev)

    def first_parent(self, rev: str) -> str:
        return self.sha(f"{rev}^1")

    def first_parent_count(self, rev: str = "HEAD") -> int:
        return int(self.run("rev-list", "--count", "--first-parent", rev).strip())

    def commit_time(self, rev: str = "HEAD") -> dt.datetime:
        return dt.datetime.fromisoformat(self.run("show", "-s", "--format=%cI", rev).strip())

    def oldest_commit_time(self, since: str | None, rev: str) -> dt.datetime | None:
        """The earliest committer time of the commits rev holds and since doesn't (all of
        rev's history without since); None when there are none"""
        out = self.run("log", "--format=%cI", rev if since is None else f"{since}..{rev}")
        return min((dt.datetime.fromisoformat(line) for line in out.split()), default=None)

    def changed_paths(self, since: str, rev: str = "HEAD") -> list[str]:
        return [p for p in self.run("diff", "--name-only", f"{since}..{rev}").splitlines() if p]

    def differs(self, a: str, b: str, path: str) -> bool:
        """Whether the trees of a and b differ under path; a git error raises rather than read as unchanged"""
        args = ("diff", "--quiet", "--no-ext-diff", a, b, "--", path)
        proc = self._proc(args)
        if proc.returncode not in (0, 1):
            raise ReleaseError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc.returncode == 1

    def tags(self) -> list[Tag]:
        """Release tags (v + a version) with their commit and creation time, oldest first;
        other tags are not the bot's and are skipped"""
        out = self.run(
            "for-each-ref",
            "--format=%(refname:strip=2)%09%(*objectname)%09%(objectname)%09%(creatordate:iso-strict)",
            "refs/tags",
        )
        found = []
        for line in out.splitlines():
            name, peeled, obj, date = line.split("\t")
            if not name.startswith(TAG_PREFIX) or not PATTERN.fullmatch(name[len(TAG_PREFIX) :]):
                continue
            found.append(Tag(Version.of_tag(name), peeled or obj, dt.datetime.fromisoformat(date)))
        return sorted(found, key=lambda t: t.date)

    def default_branch(self) -> str:
        """origin's default branch, as `git ls-remote --symref origin HEAD` names it"""
        head = self.run("ls-remote", "--symref", REMOTE, "HEAD")
        found = re.search(r"^ref: refs/heads/(\S+)\s+HEAD$", head, re.MULTILINE)
        if found is None:
            raise ReleaseError(f"origin of {self.root} names no default branch")
        return found.group(1)

    def landing_branch(self) -> str:
        """The branch releases land on, which the landing checks compare against: the `branch`
        the config at origin's default branch sets, else that default branch (#694). origin's
        default branch is fetched first and its config read at the trusted ref, never from the
        working tree, which a session may have left on a pull request's branch (D-16, D-48, #697)"""
        trusted = self.default_branch()
        ref = f"refs/remotes/{REMOTE}/{trusted}"
        self.run("fetch", "-q", REMOTE, f"+refs/heads/{trusted}:{ref}")
        text = self.show(ref, CONFIG_PATH.as_posix())
        named = None if text is None else branch_in(text, f"{CONFIG_PATH} at {REMOTE}/{trusted}")
        return trusted if named is None else named

    def remote_branch(self, branch: str) -> str | None:
        out = self.run("ls-remote", "--heads", REMOTE, f"refs/heads/{branch}").split()
        return out[0] if out else None

    def remote_tag(self, tag: str) -> bool:
        return bool(self.run("ls-remote", "--tags", REMOTE, f"refs/tags/{tag}").strip())

    def fetch(self, *refspecs: str) -> None:
        self.run("fetch", "-q", "--tags", REMOTE, *refspecs)

    def push(self, *refspecs: str) -> str:
        """Push to origin; git's error when the remote rejected it (such as a ref that
        moved), else ''"""
        proc = self._proc(("push", "-q", REMOTE, *refspecs))
        return "" if proc.returncode == 0 else proc.stderr.decode(errors="replace").strip()

    def dirty(self) -> bool:
        return bool(self.run("status", "--porcelain").strip())
