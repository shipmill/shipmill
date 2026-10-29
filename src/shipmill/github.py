"""What the bot asks of GitHub, behind a protocol so tests pass their own"""

import datetime as dt
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from shipmill.credit import Account, Commit, Messages, Pull, Review
from shipmill.errors import ReleaseError

PROPOSAL_LABEL = "shipmill-proposal"  # on every issue proposing a release or a deploy
UPGRADE_LABEL = "shipmill-upgrade"  # on every issue proposing a config upgrade (spec 014)
# on an upgrade issue whose maintainer answered "not now": asked again only once a newer
# shipmill release changes the upgrade (S-014-14)
UPGRADE_LATER_LABEL = "shipmill-upgrade-later"
OPEN_LIMIT = 100  # open issues read per label: proposals are one per lane and per environment
PULL_LIMIT = 1000  # open pull requests read at once; gh's own default is 30
MERGED_PER_BRANCH = 20  # merged pull requests read per head branch name, the newest
HISTORY_LIMIT = 100  # a merged pull request's commits, and its force-pushes, read: the last ones
# head branch names read per GraphQL query by merged_pull_requests: each costs GitHub up to
# 20 + 20 * 2 * 100 = 4,020 nodes of the 500,000 a query may ask for, so 126 local branches
# in one query were refused
BRANCHES_PER_QUERY = 50
MILESTONE_LIMIT = 1000  # a milestone's issues read at once; one with more is refused
OPEN_MILESTONE_LIMIT = 100  # open milestones read at once, one page; a repository with more is refused
COMMENTS_READ = 30  # an issue's newest comments read for a close-confirmed marker (D-29)
CLOSERS_READ = 20  # the pull requests read that close an issue
CLOSES_PER_QUERY = 40  # issues read per GraphQL query by issue_closes
CLOSED_LIMIT = 1000  # issues read by closed_since; a range closing more is refused
VOTES_PER_QUERY = 20  # issues read per GraphQL query by requester_votes
VOTE_COMMENTS = 100  # an issue's newest comments read for a pre-release notice (spec 021)
VOTE_REACTIONS = 100  # a comment's 👍 reactions read
GHOST = "ghost"  # the login GitHub shows for a deleted account, as the watch reads it
_VOTES_FRAGMENT = (
    "fragment votes on Issue { number author { __typename login } "
    f"comments(last: {VOTE_COMMENTS}) {{ totalCount nodes {{ body "
    f"reactions(content: THUMBS_UP, first: {VOTE_REACTIONS}) {{ totalCount nodes {{ user {{ login }} }} }} }} }} }}"
)
_CLOSE_FRAGMENT = (
    "fragment closed on Issue { number state stateReason "
    "timelineItems(itemTypes: [CLOSED_EVENT], last: 1) { nodes { ... on ClosedEvent { createdAt "
    "closer { __typename ... on PullRequest { merged mergeCommit { oid } } ... on Commit { oid } } } } } "
    f"closedByPullRequestsReferences(first: {CLOSERS_READ}, includeClosedPrs: true) "
    "{ nodes { merged mergeCommit { oid } } } "
    f"comments(last: {COMMENTS_READ}) "
    "{ nodes { createdAt body authorAssociation author { __typename login } } } }"
)
_MERGED_FRAGMENT = (
    "fragment merged on PullRequestConnection { nodes { number headRefName baseRefName headRefOid "
    f"commits(last: {HISTORY_LIMIT}) {{ nodes {{ commit {{ oid }} }} }} "
    f"timelineItems(itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT], last: {HISTORY_LIMIT}) "
    "{ nodes { ... on HeadRefForcePushedEvent { beforeCommit { oid } afterCommit { oid } } } } } }"
)
_LABEL_DESCRIPTIONS = {
    PROPOSAL_LABEL: "Opened by shipmill: a release or deploy waiting for a person",
    UPGRADE_LABEL: "Opened by shipmill: a config upgrade waiting for the maintainer's decision",
}
# GitHub's limits, in characters: an issue's body or a comment, and a release's notes (#499)
BODY_LIMIT = 65_536
NOTES_LIMIT = 125_000
CUT_MARK = "<!-- shipmill:cut -->"  # opens the line ending a text cut to fit
# the statuses of a run not finished yet, each listed with its own query: GitHub filters runs
# by one status at a time
ACTIVE_STATUSES = ("queued", "in_progress", "waiting", "pending", "requested")


class Forbidden(ReleaseError):
    """GitHub refused the call for the token's permissions (HTTP 403, not a rate limit)"""


@dataclass(frozen=True, slots=True)
class FileChange:
    """A file a pull request changes, as GitHub's pull request files list it: its unified diff
    hunks in patch, None when GitHub gives none (a binary file, a diff too large)"""

    path: str
    status: str  # added, removed, modified, renamed, copied, changed
    patch: str | None = None
    previous: str | None = None  # a renamed file's old path

    @property
    def paths(self) -> tuple[str, ...]:
        """The paths the change touches: a rename touches its old path too"""
        return (self.path,) if self.previous is None else (self.path, self.previous)


@dataclass(frozen=True, slots=True)
class PullChange:
    """A pull request's change: the commit it branched from on its base (the merge base, the
    side its diff is against), its head commit, and its files"""

    number: int
    base: str
    head: str
    files: tuple[FileChange, ...]


@dataclass(frozen=True, slots=True)
class Milestone:
    open_issues: int
    closed_issues: int


@dataclass(frozen=True, slots=True)
class OpenMilestone:
    """An open milestone: GitHub's number for it, which a rename names, its title, and how
    many of its issues are open"""

    number: int
    title: str
    open_issues: int


@dataclass(frozen=True, slots=True)
class MilestoneIssues:
    """The issues of a milestone, open and closed, with the repository they belong to"""

    repo: str  # owner/name, as GitHub spells it
    issues: tuple[tuple[int, str], ...]  # (number, body)


class CloseReason(StrEnum):
    """A closed issue's stateReason, as GitHub's GraphQL API names it"""

    COMPLETED = "COMPLETED"
    NOT_PLANNED = "NOT_PLANNED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class IssueComment:
    author: str  # the login; a Bot's without "[bot]", as GraphQL spells it
    bot: bool
    association: str  # OWNER, MEMBER, COLLABORATOR, CONTRIBUTOR, NONE, ...
    created_at: dt.datetime
    body: str


@dataclass(frozen=True, slots=True)
class IssueClose:
    """How an issue closed: its reason, when it last closed, the commits known to close it
    (the merge commit of each merged pull request that closes it, and the commit that closed
    it), and its newest comments; reason and closed_at are None while it is open"""

    number: int
    reason: CloseReason | None
    closed_at: dt.datetime | None
    fixes: tuple[str, ...]  # full commit SHAs
    comments: tuple[IssueComment, ...]  # the newest COMMENTS_READ, oldest first

    @property
    def open(self) -> bool:
        return self.reason is None


@dataclass(frozen=True, slots=True)
class Voted:
    """An issue comment's first line and the logins that reacted 👍 to it"""

    first_line: str
    thumbs_up: frozenset[str]
    more: bool = False  # 👍s past the first VOTE_REACTIONS, not read


@dataclass(frozen=True, slots=True)
class RequesterVotes:
    """An issue's author, its requester (spec 021), and its newest comments with their 👍s;
    the requester is None for a bot's issue or a deleted account's"""

    number: int
    requester: str | None
    comments: tuple[Voted, ...]  # the newest VOTE_COMMENTS, oldest first
    earlier: bool = False  # comments before the newest VOTE_COMMENTS, not read


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    title: str
    body: str
    closed_at: dt.datetime | None = None  # None while open
    labels: tuple[str, ...] = ()  # read by labelled_issues; empty where a call doesn't read them

    @property
    def closed(self) -> bool:
        return self.closed_at is not None


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    head: str  # the head branch's name


@dataclass(frozen=True, slots=True)
class MergedPull:
    """A merged pull request and every commit known to have been its head: its head when
    merged, its commits, and each force-push's commit before and after"""

    number: int
    head: str  # the head branch's name
    heads: frozenset[str]  # full commit SHAs
    base: str  # the branch it merged into: only a merge into the default branch landed


class DeploymentState(StrEnum):
    """A deployment status's state, as GitHub's REST API names it"""

    ERROR = "error"
    FAILURE = "failure"
    INACTIVE = "inactive"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"
    PENDING = "pending"
    SUCCESS = "success"
    WAITING = "waiting"  # an Actions job held by the environment's protection rules


@dataclass(frozen=True, slots=True)
class Deployment:
    """A GitHub deployment: what ran where. `ref` is the branch, tag, or sha it was made from"""

    id: int
    ref: str
    sha: str
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class DeploymentStatus:
    id: int  # increases with each status, so it orders them where created_at ties
    state: DeploymentState
    created_at: dt.datetime
    description: str


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    """A run of a workflow: `status` is GitHub's (queued, in_progress, waiting, completed, ...)"""

    id: int
    status: str
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class RunState:
    """Where one workflow run stands: GitHub's `status`, and its `conclusion` once completed
    (success, failure, cancelled, ...), else empty"""

    status: str
    conclusion: str

    @property
    def done(self) -> bool:
        return self.status == "completed"


class GitHub(Protocol):
    def open_issues(self, label: str) -> list[str]:
        """'#N title' for each open issue with the label"""
        ...

    def milestone(self, title: str) -> Milestone | None: ...

    def open_milestones(self) -> list[OpenMilestone]:
        """The repository's open milestones, by number (fewer than OPEN_MILESTONE_LIMIT)"""
        ...

    def milestone_issues(self, title: str) -> MilestoneIssues:
        """Every issue of the milestone with the title, open and closed (MILESTONE_LIMIT at most)"""
        ...

    def issue_closes(self, numbers: Sequence[int]) -> list[IssueClose]:
        """How each of the repository's issues closed, by number; batched, none for no number"""
        ...

    def closed_since(self, day: dt.date | None) -> list[int]:
        """The numbers of the issues closed on day or later (every closed issue for None), by
        number; more than CLOSED_LIMIT is refused"""
        ...

    def requester_votes(self, numbers: Sequence[int]) -> list[RequesterVotes]:
        """Each issue's author and newest comments with their 👍s, by number; batched, none
        for no number"""
        ...

    def app_id(self, slug: str) -> int:
        """The id of the GitHub App with the slug (a Bot's login without "[bot]")"""
        ...

    def merge_commit(self, pr: int) -> str:
        """The commit a merged pull request landed as on the default branch"""
        ...

    def create_release(self, tag: str, title: str, notes: str, prerelease: bool) -> None: ...

    def dispatch(self, workflow: str, ref: str, tag: str, inputs: Mapping[str, str] | None = None) -> str | None:
        """Start the workflow on ref with -f tag=<tag>, and -f name=value for each of inputs;
        the run's URL when GitHub tells it"""
        ...

    def find_issue(self, marker: str) -> Issue | None:
        """The open issue whose body holds the marker, among the newest 500"""
        ...

    def create_issue(self, title: str, body: str, labels: Sequence[str] = ()) -> int:
        """Open an issue; a label the repository lacks is created first"""
        ...

    def update_issue(self, number: int, title: str, body: str, labels: Sequence[str] = ()) -> None:
        """Rewrite an issue and add the labels; a label the repository lacks is created first"""
        ...

    def comment_issue(self, number: int, body: str) -> None: ...

    def labelled_issues(self, label: str) -> list[Issue]:
        """The issues with the label, open and closed, newest first (the newest 100)"""
        ...

    def open_labelled_issues(self, label: str) -> list[Issue]:
        """The open issues with the label, newest first (the newest OPEN_LIMIT)"""
        ...

    def close_issue(self, number: int, comment: str) -> None: ...

    def remove_label(self, number: int, label: str) -> None:
        """Take the label off the issue"""
        ...

    def label_names(self) -> frozenset[str]:
        """The names of the repository's labels (the first 1000), in one read"""
        ...

    def deployments(self, environment: str) -> list[Deployment]:
        """The environment's deployments, newest first (the newest 100)"""
        ...

    def deployment_statuses(self, deployment: int) -> list[DeploymentStatus]:
        """The deployment's statuses, oldest first (the newest 100)"""
        ...

    def create_deployment_status(self, deployment: int, state: DeploymentState, description: str) -> None:
        """Add a status, leaving the environment's other deployments as they are"""
        ...

    def workflow_runs(self, workflow: str, ref: str) -> list[WorkflowRun]:
        """The workflow's runs on the branch or tag, newest first (the newest 100)"""
        ...

    def run_state(self, run: int) -> RunState:
        """Where the workflow run with the id stands"""
        ...

    def open_pull_requests(self) -> list[PullRequest]:
        """The open pull requests, by number (the newest PULL_LIMIT)"""
        ...

    def merged_pull_requests(self, branches: Sequence[str]) -> list[MergedPull]:
        """The merged pull requests whose head branch is named one of branches, by number, with
        their head history (the newest MERGED_PER_BRANCH per name, the last HISTORY_LIMIT
        commits and force-pushes of each); one request for all the names, none for no name"""
        ...

    def active_runs(self, workflow: str) -> list[WorkflowRun]:
        """The workflow's runs on any branch that haven't finished (ACTIVE_STATUSES), newest
        first (the newest 100 of each status); Forbidden when the token can't read Actions"""
        ...


def _time(text: str) -> dt.datetime:
    when = dt.datetime.fromisoformat(text)
    if when.tzinfo is None:
        raise ReleaseError(f"GitHub sent a time without a zone: {text!r}")
    return when


def fit(text: str, limit: int, link: str) -> str:
    """The text whole when it is within limit characters; else cut at a line's end where one
    is near, and ended with a line saying so that links the full text, the two within limit"""
    if len(text) <= limit:
        return text
    tail = f"\n\n{CUT_MARK}\n_Cut to fit GitHub's limit of {limit:,} characters: the full text is at {link}_\n"
    room = limit - len(tail)
    if room <= 0:
        raise ReleaseError(f"the line ending a cut text is {len(tail)} characters, over the limit of {limit}")
    end = text.rfind("\n", 0, room)
    return text[: end if end > room // 2 else room] + tail


def cut_from(stored: str, wanted: str, limit: int) -> bool:
    """Whether stored is wanted as fit cut it to limit, with the link its last line gives"""
    _, mark, line = stored.partition(f"\n\n{CUT_MARK}\n")
    link = line.rpartition(" the full text is at ")[2].removesuffix("_")
    return bool(mark) and len(wanted) > limit and stored == fit(wanted, limit, link).strip()


def labelled_command(label: str) -> tuple[str, ...]:
    """gh's arguments that list the issues with the label, open and closed, the newest 100"""
    fields = "number,title,body,state,closedAt,labels"
    return ("issue", "list", "--label", label, "--state", "all", "--json", fields, "--limit", "100")


def parse_labelled(text: str) -> list[Issue]:
    """labelled_command's output, newest first"""
    found = json.loads(text)
    issues = [
        Issue(
            int(i["number"]),
            i["title"],
            i["body"],
            None if i["state"] == "OPEN" else _time(i["closedAt"]),
            tuple(str(label["name"]) for label in i["labels"]),
        )
        for i in found
    ]
    return sorted(issues, key=lambda i: i.number, reverse=True)


class GhCli:
    """GitHub through the gh CLI, authenticated by GH_TOKEN in Actions. A body or release
    notes go on stdin, never in argv, which Linux caps at 128 KiB an argument (#499); one
    over GitHub's limit is cut to fit, linking the changelog that holds the full text"""

    def __init__(
        self, root: Path, gh: str = "gh", changelog: str = "CHANGELOG.md", env: Mapping[str, str] | None = None
    ) -> None:
        """env, when given, is gh's whole environment (`shipmill gh`'s, with the App's token);
        else gh gets this process's"""
        self.root = root
        self.gh = gh
        self.changelog = changelog
        self.env = None if env is None else dict(env)
        self._url: str | None = None

    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        # gh reads and writes UTF-8, whatever the locale says
        return subprocess.run(
            [self.gh, *args], capture_output=True, text=True, encoding="utf-8", cwd=self.root, input=stdin, env=self.env
        )

    def _changelog_at(self, ref: str) -> str:
        """The changelog's URL at the ref; the repository's URL is asked of gh once"""
        if self._url is None:
            url = self._gh("repo", "view", "--json", "url", "--jq", ".url").strip()
            if not url.startswith("https://"):
                raise ReleaseError(f"gh repo view printed {url!r}, not the repository's URL")
            self._url = url
        return f"{self._url}/blob/{ref}/{self.changelog}"

    def _fit(self, text: str, limit: int, ref: str = "HEAD") -> str:
        return text if len(text) <= limit else fit(text, limit, self._changelog_at(ref))

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        proc = self._run(*args, stdin=stdin)
        if proc.returncode != 0:
            error = proc.stderr.strip()
            message = f"gh {' '.join(args[:3])} failed: {error}"
            # gh prints "<GitHub's message> (HTTP 403)"; a 403 for a rate limit isn't a permission
            if re.search(r"\bHTTP 403\b", error) and "rate limit" not in error.lower():
                raise Forbidden(message)
            raise ReleaseError(message)
        return proc.stdout

    def open_issues(self, label: str) -> list[str]:
        found = json.loads(
            self._gh(
                "issue",
                "list",
                "--label",
                label,
                "--state",
                "open",
                "--json",
                "number,title",
                "--limit",
                "50",
            )
        )
        return [f"#{i['number']} {i['title']}" for i in found]

    def milestone(self, title: str) -> Milestone | None:
        found = json.loads(self._gh("api", "repos/{owner}/{repo}/milestones?state=all&per_page=100"))
        for m in found:
            if m["title"] == title:
                return Milestone(int(m["open_issues"]), int(m["closed_issues"]))
        return None

    def open_milestones(self) -> list[OpenMilestone]:
        path = f"repos/{{owner}}/{{repo}}/milestones?state=open&per_page={OPEN_MILESTONE_LIMIT}"
        return parse_open_milestones(json.loads(self._gh("api", path)))

    def milestone_issues(self, title: str) -> MilestoneIssues:
        found = json.loads(
            self._gh(
                "issue", "list", "--milestone", title, "--state", "all", "--json", "number,body,url",
                "--limit", str(MILESTONE_LIMIT),
            )
        )  # fmt: skip
        return parse_milestone_issues(found, title)

    def issue_closes(self, numbers: Sequence[int]) -> list[IssueClose]:
        wanted = sorted(set(numbers))
        closes: list[IssueClose] = []
        for start in range(0, len(wanted), CLOSES_PER_QUERY):
            chunk = wanted[start : start + CLOSES_PER_QUERY]
            aliases = " ".join(f"i{n}: issue(number: {n}) {{ ...closed }}" for n in chunk)
            query = (
                "query($owner: String!, $name: String!) "
                f"{{ repository(owner: $owner, name: $name) {{ {aliases} }} }} {_CLOSE_FRAGMENT}"
            )
            found = json.loads(
                self._gh("api", "graphql", "-F", "owner={owner}", "-F", "name={repo}", "-f", f"query={query}")
            )
            closes.extend(parse_issue_closes(found, chunk))
        return closes

    def closed_since(self, day: dt.date | None) -> list[int]:
        search = ["--search", f"closed:>={day.isoformat()}"] if day is not None else []
        found = json.loads(
            self._gh(
                "issue", "list", "--state", "closed", *search, "--json", "number", "--limit", str(CLOSED_LIMIT),
            )
        )  # fmt: skip
        return parse_closed(found, day)

    def requester_votes(self, numbers: Sequence[int]) -> list[RequesterVotes]:
        wanted = sorted(set(numbers))
        votes: list[RequesterVotes] = []
        for start in range(0, len(wanted), VOTES_PER_QUERY):
            chunk = wanted[start : start + VOTES_PER_QUERY]
            aliases = " ".join(f"i{n}: issue(number: {n}) {{ ...votes }}" for n in chunk)
            query = (
                "query($owner: String!, $name: String!) "
                f"{{ repository(owner: $owner, name: $name) {{ {aliases} }} }} {_VOTES_FRAGMENT}"
            )
            found = json.loads(
                self._gh("api", "graphql", "-F", "owner={owner}", "-F", "name={repo}", "-f", f"query={query}")
            )
            votes.extend(parse_requester_votes(found, chunk))
        return votes

    def app_id(self, slug: str) -> int:
        found = self._api(f"apps/{slug}")
        if not isinstance(found, dict) or not isinstance(found.get("id"), int):
            raise ReleaseError(f"gh api apps/{slug} printed no App id: {str(found)[:300]}")
        return int(found["id"])

    def merge_commit(self, pr: int) -> str:
        found = json.loads(self._gh("pr", "view", str(pr), "--json", "state,mergeCommit"))
        if found["state"] != "MERGED" or not found.get("mergeCommit"):
            raise ReleaseError(f"#{pr} is not merged ({found['state']}): a hotfix takes merged pull requests")
        return str(found["mergeCommit"]["oid"])

    def create_release(self, tag: str, title: str, notes: str, prerelease: bool) -> None:
        args = ["release", "create", tag, "--verify-tag", "--title", title, "--notes-file", "-"]
        if prerelease:
            args.append("--prerelease")
        self._gh(*args, stdin=self._fit(notes, NOTES_LIMIT, tag))

    def dispatch(self, workflow: str, ref: str, tag: str, inputs: Mapping[str, str] | None = None) -> str | None:
        fields = [f"tag={tag}", *(f"{k}={v}" for k, v in (inputs or {}).items())]
        out = self._gh("workflow", "run", workflow, "--ref", ref, *(a for f in fields for a in ("-f", f)))
        found = re.search(r"https://\S+/actions/runs/\d+", out)  # gh prints the run's URL when GitHub returns it
        return found[0] if found else None

    def find_issue(self, marker: str) -> Issue | None:
        found = json.loads(
            self._gh("issue", "list", "--state", "open", "--json", "number,title,body", "--limit", "500")
        )
        hits = [Issue(int(i["number"]), i["title"], i["body"]) for i in found if marker in i["body"]]
        return min(hits, key=lambda i: i.number) if hits else None

    def label_names(self) -> frozenset[str]:
        return frozenset(
            str(label["name"]) for label in json.loads(self._gh("label", "list", "--json", "name", "--limit", "1000"))
        )

    def _create_labels(self, labels: Sequence[str]) -> None:
        """Create each label the repository lacks, as `gh issue create --label` won't. One
        another run created meanwhile (GitHub's 422, "already exists") is there: success"""
        if not labels:
            return
        have = self.label_names()
        for label in labels:
            if label not in have:
                described = _LABEL_DESCRIPTIONS.get(label, "Opened by shipmill; holds releases while open")
                proc = self._run("label", "create", label, "--description", described)
                if proc.returncode != 0 and "already exists" not in proc.stderr:
                    raise ReleaseError(f"gh label create {label} failed: {proc.stderr.strip()}")

    def create_issue(self, title: str, body: str, labels: Sequence[str] = ()) -> int:
        self._create_labels(labels)
        args = [a for label in labels for a in ("--label", label)]
        url = self._gh(
            "issue", "create", "--title", title, "--body-file", "-", *args, stdin=self._fit(body, BODY_LIMIT)
        )
        url = url.strip()
        number = url.rsplit("/", 1)[-1]
        if not number.isdigit():
            raise ReleaseError(f"gh issue create printed {url!r}, not an issue URL")
        return int(number)

    def update_issue(self, number: int, title: str, body: str, labels: Sequence[str] = ()) -> None:
        self._create_labels(labels)
        args = [a for label in labels for a in ("--add-label", label)]
        self._gh(
            "issue", "edit", str(number), "--title", title, "--body-file", "-", *args, stdin=self._fit(body, BODY_LIMIT)
        )

    def close_issue(self, number: int, comment: str) -> None:
        # `gh issue close --comment` takes the text in argv only: comment first, as it does
        self.comment_issue(number, comment)
        self._gh("issue", "close", str(number))

    def comment_issue(self, number: int, body: str) -> None:
        self._gh("issue", "comment", str(number), "--body-file", "-", stdin=self._fit(body, BODY_LIMIT))

    def remove_label(self, number: int, label: str) -> None:
        self._gh("issue", "edit", str(number), "--remove-label", label)

    def labelled_issues(self, label: str) -> list[Issue]:
        return parse_labelled(self._gh(*labelled_command(label)))

    def open_labelled_issues(self, label: str) -> list[Issue]:
        found = json.loads(
            self._gh(
                "issue", "list", "--label", label, "--state", "open", "--json", "number,title,body",
                "--limit", str(OPEN_LIMIT),
            )
        )  # fmt: skip
        issues = [Issue(int(i["number"]), i["title"], i["body"]) for i in found]
        return sorted(issues, key=lambda i: i.number, reverse=True)

    def _api(self, *args: str) -> Any:
        return json.loads(self._gh("api", *args))

    def pull_change(self, number: int) -> PullChange:
        """The pull request's merge base, head, and every file it changes with its patch (spec 030)"""
        pull = self._api(f"repos/{{owner}}/{{repo}}/pulls/{number}")
        head, tip = str(pull["head"]["sha"]), str(pull["base"]["sha"])
        compare = f"repos/{{owner}}/{{repo}}/compare/{tip}...{head}"
        base = self._gh("api", compare, "--jq", ".merge_base_commit.sha").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise ReleaseError(f"gh api {compare} named no merge base, got {base!r}")
        files_of = f"repos/{{owner}}/{{repo}}/pulls/{number}/files?per_page=100"
        listed = self._gh("api", "--paginate", files_of, "--jq", ".[]")  # one file per line, every page
        files = []
        for line in listed.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            patch = entry.get("patch")
            if patch is None and entry.get("changes") == 0:  # a rename without changes: an empty diff
                patch = ""
            files.append(
                FileChange(
                    str(entry["filename"]),
                    str(entry["status"]),
                    None if patch is None else str(patch),
                    None if entry.get("previous_filename") is None else str(entry["previous_filename"]),
                )
            )
        return PullChange(number, base, head, tuple(files))

    def pull_of(self, selector: str | None) -> str:
        """The URL of the pull request gh resolves selector to (a branch; None for the current
        branch's), as `gh pr view` does for `gh pr merge`"""
        return self._gh("pr", "view", *([] if selector is None else [selector]), "--json", "url", "--jq", ".url")

    def _pages(self, path: str) -> list[Any]:
        """Every entry of a listing, across its pages, one JSON value a line"""
        listed = self._gh("api", "--paginate", path, "--jq", ".[]")
        return [json.loads(line) for line in listed.splitlines() if line.strip()]

    def credit_pull(self, number: int) -> Pull:
        """The pull request's author, title, and body (spec 049)"""
        return Pull.parse(self._api(f"repos/{{owner}}/{{repo}}/pulls/{number}"))

    def credit_reviews(self, number: int) -> list[Review]:
        found = self._pages(f"repos/{{owner}}/{{repo}}/pulls/{number}/reviews?per_page=100")
        return [Review.parse(r) for r in found if r["state"] != "PENDING"]  # a draft review isn't one yet

    def credit_commits(self, number: int) -> list[Commit]:
        return [Commit.parse(c) for c in self._pages(f"repos/{{owner}}/{{repo}}/pulls/{number}/commits?per_page=100")]

    def credit_account(self, login: str) -> Account:
        return Account.parse(self._api(f"users/{quote(login)}"))

    def credit_messages(self) -> Messages:
        return Messages.parse(self._api("repos/{owner}/{repo}"))

    def text_at(self, sha: str, path: str) -> str:
        """The file's text at a commit, through the contents API; a missing file fails"""
        where = f"repos/{{owner}}/{{repo}}/contents/{quote(path)}?ref={sha}"
        return self._gh("api", "-H", "Accept: application/vnd.github.raw+json", where)

    def deployments(self, environment: str) -> list[Deployment]:
        found = self._api(
            "-X", "GET", "repos/{owner}/{repo}/deployments", "-f", f"environment={environment}", "-f", "per_page=100"
        )
        deployments = [Deployment(int(d["id"]), str(d["ref"]), str(d["sha"]), _time(d["created_at"])) for d in found]
        return sorted(deployments, key=lambda d: d.id, reverse=True)

    def deployment_statuses(self, deployment: int) -> list[DeploymentStatus]:
        found = self._api(
            "-X", "GET", f"repos/{{owner}}/{{repo}}/deployments/{deployment}/statuses", "-f", "per_page=100"
        )
        statuses = [
            DeploymentStatus(int(s["id"]), DeploymentState(s["state"]), _time(s["created_at"]), s["description"] or "")
            for s in found
        ]
        return sorted(statuses, key=lambda s: s.id)

    def create_deployment_status(self, deployment: int, state: DeploymentState, description: str) -> None:
        self._gh(
            "api",
            "-X",
            "POST",
            f"repos/{{owner}}/{{repo}}/deployments/{deployment}/statuses",
            "-f",
            f"state={state}",
            "-f",
            f"description={description}",
            "-F",
            "auto_inactive=false",
        )

    def workflow_runs(self, workflow: str, ref: str) -> list[WorkflowRun]:
        found = self._api(
            "-X", "GET", f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs", "-f", f"branch={ref}",
            "-f", "per_page=100",
        )  # fmt: skip
        runs = [WorkflowRun(int(r["id"]), str(r["status"]), _time(r["created_at"])) for r in found["workflow_runs"]]
        return sorted(runs, key=lambda r: r.id, reverse=True)

    def active_runs(self, workflow: str) -> list[WorkflowRun]:
        runs = {}
        # in_progress is asked again last: a run approved after the first in_progress query and
        # before the waiting one would otherwise be in neither list
        for status in (*ACTIVE_STATUSES, "in_progress"):
            found = self._api(
                "-X", "GET", f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs", "-f", f"status={status}",
                "-f", "per_page=100",
            )  # fmt: skip
            for r in found["workflow_runs"]:
                runs[int(r["id"])] = WorkflowRun(int(r["id"]), str(r["status"]), _time(r["created_at"]))
        return sorted(runs.values(), key=lambda r: r.id, reverse=True)

    def run_state(self, run: int) -> RunState:
        found = self._api("-X", "GET", f"repos/{{owner}}/{{repo}}/actions/runs/{run}")
        return RunState(str(found["status"]), str(found["conclusion"] or ""))

    def open_pull_requests(self) -> list[PullRequest]:
        found = json.loads(
            self._gh(
                "pr", "list", "--state", "open", "--json", "number,headRefName", "--limit", str(PULL_LIMIT),
            )
        )  # fmt: skip
        if not isinstance(found, list):
            raise ReleaseError(f"gh pr list printed {type(found).__name__}, not a JSON array")
        pulls = []
        for pr in found:
            if (
                not isinstance(pr, dict)
                or not isinstance(pr.get("number"), int)
                or not isinstance(pr.get("headRefName"), str)
            ):
                raise ReleaseError(f"gh pr list printed {pr!r}: a pull request needs a number and a headRefName")
            pulls.append(PullRequest(pr["number"], pr["headRefName"]))
        return sorted(pulls, key=lambda p: p.number)

    def merged_pull_requests(self, branches: Sequence[str]) -> list[MergedPull]:
        names = sorted(set(branches))
        pulls: dict[int, MergedPull] = {}
        for start in range(0, len(names), BRANCHES_PER_QUERY):
            chunk = names[start : start + BRANCHES_PER_QUERY]
            params = "".join(f", $b{i}: String!" for i in range(len(chunk)))
            aliases = " ".join(
                f"b{i}: pullRequests(headRefName: $b{i}, states: MERGED, last: {MERGED_PER_BRANCH}) {{ ...merged }}"
                for i in range(len(chunk))
            )
            query = (
                f"query($owner: String!, $name: String!{params}) "
                f"{{ repository(owner: $owner, name: $name) {{ {aliases} }} }} {_MERGED_FRAGMENT}"
            )
            variables = [a for i, n in enumerate(chunk) for a in ("-f", f"b{i}={n}")]
            found = json.loads(
                self._gh(
                    "api", "graphql", "-F", "owner={owner}", "-F", "name={repo}", "-f", f"query={query}", *variables,
                )
            )  # fmt: skip
            pulls.update((pull.number, pull) for pull in parse_merged_pulls(found, len(chunk)))
        return [pulls[n] for n in sorted(pulls)]


def parse_merged_pulls(found: Any, aliases: int) -> list[MergedPull]:
    """The `b<i>` connections of merged_pull_requests' GraphQL answer; anything else is refused,
    since a pull request misread could prove a branch landed that didn't"""

    def refuse(what: str) -> ReleaseError:
        return ReleaseError(f"gh api graphql printed {what} for the merged pull requests: {str(found)[:300]}")

    if not isinstance(found, dict) or found.get("errors"):
        raise refuse("errors or no object")
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        raise refuse("no repository")
    pulls: dict[int, MergedPull] = {}
    for i in range(aliases):
        connection = repository.get(f"b{i}")
        if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
            raise refuse(f"no b{i} connection")
        for node in connection["nodes"]:
            pull = _merged_pull(node)
            if pull is None:
                raise refuse(
                    "a pull request without a number, headRefName, baseRefName, headRefOid, commits, or timeline"
                )
            pulls[pull.number] = pull
    return [pulls[n] for n in sorted(pulls)]


def _oid(holder: Any, key: str) -> str | None:
    """holder[key]["oid"]; None when holder[key] is null (a commit GitHub no longer has)"""
    if not isinstance(holder, dict):
        raise ReleaseError(f"gh api graphql printed {holder!r} where an object holds {key}")
    value = holder.get(key)
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("oid"), str) or not value["oid"]:
        raise ReleaseError(f"gh api graphql printed {holder!r}: {key} needs an oid")
    return str(value["oid"])


def _merged_pull(node: Any) -> MergedPull | None:
    if not isinstance(node, dict):
        return None
    number, head, oid = node.get("number"), node.get("headRefName"), node.get("headRefOid")
    base, commits, timeline = node.get("baseRefName"), node.get("commits"), node.get("timelineItems")
    if (
        not isinstance(number, int)
        or not isinstance(head, str)
        or not isinstance(base, str)
        or not isinstance(oid, str)
        or not isinstance(commits, dict)
        or not isinstance(commits.get("nodes"), list)
        or not isinstance(timeline, dict)
        or not isinstance(timeline.get("nodes"), list)
    ):
        return None
    heads = {oid}
    for c in commits["nodes"]:
        sha = _oid(c, "commit")
        if sha is None:
            raise ReleaseError(f"gh api graphql printed {c!r} for #{number}: a commit needs an oid")
        heads.add(sha)
    for event in timeline["nodes"]:
        if not isinstance(event, dict):
            raise ReleaseError(f"gh api graphql printed {event!r} for #{number}: not a force-push event")
        for key in ("beforeCommit", "afterCommit"):
            sha = _oid(event, key)
            if sha is not None:
                heads.add(sha)
    return MergedPull(number, head, frozenset(heads), base)


_ISSUE_URL = re.compile(r"^https://[^/]+/([\w.-]+/[\w.-]+)/issues/(\d+)$")


def parse_milestone_issues(found: Any, title: str) -> MilestoneIssues:
    """`gh issue list --milestone --json number,body,url`'s output; the repository comes from
    the issues' URLs, so a milestone with no issue has none"""
    if not isinstance(found, list):
        raise ReleaseError(f"gh issue list --milestone {title} printed {type(found).__name__}, not a JSON array")
    if len(found) >= MILESTONE_LIMIT:
        raise ReleaseError(f"milestone {title} holds {MILESTONE_LIMIT} issues or more; shipmill reads fewer")
    repos = set()
    issues = []
    for i in found:
        url = i.get("url") if isinstance(i, dict) else None
        link = _ISSUE_URL.match(url) if isinstance(url, str) else None
        if link is None or not isinstance(i.get("number"), int) or not isinstance(i.get("body"), str):
            raise ReleaseError(f"gh issue list printed {i!r}: an issue needs a number, a body, and an issue URL")
        if int(link.group(2)) != i["number"]:
            raise ReleaseError(f"gh issue list printed #{i['number']} with the URL {url}")
        repos.add(link.group(1))
        issues.append((int(i["number"]), str(i["body"])))
    if len(repos) > 1:
        raise ReleaseError(f"milestone {title} lists issues of several repositories: {sorted(repos)}")
    return MilestoneIssues(repos.pop() if repos else "", tuple(sorted(issues)))


def parse_open_milestones(found: Any) -> list[OpenMilestone]:
    """`gh api repos/<repo>/milestones?state=open`'s answer, by number; a full page is
    refused, since a milestone past it would read as not open"""
    if not isinstance(found, list):
        raise ReleaseError(f"gh api milestones printed {type(found).__name__}, not a JSON array")
    if len(found) >= OPEN_MILESTONE_LIMIT:
        raise ReleaseError(f"the repository has {OPEN_MILESTONE_LIMIT} open milestones or more; shipmill reads fewer")
    milestones = []
    for m in found:
        fields = m if isinstance(m, dict) else {}
        number, title, count = fields.get("number"), fields.get("title"), fields.get("open_issues")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or not isinstance(title, str)
            or fields.get("state") != "open"
        ):
            raise ReleaseError(
                f"gh api milestones printed {m!r}: an open milestone needs a number, a title, and open_issues"
            )
        milestones.append(OpenMilestone(number, title, count))
    return sorted(milestones, key=lambda m: m.number)


def parse_issue_closes(found: Any, numbers: Sequence[int]) -> list[IssueClose]:
    """The `i<N>` issues of issue_closes' GraphQL answer; anything else is refused, since a
    close misread could prove a goal shipped that didn't"""

    def refuse(what: str) -> ReleaseError:
        return ReleaseError(f"gh api graphql printed {what} for the issues' closes: {str(found)[:300]}")

    if not isinstance(found, dict) or found.get("errors"):
        raise refuse("errors or no object")
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        raise refuse("no repository")
    closes = []
    for n in numbers:
        node = repository.get(f"i{n}")
        if not isinstance(node, dict) or node.get("number") != n:
            raise refuse(f"no issue #{n}")
        closes.append(_issue_close(node))
    return closes


def _nodes(holder: Any, key: str, number: int) -> list[Any]:
    connection = holder.get(key)
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        raise ReleaseError(f"gh api graphql printed no {key} for #{number}")
    return list(connection["nodes"])


def _merged_oid(pr: Any, number: int) -> str | None:
    """A merged pull request's merge commit; None for one not merged"""
    if not isinstance(pr, dict) or not isinstance(pr.get("merged"), bool):
        raise ReleaseError(f"gh api graphql printed {pr!r} for #{number}: a pull request needs merged")
    if not pr["merged"]:
        return None
    oid = _oid(pr, "mergeCommit")
    if oid is None:
        raise ReleaseError(f"gh api graphql printed {pr!r} for #{number}: a merged pull request needs a mergeCommit")
    return oid


def _issue_close(node: dict[str, Any]) -> IssueClose:
    number = int(node["number"])
    state, reason = node.get("state"), node.get("stateReason")
    if state == "OPEN":
        return IssueClose(number, None, None, (), ())
    if state != "CLOSED" or reason not in set(CloseReason):
        raise ReleaseError(f"gh api graphql printed state {state!r}, stateReason {reason!r} for #{number}")
    fixes: list[str] = []
    closed_at = None
    events = _nodes(node, "timelineItems", number)
    if events:
        event = events[-1]
        if not isinstance(event, dict) or not isinstance(event.get("createdAt"), str):
            raise ReleaseError(f"gh api graphql printed {event!r} for #{number}: a close event needs createdAt")
        closed_at = _time(event["createdAt"])
        closer = event.get("closer")
        if isinstance(closer, dict) and closer.get("__typename") == "PullRequest":
            if (oid := _merged_oid(closer, number)) is not None:
                fixes.append(oid)
        elif isinstance(closer, dict) and closer.get("__typename") == "Commit":
            if not isinstance(closer.get("oid"), str) or not closer["oid"]:
                raise ReleaseError(f"gh api graphql printed {closer!r} for #{number}: a commit needs an oid")
            fixes.append(str(closer["oid"]))
        elif closer is not None and not isinstance(closer, dict):
            raise ReleaseError(f"gh api graphql printed {closer!r} for #{number}: not a closer")
    for pr in _nodes(node, "closedByPullRequestsReferences", number):
        if (oid := _merged_oid(pr, number)) is not None and oid not in fixes:
            fixes.append(oid)
    comments = []
    for c in _nodes(node, "comments", number):
        if (
            not isinstance(c, dict)
            or not isinstance(c.get("createdAt"), str)
            or not isinstance(c.get("body"), str)
            or not isinstance(c.get("authorAssociation"), str)
        ):
            raise ReleaseError(f"gh api graphql printed {c!r} for #{number}: a comment needs createdAt, body, author")
        author = c.get("author")  # null for a deleted account
        if author is not None and (not isinstance(author, dict) or not isinstance(author.get("login"), str)):
            raise ReleaseError(f"gh api graphql printed {author!r} for #{number}: an author needs a login")
        login = str(author["login"]) if author else "ghost"
        bot = isinstance(author, dict) and author.get("__typename") == "Bot"
        comments.append(IssueComment(login, bot, c["authorAssociation"], _time(c["createdAt"]), c["body"]))
    return IssueClose(number, CloseReason(reason), closed_at, tuple(fixes), tuple(comments))


def parse_closed(found: Any, day: dt.date | None) -> list[int]:
    """`gh issue list --state closed --json number`'s output, by number; a full page is
    refused, since an issue past it would read as fixed by nothing"""
    since = f" closed since {day}" if day is not None else " closed"
    if not isinstance(found, list):
        raise ReleaseError(f"gh issue list printed {type(found).__name__}, not a JSON array")
    if len(found) >= CLOSED_LIMIT:
        raise ReleaseError(f"the repository has {CLOSED_LIMIT} issues{since} or more; shipmill reads fewer")
    numbers = []
    for i in found:
        number = i.get("number") if isinstance(i, dict) else None
        if not isinstance(number, int) or isinstance(number, bool):
            raise ReleaseError(f"gh issue list printed {i!r}: an issue needs a number")
        numbers.append(number)
    return sorted(numbers)


def parse_requester_votes(found: Any, numbers: Sequence[int]) -> list[RequesterVotes]:
    """The `i<N>` issues of requester_votes' GraphQL answer; anything else is refused"""

    def refuse(what: str) -> ReleaseError:
        return ReleaseError(f"gh api graphql printed {what} for the requesters' votes: {str(found)[:300]}")

    if not isinstance(found, dict) or found.get("errors"):
        raise refuse("errors or no object")
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        raise refuse("no repository")
    votes = []
    for n in numbers:
        node = repository.get(f"i{n}")
        if not isinstance(node, dict) or node.get("number") != n:
            raise refuse(f"no issue #{n}")
        votes.append(_requester_votes(node, n))
    return votes


def _total(holder: dict[str, Any], key: str, number: int) -> int:
    """A connection's totalCount, which says whether its nodes are all of it"""
    total = holder[key].get("totalCount")
    if not isinstance(total, int) or isinstance(total, bool):
        raise ReleaseError(f"gh api graphql printed no {key} totalCount for #{number}")
    return total


def _requester_votes(node: dict[str, Any], number: int) -> RequesterVotes:
    author = node.get("author")  # null, or the ghost user, for a deleted account
    if author is not None and (not isinstance(author, dict) or not isinstance(author.get("login"), str)):
        raise ReleaseError(f"gh api graphql printed {author!r} for #{number}: an author needs a login")
    person = author is not None and author.get("__typename") != "Bot" and author["login"] != GHOST
    requester = str(author["login"]) if author is not None and person else None
    comments = []
    nodes = _nodes(node, "comments", number)
    for c in nodes:
        if not isinstance(c, dict) or not isinstance(c.get("body"), str):
            raise ReleaseError(f"gh api graphql printed {c!r} for #{number}: a comment needs a body")
        logins = set()
        reactions = _nodes(c, "reactions", number)
        for r in reactions:
            user = r.get("user") if isinstance(r, dict) else None  # null for a deleted account
            if user is not None and (not isinstance(user, dict) or not isinstance(user.get("login"), str)):
                raise ReleaseError(f"gh api graphql printed {r!r} for #{number}: a reaction's user needs a login")
            if user is not None:
                logins.add(str(user["login"]))
        more = _total(c, "reactions", number) > len(reactions)
        comments.append(Voted(c["body"].partition("\n")[0], frozenset(logins), more))
    return RequesterVotes(number, requester, tuple(comments), _total(node, "comments", number) > len(nodes))
