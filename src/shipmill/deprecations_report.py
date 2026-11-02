"""Spec 047: `shipmill deprecations`, D-63's question for the maintainer's connected repos: does
any of them still rely on a deprecated key or reading? Read-only (D-54).

The repos are this host's gate jobs' (the launchd jobs `shipmill factory` reads), or those
`--repo` and `--fleet` name, with the host's too under `--host`. For each repo it reads
`.github/shipmill.toml` on the default branch through the contents API, with no clone, parses it
as every command does, and runs the deprecations catalogue over it; for each repo relying on an
entry with a migrating upgrade it reads that upgrade's state from the repo's shipmill-upgrade
issues and open pull requests.

Exit 0 when no repo relies on the deprecations asked about, 1 when one does, and 2 when a repo
can't be read (no access, no config on the default branch, a config that fails to parse), naming
each such repo and printing no report: an unread repo is never counted as relying on nothing.
No repos to read exits 2 too."""

import datetime as dt
import json
import re
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from shipmill.config import CONFIG_PATH, loads
from shipmill.deprecations import CATALOGUE, Deprecation
from shipmill.errors import ReleaseError
from shipmill.gate import StateRunner
from shipmill.github import (
    UPGRADE_LABEL,
    UPGRADE_LATER_LABEL,
    Issue,
    PullRequest,
    labelled_command,
    open_pulls_command,
    parse_labelled,
    parse_open_pulls,
)
from shipmill.policy import Policy
from shipmill.status import gh_read
from shipmill.upgrades import Upgrade, UpgradeId, marked
from shipmill.upgrades import find as find_upgrade
from shipmill.walk import DECISION_LABEL

# owner/name, as github-ship-watch's fleet.py checks it: a name isn't only dots
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/(?!\.+$)[A-Za-z0-9._-]+$")
FLEET_KEYS = ("repo", "incident_label")  # the keys of a fleet file's [[repos]] entry, as fleet.py reads it
UPGRADE_BRANCH = "shipmill/upgrade-"  # the branch github-ship-watch opens an upgrade's pull request from, then its id


@dataclass(frozen=True, slots=True)
class RepoName:
    """A GitHub repo, owner/name"""

    value: str

    def __post_init__(self) -> None:
        if not _REPO.match(self.value):
            raise ReleaseError(f"a repo is owner/name, such as shipmill/shipmill; got {self.value!r}")

    @property
    def key(self) -> str:
        """GitHub's owner and repo names ignore case"""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


def unique(repos: Sequence[RepoName]) -> tuple[RepoName, ...]:
    """The repos in order, each once, whatever its case"""
    seen: dict[str, RepoName] = {}
    for repo in repos:
        seen.setdefault(repo.key, repo)
    return tuple(seen.values())


def fleet_repos(path: Path) -> tuple[RepoName, ...]:
    """The repos of github-ship-watch's fleet file, in order, read as fleet.py reads it:
    [[repos]] tables of repo and an optional incident_label, nothing else, no repo twice"""
    if not path.is_file():
        raise ReleaseError(f"{path}: no such fleet file")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"{path}: not TOML: {exc}") from None
    unknown = sorted(set(raw) - {"repos"})
    if unknown:
        raise ReleaseError(f"{path}: unknown key {unknown[0]!r}: a fleet file holds only [[repos]] tables")
    tables = raw.get("repos")
    if not isinstance(tables, list) or not tables:
        raise ReleaseError(f"{path}: no [[repos]]")
    repos = []
    for index, table in enumerate(tables):
        where = f"{path}: repos[{index}]"
        if not isinstance(table, dict):
            raise ReleaseError(f"{where} is not a table")
        extra = sorted(set(table) - set(FLEET_KEYS))
        if extra:
            raise ReleaseError(f"{where} has an unknown key {extra[0]!r}: only repo and incident_label")
        if "repo" not in table:
            raise ReleaseError(f"{where} has no repo")
        repo = table["repo"]
        if not isinstance(repo, str) or not _REPO.match(repo):
            raise ReleaseError(f"{where}: repo {repo!r} is not in owner/name form")
        label = table.get("incident_label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise ReleaseError(f"{where}: incident_label must be a non-empty string")
        repos.append(RepoName(repo))
    if len(unique(repos)) != len(repos):
        twice = next(r for i, r in enumerate(repos) if r.key in {s.key for s in repos[:i]})
        raise ReleaseError(f"{path}: lists {twice} twice")
    return tuple(repos)


class StateKind(StrEnum):
    PULL_OPEN = "pull request open"
    LATER = "not now"
    ASKED = "asked, waiting"
    ISSUE_OPEN = "issue open"
    DECLINED = "declined"
    NOT_PROPOSED = "not proposed"


@dataclass(frozen=True, slots=True)
class UpgradeState:
    """Where a relying repo stands with the deprecation's migrating upgrade: its kind, the
    upgrade's issue it was read from (None: none), and its open pull request's number"""

    kind: StateKind
    issue: int | None = None
    pull: int | None = None

    def text(self) -> str:
        if self.kind is StateKind.PULL_OPEN:
            return f"pull request #{self.pull} open"
        if self.kind is StateKind.ISSUE_OPEN:
            return f"issue #{self.issue} open"
        return str(self.kind)


NOT_PROPOSED = UpgradeState(StateKind.NOT_PROPOSED)


def upgrade_state(
    upgrade: Upgrade, raw: Mapping[str, Any], issues: Sequence[Issue], pulls: Sequence[PullRequest]
) -> UpgradeState:
    """The upgrade's state in a repo, from its config (raw), its shipmill-upgrade issues, open and
    closed, and its open pull requests: a pull request open from the upgrade's branch; else the
    first open issue carrying the upgrade's marker, labelled shipmill-upgrade-later (not now) or
    needs-decision (asked, waiting), or neither (open); else a closed one while the config hasn't
    decided the upgrade, which is a decline; else not proposed"""
    mine = sorted((i for i in issues if marked(i) == upgrade.id), key=lambda i: i.number)
    opened = [i for i in mine if not i.closed]
    first = opened[0].number if opened else None
    branch = f"{UPGRADE_BRANCH}{upgrade.id}"
    pull = min((p.number for p in pulls if p.head == branch), default=None)
    if pull is not None:
        return UpgradeState(StateKind.PULL_OPEN, first, pull)
    if opened:
        labels = opened[0].labels
        if UPGRADE_LATER_LABEL in labels:
            return UpgradeState(StateKind.LATER, first)
        if DECISION_LABEL in labels:
            return UpgradeState(StateKind.ASKED, first)
        return UpgradeState(StateKind.ISSUE_OPEN, first)
    closed = [i for i in mine if i.closed]
    if closed and not upgrade.decided(raw):
        return UpgradeState(StateKind.DECLINED, closed[-1].number)
    return NOT_PROPOSED


class Reads(Protocol):
    """What the report reads of each repo on GitHub, as tests pass fakes; each read that fails
    raises ReleaseError"""

    def config(self, repo: RepoName) -> str:
        """.github/shipmill.toml's text on the default branch"""
        ...

    def upgrade_issues(self, repo: RepoName) -> Sequence[Issue]:
        """The shipmill-upgrade issues, open and closed"""
        ...

    def open_pulls(self, repo: RepoName) -> Sequence[PullRequest]: ...


class GhReads:
    """Reads through gh, each naming the repo with -R or its path; a transient failure is run once more"""

    def __init__(self, run: StateRunner, pause: Callable[[float], None] = time.sleep) -> None:
        self._run, self._pause = run, pause

    def config(self, repo: RepoName) -> str:
        path = f"repos/{repo}/contents/{CONFIG_PATH.as_posix()}"  # no ref: the default branch's
        cmd = ["gh", "api", "-H", "Accept: application/vnd.github.raw+json", path]
        return gh_read(cmd, self._run, f"gh api {path}", self._pause)

    def upgrade_issues(self, repo: RepoName) -> Sequence[Issue]:
        cmd = ["gh", *labelled_command(UPGRADE_LABEL), "-R", str(repo)]
        return parse_labelled(gh_read(cmd, self._run, "gh issue list", self._pause))

    def open_pulls(self, repo: RepoName) -> Sequence[PullRequest]:
        cmd = ["gh", *open_pulls_command(), "-R", str(repo)]
        return parse_open_pulls(gh_read(cmd, self._run, "gh pr list", self._pause))


@dataclass(frozen=True, slots=True)
class Relying:
    repo: RepoName
    state: UpgradeState

    def record(self) -> dict[str, object]:
        return {"repo": str(self.repo), "upgrade_state": self.state.text(), "issue": self.state.issue}


@dataclass(frozen=True, slots=True)
class Block:
    """A deprecation and the repos relying on it, in the order they were read"""

    deprecation: Deprecation
    relying: tuple[Relying, ...]

    def record(self) -> dict[str, object]:
        d = self.deprecation
        return {
            "id": str(d.id),
            "replacement": d.replacement,
            "upgrade": None if d.upgrade is None else str(d.upgrade),
            "relied_on_by": [r.record() for r in self.relying],
        }


@dataclass(frozen=True, slots=True)
class Report:
    repos: tuple[RepoName, ...]
    blocks: tuple[Block, ...]

    @property
    def code(self) -> int:
        """0 when no repo relies on a deprecation asked about, 1 when one does"""
        return 1 if any(b.relying for b in self.blocks) else 0

    def text(self, today: dt.date) -> str:
        """A line naming the date and the repos read, which a decision cites, then one block per deprecation"""
        count = len(self.repos)
        named = ", ".join(map(str, self.repos))
        lines = [f"{count} repo{'s' if count != 1 else ''} read on {today.isoformat()}: {named}"]
        for block in self.blocks:
            d = block.deprecation
            upgrade = "none" if d.upgrade is None else str(d.upgrade)
            lines.append(f"{d.id}: {d.subject}, replaced by {d.replacement}; upgrade: {upgrade}")
            lines += [f"  {r.repo}: {r.state.text()}" for r in block.relying]
            if not block.relying:
                lines.append(f"  none of {count} repos")
        return "\n".join(lines) + "\n"

    def json(self) -> str:
        record = {"repos": [str(r) for r in self.repos], "deprecations": [b.record() for b in self.blocks]}
        return json.dumps(record, indent=2) + "\n"


def _states(
    repo: RepoName, raw: Mapping[str, Any], relied: Sequence[Deprecation], reads: Reads
) -> dict[UpgradeId, UpgradeState]:
    """The state of each relied-on deprecation's migrating upgrade; GitHub is read only when one has an upgrade"""
    wanted = list(dict.fromkeys(d.upgrade for d in relied if d.upgrade is not None))
    if not wanted:
        return {}
    issues, pulls = reads.upgrade_issues(repo), reads.open_pulls(repo)
    return {u: upgrade_state(find_upgrade(u), raw, issues, pulls) for u in wanted}


def report(repos: Sequence[RepoName], asked: Sequence[Deprecation], reads: Reads) -> Report:
    """Read every repo, then report each deprecation asked about. A repo that can't be read, or
    whose config doesn't parse, raises one error naming every such repo after all were tried"""
    repos = unique(repos)
    if not repos:
        raise ReleaseError("no repos to read: no gate job on this host, and no --repo or --fleet")
    found: dict[RepoName, tuple[tuple[Deprecation, ...], dict[UpgradeId, UpgradeState]]] = {}
    unread: list[str] = []
    for repo in repos:
        where = f"{CONFIG_PATH.as_posix()} of {repo}"
        try:
            raw = loads(reads.config(repo), where)
            policy = Policy.parse(raw, where)
            relied = tuple(d for d in asked if d.relies(policy))
            found[repo] = (relied, _states(repo, raw, relied, reads))
        except ReleaseError as exc:
            unread.append(f"{repo}: {exc}")
    if unread:
        lines = "\n".join(f"  {line}" for line in unread)
        raise ReleaseError(
            f"can't read {len(unread)} of {len(repos)} repos, and an unread repo never counts as relying on"
            f" nothing:\n{lines}"
        )
    blocks = []
    for deprecation in asked:
        relying = []
        for repo in repos:
            relied, states = found[repo]
            if deprecation in relied:
                upgrade = deprecation.upgrade
                relying.append(Relying(repo, NOT_PROPOSED if upgrade is None else states[upgrade]))
        blocks.append(Block(deprecation, tuple(relying)))
    return Report(repos, tuple(blocks))


def asked_about(deprecation: Deprecation | None) -> tuple[Deprecation, ...]:
    """The one deprecation <id> names, else the whole catalogue in its order"""
    return CATALOGUE if deprecation is None else (deprecation,)
