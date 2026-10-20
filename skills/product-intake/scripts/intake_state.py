#!/usr/bin/env python3
"""Where a repo's product feedback stands: which requests no opportunity groups yet, and
where each opportunity issue is in the maintainer's accept or decline.

Usage: intake_state.py <owner/repo> [--config PATH] [--label opportunity]
                       [--accepted-label planned] [--marker "Triage:"] [--skip-label L]...
                       [--category C]... [--json]
                       [--plans [--wip N] [--bot-login LOGIN] [--tool SPEC]]

Feedback is an open issue, or an open discussion when the repo enables Discussions, that:
  - carries none of SKIP_LABELS (bug, roadmap, and shipmill's own labels), no --skip-label
    (repeatable, added to SKIP_LABELS), and not --label
  - has no triage verdict of implement, feature, duplicate, or won't fix: the verdict is
    the first bold word of the newest comment starting with --marker
    ("Triage: **implement**"), so a bug or a contract change stays with triage
  - for a discussion, sits in a --category (default: any category but Announcements)

An opportunity is an issue labelled --label, open or closed. Its members are the issues
and discussions its "## Evidence" section links: #N, owner/repo#N of this repo, or a
github.com link to an issue or a discussion. A member stays a member after it closes.

For each opportunity:
  OPPORTUNITY_OPEN  open: waiting for the maintainer to accept or decline it
  ACCEPTED          open and labelled --accepted-label, and its newest triage comment is
                    intake's own (Triage: **opportunity**) or there is none: hand it to
                    github-issue-triage's spec gate as a feature
  HANDED_OFF        accepted, and triage gave it a newer verdict (feature, with its spec
                    PR on a hold line): triage owns it now
  DECLINED          closed as not planned. The note is the reason: the first line of the
                    oldest non-triage comment from an hour before the close on, so a later
                    comment on the closed issue doesn't replace it. Its members
                    read as declined and are never proposed again
  NO_REASON         closed as not planned with no such comment: the reason isn't recorded
  DONE              closed as completed
  MERGED            closed as a duplicate of another opportunity; it groups nothing, so its
                    members read NEW_FEEDBACK until the surviving opportunity lists them

For feedback and members:
  NEW_FEEDBACK      feedback that no opportunity lists (a MERGED one aside)
  OVERLAP           listed by more than one opportunity that is open or declined

Each opportunity's evidence: its members, and the thumbs-up reactions on them and on the
opportunity itself. The first line (text) or the first JSON line is the [autonomy] intake
level from the shipmill config (.github/shipmill.toml in the current directory; none
means the default, propose).

With --plans (spec 028), the goals of the direction come next, read with
`uvx shipmill==<version> product show --section goals --json` in the current directory
(the version in the plugin's .claude-plugin/plugin.json, spec 031; --tool runs `uvx --from
<tool> shipmill` instead), and a goal with no open plan issue (an issue labelled goal-plan whose body's
first line is the plan marker <!-- shipmill:plan goal=G-n rev=k -->) reads:
  PLAN_DUE          a trigger holds; the note is the trigger:
                    requested in #N  an open issue labelled goal-plan without the plan
                                     marker, opened by an OWNER, MEMBER, or COLLABORATOR,
                                     whose title names one goal id, a listed one; an
                                     issue opened by anyone else is never a request
                    no-work          nothing open serves the goal: no spec in docs/specs/
                                     at the default branch's head with status draft or
                                     approved whose serves: line names it, no open issue
                                     whose newest triage comment names it in `Serves:`,
                                     no open pull request whose `## Plan` names it in
                                     `Serves:`, no open opportunity whose body names it in
                                     `Serves:`, and no open plan item (an issue whose
                                     body's first line is <!-- shipmill:plan-item #P W-n -->,
                                     opened by an OWNER, MEMBER, or COLLABORATOR or the
                                     --bot-login, under plan #P of the goal); never for a
                                     goal whose newest plan was closed as not planned
                    stalled          spec 027's report says the goal is stalled; spec 027
                                     isn't built yet, so this trigger never fires
  PLAN_WAITS        with --wip N, a no-work or stalled trigger holds while
                    `triage_state.py --wip N` reports no room left; the note is the
                    trigger and "waits for room". A request never waits
A goal with an open plan issue reads nothing, whatever its trigger; nor does a goal no
trigger holds for.

Then one row per plan issue: an issue labelled goal-plan whose first line opens the plan
marker, well-formed or not, or that the --bot-login opened. Its answer is the newest
comment newer than its newest revision (the opening body, or the newest comment whose
first line is <!-- shipmill:plan-revised rev=<k> -->, by the --bot-login, with a rev
higher than the revision before it) from an OWNER,
MEMBER, or COLLABORATOR other than the --bot-login; a triage comment (--marker) and a
comment whose first line is a shipmill marker are the sessions' own and never an answer,
and no other comment, reaction, or label is read:
  PLAN_OPEN         open, with no answer; or its answer is an accept older than the
                    body's last edit, noted "edited after accept"
  PLAN_ANSWERED     open, and the answer's first line starts with `decline` (any case;
                    noted "decline") or is anything but an accept (noted "edit")
  PLAN_ACCEPTED     open, the answer's first line is `accept` (any case, an optional
                    final period), and a feature or fix item has no issue carrying its
                    plan-item marker (as `plans.py items` reads it), or the Milestone names
                    a title and a filed item or an existing item of this repo isn't in it;
                    the note names them
  PLAN_FILED        accepted, and neither holds
  PLAN_MALFORMED    open, and `plans.py check` refuses the body; the note names the first
                    line and rule
  PLAN_DECLINED     closed as not planned; the note is the reason: the rest of the newest
                    answer starting with `decline`, else the first comment from an hour
                    before the close on, as for an opportunity
A plan closed as completed or as a duplicate reads nothing.

Exit 0 when nothing needs action, 1 when any row is NEW_FEEDBACK, ACCEPTED, NO_REASON,
OVERLAP, PLAN_DUE, PLAN_ANSWERED, PLAN_ACCEPTED, or PLAN_MALFORMED, 2 on bad input (an
issue with more than 100 labels, a malformed config or goals, an existing item naming no
issue) or a gh failure. Needs the gh CLI, authenticated, and with --plans uvx.
Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the config is read with regexes instead
    tomllib = None  # type: ignore[assignment]

CONFIG = Path(".github/shipmill.toml")
INTAKE_LEVELS = ("observe", "propose")  # shipmill's autonomy: intake never acts
# Labels whose issues are never feedback: bugs, tracking issues, and shipmill's own. Extend
# the list here for every repo, or per run with --skip-label
SKIP_LABELS = (
    "bug",
    "roadmap",
    "shipmill-proposal",
    "shipmill-hold",
    "incident",
    "release-blocker",
    "milestone-proposal",
)
SKIP_CATEGORIES = ("Announcements",)
CLOSING_VERDICTS = ("implement", "feature", "duplicate", "won't fix", "won’t fix", "wont fix")
OWN_VERDICT = "opportunity"  # intake's triage comment on an opportunity it opens
REASON_WINDOW = dt.timedelta(hours=1)  # "close with comment" posts the comment just before the close
ACTION = {"NEW_FEEDBACK", "ACCEPTED", "NO_REASON", "OVERLAP"}
ORDER = (
    "OVERLAP",
    "NO_REASON",
    "ACCEPTED",
    "NEW_FEEDBACK",
    "OPPORTUNITY_OPEN",
    "HANDED_OFF",
    "DECLINED",
    "DONE",
    "MERGED",
)
LIVE = {"OPPORTUNITY_OPEN", "ACCEPTED", "HANDED_OFF", "DECLINED", "NO_REASON"}  # an OVERLAP counts these

ISSUE_FIELDS = """
        number title url state stateReason closedAt body milestone { title }
        author { __typename login } authorAssociation
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        reactions(content: THUMBS_UP) { totalCount }
        comments(last: 50) { pageInfo { hasPreviousPage startCursor } nodes { body createdAt } }
"""
OPEN_ISSUES = (
    """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    hasDiscussionsEnabled
    issues(states: OPEN, first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {"""
    + ISSUE_FIELDS
    + """      }
    }
  }
}
"""
)
OPPORTUNITIES = (
    """
query($owner: String!, $name: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {"""
    + ISSUE_FIELDS
    + """      }
    }
  }
}
"""
)
DISCUSSIONS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url closed category { name } reactions(content: THUMBS_UP) { totalCount } }
    }
  }
}
"""
OLDER_COMMENTS = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(last: 50, before: $cursor) { pageInfo { hasPreviousPage startCursor } nodes { body createdAt } }
    }
  }
}
"""
REF = re.compile(
    r"https?://github\.com/(?P<o1>[\w.-]+)/(?P<n1>[\w.-]+)/(?:issues|discussions|pull)/(?P<k1>\d+)"
    r"|(?<![\w/#])(?:(?P<o2>[\w.-]+)/(?P<n2>[\w.-]+))?#(?P<k2>\d+)\b"
)
MEMBER_THUMBS = "... on Issue { reactions(content: THUMBS_UP) { totalCount } }"
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")
Variables = dict[str, Any]
# Runs one GraphQL query with its variables and returns the parsed JSON response
Runner = Callable[[str, Variables], dict[str, Any]]

# -- goal plans (spec 028)
PLAN_LABEL = "goal-plan"
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE_STATE = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
PLAN_ITEM = re.compile(r"^<!-- shipmill:plan-item #([1-9][0-9]*) W-[1-9][0-9]* -->$")
GOAL_ID = re.compile(r"(?<![\w-])G-[1-9][0-9]*(?![\w-])")
SERVES = re.compile(r"(?<![\w-])Serves:[ \t]*(G-[1-9][0-9]*(?:[ \t]*,[ \t]*G-[1-9][0-9]*)*)")
PLAN_FIELD_SERVES = re.compile(r"^\s*(?:[-*]\s+)?Serves:(.*)$")  # as pr_gate.py reads a plan's line
SPEC_STATUS = re.compile(r"^status:[ \t]*(\S+)[ \t]*$")
SPEC_SERVES = re.compile(r"^serves:(.*)$")
NOT_SPECS = ("TEMPLATE.md", "README.md")  # as specs.py skips them
SERVING_STATUSES = ("draft", "approved")
AUTOMATIC = ("no-work", "stalled")  # the triggers that wait for room under --wip
PLAN_ACTION = {"PLAN_DUE", "PLAN_MALFORMED", "PLAN_ANSWERED", "PLAN_ACCEPTED"}
PLAN_ORDER = (
    "PLAN_DUE",
    "PLAN_MALFORMED",
    "PLAN_ANSWERED",
    "PLAN_ACCEPTED",
    "PLAN_WAITS",
    "PLAN_OPEN",
    "PLAN_FILED",
    "PLAN_DECLINED",
)
PLAN_OPENER = "<!-- shipmill:plan "  # a first line that means to be the plan marker, well-formed or not
SHIPMILL_MARKER = "<!-- shipmill:"  # a session's own marked comment, never an answer
REVISED = re.compile(r"^<!-- shipmill:plan-revised rev=([1-9][0-9]*) -->$")
ACCEPT = re.compile(r"^accept\.?$", re.IGNORECASE)
DECLINE = re.compile(r"^decline", re.IGNORECASE)
FILED_KINDS = ("feature", "fix")
EXISTING_REF = re.compile(r"^(?:([\w.-]+)/([\w.-]+))?#([1-9][0-9]*)$")
PLAN_COMMENT = "body createdAt author { __typename login } authorAssociation"
PLAN_ISSUES = (
    """
query($owner: String!, $name: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url state stateReason closedAt createdAt lastEditedAt body
        author { __typename login } authorAssociation
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        comments(last: 50) { pageInfo { hasPreviousPage startCursor } nodes { """
    + PLAN_COMMENT
    + """ } }
      }
    }
  }
}
"""
)
OLDER_PLAN_COMMENTS = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(last: 50, before: $cursor) { pageInfo { hasPreviousPage startCursor } nodes { """
    + PLAN_COMMENT
    + """ } }
    }
  }
}
"""
)
PULLS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    specs: object(expression: "HEAD:docs/specs") { ... on Tree { entries { name object { ... on Blob { text } } } } }
    pullRequests(states: OPEN, first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number body }
    }
  }
}
"""


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


def load_plans() -> ModuleType:
    """plans.py beside this script: the plan marker, the body's sections, and D-29's trust"""
    path = Path(__file__).resolve().parent / "plans.py"
    spec = importlib.util.spec_from_file_location("shipmill_plans", path)
    if spec is None or spec.loader is None:
        fail(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


PLANS = load_plans()


def gh_graphql(query: str, variables: Variables) -> dict[str, Any]:
    """The default runner: one ``gh api graphql`` call"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        # -F sends an int as a number; -f keeps a string a string (a cursor, a numeric repo name)
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(2)
    response: dict[str, Any] = json.loads(proc.stdout)
    return response


def split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    return owner, name


def repository(run: Runner, query: str, variables: Variables) -> dict[str, Any]:
    response = run(query, variables)
    if response.get("errors"):
        fail(f"GitHub GraphQL errors: {json.dumps(response['errors'])}")
    data = (response.get("data") or {}).get("repository")
    if data is None:
        fail(f"no repository {variables['owner']}/{variables['name']} in the GraphQL response")
    result: dict[str, Any] = data
    return result


def paged(run: Runner, query: str, variables: Variables, key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every node of one connection, oldest first, and the first page's repository fields"""
    first: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        data = repository(run, query, {**variables, **({"cursor": cursor} if cursor else {})})
        first = first if first is not None else data
        nodes += data[key]["nodes"]
        info = data[key]["pageInfo"]
        if not info["hasNextPage"]:
            return nodes, first
        cursor = info["endCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more {key}, but the page cursor did not advance ({cursor!r})")
        seen.add(cursor)


def labels(issue: dict[str, Any]) -> set[str]:
    if issue["labels"]["pageInfo"]["hasNextPage"]:
        fail(f"bad input: issue #{issue['number']} has more than 100 labels, which intake_state.py does not page")
    return {n["name"] for n in issue["labels"]["nodes"]}


def verdict(body: str, marker: str) -> str | None:
    """A triage comment's verdict, lowercased: its first bold phrase, else its first word;
    None for a comment that isn't a triage comment"""
    text = body.lstrip()
    if not text.startswith(marker):
        return None
    rest = text[len(marker) :].strip()
    bold = re.match(r"\*\*([^*]+)\*\*", rest)
    if bold:
        return bold.group(1).strip().lower()
    return rest.split(maxsplit=1)[0].lower() if rest else ""


def newest_triage(issue: dict[str, Any], marker: str) -> str | None:
    """The body of the issue's newest triage comment, None without one"""
    for comment in reversed(issue["comments"]["nodes"]):
        if verdict(comment["body"], marker) is not None:
            body: str = comment["body"]
            return body
    return None


def newest_verdict(issue: dict[str, Any], marker: str) -> str | None:
    body = newest_triage(issue, marker)
    return None if body is None else verdict(body, marker)


def complete_comments(run: Runner, owner: str, name: str, issue: dict[str, Any], marker: str) -> None:
    """Page an issue's comments back, oldest first, only while none of them is a triage comment:
    the newest triage comment is all intake reads from an issue's history"""
    comments = issue["comments"]
    seen: set[str] = set()
    while comments["pageInfo"]["hasPreviousPage"] and newest_verdict(issue, marker) is None:
        cursor = comments["pageInfo"]["startCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more comments on #{issue['number']}, but the page cursor did not advance")
        seen.add(cursor)
        variables: Variables = {"owner": owner, "name": name, "number": issue["number"], "cursor": cursor}
        page = (repository(run, OLDER_COMMENTS, variables).get("issue") or {}).get("comments")
        if page is None:
            fail(f"issue #{issue['number']} vanished while paging its comments")
        comments["nodes"] = page["nodes"] + comments["nodes"]
        comments["pageInfo"] = page["pageInfo"]


def evidence(body: str, owner: str, name: str, section: str = "evidence") -> set[int]:
    """The issue and discussion numbers the body's "Evidence" section (or another, by its
    lowercased heading) links in this repo"""
    found: set[int] = set()
    inside = False
    for line in (body or "").splitlines():
        heading = HEADING.match(line)
        if heading:
            inside = heading.group(1).lower() == section
            continue
        if not inside:
            continue
        for m in REF.finditer(line):
            ref_owner, ref_name = (m["o1"], m["n1"]) if m["k1"] else (m["o2"], m["n2"])
            same = ref_owner is None or (ref_owner.lower(), ref_name.lower()) == (owner.lower(), name.lower())
            if same:
                found.add(int(m["k1"] or m["k2"]))
    return found


def timestamp(text: str) -> dt.datetime:
    """A GitHub ISO 8601 time; "Z", which fromisoformat rejects before Python 3.11, made an offset"""
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail(f"gh returned a time that isn't ISO 8601: {text!r}")
    if moment.tzinfo is None:
        fail(f"gh returned a time without a timezone: {text!r}")
    return moment


def decline_reason(issue: dict[str, Any], marker: str) -> str | None:
    """The first line of the oldest comment that isn't a triage comment, from an hour before
    the close on: the maintainer's reason, not a later reply on the closed issue; None when
    there is none"""
    closed = timestamp(issue["closedAt"]) - REASON_WINDOW
    for comment in issue["comments"]["nodes"]:
        if verdict(comment["body"], marker) is None and timestamp(comment["createdAt"]) >= closed:
            lines = [line.strip() for line in comment["body"].splitlines() if line.strip()]
            if lines:
                return lines[0]
    return None


def opportunity_state(issue: dict[str, Any], accepted: str, marker: str) -> tuple[str, str]:
    if issue["state"] == "CLOSED":
        if issue["stateReason"] == "NOT_PLANNED":
            reason = decline_reason(issue, marker)
            return ("DECLINED", reason) if reason else ("NO_REASON", "closed as not planned with no comment")
        if issue["stateReason"] == "DUPLICATE":
            return "MERGED", "closed as a duplicate"
        return "DONE", ""
    if accepted not in labels(issue):
        return "OPPORTUNITY_OPEN", ""
    found = newest_verdict(issue, marker)
    if found is None or found.startswith(OWN_VERDICT):
        return "ACCEPTED", "hand it to triage's spec gate"
    return "HANDED_OFF", f"triage: {found}"


def skip_labels(extra: list[str]) -> set[str]:
    """SKIP_LABELS and the run's --skip-label additions"""
    return {*SKIP_LABELS, *extra}


def is_feedback(issue: dict[str, Any], skip: set[str], marker: str) -> bool:
    if labels(issue) & skip:
        return False
    found = newest_verdict(issue, marker)
    return found is None or not found.startswith(CLOSING_VERDICTS)


@dataclass
class Item:
    """An issue or a discussion, as intake counts it"""

    number: int
    kind: str  # issue, discussion, or opportunity
    title: str
    thumbs: int
    feedback: bool = False
    state: str = ""
    note: str = ""
    members: list[int] = field(default_factory=list)


@dataclass
class Intake:
    autonomy: str
    opportunities: list[Item]
    feedback: list[Item]
    thumbs: dict[int, int]  # every issue and discussion number with a known thumbs-up count
    # as GitHub returned them, comments paged back to the newest triage comment: the open
    # issues but opportunities, and every opportunity; --plans reads them again
    open_issues: list[dict[str, Any]] = field(default_factory=list)
    opportunity_issues: list[dict[str, Any]] = field(default_factory=list)


def fetch(
    repo: str,
    *,
    label: str,
    accepted: str,
    marker: str,
    skip: set[str],
    categories: set[str] | None,
    autonomy: str,
    run: Runner = gh_graphql,
) -> Intake:
    owner, name = split_repo(repo)
    base: Variables = {"owner": owner, "name": name}
    opened, first = paged(run, OPEN_ISSUES, base, "issues")
    opened = [i for i in opened if label not in labels(i)]  # an open opportunity comes with the rest
    opps, _ = paged(run, OPPORTUNITIES, {**base, "label": label}, "issues")
    for issue in opened + opps:
        complete_comments(run, owner, name, issue, marker)
    thumbs = {i["number"]: i["reactions"]["totalCount"] for i in opened + opps}
    feedback = [
        Item(i["number"], "issue", i["title"], i["reactions"]["totalCount"], feedback=True)
        for i in opened
        if is_feedback(i, skip, marker)
    ]
    if first["hasDiscussionsEnabled"]:
        discussions, _ = paged(run, DISCUSSIONS, base, "discussions")
        for d in discussions:
            thumbs[d["number"]] = d["reactions"]["totalCount"]
            category = (d.get("category") or {}).get("name", "")
            counted = category in categories if categories is not None else category not in SKIP_CATEGORIES
            if not d["closed"] and counted:
                feedback.append(Item(d["number"], "discussion", d["title"], d["reactions"]["totalCount"], True))
    opportunities = []
    for issue in opps:
        state, note = opportunity_state(issue, accepted, marker)
        members = sorted(evidence(issue["body"], owner, name) - {issue["number"]})
        item = Item(issue["number"], "opportunity", issue["title"], issue["reactions"]["totalCount"])
        item.state, item.note, item.members = state, note, members
        opportunities.append(item)
    missing = sorted({m for o in opportunities for m in o.members} - set(thumbs))
    thumbs.update(member_thumbs(run, owner, name, missing))
    return Intake(autonomy, opportunities, feedback, thumbs, opened, opps)


def member_thumbs(run: Runner, owner: str, name: str, numbers: list[int]) -> dict[int, int]:
    """Thumbs-up counts of members fetch didn't see (closed issues), 50 to a query; a number
    that is a pull request or doesn't exist counts 0"""
    found: dict[int, int] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        parts = " ".join(f"m{n}: issueOrPullRequest(number: {n}) {{ {MEMBER_THUMBS} }}" for n in chunk)
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            node = data.get(f"m{n}") or {}
            found[n] = (node.get("reactions") or {}).get("totalCount", 0)
    return found


def rows(intake: Intake) -> list[Item]:
    """The opportunities with their evidence, then NEW_FEEDBACK and OVERLAP"""
    listed: dict[int, list[int]] = {}
    found = [
        replace(o, thumbs=o.thumbs + sum(intake.thumbs.get(m, 0) for m in o.members)) for o in intake.opportunities
    ]
    for o in intake.opportunities:
        if o.state != "MERGED":
            for m in o.members:
                listed.setdefault(m, []).append(o.number)
    for item in intake.feedback:
        if item.number not in listed:
            item.state = "NEW_FEEDBACK"
            item.note = item.kind
            found.append(item)
    states = {o.number: o.state for o in intake.opportunities}
    titles = {i.number: (i.kind, i.title) for i in intake.feedback}
    for number, owners in sorted(listed.items()):
        live = [o for o in owners if states[o] in LIVE]
        if len(live) > 1:
            kind, title = titles.get(number, ("member", ""))
            shown = ", ".join(f"#{o}:{states[o].lower()}" for o in live)
            found.append(Item(number, kind, title, intake.thumbs.get(number, 0), state="OVERLAP", note=shown))
    found.sort(key=lambda r: (ORDER.index(r.state), -r.number))
    return found


# -- goal plans (spec 028): which goals a plan is due for


@dataclass(frozen=True)
class Goal:
    id: str  # G-<n>
    text: str


@dataclass
class PlanRow:
    goal: str | None  # None for a plan whose marker names no goal
    state: str
    title: str  # the goal's text, or the plan issue's title
    note: str
    number: int | None = None  # the request issue for a requested plan, the plan issue for a plan's row
    kind: str = "goal"  # goal: a row per goal (PLAN_DUE, PLAN_WAITS); plan: a row per plan issue


# Reads the direction's goals, in the direction's order
GoalsReader = Callable[[], list[Goal]]
# The room `triage_state.py --wip N` reports under the limit N
RoomReader = Callable[[int], int]


def parse_goals(text: str) -> list[Goal]:
    """`shipmill product show --section goals --json`'s output, strictly"""
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"shipmill product show printed no JSON: {exc}")
    listed = record.get("goals") if isinstance(record, dict) else None
    if not isinstance(listed, list):
        fail("shipmill product show --json printed no `goals` list")
    goals: list[Goal] = []
    for entry in listed:
        ident = entry.get("id") if isinstance(entry, dict) else None
        text_ = entry.get("text") if isinstance(entry, dict) else None
        if not isinstance(ident, str) or not GOAL_ID.fullmatch(ident) or not isinstance(text_, str):
            fail(f"shipmill product show --json listed a goal that isn't an id and a text: {entry!r}")
        goals.append(Goal(ident, text_))
    return goals


def shipmill_command(tool: str | None, plugin: Path | None = None) -> list[str]:
    """How the CLI runs: `uvx shipmill==<version>`, the version in the plugin's own
    .claude-plugin/plugin.json (spec 031), or `uvx --from <tool> shipmill` with --tool. It is
    github-ship-watch's watch_state.py's shipmill_cli; a broken plugin.json exits 2 naming it"""
    spec = importlib.util.spec_from_file_location("shipmill_watch_state", WATCH_STATE)
    if spec is None or spec.loader is None:
        fail(f"can't load {WATCH_STATE}")
    ws = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ws  # its dataclasses look their module up by name
    spec.loader.exec_module(ws)
    try:
        found: list[str] = ws.shipmill_cli(tool, plugin or ws.PLUGIN_JSON)
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    return found


def uvx_goals(tool: str | None) -> GoalsReader:
    """The default goals reader: the direction of the checkout in the current directory"""

    def read() -> list[Goal]:
        cmd = [*shipmill_command(tool), "product", "show", "--section", "goals", "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            fail("uvx is not on PATH: --plans reads the goals with `shipmill product show`")
        if proc.returncode != 0:
            fail(f"shipmill product show failed with exit {proc.returncode}: {proc.stderr.strip()}")
        return parse_goals(proc.stdout)

    return read


def triage_room(repo: str, bot_login: str | None, script: Path = TRIAGE_STATE) -> RoomReader:
    """The default room reader: `triage_state.py <repo> --wip N --json`'s last line"""

    def read(wip: int) -> int:
        cmd = [sys.executable, str(script), repo, "--wip", str(wip), "--json"]
        cmd += ["--bot-login", bot_login] if bot_login else []
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):  # 1 is "an issue needs action", not a failure
            fail(f"triage_state.py --wip failed with exit {proc.returncode}: {proc.stderr.strip()}")
        lines = proc.stdout.strip().splitlines()
        try:
            room = json.loads(lines[-1])["room"] if lines else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            fail(f"triage_state.py --wip --json printed no room line: {exc}")
        if not isinstance(room, int):
            fail(f"triage_state.py --wip --json printed no room line: {lines[-1:]!r}")
        return room

    return read


def goal_ids(text: str) -> set[str]:
    return set(GOAL_ID.findall(text))


def serves(text: str) -> set[str]:
    """The goal ids every `Serves: G-n[, G-m]` in the text names"""
    return {g for m in SERVES.finditer(text) for g in goal_ids(m.group(1))}


def spec_serves(text: str) -> set[str]:
    """The goals a spec serves while its status is draft or approved: its serves: line, read
    from its header (the lines before the first `## ` heading)"""
    status: str | None = None
    named: set[str] = set()
    for line in text.splitlines():
        if line.startswith("## "):
            break
        found = SPEC_STATUS.match(line)
        if found and status is None:
            status = found.group(1)
            continue
        listed = SPEC_SERVES.match(line)
        if listed:
            named |= goal_ids(listed.group(1))
    return named if status in SERVING_STATUSES else set()


def plan_serves(body: str) -> set[str]:
    """The goals a pull request's `## Plan` names in its `Serves:` line"""
    named: set[str] = set()
    for _, level, heading, lines in PLANS.sections(body or ""):
        if level == 2 and heading == "Plan":
            for _, line in lines:
                field_ = PLAN_FIELD_SERVES.match(line)
                if field_:
                    named |= goal_ids(field_.group(1))
    return named


def plan_goal(issue: dict[str, Any]) -> str | None:
    """The goal a plan issue's first-line marker names, None without the marker"""
    found = PLANS.MARKER.match(PLANS.first_line(issue.get("body") or ""))
    return found.group(1) if found else None


def plan_rows(
    goals: list[Goal],
    *,
    open_issues: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    plan_issues: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    specs: list[str],
    marker: str,
    bot_login: str | None,
    wip: int | None,
    room: RoomReader,
) -> list[PlanRow]:
    """One PLAN_DUE or PLAN_WAITS row per goal a trigger holds for and no open plan has"""
    listed = {g.id for g in goals}
    plans_of: dict[int, str] = {}  # each plan issue's goal
    newest: dict[str, dict[str, Any]] = {}  # each goal's newest plan issue
    planned: set[str] = set()  # goals with an open plan issue
    for issue in plan_issues:
        goal = plan_goal(issue)
        if goal is None:
            continue
        plans_of[issue["number"]] = goal
        if issue["state"] == "OPEN":
            planned.add(goal)
        if goal not in newest or issue["number"] > newest[goal]["number"]:
            newest[goal] = issue
    declined = {g for g, i in newest.items() if i["state"] == "CLOSED" and i["stateReason"] == "NOT_PLANNED"}

    served: set[str] = set()
    for text in specs:
        served |= spec_serves(text)
    for pull in pulls:
        served |= plan_serves(pull.get("body") or "")
    for opp in opportunities:
        if opp["state"] == "OPEN":
            served |= serves(opp.get("body") or "")
    requests: dict[str, int] = {}
    for issue in open_issues:
        served |= serves(newest_triage(issue, marker) or "")
        first = PLANS.first_line(issue.get("body") or "")
        item = PLAN_ITEM.match(first)
        if item and PLANS.trusted(issue, bot_login) and int(item.group(1)) in plans_of:
            served.add(plans_of[int(item.group(1))])
        if PLAN_LABEL not in labels(issue) or is_plan(issue, bot_login):
            continue
        if str(issue.get("authorAssociation") or "NONE") not in PLANS.TRUSTED:
            continue  # D-16: only the maintainer's side requests a plan
        named = goal_ids(issue.get("title") or "")
        if len(named) == 1 and named <= listed:
            (goal,) = named
            requests[goal] = min(requests.get(goal, issue["number"]), issue["number"])

    found: list[PlanRow] = []
    left: int | None = None  # the room under --wip, read once and only when a goal waits on it
    for goal in goals:
        if goal.id in planned:
            continue
        if goal.id in requests:
            number = requests[goal.id]
            found.append(PlanRow(goal.id, "PLAN_DUE", goal.text, f"requested in #{number}", number))
            continue
        # `stalled` reads spec 027's report, which isn't built: until it is, it never fires
        if goal.id in served or goal.id in declined:
            continue
        trigger = "no-work"
        if wip is not None:
            left = room(wip) if left is None else left
            if left <= 0:
                found.append(PlanRow(goal.id, "PLAN_WAITS", goal.text, f"{trigger}; waits for room"))
                continue
        found.append(PlanRow(goal.id, "PLAN_DUE", goal.text, trigger))
    found.sort(key=lambda r: PLAN_ORDER.index(r.state))
    return found


# -- goal plans (spec 028): where each plan issue stands


def is_plan(issue: dict[str, Any], bot_login: str | None) -> bool:
    """A goal-plan issue meant as a plan: its first line opens the plan marker, well-formed
    or not, or the --bot-login opened it. Any other goal-plan issue is a request"""
    if PLAN_LABEL not in labels(issue):
        return False
    if PLANS.first_line(issue.get("body") or "").startswith(PLAN_OPENER):
        return True
    return bot_login is not None and PLANS.login(issue.get("author")).lower() == bot_login.lower()


@dataclass(frozen=True)
class Answer:
    kind: str  # accept, decline, or edit
    at: dt.datetime
    body: str


def answerer(comment: dict[str, Any], bot_login: str | None, marker: str) -> bool:
    """D-16: an OWNER, MEMBER, or COLLABORATOR other than the --bot-login; a triage comment
    or a shipmill-marked comment is a session's own, never an answer"""
    if str(comment.get("authorAssociation") or "NONE") not in PLANS.TRUSTED:
        return False
    if bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower():
        return False
    body = comment.get("body") or ""
    return verdict(body, marker) is None and not PLANS.first_line(body).startswith(SHIPMILL_MARKER)


def plan_answer(issue: dict[str, Any], bot_login: str | None, marker: str) -> Answer | None:
    """The newest trusted answer newer than the plan's newest revision: the opening body, or
    the newest `plan-revised` comment by the --bot-login whose rev is higher than the
    revision before it. Anyone else's `plan-revised` comment revises nothing, and, starting
    with a shipmill marker, is no answer either. None while there is none"""
    since = timestamp(issue["createdAt"])
    rev = 0
    found: Answer | None = None
    for comment in sorted(issue["comments"]["nodes"], key=lambda c: timestamp(c["createdAt"])):
        body = comment.get("body") or ""
        at = timestamp(comment["createdAt"])
        revised = REVISED.match(PLANS.first_line(body))
        if revised is not None:
            by_bot = bot_login is not None and PLANS.login(comment.get("author")).lower() == bot_login.lower()
            if by_bot and int(revised.group(1)) > rev and at >= since:
                rev, since, found = int(revised.group(1)), at, None
            continue
        if at <= since or not answerer(comment, bot_login, marker):
            continue
        if found is None or at >= found.at:
            first = PLANS.first_line(body)
            kind = "accept" if ACCEPT.match(first) else "decline" if DECLINE.match(first) else "edit"
            found = Answer(kind, at, body)
    return found


def decline_text(answer: Answer) -> str:
    """A decline's reason: the rest of the comment after `decline`, its first line with text"""
    rest = DECLINE.sub("", answer.body.strip(), count=1).lstrip(" \t:.,;-—–")
    lines = [line.strip() for line in rest.splitlines() if line.strip()]
    return lines[0] if lines else ""


def complete_plan_comments(run: Runner, owner: str, name: str, issue: dict[str, Any]) -> None:
    """Page a plan issue's comments back to its first: an answer is read against every revision"""
    comments = issue["comments"]
    seen: set[str] = set()
    while comments["pageInfo"]["hasPreviousPage"]:
        cursor = comments["pageInfo"]["startCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more comments on #{issue['number']}, but the page cursor did not advance")
        seen.add(cursor)
        variables: Variables = {"owner": owner, "name": name, "number": issue["number"], "cursor": cursor}
        page = (repository(run, OLDER_PLAN_COMMENTS, variables).get("issue") or {}).get("comments")
        if page is None:
            fail(f"issue #{issue['number']} vanished while paging its comments")
        comments["nodes"] = page["nodes"] + comments["nodes"]
        comments["pageInfo"] = page["pageInfo"]


# Where an accepted plan's filing stands: (PLAN_ACCEPTED or PLAN_FILED, the note)
FilingReader = Callable[[dict[str, Any], Any], tuple[str, str]]


def plan_state(
    issue: dict[str, Any],
    *,
    goals: frozenset[str],
    marker: str,
    bot_login: str | None,
    filing: FilingReader,
) -> PlanRow | None:
    """A plan issue's row; None for a plan closed but not as not planned"""
    goal = plan_goal(issue)
    title = issue.get("title") or ""
    number = issue["number"]
    if issue["state"] == "CLOSED":
        if issue["stateReason"] != "NOT_PLANNED":
            return None
        answer = plan_answer(issue, bot_login, marker)
        reason = decline_text(answer) if answer is not None and answer.kind == "decline" else ""
        reason = reason or decline_reason(issue, marker) or "closed as not planned with no reason"
        return PlanRow(goal, "PLAN_DECLINED", title, reason, number, "plan")
    plan, problems = PLANS.parse(issue.get("body") or "", goals)
    if plan is None:
        line, rule = problems[0]
        more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
        return PlanRow(goal, "PLAN_MALFORMED", title, f"line {line}: {rule}{more}", number, "plan")
    answer = plan_answer(issue, bot_login, marker)
    if answer is None:
        return PlanRow(goal, "PLAN_OPEN", title, "", number, "plan")
    if answer.kind != "accept":
        return PlanRow(goal, "PLAN_ANSWERED", title, answer.kind, number, "plan")
    edited = issue.get("lastEditedAt")
    if edited and timestamp(edited) > answer.at:
        return PlanRow(goal, "PLAN_OPEN", title, "edited after accept", number, "plan")
    state, note = filing(issue, plan)
    return PlanRow(goal, state, title, note, number, "plan")


def plan_issue_rows(
    plan_issues: list[dict[str, Any]],
    *,
    goals: frozenset[str],
    marker: str,
    bot_login: str | None,
    filing: FilingReader,
) -> list[PlanRow]:
    found: list[PlanRow] = []
    for issue in plan_issues:
        if is_plan(issue, bot_login):
            row = plan_state(issue, goals=goals, marker=marker, bot_login=bot_login, filing=filing)
            if row is not None:
                found.append(row)
    return found


def existing_milestones(run: Runner, owner: str, name: str, numbers: list[int]) -> dict[int, str | None]:
    """The milestone title of each issue of this repo, 50 to a query"""
    found: dict[int, str | None] = {}
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        parts = " ".join(f"e{n}: issue(number: {n}) {{ milestone {{ title }} }}" for n in chunk)
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
        data = repository(run, query, {"owner": owner, "name": name})
        for n in chunk:
            node = data.get(f"e{n}")
            if node is None:
                fail(f"no issue #{n} in {owner}/{name}, which a plan names as an existing item")
            title = (node.get("milestone") or {}).get("title")
            found[n] = None if title is None else str(title)
    return found


def gh_filing(repo: str, bot_login: str | None, run: Runner) -> FilingReader:
    """The default filing reader: plans.py's items query, and the existing items' milestones"""
    owner, name = split_repo(repo)

    def read(issue: dict[str, Any], plan: Any) -> tuple[str, str]:
        try:
            _, filed = PLANS.plan_carriers(f"{owner}/{name}#{issue['number']}", bot_login, run)
        except PLANS.PlanError as exc:
            fail(str(exc))
        unfiled = [item.id for item, carrier in filed if item.kind in FILED_KINDS and carrier is None]
        carried = [carrier for item, carrier in filed if item.kind in FILED_KINDS and carrier is not None]
        outside: list[int] = []
        if plan.milestone is not None:
            outside += [c.number for c in carried if c.milestone != plan.milestone]
            here: list[int] = []
            for item, _ in filed:
                ref = EXISTING_REF.match(item.text) if item.kind == "existing" else None
                if ref is None:
                    continue
                named = (ref.group(1) or owner, ref.group(2) or name)
                if (named[0].lower(), named[1].lower()) == (owner.lower(), name.lower()):
                    here.append(int(ref.group(3)))
            titles = existing_milestones(run, owner, name, sorted(set(here)))
            outside += [n for n in sorted(set(here)) if titles[n] != plan.milestone]
        notes = []
        if unfiled:
            notes.append(f"not filed: {', '.join(unfiled)}")
        if outside:
            notes.append(f"not in milestone {plan.milestone}: {', '.join(f'#{n}' for n in sorted(set(outside)))}")
        if notes:
            return "PLAN_ACCEPTED", "; ".join(notes)
        return "PLAN_FILED", f"filed: {', '.join(f'#{c.number}' for c in carried)}" if carried else "nothing to file"

    return read


def spec_texts(tree: dict[str, Any] | None) -> list[str]:
    """The text of each spec in docs/specs/ at the default branch's head"""
    entries = (tree or {}).get("entries") or []
    texts = []
    for entry in entries:
        name = str(entry.get("name") or "")
        if name.endswith(".md") and name not in NOT_SPECS:
            texts.append(str((entry.get("object") or {}).get("text") or ""))
    return texts


def fetch_plans(
    repo: str,
    intake: Intake,
    *,
    goals: GoalsReader,
    marker: str,
    bot_login: str | None,
    wip: int | None,
    room: RoomReader,
    run: Runner = gh_graphql,
    filing: FilingReader | None = None,
) -> list[PlanRow]:
    """The plan rows: two queries more than fetch, the open pull requests with the specs at the
    default branch's head, and the plan issues; then a plan's older comments when it has more
    than 50, and for each accepted plan its items' issues; triage_state.py only when a goal
    waits on --wip"""
    owner, name = split_repo(repo)
    base: Variables = {"owner": owner, "name": name}
    direction = goals()
    if not direction:
        return []
    pulls, first = paged(run, PULLS, base, "pullRequests")
    plan_issues, _ = paged(run, PLAN_ISSUES, {**base, "label": PLAN_LABEL}, "issues")
    for issue in plan_issues:
        if is_plan(issue, bot_login) and (issue["state"] == "OPEN" or issue["stateReason"] == "NOT_PLANNED"):
            complete_plan_comments(run, owner, name, issue)
    by_issue = plan_issue_rows(
        plan_issues,
        goals=frozenset(g.id for g in direction),
        marker=marker,
        bot_login=bot_login,
        filing=filing or gh_filing(repo, bot_login, run),
    )
    by_goal = plan_rows(
        direction,
        open_issues=intake.open_issues,
        opportunities=intake.opportunity_issues,
        plan_issues=plan_issues,
        pulls=pulls,
        specs=spec_texts(first.get("specs")),
        marker=marker,
        bot_login=bot_login,
        wip=wip,
        room=room,
    )
    found = by_goal + by_issue
    found.sort(key=lambda r: PLAN_ORDER.index(r.state))
    return found


def show_plan(row: PlanRow) -> str:
    if row.kind == "plan":
        note = "; ".join(part for part in (row.goal, row.note) if part)
        return f"#{row.number:<5} {row.state:<16} {row.title[:70]}  [{note}]"
    return f"{row.goal:<6} {row.state:<16} {row.title[:70]}  [{row.note}]"


# -- the config: [autonomy] intake, read with tomllib on 3.11+, with regexes on 3.10, where any
# form but a plain key = value line in a plain [table] is refused rather than misread


def config_file(given: Path | None) -> Path | None:
    if given is not None:
        if not given.is_file():
            fail(f"no config at {given}")
        return given
    return CONFIG if CONFIG.is_file() else None


def config_values(path: Path, table: str, keys: tuple[str, ...]) -> dict[str, object]:
    """The keys a config table sets, of those asked for"""
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            fail(f"{path}: {exc}")
        section = raw.get(table, {})
        if not isinstance(section, dict):
            fail(f"{path}: {table} must be a table")
        return {k: section[k] for k in keys if k in section}
    return config_values_310(text, path, table, keys)


def config_values_310(text: str, path: Path, table: str, keys: tuple[str, ...]) -> dict[str, object]:
    unreadable = f"{path}: can't read [{table}] on Python 3.10: use 3.11+, or plain key = value lines in [{table}]"
    body: list[str] | None = None
    current = ""
    for line in text.splitlines():
        header = re.match(r"^\s*\[\[?\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$", line)
        if header:
            current = ".".join(p.strip().strip("\"'") for p in header.group(1).split("."))
            if current == table:
                body = []
            continue
        if current == "" and re.match(rf"^\s*[\"']?{re.escape(table)}[\"']?\s*[.=]", line):
            fail(unreadable)
        if current == table and body is not None:
            body.append(line)
    found: dict[str, object] = {}
    for line in body or []:
        for key in keys:
            if not re.match(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*=", line):
                continue
            value = re.match(
                r"^[^=]*=\s*(?:\"([^\"\\]*)\"|'([^']*)'|(-?\d+)|(true|false))\s*(?:#.*)?$",
                line,
            )
            if value is None:
                fail(unreadable)
            text_value = value.group(1) if value.group(1) is not None else value.group(2)
            if text_value is not None:
                found[key] = text_value
            elif value.group(3) is not None:
                found[key] = int(value.group(3))
            else:
                found[key] = value.group(4) == "true"
    return found


def intake_autonomy(path: Path | None) -> str:
    if path is None:
        return "propose"
    level = config_values(path, "autonomy", ("intake",)).get("intake", "propose")
    if level == "act":
        fail(f"{path}: [autonomy] intake is observe or propose: only the maintainer accepts an opportunity")
    if not isinstance(level, str) or level not in INTAKE_LEVELS:
        fail(f"{path}: [autonomy] intake must be one of {list(INTAKE_LEVELS)}, got {level!r}")
    return level


def show(row: Item) -> str:
    detail = []
    if row.kind == "opportunity":
        detail.append(f"{len(row.members)} requests, +1 {row.thumbs}")
    else:
        detail.append(f"+1 {row.thumbs}")
    if row.note:
        detail.append(row.note)
    return f"#{row.number:<5} {row.state:<16} {row.title[:70]}  [{'; '.join(detail)}]"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--config", type=Path, help="the shipmill config (default: .github/shipmill.toml)")
    parser.add_argument("--label", default="opportunity", help="the label of opportunity issues")
    parser.add_argument("--accepted-label", default="planned", help="the label the maintainer accepts with")
    parser.add_argument("--marker", default="Triage:", help="prefix of a triage comment")
    parser.add_argument(
        "--skip-label", action="append", default=[], help=f"not feedback, added to {list(SKIP_LABELS)} (repeatable)"
    )
    parser.add_argument("--category", action="append", help="discussion categories that count (repeatable)")
    parser.add_argument("--json", action="store_true", help="JSON lines instead of a table")
    parser.add_argument("--plans", action="store_true", help="also report the goals a plan is due for (spec 028)")
    parser.add_argument("--wip", type=int, help="with --plans: no-work plans wait while N issues are in progress")
    parser.add_argument("--bot-login", help="with --plans: the login shipmill's sessions write as (<slug>[bot])")
    parser.add_argument(
        "--tool", help="with --plans: where uvx gets shipmill (default: shipmill==<the plugin.json version>)"
    )
    args = parser.parse_args()
    if not args.plans and (args.wip is not None or args.bot_login is not None):
        parser.error("--wip and --bot-login go with --plans")
    if args.wip is not None and args.wip < 1:
        parser.error("--wip must be at least 1")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login must not be empty")

    autonomy = intake_autonomy(config_file(args.config))
    intake = fetch(
        args.repo,
        label=args.label,
        accepted=args.accepted_label,
        marker=args.marker,
        skip=skip_labels(args.skip_label),
        categories=set(args.category) if args.category else None,
        autonomy=autonomy,
    )
    found = rows(intake)
    planned: list[PlanRow] = []
    if args.plans:
        planned = fetch_plans(
            args.repo,
            intake,
            goals=uvx_goals(args.tool),
            marker=args.marker,
            bot_login=args.bot_login,
            wip=args.wip,
            room=triage_room(args.repo, args.bot_login),
        )
    if args.json:
        print(json.dumps({"autonomy": autonomy}))
        for r in found:
            print(
                json.dumps(
                    {
                        "number": r.number,
                        "kind": r.kind,
                        "state": r.state,
                        "title": r.title,
                        "thumbs": r.thumbs,
                        "members": r.members,
                        "note": r.note,
                    },
                    sort_keys=True,
                )
            )
        for p in planned:
            row = {"goal": p.goal, "kind": p.kind, "number": p.number, "state": p.state, "title": p.title}
            print(json.dumps({**row, "note": p.note}, sort_keys=True))
    else:
        print(f"intake autonomy: {autonomy}")
        for r in found:
            print(show(r))
        for p in planned:
            print(show_plan(p))
    actions = any(r.state in ACTION for r in found) or any(p.state in PLAN_ACTION for p in planned)
    return 1 if actions else 0


if __name__ == "__main__":
    sys.exit(main())
