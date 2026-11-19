"""`shipmill review history <N>` (spec 073): the history of the files pull request #N touches,
read from the checkout and GitHub only (D-6), for the PR reviewer to check the change against.

Four kinds, in this order: reverts, settled decisions, incidents, and open pull requests. This
build fills reverts and open pull requests; settled decisions and incidents print `none` until
their build (S-073-2, S-073-3). Text from an author who isn't an OWNER, MEMBER, COLLABORATOR,
or the App is never printed (D-16). A failed read exits 2 and prints nothing, never a partial
pack (S-073-8)"""

import datetime as dt
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from shipmill.errors import ReleaseError
from shipmill.github import Missing
from shipmill.gitrepo import REMOTE, Git

KINDS = ("reverts", "settled_decisions", "incidents", "open_pull_requests")  # the pack's order (S-073-5)
NAMES = {
    "reverts": "reverts",
    "settled_decisions": "settled decisions",
    "incidents": "incidents",
    "open_pull_requests": "open pull requests",
}
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})  # D-16, with the App
UNTRUSTED = "(untrusted author, text left out)"
DAYS = 180
LIMIT = 10
FILES_SHOWN = 5  # an item's shared files the text names before `and K more`
TITLE_CHARS = 200  # a title is cut here in the text, so one item stays one short line
OPEN_PER_PAGE = 100
OPEN_PAGES = 10  # 1,000 open pull requests at most; a repository with more is refused
FILES_PER_PULL = 100  # an open pull request's files read with it; one with more is read on its own
PULLS_PER_QUERY = 50  # merged pull requests read per GraphQL query
SHA = re.compile(r"[0-9a-f]{7,40}")
# git's revert message, and the line GitHub's Revert button writes in a revert pull request's
# body (spec 058's reading)
REVERTS_COMMIT = re.compile(r"^This reverts commit ([0-9a-f]{7,40})\b", re.MULTILINE)
REVERTS_PULL = re.compile(r"^\s*Reverts (?:([\w.-]+/[\w.-]+))?#([1-9][0-9]*)\s*$")
SQUASHED = re.compile(r" \(#([1-9][0-9]*)\)$")  # a squash merge's subject ends with its number
MERGED = re.compile(r"^Merge pull request #([1-9][0-9]*) from ")


@dataclass(frozen=True, slots=True)
class Author:
    """Who wrote a pull request: its login (None for a deleted account), GitHub's
    authorAssociation, and whether the account is a bot"""

    login: str | None
    association: str
    bot: bool


@dataclass(frozen=True, slots=True)
class PullText:
    """A pull request a squash or merge subject on the default branch names"""

    number: int
    title: str
    body: str
    merged: bool
    author: Author


@dataclass(frozen=True, slots=True)
class OpenPull:
    """An open pull request; files is None when it changes more than FILES_PER_PULL files,
    which are then read on their own"""

    number: int
    title: str
    head: str
    created: dt.datetime
    author: Author
    files: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class Repository:
    """The repository's owner/name, its default branch, and its open pull requests"""

    slug: str
    default: str
    pulls: tuple[OpenPull, ...]


class Reads(Protocol):
    """What review history asks of GitHub, reads only; GhReads is the real one, tests pass a fake"""

    def touched(self, number: int) -> tuple[str, ...]:
        """The files the pull request changes; Missing when GitHub has no such pull request"""
        ...

    def repository(self) -> Repository: ...

    def pulls(self, numbers: Sequence[int]) -> Mapping[int, PullText]:
        """The pull requests of numbers GitHub has; a number it has none for is left out"""
        ...

    def app_id(self, slug: str) -> int:
        """The id of the App whose slug this is; Missing when there is no such App"""
        ...


@dataclass(frozen=True, slots=True)
class Window:
    """What the pack reads: --days back from --before's committer date, or from now"""

    days: int
    limit: int
    start: dt.datetime
    end: dt.datetime
    before: str | None  # the --before commit's full SHA

    @classmethod
    def of(cls, git: Git, days: int, limit: int, before: str | None, now: dt.datetime) -> Window:
        """S-073-8: a --days or --limit below 1, or a --before that isn't a commit of the
        checkout, is refused naming the fix, before any read"""
        if days < 1:
            raise ReleaseError(
                f"--days {days}: give the days of history to read, a whole number from 1 (default {DAYS})"
            )
        if limit < 1:
            raise ReleaseError(
                f"--limit {limit}: give the most items per kind, a whole number from 1 (default {LIMIT})"
            )
        sha = None
        end = now
        if before is not None:
            if not SHA.fullmatch(before) or not git.ok("rev-parse", "--verify", "--quiet", f"{before}^{{commit}}"):
                raise ReleaseError(
                    f"--before {before!r} is no commit of the checkout {git.root}: name a commit's SHA it holds,"
                    f" or `git -C {git.root} fetch {REMOTE}` first"
                )
            sha = git.sha(before)
            end = git.commit_time(sha)
        return cls(days, limit, end - dt.timedelta(days=days), end, sha)


@dataclass(slots=True)
class Item:
    """One history item; fields holds what its kind names, text a trusted author's"""

    kind: str
    date: dt.datetime
    trusted: bool
    fields: dict[str, Any]
    id: str = ""


@dataclass(frozen=True, slots=True)
class Pack:
    number: int
    files: tuple[str, ...]
    window: Window
    shown: Mapping[str, tuple[Item, ...]]
    matched: Mapping[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """S-073-5: one object, a key per kind holding its items, each with its id"""
        record: dict[str, Any] = {
            "pull": self.number,
            "files": list(self.files),
            "days": self.window.days,
            "since": self.window.start.isoformat(),
            "until": self.window.end.isoformat(),
            "before": self.window.before,
        }
        for kind in KINDS:
            record[kind] = [{"id": item.id, **item.fields} for item in self.shown[kind]]
        record["matched"] = {kind: self.matched[kind] for kind in KINDS}
        return record

    def render(self) -> str:
        files = "file" if len(self.files) == 1 else "files"
        until = self.window.end.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
        held = f" (--before {self.window.before[:12]})" if self.window.before else ""
        lines = [
            f"#{self.number} touches {len(self.files)} {files}; history of {self.window.days} days to {until}{held}"
        ]
        for kind in KINDS:
            items = self.shown[kind]
            if not items:
                lines.append(f"{NAMES[kind]}: none")
                continue
            lines.append(f"{NAMES[kind]}:")
            lines.extend(f"- {_line(item)}" for item in items)
            if self.matched[kind] > len(items):
                lines.append(f"- H: {len(items)} of {self.matched[kind]} {NAMES[kind]} shown")
        return "\n".join(lines) + "\n"


def _shares(files: Sequence[str]) -> str:
    named = ", ".join(files[:FILES_SHOWN])
    more = len(files) - FILES_SHOWN
    return f"shares {named}" + (f" and {more} more" if more > 0 else "")


def _title(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= TITLE_CHARS else flat[: TITLE_CHARS - 1] + "…"


def _line(item: Item) -> str:
    f = item.fields
    who = "" if f["author"] is None else f", @{f['author']}"
    if item.kind == "revert":
        number = "" if f["pull"] is None else f" #{f['pull']}"
        undone = f": reverts {', '.join(f['reverts'])}" if f["reverts"] else ""
        when = item.date.astimezone(dt.UTC).strftime("%Y-%m-%d")
        named = f"{item.id} revert {f['commit'][:12]}{number} {_title(f['title'])}"
        return f"{named} ({when}{who}){undone}; {_shares(f['files'])}"
    where = ", ".join(part for part in (f["head"], who.removeprefix(", ")) if part)
    return f"{item.id} #{f['pull']} {_title(f['title'])} ({where}); {_shares(f['files'])}"


class Trust:
    """D-16: an OWNER, MEMBER, or COLLABORATOR, or the App of [agents] app_id; each bot's App
    is asked of GitHub once"""

    def __init__(self, reads: Reads, app_id: int | None) -> None:
        self._reads = reads
        self._app_id = app_id
        self._apps: dict[str, bool] = {}

    def __call__(self, author: Author) -> bool:
        if author.login is None:
            return False
        if author.association in TRUSTED:
            return True
        if not author.bot or self._app_id is None:
            return False
        slug = author.login.removesuffix("[bot]")
        if slug not in self._apps:
            try:
                self._apps[slug] = self._reads.app_id(slug) == self._app_id
            except Missing:
                self._apps[slug] = False
        return self._apps[slug]


@dataclass(frozen=True, slots=True)
class Logged:
    """A commit on the default branch that touched a touched file"""

    sha: str
    date: dt.datetime
    message: str
    files: tuple[str, ...]  # the touched files it changed

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0].strip()

    @property
    def pull(self) -> int | None:
        """The pull request its squash or merge subject names"""
        found = SQUASHED.search(self.subject) or MERGED.match(self.subject)
        return None if found is None else int(found.group(1))

    @property
    def reverted_commits(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(REVERTS_COMMIT.findall(self.message)))

    @property
    def is_revert(self) -> bool:
        return bool(self.reverted_commits) or self.subject.startswith('Revert "')


def log(git: Git, default: str, files: Sequence[str], window: Window) -> list[Logged]:
    """The commits on origin/<default> in the window that touched one of files, newest first,
    each with the files of those it changed. History is read in full, so a merge commit of a
    pull request shows beside its own commits; a path is matched literally"""
    tracking = f"refs/remotes/{REMOTE}/{default}"
    if not git.ok("rev-parse", "--verify", "--quiet", f"{tracking}^{{commit}}"):
        raise ReleaseError(
            f"the checkout {git.root} has no {REMOTE}/{default}: `git -C {git.root} fetch {REMOTE} {default}` first"
        )
    reader = Git(git.root)
    reader.env = {
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.quotePath",
        "GIT_CONFIG_VALUE_0": "false",
    }
    out = reader.run(
        "log",
        tracking,
        "--full-history",
        "--diff-merges=first-parent",
        "--name-only",
        "--format=%x1e%H%x1f%cI%x1f%B%x1f",
        f"--since={window.start.isoformat()}",
        f"--until={window.end.isoformat()}",
        "--",
        *files,
    )
    wanted = set(files)
    found = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f")
        if len(parts) != 4:
            raise ReleaseError(f"git log of {REMOTE}/{default} printed a record it can't read: {record[:200]!r}")
        sha, when, message, names = parts
        date = dt.datetime.fromisoformat(when)
        # S-073-7: with --before, only what came strictly before that commit
        if date < window.start or (window.before is not None and date >= window.end):
            continue
        shared = tuple(dict.fromkeys(name for name in names.splitlines() if name in wanted))
        if shared:
            found.append(Logged(sha, date, message.strip(), shared))
    return sorted(found, key=lambda c: c.date, reverse=True)


def _reverted_pulls(body: str, slug: str) -> tuple[str, ...]:
    """The `#M` a body's `Reverts #M` or `Reverts <this repo>#M` lines name"""
    numbers = []
    for line in body.splitlines():
        found = REVERTS_PULL.match(line)
        if found is not None and (found.group(1) is None or found.group(1).lower() == slug.lower()):
            numbers.append(f"#{found.group(2)}")
    return tuple(dict.fromkeys(numbers))


def reverts(commits: Sequence[Logged], pulls: Mapping[int, PullText], slug: str, trust: Trust) -> list[Item]:
    """S-073-1: a commit whose message reverts a commit, or whose subject starts `Revert "`, and
    a merged pull request whose body has a `Reverts #M` line, one item per commit"""
    items = []
    for commit in commits:
        number = commit.pull
        pull = None if number is None else pulls.get(number)
        undone_pulls = () if pull is None or not pull.merged else _reverted_pulls(pull.body, slug)
        if not commit.is_revert and not undone_pulls:
            continue
        # a commit no pull request names was pushed to the default branch, by someone who may
        trusted = True if pull is None else trust(pull.author)
        title = pull.title if pull is not None else commit.subject
        fields = {
            "kind": "revert",
            "commit": commit.sha,
            "pull": number if pull is not None else None,
            "title": title if trusted else UNTRUSTED,
            "reverts": [*undone_pulls, *(sha[:12] for sha in commit.reverted_commits)],
            "files": list(commit.files),
            "date": commit.date.isoformat(),
            "author": None if pull is None else pull.author.login,
            "trusted": trusted,
        }
        items.append(Item("revert", commit.date, trusted, fields))
    return items


def open_pulls(
    repository: Repository, number: int, touched: Sequence[str], window: Window, reads: Reads, trust: Trust
) -> list[Item]:
    """S-073-4: every other open pull request that changes a touched file, newest first; with
    --before, only those opened before it"""
    wanted = set(touched)
    items = []
    for pull in repository.pulls:
        if pull.number == number or pull.created >= window.end:
            continue
        changed = set(pull.files if pull.files is not None else reads.touched(pull.number)) & wanted
        shared = [name for name in touched if name in changed]
        if not shared:
            continue
        trusted = trust(pull.author)
        fields = {
            "kind": "open pull request",
            "pull": pull.number,
            "title": pull.title if trusted else UNTRUSTED,
            "head": pull.head if trusted else None,
            "author": pull.author.login,
            "files": shared,
            "date": pull.created.isoformat(),
            "trusted": trusted,
        }
        items.append(Item("open pull request", pull.created, trusted, fields))
    return sorted(items, key=lambda i: i.date, reverse=True)


def pack(git: Git, reads: Reads, number: int, window: Window, app_id: int | None) -> Pack:
    """Spec 073's history pack of pull request #number: every read first, then the ids, so a
    failed read leaves nothing printed"""
    if number < 1:
        raise ReleaseError(f"#{number} is no pull request: give its number, from 1")
    try:
        touched = reads.touched(number)
    except Missing:
        raise ReleaseError(
            f"GitHub has no pull request #{number} in this checkout's repo: give the number of an open"
            " or merged pull request, as `gh pr list` names it"
        ) from None
    repository = reads.repository()
    trust = Trust(reads, app_id)
    commits = log(git, repository.default, touched, window) if touched else []
    numbers = sorted({n for n in (c.pull for c in commits) if n is not None and n != number})
    pulls = reads.pulls(numbers) if numbers else {}
    found = {
        "reverts": reverts(commits, pulls, repository.slug, trust),
        "settled_decisions": [],  # S-073-2, a later build
        "incidents": [],  # S-073-3, a later build
        "open_pull_requests": open_pulls(repository, number, touched, window, reads, trust),
    }
    shown: dict[str, tuple[Item, ...]] = {}
    next_id = 1
    for kind in KINDS:
        kept = tuple(found[kind][: window.limit])
        for item in kept:
            item.id = f"H-{next_id}"
            next_id += 1
        shown[kind] = kept
    return Pack(number, touched, window, shown, {kind: len(found[kind]) for kind in KINDS})


def history(
    git: Git,
    reads: Callable[[], Reads],
    number: int,
    days: int,
    limit: int,
    before: str | None,
    app_id: int | None,
    now: dt.datetime,
    as_json: bool,
) -> str:
    """The pack as text, or as JSON with as_json; the window is checked before GitHub is asked"""
    window = Window.of(git, days, limit, before, now)
    built = pack(git, reads(), number, window, app_id)
    return json.dumps(built.to_json(), indent=2) + "\n" if as_json else built.render()


# --- GitHub through gh ---------------------------------------------------------------


class Gh(Protocol):
    """The gh calls GhReads makes; GhCli is one"""

    def graphql(self, query: str) -> Any: ...

    def graphql_numbers(self, query: str, numbers: int) -> Any: ...

    def pull_files(self, number: int) -> tuple[str, ...]: ...

    def app_id(self, slug: str) -> int: ...


_AUTHOR = "authorAssociation author { __typename login }"
_OPEN_QUERY = (
    "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {"
    " nameWithOwner defaultBranchRef { name }"
    f" pullRequests(states: OPEN, first: {OPEN_PER_PAGE}, after: AFTER,"
    " orderBy: {field: CREATED_AT, direction: DESC}) { pageInfo { hasNextPage endCursor }"
    f" nodes {{ number title headRefName createdAt {_AUTHOR}"
    f" files(first: {FILES_PER_PULL}) {{ totalCount nodes {{ path }} }} }} }} }} }}"
)
_PULL_FIELDS = f"number title body merged {_AUTHOR}"


def _refuse(what: str, found: Any) -> ReleaseError:
    return ReleaseError(f"gh api graphql printed {what}: {str(found)[:300]}")


def _author(node: Mapping[str, Any]) -> Author:
    association = node.get("authorAssociation")
    author = node.get("author")
    if not isinstance(association, str):
        raise _refuse("a pull request without its authorAssociation", node)
    if author is None:  # a deleted account, GitHub's ghost
        return Author(None, association, False)
    if not isinstance(author, dict) or not isinstance(author.get("login"), str):
        raise _refuse("a pull request's author without a login", node)
    return Author(str(author["login"]), association, author.get("__typename") == "Bot")


def _time(text: Any, node: Any) -> dt.datetime:
    if not isinstance(text, str):
        raise _refuse("a pull request without its time", node)
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def parse_open_page(found: Any) -> tuple[str, str, list[OpenPull], str | None]:
    """A page of the open pull requests: the repo's owner/name, its default branch, the pull
    requests, and the next page's cursor (None on the last); anything else is refused"""
    if not isinstance(found, dict) or found.get("errors"):
        raise _refuse("errors or no object for the open pull requests", found)
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict) or not isinstance(repository.get("nameWithOwner"), str):
        raise _refuse("no repository", found)
    branch = repository.get("defaultBranchRef")
    if not isinstance(branch, dict) or not isinstance(branch.get("name"), str) or not branch["name"]:
        raise _refuse("no default branch", repository)
    connection = repository.get("pullRequests")
    info = connection.get("pageInfo") if isinstance(connection, dict) else None
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(info, dict) or not isinstance(info.get("hasNextPage"), bool) or not isinstance(nodes, list):
        raise _refuse("no page of open pull requests", connection)
    pulls = []
    for node in nodes:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("number"), int)
            or not isinstance(node.get("title"), str)
            or not isinstance(node.get("headRefName"), str)
            or not isinstance(node.get("files"), dict)
            or not isinstance(node["files"].get("totalCount"), int)
            or not isinstance(node["files"].get("nodes"), list)
        ):
            raise _refuse("an open pull request without its number, title, head, or files", node)
        listed = node["files"]["nodes"]
        if not all(isinstance(f, dict) and isinstance(f.get("path"), str) for f in listed):
            raise _refuse("an open pull request's file without its path", node)
        files = tuple(str(f["path"]) for f in listed) if node["files"]["totalCount"] <= len(listed) else None
        created = _time(node.get("createdAt"), node)
        pulls.append(OpenPull(node["number"], node["title"], node["headRefName"], created, _author(node), files))
    cursor = info.get("endCursor") if info["hasNextPage"] else None
    if info["hasNextPage"] and not isinstance(cursor, str):
        raise _refuse("a next page without its cursor", info)
    return str(repository["nameWithOwner"]), str(branch["name"]), pulls, cursor


def parse_pulls(found: Any, numbers: Sequence[int]) -> dict[int, PullText]:
    """The `n<i>` pull requests of a pulls query; a null alias, which graphql_numbers lets
    through only for GitHub's NOT_FOUND, is a number with no pull request"""
    if not isinstance(found, dict):
        raise _refuse("no object for the merged pull requests", found)
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        raise _refuse("no repository for the merged pull requests", found)
    pulls = {}
    for i, number in enumerate(numbers):
        node = repository.get(f"n{i}")
        if node is None:
            continue
        if (
            not isinstance(node, dict)
            or node.get("number") != number
            or not isinstance(node.get("title"), str)
            or not isinstance(node.get("merged"), bool)
            or not isinstance(node.get("body"), str | None)
        ):
            raise _refuse(f"pull request #{number} without its number, title, body, or merged state", node)
        pulls[number] = PullText(number, node["title"], node.get("body") or "", node["merged"], _author(node))
    return pulls


class GhReads:
    """Reads through gh, batched: the touched files one paginated REST read, the open pull
    requests a GraphQL page of OPEN_PER_PAGE, the merged pull requests PULLS_PER_QUERY a
    query, and an App's id once per bot"""

    def __init__(self, gh: Gh) -> None:
        self._gh = gh

    def touched(self, number: int) -> tuple[str, ...]:
        return self._gh.pull_files(number)

    def repository(self) -> Repository:
        after: str | None = None
        pulls: list[OpenPull] = []
        for _ in range(OPEN_PAGES):
            query = _OPEN_QUERY.replace("AFTER", "null" if after is None else json.dumps(after))
            slug, default, page, after = parse_open_page(self._gh.graphql(query))
            pulls.extend(page)
            if after is None:
                return Repository(slug, default, tuple(pulls))
        raise ReleaseError(
            f"the repo has more than {OPEN_PAGES * OPEN_PER_PAGE} open pull requests, more than review history"
            " reads: close the stale ones"
        )

    def pulls(self, numbers: Sequence[int]) -> dict[int, PullText]:
        found: dict[int, PullText] = {}
        for start in range(0, len(numbers), PULLS_PER_QUERY):
            chunk = list(numbers[start : start + PULLS_PER_QUERY])
            aliases = " ".join(f"n{i}: pullRequest(number: {n}) {{ {_PULL_FIELDS} }}" for i, n in enumerate(chunk))
            query = (
                f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {aliases} }} }}"
            )
            found.update(parse_pulls(self._gh.graphql_numbers(query, len(chunk)), chunk))
        return found

    def app_id(self, slug: str) -> int:
        return self._gh.app_id(slug)
