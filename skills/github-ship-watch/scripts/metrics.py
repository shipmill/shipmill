#!/usr/bin/env python3
"""Measure a repo's issue-to-release line over a window: the four DORA measures and the
factory's own, from what GitHub already holds.

Usage: metrics.py <owner/repo> [--days 30] [--until TIME] [--environment NAME ...]
                  [--incident-label incident] [--blocker-label release-blocker]
                  [--bot LOGIN ...] [--json | --markdown]

Measures, each over the --days before --until (default now; a date is its 00:00 UTC, and a
time needs its offset, such as the "start" a --json run prints, which gives the window
before it):
  Deploy frequency   deployments that reached success, by environment (created in the
                     window); for a repo with no deployment by the window's end, stable GitHub releases
                     (not a draft or a pre-release) published in the window
  Lead time          for each merged PR first shipped by a stable release published in the
                     window: its first commit's author date to that release (median, p90).
                     "First shipped by" means its merge commit is among the commits the
                     release's tag adds over the previous stable version (by version, not by
                     date), from GitHub's compare; a release with no earlier stable version
                     isn't measured. One edge it misreads: a patch release cut from main and
                     published before the window, when the previous version is a later patch
                     on a release/X.Y branch that lacks it (v1.2.1 from main, then the hotfix
                     v1.2.2 on release/1.2 from v1.2.0). The next minor (v1.3.0) adds
                     v1.2.1's commits over v1.2.2, so their lead time runs to v1.3.0. Ruling
                     it out takes a compare against every earlier release, not one
  Change failure     with deployments: issues labelled --incident-label opened in the window
  rate               / deployments. Without: --blocker-label issues opened in the window plus
                     hotfix releases / stable releases. A hotfix release is a stable X.Y.Z
                     (Z > 0) whose tag is on a release/X.Y branch, where shipmill's hotfix
                     lane puts it
  Time to restore    issues labelled --incident-label restored in the window: opened to the
                     first "<env> is healthy again on" comment shipmill operate posts, or to
                     closed, whichever is first (median); ones still open at the window's
                     end are counted aside
  Issue to release   for each issue a merged PR closes (GitHub's closing links) whose
                     merge commit a stable release published in the window first shipped, as
                     Lead time reads it: the issue's opening to that release (median, p90).
                     When several PRs close it, the one whose release is earliest (the
                     earliest merged on a tie). No notice is read: shipmill posts none (D-69)
  The stages         over the same issues and PRs (median, p90 in hours each):
                     Issue to first agent comment: opening to the first comment at or before
                     the release an agent wrote (the agent marker as a line of its own, D-62,
                     or a Bot, "[bot]" or --bot author); an issue with none is left out, and
                     the detail counts it. Issue to PR opened: opening to the PR's creation,
                     negative for a PR created first. Issue to PR opened, person-filed and
                     agent-filed: split by the issue (agent-filed: the marker in its body, or a
                     bot author). PR opened to merged, and Merged to release. Per issue, Issue
                     to PR opened, PR opened to merged and Merged to release sum to Issue to
                     release. An issue's comments are paged only until the first agent comment
                     or one after its release
  Human touch        PRs merged in the window that a person merged or approved / all merged
                     PRs. A person is a GitHub User whose login doesn't end in "[bot]" and
                     isn't a --bot; apps (github-actions, dependabot, mergify) are Bots. An
                     agent that merges with a person's token counts as that person
  Agent share        PRs merged in the window whose own work says an agent made them / all
                     merged PRs: the body carries Claude Code's "Generated with [Claude Code]"
                     footer, or a commit a "Co-Authored-By: Claude" or "Claude-Session:"
                     trailer (AGENT_MARKS, case-insensitive). Of those, how many a person
                     approved in a GitHub review: the human gate
  Decided work       of the PRs merged in the window that name a decider (spec 049: an
  credited           approver whose latest review is APPROVED, a trusted needs-decision
                     answerer or the login a bot's "Decision by @<login>" relay names, the
                     trusted author of an issue it closes or of its parent, the person with
                     write, maintain or admin permission who added planned to an opportunity
                     it closes or to its parent; never a Bot, "[bot]" or --bot account, the
                     PR's author, or a record carrying the agent marker as a line of its
                     own), those whose every decider's login is among the accounts GitHub
                     credits the merge commit to (its authors)
  Decided work       of those decided PRs, the ones whose merge commit's git author resolves
  written as the     to a decider and whose message has a Co-authored-by trailer for an
  decider            App's bot ("[bot]@users.noreply.github.com"). Both carry, in --json only,
                     a "people" list counting the PRs each decider login decided

The agent quality measures (spec 078), over the PRs Agent share counts as an agent's. A
verdict is a review whose body's first line is a review record (`<!-- shipmill:review merge
-->` or `refuse`) by a Bot, "[bot]" or --bot author, or an APPROVED or CHANGES_REQUESTED
review by an OWNER, MEMBER, or COLLABORATOR who is a person; a review round is one distinct
commit verdicts were given at; a fix commit is a one-parent commit authored after the PR's
creation (a rebase keeps author dates):
  Rework cycles      per PR, its review rounds beyond the first plus its fix commits (mean;
                     the detail gives the mean rounds and the mean fix commits)
  First-pass merge   PRs with 0 rework cycles / agent PRs
  rate
  Review time        the PR's creation to its first verdict (median, p90); a PR with no
                     verdict is left out, and the detail counts it
  Plan match         of the PRs whose body has one "## Plan" with a "Files:" line naming
                     backticked paths, those whose every changed file (a rename by its new
                     path) equals a path, is under one ending in "/", or matches one as a
                     glob ("**" any run, "*" any run without "/", "?" one character but "/");
                     the detail counts the PRs with no such plan

A measure with nothing to measure (no releases, no merges, no deployments) reads "no data",
never 0. Exit 0 on success, 2 on bad input or a gh failure. Every list is paged; a page GitHub
rejects for its resource limits is asked again at half the size, down to 10 items; one
rejected at 10 fails with one error line. Needs the gh CLI, authenticated. Python 3.10+,
standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import statistics
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn

STABLE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
HEALTHY = re.compile(r"^\S+ is healthy again on ")  # shipmill operate's comment on an incident
PAGE_INFO = "pageInfo { hasNextPage endCursor }"

# What the work itself says about who made it: a PR is agent-made when its body ("body") or
# any of its commit messages ("commit") matches one of these, ignoring case. Add another
# agent's footer or trailer here
AGENT_MARKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("body", re.compile(r"Generated with \[Claude Code\]", re.IGNORECASE)),  # Claude Code's PR footer
    ("commit", re.compile(r"^Co-Authored-By: Claude\b", re.IGNORECASE | re.MULTILINE)),
    ("commit", re.compile(r"^Claude-Session:", re.IGNORECASE | re.MULTILINE)),
)
# shipmill's agent marker (D-62), counted only as a line of its own; attributes may follow a space
AGENT_MARKER = re.compile(r"<!-- shipmill:agent(?:\s[^>]*)?-->")

RELEASES = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    releases(first: $size, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      """
    + PAGE_INFO
    + """
      nodes { tagName publishedAt isDraft isPrerelease }
    }
  }
}
"""
)
COMPARE = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $base: String!, $head: String!) {
  repository(owner: $owner, name: $name) {
    base: ref(qualifiedName: $base) {
      compare(headRef: $head) {
        commits(first: $size, after: $cursor) { """
    + PAGE_INFO
    + """ nodes { oid committedDate } }
      }
    }
  }
}
"""
)
LINE = """
query($owner: String!, $name: String!, $branch: String!, $head: String!) {
  repository(owner: $owner, name: $name) {
    line: ref(qualifiedName: $branch) { compare(headRef: $head) { status } }
  }
}
"""
# What a review needs to be read as a verdict (spec 078)
VERDICT_FIELDS = " nodes { state authorAssociation submittedAt body commit { oid } author { __typename login } }"
PULLS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: $size, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      """
    + PAGE_INFO
    + """
      nodes {
        number createdAt updatedAt mergedAt body
        mergeCommit { oid }
        mergedBy { __typename login }
        closingIssuesReferences(first: 20) {
          nodes {
            url number createdAt body
            author { __typename login }
            repository { owner { login } name }
            comments(first: 10) { """
    + PAGE_INFO
    + """ nodes { createdAt body author { __typename login } } }
          }
        }
        commits(first: 100) { """
    + PAGE_INFO
    + """ nodes { commit { authoredDate message parents { totalCount } } } }
        reviews(states: APPROVED, first: 50) { pageInfo { hasNextPage } nodes { author { __typename login } } }
        verdicts: reviews(first: 50) { """
    + PAGE_INFO
    + VERDICT_FIELDS
    + """ }
        files(first: 100) { """
    + PAGE_INFO
    + """ nodes { path } }
      }
    }
  }
}
"""
)
ISSUE_COMMENTS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { comments(first: $size, after: $cursor) { """
    + PAGE_INFO
    + """ nodes { createdAt body author { __typename login } } } }
  }
}
"""
)
PULL_COMMITS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { commits(first: $size, after: $cursor) { """
    + PAGE_INFO
    + """ nodes { commit { authoredDate message parents { totalCount } } } } }
  }
}
"""
)
PULL_VERDICTS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { verdicts: reviews(first: $size, after: $cursor) { """
    + PAGE_INFO
    + VERDICT_FIELDS
    + """ } }
  }
}
"""
)
PULL_FILES = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { files(first: $size, after: $cursor) { """
    + PAGE_INFO
    + """ nodes { path } } }
  }
}
"""
)
DEPLOYMENTS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    deployments(first: $size, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      """
    + PAGE_INFO
    + """
      nodes { environment createdAt statuses(first: 100) { pageInfo { hasNextPage } nodes { state } } }
    }
  }
}
"""
)
LABELLED = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $label: String!, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    issues(first: $size, after: $cursor, filterBy: {labels: [$label], since: $since},
           orderBy: {field: UPDATED_AT, direction: DESC}) {
      """
    + PAGE_INFO
    + """
      nodes { number createdAt closedAt comments(first: 50) { """
    + PAGE_INFO
    + """ nodes { body createdAt } } }
    }
  }
}
"""
)
LABELLED_COMMENTS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { comments(first: $size, after: $cursor) { """
    + PAGE_INFO
    + """ nodes { body createdAt } } }
  }
}
"""
)
# What spec 109 reads of a PR merged in the window, and of each issue it closes and its parent
FILED = (
    "number repository { nameWithOwner } authorAssociation body author { __typename login }"
    " labels(first: 100) { pageInfo { hasNextPage } nodes { name } }"
)
COMMENT_FIELDS = " nodes { body authorAssociation author { __typename login } }"
COMMENTS = " comments(first: $size) { " + PAGE_INFO + COMMENT_FIELDS + " }"
# DECIDED reads BATCH PRs at once, as p0, p1, ... for the numbers $n0, $n1, ...: one read per
# PR took a run over a busy month past ten minutes
BATCH = 10
DECIDED = (
    "query($owner: String!, $name: String!, $size: Int!, "
    + ", ".join(f"$n{k}: Int!" for k in range(BATCH))
    + ") {\n  repository(owner: $owner, name: $name) {\n"
    + "".join(f"    p{k}: pullRequest(number: $n{k}) {{ ...decided }}\n" for k in range(BATCH))
    + """  }
}
fragment decided on PullRequest {
  author { __typename login }
  mergeCommit {
    message
    author { user { login } }
    authors(first: 100) { pageInfo { hasNextPage } nodes { user { login } } }
  }
 """
    + COMMENTS
    + """
  closingIssuesReferences(first: 20) { pageInfo { hasNextPage } nodes { ...filed parent { ...filed } } }
}
fragment filed on Issue { """
    + FILED
    + COMMENTS
    + " }\n"
)
THREAD_COMMENTS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    thread: issueOrPullRequest(number: $number) {
      ... on Issue { comments(first: $size, after: $cursor) { """
    + PAGE_INFO
    + COMMENT_FIELDS
    + """ } }
      ... on PullRequest { comments(first: $size, after: $cursor) { """
    + PAGE_INFO
    + COMMENT_FIELDS
    + """ } }
    }
  }
}
"""
)
LABELERS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      timelineItems(itemTypes: [LABELED_EVENT], first: $size, after: $cursor) { """
    + PAGE_INFO
    + """ nodes { ... on LabeledEvent { label { name } actor { __typename login } } } }
    }
  }
}
"""
)
PERMISSION = """
query($owner: String!, $name: String!, $login: String!) {
  repository(owner: $owner, name: $name) {
    collaborators(login: $login, first: 1) { edges { permission } }
  }
}
"""
# Each query's first page size. Issues and pull requests carry nested connections, so they
# start smaller; a rejected page halves (see sized), and the smaller size sticks
SIZES = {
    DECIDED: 50,
    THREAD_COMMENTS: 100,
    LABELERS: 100,
    RELEASES: 100,
    COMPARE: 100,
    PULLS: 50,
    PULL_COMMITS: 100,
    PULL_VERDICTS: 100,
    PULL_FILES: 100,
    ISSUE_COMMENTS: 100,
    DEPLOYMENTS: 100,
    LABELLED: 50,
    LABELLED_COMMENTS: 100,
}
MIN_PAGE = 10
RESOURCE_LIMITS = "RESOURCE_LIMITS_EXCEEDED"
Variables = dict[str, str | int]
# Runs one GraphQL query with its variables and returns the parsed JSON response
Runner = Callable[[str, Variables], dict[str, Any]]
Sizes = dict[str, int]
Node = dict[str, Any]


class ResourceLimitsExceeded(Exception):
    """GitHub rejected a query as too costly to run; a smaller page may fit"""


def resource_limited(response: dict[str, Any]) -> bool:
    """Every error is GitHub's resource limit, so a smaller page may succeed; any other error is real"""
    errors = response.get("errors")
    return bool(errors) and all(isinstance(e, dict) and e.get("type") == RESOURCE_LIMITS for e in errors)


def gh_graphql(query: str, variables: Variables) -> dict[str, Any]:
    """The default runner: one ``gh api graphql`` call"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        # -F sends an int as a number; -f keeps a string a string (a cursor, a numeric repo name)
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # gh exits 1 on a resource limit, with the response on stdout: hand it back to be retried smaller
        try:
            rejected = json.loads(proc.stdout)
        except ValueError:
            rejected = None
        if isinstance(rejected, dict) and resource_limited(rejected):
            return rejected
        sys.stderr.write(proc.stderr)
        raise SystemExit(2)
    response: dict[str, Any] = json.loads(proc.stdout)
    return response


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


def repository(run: Runner, query: str, variables: Variables) -> dict[str, Any]:
    response = run(query, variables)
    if resource_limited(response):
        raise ResourceLimitsExceeded
    if response.get("errors"):
        fail(f"GitHub GraphQL errors: {json.dumps(response['errors'])}")
    data = (response.get("data") or {}).get("repository")
    if data is None:
        fail(f"no repository {variables['owner']}/{variables['name']} in the GraphQL response")
    result: dict[str, Any] = data
    return result


def advance(cursor: str | None, seen: set[str], what: str) -> str:
    """The next page's cursor; a missing or repeated one would page forever"""
    if not cursor or cursor in seen:
        fail(f"GitHub reported more {what}, but the page cursor did not advance ({cursor!r})")
    seen.add(cursor)
    return cursor


def sized(run: Runner, query: str, variables: Variables, sizes: Sizes, what: str) -> dict[str, Any]:
    """``repository`` at the query's page size, halving it while GitHub rejects the page for
    its resource limits. The smaller size sticks for the query's later pages, and a cursor
    from a bigger page stays valid. A page rejected at MIN_PAGE fails with one line"""
    while True:
        size = sizes[query]
        try:
            return repository(run, query, {**variables, "size": size})
        except ResourceLimitsExceeded:
            if size <= MIN_PAGE:
                fail(
                    f"{variables['owner']}/{variables['name']}: GitHub's resource limits rejected "
                    f"{what} even at {size} per page"
                )
            sizes[query] = max(size // 2, MIN_PAGE)


def dig(data: dict[str, Any], path: Sequence[str], what: str) -> dict[str, Any]:
    for key in path:
        if data.get(key) is None:
            fail(f"GitHub returned no {key} for {what}")
        data = data[key]
    return data


def pages(
    run: Runner,
    query: str,
    base: Variables,
    sizes: Sizes,
    path: Sequence[str],
    what: str,
    done: Callable[[Node], bool] | None = None,
) -> list[Node]:
    """Every node of the connection at path, paging forwards; paging stops after a page
    holding a node that ``done`` accepts (the list is ordered, so the rest is older)"""
    nodes: list[Node] = []
    seen: set[str] = set()
    variables = dict(base)
    while True:
        connection = dig(sized(run, query, variables, sizes, what), path, what)
        nodes += connection["nodes"]
        if not connection["pageInfo"]["hasNextPage"] or (done and any(done(n) for n in connection["nodes"])):
            return nodes
        variables["cursor"] = advance(connection["pageInfo"]["endCursor"], seen, what)


def timestamp(text: str) -> dt.datetime:
    """A GitHub ISO 8601 time; its "Z" is rejected by fromisoformat before Python 3.11"""
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        fail(f"gh returned a time without a timezone or not ISO 8601: {text!r}")
    return moment


# -- what GitHub holds -------------------------------------------------------------------------


@dataclass(frozen=True)
class Release:
    tag: str
    published: dt.datetime
    version: tuple[int, int, int] | None  # X.Y.Z for a plain version tag


@dataclass(frozen=True)
class Window:
    start: dt.datetime
    end: dt.datetime

    def __contains__(self, moment: dt.datetime) -> bool:
        return self.start <= moment <= self.end

    @property
    def weeks(self) -> float:
        return (self.end - self.start) / dt.timedelta(weeks=1)


@dataclass
class Data:
    """Everything the measures read, fetched once"""

    releases: list[Release]  # stable releases, newest first
    shipped: dict[str, set[str]]  # an in-window release's tag: the commits it first shipped
    hotfixes: set[str]  # in-window release tags on a release/X.Y branch
    pulls: list[Node]
    deployed: bool  # the repo has any deployment (in the chosen environments)
    deployments: list[Node]  # created in the window, in the chosen environments
    incidents: list[Node]
    blockers: list[Node]
    bots: frozenset[str] = field(default_factory=frozenset)
    # spec 109: what names a decider, by PR number, for each PR merged in the window; a PR
    # with no entry names none
    decisions: dict[int, Decision] = field(default_factory=dict)


@dataclass(frozen=True)
class Thread:
    """An issue a PR merged in the window closes, or that issue's parent, with what spec 049
    reads of it: its labels lowercased, its comments oldest first, and the actors of its
    `labeled` events adding planned, oldest first (None for a deleted account), read only for
    an opportunity labelled planned"""

    number: int
    author: Node | None
    association: str
    body: str
    labels: frozenset[str]
    comments: list[Node]
    labelers: list[Node | None]


@dataclass(frozen=True)
class Decision:
    """What spec 109 reads of a PR merged in the window: its author, its reviews and comments
    oldest first, the issues of the repo it closes and their parents (each once), its merge
    commit (message, git author, and the accounts GitHub credits it to), and the permission on
    the repo of each person who accepted one of those issues, by lowercase login"""

    author: Node | None
    reviews: list[Node]
    comments: list[Node]
    issues: list[Thread]
    merge: Node | None
    permissions: dict[str, str]


def stable_releases(nodes: list[Node]) -> list[Release]:
    found = []
    for n in nodes:
        if n["isDraft"] or n["isPrerelease"] or not n["publishedAt"]:
            continue
        m = STABLE.match(n["tagName"])
        version = (int(m[1]), int(m[2]), int(m[3])) if m else None
        found.append(Release(n["tagName"], timestamp(n["publishedAt"]), version))
    return sorted(found, key=lambda r: r.published, reverse=True)


def previous(release: Release, releases: list[Release]) -> Release | None:
    """The highest stable version below the release's, published before it"""
    if release.version is None:
        return None
    lower = [
        r for r in releases if r.version is not None and r.version < release.version and r.published < release.published
    ]
    return max(lower, key=lambda r: r.version or (0, 0, 0)) if lower else None


def fetch(
    repo: str,
    window: Window,
    environments: frozenset[str],
    incident: str,
    blocker: str,
    run: Runner = gh_graphql,
    bots: frozenset[str] = frozenset(),
    decided: bool = False,
) -> Data:
    """What the measures read; decided adds spec 109's records of each PR merged in the
    window, which only Decided work credited and written as the decider read (trends.py
    leaves them out)"""
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    base: Variables = {"owner": owner, "name": name}
    sizes = dict(SIZES)
    since = window.start.isoformat().replace("+00:00", "Z")

    # Every release: a release's previous version may be older than any date cutoff
    releases = stable_releases(pages(run, RELEASES, base, sizes, ["releases"], "releases"))
    recent = [r for r in releases if r.published in window]
    shipped: dict[str, set[str]] = {}
    hotfixes: set[str] = set()
    oldest = window.start
    for release in recent:
        head = f"refs/tags/{release.tag}"
        prev = previous(release, releases)
        if prev is not None:
            what = f"the commits {release.tag} adds over {prev.tag}"
            variables: Variables = {**base, "base": f"refs/tags/{prev.tag}", "head": head}
            commits = pages(run, COMPARE, variables, sizes, ["base", "compare", "commits"], what)
            shipped[release.tag] = {c["oid"] for c in commits}
            oldest = min([oldest, *(timestamp(c["committedDate"]) for c in commits)])
        if release.version is not None and release.version[2] > 0:
            major, minor, _ = release.version
            variables = {**base, "branch": f"refs/heads/release/{major}.{minor}", "head": head}
            line = repository(run, LINE, variables)["line"]  # one status, nothing to page or shrink
            if line is not None and line["compare"]["status"] in ("IDENTICAL", "BEHIND"):
                hotfixes.add(release.tag)

    # Merged PRs, newest update first, back to the oldest commit a release in the window
    # shipped (a merge's commit date is its merge time; a day covers clock skew)
    cutoff = oldest - dt.timedelta(days=1)
    pulls = pages(run, PULLS, base, sizes, ["pullRequests"], "merged pull requests", lambda n: _older(n, cutoff))
    todo: list[Node] = []  # the PRs merged in the window, whose deciders spec 109 reads
    for pr in pulls:
        pull_commits(run, base, sizes, pr, window)
        if not merged(pr, window):
            continue
        made = agent_made(pr)
        if made or decided:  # the agent quality measures and spec 109's approvers read all its reviews
            extend(run, base, sizes, pr, "verdicts", PULL_VERDICTS, f"the reviews of PR #{pr['number']}")
        if made:  # the agent quality measures read its files
            extend(run, base, sizes, pr, "files", PULL_FILES, f"the changed files of PR #{pr['number']}")
        if decided:
            todo.append(pr)
    decisions = decisions_of(run, base, sizes, todo, bots)

    # Newest first, back to the window's start; with --environment, also back to a chosen
    # environment's deployment, so one deployed only before the window still counts as deployed
    deploys = pages(
        run,
        DEPLOYMENTS,
        base,
        sizes,
        ["deployments"],
        "deployments",
        lambda n: timestamp(n["createdAt"]) < window.start and (not environments or n["environment"] in environments),
    )
    # Deployed by the window's end: with --until, a repo that first deployed later still
    # counted its releases then
    chosen = [d for d in deploys if not environments or d["environment"] in environments]
    deployed = any(timestamp(d["createdAt"]) <= window.end for d in chosen)
    in_window = [d for d in chosen if timestamp(d["createdAt"]) in window]
    for d in in_window:
        if d["statuses"]["pageInfo"]["hasNextPage"] and not _succeeded(d):
            fail(f"a deployment to {d['environment']} at {d['createdAt']} has over 100 statuses, none a success")

    incidents = labelled(run, base, sizes, incident, since)
    blockers = labelled(run, base, sizes, blocker, since)
    data = Data(releases, shipped, hotfixes, pulls, deployed, in_window, incidents, blockers, bots, decisions)
    for closed in closed_issues(data, window):
        issue_comments(run, sizes, closed, bots)
    return data


def decisions_of(
    run: Runner, base: Variables, sizes: Sizes, pulls: Sequence[Node], bots: frozenset[str]
) -> dict[int, Decision]:
    """Spec 109: each PR's records, read BATCH PRs to a DECIDED query; a batch short of BATCH
    asks its last PR again in the free places"""
    decisions: dict[int, Decision] = {}
    threads: dict[int, Thread] = {}
    permissions: dict[str, str] = {}
    for start in range(0, len(pulls), BATCH):
        batch = pulls[start : start + BATCH]
        numbers = [pr["number"] for pr in batch]
        padded = numbers + [numbers[-1]] * (BATCH - len(numbers))
        variables: Variables = {**base, **{f"n{k}": n for k, n in enumerate(padded)}}
        what = f"the deciders of PRs {', '.join(f'#{n}' for n in numbers)}"
        found = sized(run, DECIDED, variables, sizes, what)
        for k, pr in enumerate(batch):
            node = dig(found, [f"p{k}"], f"the deciders of PR #{pr['number']}")
            decisions[pr["number"]] = decision(run, base, sizes, pr, node, threads, permissions, bots)
    return decisions


def decision(
    run: Runner,
    base: Variables,
    sizes: Sizes,
    pr: Node,
    found: Node,
    threads: dict[int, Thread],
    permissions: dict[str, str],
    bots: frozenset[str],
) -> Decision:
    """Spec 109: the records that name a PR's deciders (spec 049) and its merge commit's
    credit, from its DECIDED node. threads and permissions are shared across PRs, so an issue
    or a person is read once"""
    number = pr["number"]
    merge = found["mergeCommit"]
    if merge is not None and merge["authors"]["pageInfo"]["hasNextPage"]:
        fail(f"the merge commit of PR #{number} has over 100 authors")
    closes = found["closingIssuesReferences"]
    if closes["pageInfo"]["hasNextPage"]:
        fail(f"PR #{number} closes over 20 issues")
    repo = f"{base['owner']}/{base['name']}".lower()
    issues: list[Thread] = []
    for node in closes["nodes"]:
        if home(node) != repo:
            continue  # an issue of another repo: its records are that repo's
        parent = node["parent"]
        for one in (node, parent if parent is not None and home(parent) == repo else None):
            if one is None or any(i.number == one["number"] for i in issues):
                continue
            if one["number"] not in threads:
                threads[one["number"]] = thread(run, base, sizes, one)
            issues.append(threads[one["number"]])
    held: dict[str, str] = {}
    for issue in issues:
        who = accepter(issue, bots)
        if who is not None:
            key = who["login"].lower()
            if key not in permissions:
                permissions[key] = permission(run, base, who["login"])
            held[key] = permissions[key]
    comments = thread_comments(run, base, sizes, number, found["comments"])
    return Decision(found["author"], list(pr["verdicts"]["nodes"]), comments, issues, merge, held)


def home(node: Node) -> str:
    """The repo an issue is of, lowercased"""
    return str(dig(node, ["repository"], f"issue #{node['number']}")["nameWithOwner"]).lower()


def thread(run: Runner, base: Variables, sizes: Sizes, node: Node) -> Thread:
    """An issue as FILED gives it, with the rest of its comments, and for an opportunity
    labelled planned the actors of its `labeled` events adding planned"""
    number = node["number"]
    if node["labels"]["pageInfo"]["hasNextPage"]:
        fail(f"issue #{number} has over 100 labels")
    labels = frozenset(str(label["name"]).lower() for label in node["labels"]["nodes"])
    labelers: list[Node | None] = []
    if {OPPORTUNITY, PLANNED} <= labels:
        what = f"the label events of #{number}"
        events = pages(run, LABELERS, {**base, "number": number}, sizes, ["issue", "timelineItems"], what)
        labelers = [e["actor"] for e in events if str(e["label"]["name"]).lower() == PLANNED]
    comments = thread_comments(run, base, sizes, number, node["comments"])
    return Thread(
        number, node["author"], str(node["authorAssociation"]), node["body"] or "", labels, comments, labelers
    )


def thread_comments(run: Runner, base: Variables, sizes: Sizes, number: int, first: Node) -> list[Node]:
    """Every comment on the issue or PR number, oldest first, from its first page to its last"""
    what = f"the comments on #{number}"
    path = ["thread", "comments"]
    connection = first
    nodes: list[Node] = list(connection["nodes"])
    seen: set[str] = set()
    while connection["pageInfo"]["hasNextPage"]:
        cursor = advance(connection["pageInfo"]["endCursor"], seen, what)
        variables: Variables = {**base, "number": number, "cursor": cursor}
        connection = dig(sized(run, THREAD_COMMENTS, variables, sizes, what), path, what)
        nodes += connection["nodes"]
    return nodes


def permission(run: Runner, base: Variables, login: str) -> str:
    """The person's permission on the repo, lowercased (admin, maintain, write, triage, read),
    or none when they aren't a collaborator"""
    collaborators = repository(run, PERMISSION, {**base, "login": login}).get("collaborators")
    if collaborators is None:
        fail(f"GitHub returned no collaborators for {login}'s permission")
    edges = collaborators["edges"]
    return str(edges[0]["permission"]).lower() if edges else "none"


def issue_comments(run: Runner, sizes: Sizes, closed: Closed, bots: frozenset[str]) -> None:
    """Page a counted issue's comments forwards, oldest first, while none is an agent's and
    none came after its release: only those can end Issue to first agent comment"""
    issue = closed.issue
    comments = issue["comments"]
    seen: set[str] = set()
    where = issue["repository"]
    base: Variables = {"owner": where["owner"]["login"], "name": where["name"]}
    what = f"comments on {issue['url']}"
    while comments["pageInfo"]["hasNextPage"] and not any(
        agent_wrote(c, bots) or timestamp(c["createdAt"]) > closed.release.published for c in comments["nodes"]
    ):
        cursor = advance(comments["pageInfo"]["endCursor"], seen, what)
        variables: Variables = {**base, "number": issue["number"], "cursor": cursor}
        page = dig(sized(run, ISSUE_COMMENTS, variables, sizes, what), ["issue", "comments"], what)
        comments["nodes"] = comments["nodes"] + page["nodes"]
        comments["pageInfo"] = page["pageInfo"]


def extend(
    run: Runner,
    base: Variables,
    sizes: Sizes,
    pr: Node,
    key: str,
    query: str,
    what: str,
    stop: Callable[[], bool] = lambda: False,
) -> None:
    """Page the PR's connection at key forwards to its end, or until stop() holds"""
    connection = pr[key]
    seen: set[str] = set()
    while connection["pageInfo"]["hasNextPage"] and not stop():
        cursor = advance(connection["pageInfo"]["endCursor"], seen, what)
        variables: Variables = {**base, "number": pr["number"], "cursor": cursor}
        page = dig(sized(run, query, variables, sizes, what), ["pullRequest", key], what)
        connection["nodes"] = connection["nodes"] + page["nodes"]
        connection["pageInfo"] = page["pageInfo"]


def pull_commits(run: Runner, base: Variables, sizes: Sizes, pr: Node, window: Window | None = None) -> None:
    """Page the PR's commits forwards while none carries an agent's mark, and to their end for
    an agent's PR merged in the window, whose fix commits are counted (retro.py gives none)"""
    what = f"the commits of PR #{pr['number']}"

    def done() -> bool:
        return agent_made(pr) and (window is None or not merged(pr, window))

    extend(run, base, sizes, pr, "commits", PULL_COMMITS, what, done)


def merged(pr: Node, window: Window) -> bool:
    return bool(pr["mergedAt"]) and timestamp(pr["mergedAt"]) in window


def measured(pr: Node, window: Window) -> bool:
    """An agent's PR merged in the window: the ones the agent quality measures read"""
    return merged(pr, window) and agent_made(pr)


def agent_made(pr: Node) -> bool:
    """The PR's body or one of its commits carries one of AGENT_MARKS"""
    texts = {"body": [pr["body"] or ""], "commit": [c["commit"]["message"] for c in pr["commits"]["nodes"]]}
    return any(pattern.search(text) for where, pattern in AGENT_MARKS for text in texts[where])


def _older(node: Node, cutoff: dt.datetime) -> bool:
    return timestamp(node["updatedAt"]) < cutoff


def _succeeded(deployment: Node) -> bool:
    return any(s["state"] == "SUCCESS" for s in deployment["statuses"]["nodes"])


def labelled(run: Runner, base: Variables, sizes: Sizes, label: str, since: str) -> list[Node]:
    """Issues with the label updated since, each with its comments up to the first
    "healthy again" one (paged forwards only while none is found)"""
    what = f"issues labelled {label}"
    issues = pages(run, LABELLED, {**base, "label": label, "since": since}, sizes, ["issues"], what)
    for issue in issues:
        comments = issue["comments"]
        seen: set[str] = set()
        while comments["pageInfo"]["hasNextPage"] and not any(HEALTHY.match(c["body"]) for c in comments["nodes"]):
            cursor = advance(comments["pageInfo"]["endCursor"], seen, f"comments on #{issue['number']}")
            variables: Variables = {**base, "number": issue["number"], "cursor": cursor}
            page = dig(sized(run, LABELLED_COMMENTS, variables, sizes, what), ["issue", "comments"], what)
            comments["nodes"] = comments["nodes"] + page["nodes"]
            comments["pageInfo"] = page["pageInfo"]
    return issues


# -- the measures ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Measure:
    name: str
    value: float | None  # None: no data
    text: str  # the value as the table shows it
    detail: str
    unit: str  # of value: "per week", "hours", "ratio", or "count"
    extra: dict[str, Any] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return {"measure": self.name, "value": self.value, "unit": self.unit, "text": self.text, **self.extra}


NO_DATA = "no data"
SHOWN = 5  # release tags a detail names before "..."


def span(hours: float) -> str:
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} d"


def hours(start: dt.datetime, end: dt.datetime) -> float:
    return (end - start) / dt.timedelta(hours=1)


def p90(values: list[float]) -> float:
    """The nearest-rank 90th percentile"""
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def durations(name: str, values: list[float], detail: str, empty: str) -> Measure:
    if not values:
        return Measure(name, None, NO_DATA, empty, "hours")
    median = statistics.median(values)
    text = f"median {span(median)}, p90 {span(p90(values))}"
    return Measure(name, median, text, detail, "hours", {"p90": p90(values), "count": len(values)})


def in_window_releases(data: Data, window: Window) -> list[Release]:
    return [r for r in data.releases if r.published in window]


def deploy_frequency(data: Data, window: Window) -> Measure:
    name = "Deploy frequency"
    if data.deployed:
        done = [d for d in data.deployments if _succeeded(d)]
        if not done:
            return Measure(name, None, NO_DATA, "no deployment reached success in the window", "per week")
        counts: dict[str, int] = {}
        for d in done:
            counts[d["environment"]] = counts.get(d["environment"], 0) + 1
        rate = len(done) / window.weeks
        detail = ", ".join(f"{env} {n}" for env, n in sorted(counts.items()))
        extra = {"source": "deployments", "count": len(done), "environments": counts}
        return Measure(name, rate, f"{rate:.1f}/week ({len(done)} deploys)", detail, "per week", extra)
    releases = in_window_releases(data, window)
    if not releases:
        return Measure(name, None, NO_DATA, "no deployments, and no stable release in the window", "per week")
    rate = len(releases) / window.weeks
    shown = " ".join(r.tag for r in releases[:SHOWN]) + (" ..." if len(releases) > SHOWN else "")
    detail = f"stable releases, no deployments: {shown}"
    extra = {"source": "releases", "count": len(releases)}
    return Measure(name, rate, f"{rate:.1f}/week ({len(releases)} releases)", detail, "per week", extra)


def first_shipped(data: Data, window: Window) -> dict[str, Release]:
    """Each commit an in-window stable release first shipped, to that release"""
    found: dict[str, Release] = {}
    for release in sorted(in_window_releases(data, window), key=lambda r: r.published, reverse=True):
        for oid in data.shipped.get(release.tag, ()):
            found[oid] = release  # oldest release wins: the loop runs newest first
    return found


def lead_times(data: Data, window: Window) -> list[tuple[int, float]]:
    """Each merged PR a stable release published in the window first shipped: its number and
    the hours from its first commit's author date to that release"""
    first_shipped_by = first_shipped(data, window)
    found = []
    for pr in data.pulls:
        merge = (pr.get("mergeCommit") or {}).get("oid")
        commits = pr["commits"]["nodes"]
        if merge in first_shipped_by and commits:
            at = timestamp(commits[0]["commit"]["authoredDate"])
            found.append((pr["number"], hours(at, first_shipped_by[merge].published)))
    return found


def lead_time(data: Data, window: Window) -> Measure:
    values = [h for _, h in lead_times(data, window)]
    shipped = sum(1 for r in in_window_releases(data, window) if r.tag in data.shipped)
    detail = f"{len(values)} PRs in {shipped} releases"
    return durations("Lead time for changes", values, detail, "no merged PR shipped by a stable release in the window")


def change_failure_rate(data: Data, window: Window) -> Measure:
    name = "Change failure rate"
    opened = [i for i in (data.incidents if data.deployed else data.blockers) if timestamp(i["createdAt"]) in window]
    issues = " ".join(f"#{i['number']}" for i in sorted(opened, key=lambda i: i["number"]))
    if data.deployed:
        total = sum(1 for d in data.deployments if _succeeded(d))
        failures, named, source = len(opened), issues, "deployments"
        detail = f"{len(opened)} incidents / {total} deploys"
    else:
        releases = in_window_releases(data, window)
        hot = [r.tag for r in releases if r.tag in data.hotfixes]
        total, failures, source = len(releases), len(opened) + len(hot), "releases"
        named = " ".join(x for x in (issues, *hot) if x)
        detail = f"{len(opened)} blocker issues + {len(hot)} hotfixes / {total} releases"
    extra: dict[str, Any] = {"source": source}
    detail += f": {named}" if named else ""
    if total == 0:
        return Measure(name, None, NO_DATA, f"no {source} in the window", "ratio", extra)
    rate = failures / total
    return Measure(name, rate, f"{rate:.0%}", detail, "ratio", {**extra, "failures": failures, "total": total})


def restored_at(issue: Node) -> dt.datetime | None:
    moments = [timestamp(c["createdAt"]) for c in issue["comments"]["nodes"] if HEALTHY.match(c["body"])]
    if issue["closedAt"]:
        moments.append(timestamp(issue["closedAt"]))
    return min(moments) if moments else None


def time_to_restore(data: Data, window: Window) -> Measure:
    values, still = [], 0
    for issue in data.incidents:
        if timestamp(issue["createdAt"]) > window.end:
            continue
        done = restored_at(issue)
        if done is None or done > window.end:
            still += 1
        elif done in window:
            values.append(hours(timestamp(issue["createdAt"]), done))
    name = "Time to restore"
    if not values:
        return Measure(name, None, NO_DATA, f"no incident restored in the window, {still} open", "hours")
    median = statistics.median(values)
    detail = f"{len(values)} incidents restored, {still} open"
    return Measure(name, median, f"median {span(median)}", detail, "hours", {"count": len(values), "open": still})


@dataclass(frozen=True)
class Closed:
    """An issue Issue to release counts, the PR that closed it, and the release that shipped it"""

    issue: Node
    pr: Node
    release: Release

    @property
    def opened(self) -> dt.datetime:
        return timestamp(self.issue["createdAt"])

    @property
    def created(self) -> dt.datetime:
        return timestamp(self.pr["createdAt"])

    @property
    def merged(self) -> dt.datetime:
        return timestamp(self.pr["mergedAt"])


def closed_issues(data: Data, window: Window) -> list[Closed]:
    """Each issue a merged PR closes whose merge commit an in-window stable release first
    shipped, with the PR whose release is earliest, the earliest merged on a tie (D-69: read
    from the release and the close, never from a notice)"""
    first_shipped_by = first_shipped(data, window)
    found: dict[str, Closed] = {}  # by the issue's url
    for pr in data.pulls:
        release = first_shipped_by.get((pr.get("mergeCommit") or {}).get("oid") or "")
        if release is None:
            continue
        for issue in (pr.get("closingIssuesReferences") or {}).get("nodes") or []:
            closed = Closed(issue, pr, release)
            held = found.get(issue["url"])
            if held is None or (release.published, closed.merged) < (held.release.published, held.merged):
                found[issue["url"]] = closed
    return list(found.values())


EMPTY_CLOSED = "no issue closed by a PR a stable release shipped in the window"


def issue_to_release(data: Data, window: Window) -> Measure:
    """Each counted issue, from its opening to the release that first shipped its PR"""
    values = [hours(c.opened, c.release.published) for c in closed_issues(data, window)]
    detail = f"{len(values)} issues closed by a PR a stable release shipped"
    return durations("Issue to release", values, detail, EMPTY_CLOSED)


def bot_author(actor: Node | None, bots: frozenset[str]) -> bool:
    """A Bot, a login ending "[bot]", or a --bot login; a deleted (null) author is none"""
    if actor is None:
        return False
    login: str = actor["login"]
    return actor["__typename"] == "Bot" or login.endswith("[bot]") or login in bots


def marked(body: str | None) -> bool:
    """The body carries the agent marker as a line of its own (D-62)"""
    return any(AGENT_MARKER.fullmatch(line.strip()) for line in (body or "").splitlines())


def agent_wrote(record: Node, bots: frozenset[str]) -> bool:
    """A comment or an issue an agent wrote: the marker, or a bot author"""
    return marked(record["body"]) or bot_author(record["author"], bots)


def first_agent_comment(closed: Closed, bots: frozenset[str]) -> dt.datetime | None:
    """The first comment, oldest first, at or before the release that an agent wrote"""
    for comment in closed.issue["comments"]["nodes"]:
        at = timestamp(comment["createdAt"])
        if at > closed.release.published:
            return None
        if agent_wrote(comment, bots):
            return at
    return None


def issue_to_agent_comment(data: Data, window: Window) -> Measure:
    closed = closed_issues(data, window)
    found = [(c, first_agent_comment(c, data.bots)) for c in closed]
    values = [hours(c.opened, at) for c, at in found if at is not None]
    left = len(closed) - len(values)
    detail = f"{len(values)} issues; {left} with no agent comment by their release left out"
    empty = f"no agent comment by its release on any of {left} issues, all left out" if closed else EMPTY_CLOSED
    return durations("Issue to first agent comment", values, detail, empty)


def issue_to_pr(data: Data, window: Window) -> Measure:
    """A PR created before its issue counts negative, so the three stages sum to Issue to release"""
    values = [hours(c.opened, c.created) for c in closed_issues(data, window)]
    detail = f"{len(values)} issues, to the PR that closed them being opened"
    return durations("Issue to PR opened", values, detail, EMPTY_CLOSED)


def issue_to_pr_filed(data: Data, window: Window, by_agent: bool) -> Measure:
    who = "agent" if by_agent else "person"
    closed = [c for c in closed_issues(data, window) if agent_wrote(c.issue, data.bots) is by_agent]
    values = [hours(c.opened, c.created) for c in closed]
    detail = f"{len(values)} {who}-filed issues"
    empty = f"no {who}-filed issue closed by a PR a stable release shipped in the window"
    return durations(f"Issue to PR opened, {who}-filed", values, detail, empty)


def issue_to_pr_person(data: Data, window: Window) -> Measure:
    return issue_to_pr_filed(data, window, by_agent=False)


def issue_to_pr_agent(data: Data, window: Window) -> Measure:
    return issue_to_pr_filed(data, window, by_agent=True)


def pr_to_merge(data: Data, window: Window) -> Measure:
    values = [hours(c.created, c.merged) for c in closed_issues(data, window)]
    detail = f"{len(values)} issues, their PR's opening to its merge"
    return durations("PR opened to merged", values, detail, EMPTY_CLOSED)


def merge_to_release(data: Data, window: Window) -> Measure:
    values = [hours(c.merged, c.release.published) for c in closed_issues(data, window)]
    detail = f"{len(values)} issues, their PR's merge to its release"
    return durations("Merged to release", values, detail, EMPTY_CLOSED)


def person(actor: Node | None, bots: frozenset[str]) -> bool:
    if actor is None or actor["__typename"] != "User":
        return False
    login: str = actor["login"]
    return not login.endswith("[bot]") and login not in bots


def approved_by_person(pr: Node, bots: frozenset[str]) -> bool:
    """A person approved the PR in a GitHub review"""
    reviews = pr["reviews"]
    approver = any(person(r["author"], bots) for r in reviews["nodes"])
    if reviews["pageInfo"]["hasNextPage"] and not approver:
        fail(f"PR #{pr['number']} has over 50 approvals, none by a person")
    return approver


def merged_in(data: Data, window: Window) -> list[Node]:
    return [p for p in data.pulls if merged(p, window)]


def human_touch(data: Data, window: Window) -> Measure:
    name = "Human touch"
    merged = merged_in(data, window)
    if not merged:
        return Measure(name, None, NO_DATA, "no PR merged in the window", "ratio")
    by_person = approved = touched = 0
    for pr in merged:
        merger = person(pr["mergedBy"], data.bots)
        approver = approved_by_person(pr, data.bots)
        by_person += merger
        approved += approver
        touched += merger or approver
    rate = touched / len(merged)
    detail = (
        f"{touched} of {len(merged)} merges: {by_person} merged by a person, {approved} approved by one"
        " (an agent merging with a person's token counts as the person)"
    )
    extra = {"merges": len(merged), "merged_by_person": by_person, "approved_by_person": approved}
    return Measure(name, rate, f"{rate:.0%}", detail, "ratio", extra)


def agent_share(data: Data, window: Window) -> Measure:
    name = "Agent share"
    merged = merged_in(data, window)
    if not merged:
        return Measure(name, None, NO_DATA, "no PR merged in the window", "ratio")
    made = [pr for pr in merged if agent_made(pr)]
    gated = sum(approved_by_person(pr, data.bots) for pr in made)
    rate = len(made) / len(merged)
    detail = f"{len(made)} of {len(merged)} merges agent-made; a person approved {gated} of them in a review"
    extra = {"merges": len(merged), "agent_made": len(made), "approved_by_person": gated}
    return Measure(name, rate, f"{rate:.0%}", detail, "ratio", extra)


# -- the agent quality measures (spec 078) -------------------------------------------------------

TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})  # D-16: whose review is a verdict
REVIEW_RECORDS = frozenset({"<!-- shipmill:review merge -->", "<!-- shipmill:review refuse -->"})  # spec 055
NO_AGENT_PR = "no agent PR merged in the window"


def verdict(review: Node, bots: frozenset[str]) -> bool:
    """A review record (its body's first line a spec 055 marker) by a bot, or an APPROVED or
    CHANGES_REQUESTED review by a trusted person; a pending review isn't submitted yet"""
    if review["state"] == "PENDING" or not review["submittedAt"]:
        return False
    first = (review["body"] or "").lstrip().split("\n", 1)[0].strip()
    if first in REVIEW_RECORDS and bot_author(review["author"], bots):
        return True
    return (
        review["state"] in ("APPROVED", "CHANGES_REQUESTED")
        and review["authorAssociation"] in TRUSTED
        and person(review["author"], bots)
    )


def fix_commit(commit: Node, created: dt.datetime) -> bool:
    """One parent (a merge of the base has two), authored after the PR's creation: a rebase
    keeps author dates, so a commit written before the PR opened is none"""
    c = commit["commit"]
    return c["parents"]["totalCount"] == 1 and timestamp(c["authoredDate"]) > created


@dataclass(frozen=True)
class Rework:
    """One agent PR's review rounds, fix commits, and first verdict"""

    number: int
    rounds: int  # distinct commits its verdicts were given at
    fixes: int
    created: dt.datetime
    first_verdict: dt.datetime | None

    @property
    def cycles(self) -> int:
        return max(self.rounds - 1, 0) + self.fixes


def rework(pr: Node, bots: frozenset[str]) -> Rework:
    verdicts = [r for r in pr["verdicts"]["nodes"] if verdict(r, bots)]
    rounds = len({(r.get("commit") or {}).get("oid") for r in verdicts})
    created = timestamp(pr["createdAt"])
    fixes = sum(fix_commit(c, created) for c in pr["commits"]["nodes"])
    first = min((timestamp(r["submittedAt"]) for r in verdicts), default=None)
    return Rework(pr["number"], rounds, fixes, created, first)


def reworks(data: Data, window: Window) -> list[Rework]:
    """The agent PRs merged in the window, the ones Agent share counts"""
    return [rework(pr, data.bots) for pr in data.pulls if measured(pr, window)]


def rework_cycles(data: Data, window: Window) -> Measure:
    name = "Rework cycles"
    found = reworks(data, window)
    if not found:
        return Measure(name, None, NO_DATA, NO_AGENT_PR, "count")
    mean = statistics.mean(r.cycles for r in found)
    rounds = statistics.mean(r.rounds for r in found)
    fixes = statistics.mean(r.fixes for r in found)
    detail = f"{len(found)} agent PRs: mean {rounds:.1f} review rounds, {fixes:.1f} fix commits"
    extra = {"count": len(found), "review_rounds": rounds, "fix_commits": fixes}
    return Measure(name, mean, f"mean {mean:.1f}", detail, "count", extra)


def first_pass_merge_rate(data: Data, window: Window) -> Measure:
    name = "First-pass merge rate"
    found = reworks(data, window)
    if not found:
        return Measure(name, None, NO_DATA, NO_AGENT_PR, "ratio")
    first = sum(r.cycles == 0 for r in found)
    rate = first / len(found)
    detail = f"{first} of {len(found)} agent PRs merged with 0 rework cycles"
    return Measure(name, rate, f"{rate:.0%}", detail, "ratio", {"first_pass": first, "agent_merges": len(found)})


def review_times(data: Data, window: Window) -> list[tuple[int, float]]:
    """Each agent PR merged in the window with a verdict: its number and the hours from its
    creation to its first verdict"""
    return [(r.number, hours(r.created, r.first_verdict)) for r in reworks(data, window) if r.first_verdict]


def review_time(data: Data, window: Window) -> Measure:
    found = reworks(data, window)
    values = [h for _, h in review_times(data, window)]
    left = len(found) - len(values)
    detail = f"{len(values)} agent PRs; {left} with no verdict left out"
    empty = f"no verdict on any of {left} agent PRs, all left out" if found else NO_AGENT_PR
    return durations("Review time", values, detail, empty)


FENCE = re.compile(r"^[ \t]*(```|~~~)")
SECTION = re.compile(r"^#{1,2}(?:[ \t]|$)")  # a heading that ends a "## Plan" section
FILES_LINE = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?Files:(?P<paths>.*)$")
BACKTICKED = re.compile(r"`([^`]+)`")


def plan_paths(body: str | None) -> list[str] | None:
    """The backticked paths on the Files: lines of the body's one "## Plan" section, outside a
    fence; None when there isn't exactly one such section or its Files: lines name no path"""
    sections: list[list[str]] = []
    current: list[str] | None = None
    fenced = False
    for line in (body or "").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.strip() == "## Plan":
            current = []
            sections.append(current)
        elif SECTION.match(line):
            current = None
        elif current is not None and (found := FILES_LINE.match(line)):
            current += BACKTICKED.findall(found["paths"])
    if len(sections) != 1 or not sections[0]:
        return None
    return sections[0]


def glob_regex(path: str) -> re.Pattern[str]:
    """A path as spec 061 reads a ``Revisit on:`` path: ``**`` any run of characters, ``/``
    included, ``*`` any run without ``/``, ``?`` one character other than ``/``, anything else
    itself"""
    parts = []
    i = 0
    while i < len(path):
        if path.startswith("**", i):
            parts.append(".*")
            i += 2
        elif path[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif path[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(path[i]))
            i += 1
    return re.compile("".join(parts), re.DOTALL)


def covered(changed: str, paths: list[str]) -> bool:
    """The changed file equals a path, is under one ending in "/", or matches one as a glob"""
    return any(
        changed == p or (p.endswith("/") and changed.startswith(p)) or glob_regex(p).fullmatch(changed) for p in paths
    )


def plan_match(data: Data, window: Window) -> Measure:
    name = "Plan match"
    pulls = [pr for pr in data.pulls if measured(pr, window)]
    planned = [(pr, paths) for pr in pulls if (paths := plan_paths(pr["body"])) is not None]
    left = len(pulls) - len(planned)
    if not planned:
        empty = f"no plan naming its files on any of {left} agent PRs, all left out" if pulls else NO_AGENT_PR
        return Measure(name, None, NO_DATA, empty, "ratio")
    matched = sum(all(covered(f["path"], paths) for f in pr["files"]["nodes"]) for pr, paths in planned)
    rate = matched / len(planned)
    detail = (
        f"{matched} of {len(planned)} planned agent PRs changed only files their plan names;"
        f" {left} with no plan left out"
    )
    extra = {"matched": matched, "planned": len(planned), "no_plan": left}
    return Measure(name, rate, f"{rate:.0%}", detail, "ratio", extra)


# -- spec 109: how much of the work a person decided GitHub credits to them ---------------------

# spec 049's reading of who decided a merged PR, as src/shipmill/credit.py reads it, the App
# being any Bot, "[bot]" or --bot account, since metrics.py knows no App login
NEEDS_DECISION = "<!-- shipmill:needs-decision -->"  # a needs-decision question's first line
LOGIN_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
DECISION_BY = re.compile(
    r"Decision by (?:@(" + LOGIN_PATTERN + r")(?=$|\s|[,;:)]|[.!?](?:\s|$))|`@(" + LOGIN_PATTERN + r")`(?![\w`-]))"
)
WRITERS = frozenset({"admin", "maintain", "write"})  # the permissions a label event is trusted by
OPPORTUNITY = "opportunity"
PLANNED = "planned"
NO_STATE = frozenset({"COMMENTED", "PENDING"})  # reviews that leave a person's state as it was
TRAILER_EMAIL = re.compile(r"^co-authored-by:.*<([^<>\s]+)>\s*$", re.IGNORECASE | re.MULTILINE)
AGENT_EMAIL = "[bot]@users.noreply.github.com"  # an App's bot, the co-author spec 051 writes
NO_DECIDED = "no decided PR merged in the window"
Named = tuple[Node, bool]  # an account a record names, and whether its own rule trusts it


def first_line(body: str | None) -> str:
    """A body's first line, past any leading blank lines"""
    return (body or "").lstrip().split("\n", 1)[0].strip()


def relay(line: str) -> Node | None:
    """The person a `Decision by @<login>` line names (D-68)"""
    found = DECISION_BY.match(line)
    return None if found is None else {"__typename": "User", "login": found[1] or found[2]}


def approvals(reviews: Sequence[Node]) -> list[Named]:
    """S-049-3: each person whose latest review that changes state is APPROVED, trusted by its
    author association; an approval whose body carries the agent marker names no one"""
    latest: dict[str, Node] = {}
    for review in reviews:
        if review["author"] is not None and review["state"] not in NO_STATE:
            latest[review["author"]["login"].lower()] = review
    return [
        (r["author"], r["authorAssociation"] in TRUSTED)
        for r in latest.values()
        if r["state"] == "APPROVED" and not marked(r["body"])
    ]


def answers(comments: Sequence[Node], bots: frozenset[str]) -> list[Named]:
    """S-049-4: a question is a comment whose first line is the needs-decision marker, by a bot
    or a trusted person; a reply is a later comment by a person, without the marker first or
    the agent marker in it, trusted by its author association. A bot's comment whose first line
    is `Decision by @<login>` relays that person's answer, whatever agent marker it carries"""
    found: list[Named] = []
    asked = False
    for comment in comments:
        who = comment["author"]
        if who is None:
            continue
        line = first_line(comment["body"])
        bot = bot_author(who, bots)
        if line == NEEDS_DECISION:
            asked = asked or bot or comment["authorAssociation"] in TRUSTED
        elif bot:
            relayed = relay(line)
            if relayed is not None:
                found.append((relayed, True))
        elif asked and not marked(comment["body"]):
            found.append((who, comment["authorAssociation"] in TRUSTED))
    return found


def relayed_accepter(comments: Sequence[Node], bots: frozenset[str]) -> Node | None:
    """S-108-10, D-115: the person a bot's newest relay of an accept names, its first line
    `Decision by @<login>` and its next line starting `accept`"""
    for comment in reversed(comments):
        if not bot_author(comment["author"], bots):
            continue
        lines = [line.strip() for line in (comment["body"] or "").splitlines() if line.strip()]
        relayed = relay(lines[0]) if len(lines) > 1 else None
        if relayed is not None and lines[1].split()[0] == "accept":
            return relayed
    return None


def accepter(issue: Thread, bots: frozenset[str]) -> Node | None:
    """S-049-6: for an opportunity labelled planned, who added planned last, or when a bot did,
    the person its relay of the accept names; None for none"""
    if not {OPPORTUNITY, PLANNED} <= issue.labels or not issue.labelers:
        return None
    last = issue.labelers[-1]
    if last is None:
        return None
    return relayed_accepter(issue.comments, bots) if bot_author(last, bots) else last


def deciders(decision: Decision, bots: frozenset[str]) -> list[str]:
    """S-049-7: the logins of the trusted people spec 049's sources name, in its order, each
    once: approvers; answerers on the PR, then on each issue it closes and their parents; those
    issues' authors (when the body carries no agent marker); and their accepters, trusted by a
    write, maintain, or admin permission. Never a bot, a --bot login, or the PR's author"""
    named = approvals(decision.reviews) + answers(decision.comments, bots)
    for issue in decision.issues:
        named += answers(issue.comments, bots)
    named += [(i.author, i.association in TRUSTED) for i in decision.issues if i.author and not marked(i.body)]
    for issue in decision.issues:
        who = accepter(issue, bots)
        if who is not None:
            named.append((who, decision.permissions[who["login"].lower()] in WRITERS))
    author = (decision.author or {}).get("login", "").lower()
    found: dict[str, str] = {}
    for who, trusted in named:
        key = who["login"].lower()
        if trusted and not bot_author(who, bots) and key != author and key not in found:
            found[key] = who["login"]
    return list(found.values())


def credited(decision: Decision, people: Sequence[str]) -> bool:
    """Every decider's login is among the accounts GitHub credits the merge commit to"""
    merge = decision.merge
    if merge is None:
        return False
    accounts = {n["user"]["login"].lower() for n in merge["authors"]["nodes"] if n["user"] is not None}
    return all(p.lower() in accounts for p in people)


def written_as_decider(decision: Decision, people: Sequence[str]) -> bool:
    """The merge commit's git author resolves to a decider, and a Co-authored-by trailer names
    an App's bot (spec 051)"""
    merge = decision.merge
    user = None if merge is None or merge["author"] is None else merge["author"]["user"]
    if user is None or user["login"].lower() not in {p.lower() for p in people}:
        return False
    return any(email.lower().endswith(AGENT_EMAIL) for email in TRAILER_EMAIL.findall(merge["message"] or ""))


@dataclass(frozen=True)
class Decided:
    """A decided PR merged in the window: its deciders, and how its merge commit credits them"""

    number: int
    people: list[str]
    credited: bool
    written: bool
    sha: str | None


def decided_merges(data: Data, window: Window) -> tuple[int, list[Decided]]:
    """The PRs merged in the window, and the decided ones among them"""
    merged = merged_in(data, window)
    found = []
    for pr in merged:
        decision = data.decisions.get(pr["number"])
        people = [] if decision is None else deciders(decision, data.bots)
        if decision is not None and people:
            found.append(
                Decided(
                    pr["number"],
                    people,
                    credited(decision, people),
                    written_as_decider(decision, people),
                    (pr.get("mergeCommit") or {}).get("oid"),
                )
            )
    return len(merged), found


def decided_extra(merges: int, found: Sequence[Decided]) -> dict[str, Any]:
    """The counts both measures carry, per decider login, sorted, the PRs they decided, and
    each decided PR, sorted by number, with its merge commit and both reads"""
    people: dict[str, dict[str, Any]] = {}
    for d in found:
        for login in d.people:
            entry = people.setdefault(
                login.lower(), {"login": login, "decided": 0, "credited": 0, "written_as_decider": 0}
            )
            entry["decided"] += 1
            entry["credited"] += d.credited
            entry["written_as_decider"] += d.written
    return {
        "merges": merges,
        "decided": len(found),
        "credited": sum(d.credited for d in found),
        "written_as_decider": sum(d.written for d in found),
        "people": [people[key] for key in sorted(people)],
        "pulls": [
            {"number": d.number, "sha": d.sha, "credited": d.credited, "written_as_decider": d.written}
            for d in sorted(found, key=lambda d: d.number)
        ],
    }


def decided_measure(name: str, data: Data, window: Window, part: str) -> Measure:
    merges, found = decided_merges(data, window)
    extra = decided_extra(merges, found)
    if not found:
        return Measure(name, None, NO_DATA, NO_DECIDED, "ratio", extra)
    rate = extra[part] / len(found)
    if part == "credited":
        detail = (
            f"{extra['credited']} of {len(found)} decided merges credited to every decider;"
            f" {merges} merged, {merges - len(found)} with no decider"
        )
    else:
        detail = f"{extra[part]} of {len(found)} decided merges written as the decider with the agent as co-author"
    return Measure(name, rate, f"{rate:.0%}", detail, "ratio", extra)


def decided_credited(data: Data, window: Window) -> Measure:
    return decided_measure("Decided work credited", data, window, "credited")


def decided_written(data: Data, window: Window) -> Measure:
    return decided_measure("Decided work written as the decider", data, window, "written_as_decider")


def measures(data: Data, window: Window) -> list[Measure]:
    return [
        f(data, window)
        for f in (
            deploy_frequency,
            lead_time,
            change_failure_rate,
            time_to_restore,
            issue_to_release,
            issue_to_agent_comment,
            issue_to_pr,
            issue_to_pr_person,
            issue_to_pr_agent,
            pr_to_merge,
            merge_to_release,
            human_touch,
            agent_share,
            decided_credited,
            decided_written,
            rework_cycles,
            first_pass_merge_rate,
            review_time,
            plan_match,
        )
    ]


def render(repo: str, days: int, window: Window, found: list[Measure], form: str) -> str:
    if form == "json":
        return json.dumps(
            {
                "repo": repo,
                "days": days,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "measures": [m.json() for m in found],
            },
            indent=2,
            sort_keys=True,
        )
    if form == "markdown":
        lines = [
            f"**Factory metrics: {repo}, the {days} days to {window.end:%Y-%m-%d}**",
            "",
            "| Measure | Value | Detail |",
            "|---|---|---|",
            *(f"| {m.name} | {m.text} | {m.detail} |" for m in found),
        ]
        return "\n".join(lines)
    head = f"{repo}: the {days} days to {window.end:%Y-%m-%d %H:%M} UTC"
    wide = max((len(m.name) for m in found), default=0)
    return "\n".join([head, *(f"{m.name:<{wide}} {m.text:<32} {m.detail}" for m in found)])


def until(text: str, now: dt.datetime) -> dt.datetime:
    """--until: a date (its 00:00 UTC) or a time with its offset, no later than now"""
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail(f"--until must be a date or a time with its offset, got {text!r}")
    if len(text) == len("YYYY-MM-DD"):
        moment = moment.replace(tzinfo=dt.timezone.utc)  # noqa: UP017 (3.10 has no dt.UTC)
    if moment.tzinfo is None:
        fail(f"--until needs a time's offset, such as Z or +00:00, got {text!r}")
    if moment > now:
        fail(f"--until is in the future: {text}")
    return moment.astimezone(dt.timezone.utc)  # noqa: UP017


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--days", type=int, default=30, help="the window, in days before --until")
    parser.add_argument("--until", help="the window's end: a date or a time with its offset (default now)")
    parser.add_argument("--environment", action="append", default=[], help="count only these environments")
    parser.add_argument("--incident-label", default="incident", help="[operate] incident_label")
    parser.add_argument("--blocker-label", default="release-blocker")
    parser.add_argument("--bot", action="append", default=[], help="a machine user's login, not a person")
    form = parser.add_mutually_exclusive_group()
    form.add_argument("--json", action="store_true")
    form.add_argument("--markdown", action="store_true", help="a table to post on the tracking issue")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)  # noqa: UP017 (3.10 has no dt.UTC)
    end = now if args.until is None else until(args.until, now)
    window = Window(end - dt.timedelta(days=args.days), end)
    bots = frozenset(args.bot)
    environments = frozenset(args.environment)
    data = fetch(args.repo, window, environments, args.incident_label, args.blocker_label, bots=bots, decided=True)
    form_name = "json" if args.json else "markdown" if args.markdown else "table"
    print(render(args.repo, args.days, window, measures(data, window), form_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
