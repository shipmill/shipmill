#!/usr/bin/env python3
"""Gather a repo's weekly retro, and check its proposals against the open issues.

Usage: retro.py gather <owner/repo> [--days 7] [--environment NAME ...]
                       [--incident-label incident] [--bot LOGIN ...] [--json]
                       [--goals [--checkout DIR] [--stalled-weeks 3] [--met-weeks 4]]
                       [--decisions [--checkout DIR] [--raise-at 2] [--lower-after 4]
                                    [--lower-rate 90] [--lower-min 10] [--revert-days 14]
                                    [--role NAME=FILLER[,FILLER...] ...]]
       retro.py findings <owner/repo> [--days 28] [--bot LOGIN ...] [--json]
       retro.py dedupe <owner/repo> --title TITLE [--title TITLE ...] [--json]

gather   runs metrics.py over the --days to now and over the --days before that, and prints
         each measure for both windows; then the pull requests of the window that were
         refused (closed without a merge) or reworked (merged after a review requested
         changes). Read-only
         --goals adds the report per goal of the direction (spec 027), read from DIR, a
         checkout whose HEAD is origin/HEAD's commit (else exit 2), through `shipmill product
         show --json` (as `uvx shipmill==<version>`, the version in the plugin's
         .claude-plugin/plugin.json, spec 031; a direction it refuses exits 2); without
         docs/product.md it says so and exits 0. "A week" is one --days window. Per goal: the
         issues closed as completed and the pull requests merged that served it, this week
         and the week before (an issue by its latest trusted verdict comment's `Serves:`, or
         the `serves:` of a spec listing it under Issues; a pull request by its `## Plan`
         `Serves:`); its measure met, not met, no data, or no measure, from metrics.py, and
         the weeks in a row it was met (metrics.py runs for earlier weeks, up to
         --met-weeks, only while a measured goal is still met); for a not-met
         issue_to_release_* or lead_time_* measure, grew_most: the stage whose same statistic
         grew most in hours from the week before (spec 066); stalled when nothing served
         it in each of the last --stalled-weeks weeks, unless its id entered the direction
         (git log in DIR) fewer weeks ago. Then the `quality bar` row, the off-direction
         verdicts (postponed for no goal, won't fix for a non-goal, the most-cited N-n, ties
         to the lowest id), and the agent-made merged pull requests whose plan names no
         listed goal. A verdict comment counts only when its first line starts `Triage: ` and
         an OWNER, MEMBER, or COLLABORATOR or a --bot login wrote it (D-29)
         --decisions adds the report per zone of the decision policy (spec 030), the levels
         read from DIR's .github/shipmill.toml [decisions] (DIR at origin/HEAD, else exit 2;
         the zones, defaults, and floors from github-issue-triage's decisions.py). Per zone,
         on the issues' and pull requests' comments posted in this --days window by a
         trusted author as above: the decided markers, the veto-handled markers, the
         needs-decision questions with a zone line, those answered, and those answered with
         the recommended option: the zone line's answer= when it has one, else the first
         answer after the question (a trusted person's reply without the agent marker, or a
         --bot login's relay `Decision by @<login>` naming the maintainer the --role flags
         give), its first non-blank line taking the option marked (recommended) as it stands,
         its number or its text alone or both as listed (`1. <text>`); an answer that can't be
         read is answered and not recommended, a question with no answer yet is not answered;
         and the same over the last --lower-after windows, with the rate, the percent
         recommended of answered, rounded down. Questions whose second line is no zone line
         are counted apart (`unzoned`, with their items) and with the rest under `all`, never
         in a zone. Per zone, the decided markers over the windows and what became of each
         item (spec 058): vetoed (a veto-handled marker for the zone after it), else reverted
         (within --revert-days after it, an issue reopened, or a merged pull request reverted
         by another merged one: a body line `Reverts <owner/repo>#N` or `Reverts #N`, or the
         title `Revert "<its title>"`), else held once the marker is --revert-days old. It
         proposes `Decision policy: <zone> from notify to ask` for a zone at notify with
         --raise-at vetoes or more this window (reverted items count for nothing), and
         `<zone> from ask to notify` for a zone at ask, above its floor, whose answered
         questions over the --lower-after windows number at least --lower-min (10) with at
         least --lower-rate (90, 1 to 100) percent recommended; never notify to act. A marker
         naming no zone id is listed apart
findings what reviews raised on the pull requests closed, merged or not, in the last --days
         (spec 077), newest pull request first, each item with an F-n id: `record`, a --bot
         login's review whose first line is `<!-- shipmill:review merge|refuse -->`; `review`,
         a review that requested changes, and `comment`, an inline review comment (with its
         path:line), by an OWNER, MEMBER, or COLLABORATOR who is no --bot login, without the
         agent marker; `refusal`, the newest comment at or before the close of a pull request
         closed unmerged, by a --bot login or an OWNER, MEMBER, or COLLABORATOR. Each names its
         author, the head it was raised on, the I-n, N-n, Q-n, and D-n ids it cites, and its
         text cut at 600 characters. Anyone else's is left out whole (D-16), and a pull request
         with no item is not listed. Then Proposed: every `rule-proposal` issue, of any age,
         whose first line is `<!-- shipmill:rule-proposal pulls=N,M place=P -->` and whose
         author is trusted as above, as open, accepted (closed as completed), or declined
         (closed as not planned). --json prints {window, findings, proposed}. Read-only
dedupe   each proposed issue title against the repo's open issues: DUPLICATE with the open
         issue whose title matches (ignoring case, punctuation, and spacing), else NEW.
         Read-only: the retro opens only the NEW ones

Exit 0 on success (dedupe: every title is new), 1 when dedupe finds a duplicate, 2 on bad
input or a gh, git, shipmill, or metrics.py failure. Needs the gh CLI, authenticated, and for
--goals git and uvx. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable, Container, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from metrics import PULL_COMMITS, Runner, Variables, agent_made, dig, gh_graphql, pages, pull_commits, sized, span

METRICS = Path(__file__).resolve().parent / "metrics.py"
PR_LIMIT = 500  # closed pull requests in one window; more is refused, not truncated
ISSUE_LIMIT = 1000


@dataclass(frozen=True)
class Change:
    measure: str
    previous: str
    current: str


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    url: str
    why: str


@dataclass(frozen=True)
class Verdict:
    title: str
    duplicate: int | None  # the open issue it matches
    existing: str


def fail(message: str) -> SystemExit:
    sys.stderr.write(f"error: {message}\n")
    return SystemExit(2)


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def gh_output(cmd: list[str], fix: str = "", run: Callable[[list[str]], Any] = run_command) -> str:
    proc = run(["gh", *cmd])
    if proc.returncode != 0:
        raise fail(f"gh {' '.join(cmd[:2])}: {proc.stderr.strip()}{fix}")
    return str(proc.stdout)


def gh(cmd: list[str]) -> Any:
    return json.loads(gh_output(cmd))


GH_FIX = "; check `gh auth status` and the repo's name, then run findings again"


def gh_read(cmd: list[str], run: Callable[[list[str]], Any] = run_command) -> Any:
    """gh's JSON for a command, naming the fix when it fails; a `gh api --paginate ... --jq .[]`
    read gives one JSON value per line, returned as a list"""
    out = gh_output(cmd, GH_FIX, run)
    if "--paginate" in cmd:
        return [json.loads(line) for line in out.splitlines() if line.strip()]
    return json.loads(out)


def timestamp(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


# -- gather ---------------------------------------------------------------------------------


def compare(previous: dict[str, Any], current: dict[str, Any]) -> list[Change]:
    """Each measure of the current window beside the previous window's, in metrics.py's order"""
    before = {m["measure"]: m["text"] for m in previous["measures"]}
    missing = [m["measure"] for m in current["measures"] if m["measure"] not in before]
    if missing:
        raise fail(f"the earlier window has no {', '.join(missing)}")
    return [Change(m["measure"], before[m["measure"]], m["text"]) for m in current["measures"]]


def classify(pulls: list[dict[str, Any]], start: dt.datetime, end: dt.datetime) -> tuple[list[Pull], list[Pull]]:
    """The window's refused pull requests (closed unmerged) and reworked ones (merged after a
    review requested changes), each newest first as gh lists them"""
    refused, reworked = [], []
    for p in pulls:
        if p["mergedAt"] is None:
            if p["closedAt"] is not None and start <= timestamp(p["closedAt"]) <= end:
                refused.append(Pull(p["number"], p["title"], p["url"], "closed without a merge"))
            continue
        if not start <= timestamp(p["mergedAt"]) <= end:
            continue
        asked = sorted(
            {(r["author"] or {}).get("login", "ghost") for r in p["reviews"] if r["state"] == "CHANGES_REQUESTED"}
        )
        if asked:
            reworked.append(Pull(p["number"], p["title"], p["url"], "changes requested by @" + ", @".join(asked)))
    return refused, reworked


def metrics(repo: str, days: int, until: str | None, extra: list[str]) -> dict[str, Any]:
    cmd = [sys.executable, str(METRICS), repo, "--days", str(days), "--json", *extra]
    if until is not None:
        cmd += ["--until", until]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise fail(f"metrics.py: {proc.stderr.strip()}")
    found: dict[str, Any] = json.loads(proc.stdout)
    return found


@dataclass(frozen=True)
class Sources:
    """Everything gather reads from outside, injectable for tests: gh's JSON for a command,
    metrics.py's JSON for the window ending at a time (None: now), GitHub's GraphQL, a
    command run (git, shipmill), and how shipmill is run"""

    gh: Callable[[list[str]], Any]
    metrics: Callable[[str | None], dict[str, Any]]
    graphql: Runner = gh_graphql
    command: Callable[[list[str]], subprocess.CompletedProcess[str]] = run_command
    shipmill: tuple[str, ...] = field(default_factory=tuple)


def sources_for(args: argparse.Namespace) -> Sources:
    extra = [f"--environment={e}" for e in args.environment] + [f"--bot={b}" for b in args.bot]
    extra.append(f"--incident-label={args.incident_label}")
    shipmill = pinned_shipmill() if args.goals else ()
    return Sources(gh, lambda until: metrics(args.repo, args.days, until, extra), shipmill=shipmill)


def pinned_shipmill(plugin: Path | None = None) -> tuple[str, ...]:
    """`uvx shipmill==<version>`, the version in the plugin's .claude-plugin/plugin.json, as
    every skill runs the CLI (spec 031); a missing or malformed one exits 2 naming it"""
    import watch_state  # beside this script; loaded only for --goals, the one read that runs shipmill

    try:
        return tuple(watch_state.shipmill_cli(None, plugin or watch_state.PLUGIN_JSON))
    except watch_state.Refused as refused:
        raise fail(str(refused).removeprefix("error: ")) from None


def gather(args: argparse.Namespace, sources: Sources) -> int:
    maintainers = maintainer_logins(args.role) if args.decisions else frozenset()
    direction = read_direction(sources, args.checkout) if args.goals else None
    levels = read_policy(sources, args.checkout) if args.decisions else None
    current = sources.metrics(None)
    previous = sources.metrics(current["start"])
    start, end = timestamp(current["start"]), timestamp(current["end"])
    fields = "number,title,url,mergedAt,closedAt,reviews"
    search = f"closed:>={start:%Y-%m-%d}"
    cmd = [
        "pr",
        "list",
        "-R",
        args.repo,
        "--state",
        "closed",
        "--search",
        search,
        "-L",
        str(PR_LIMIT),
        "--json",
        fields,
    ]
    pulls = sources.gh(cmd)
    if len(pulls) >= PR_LIMIT:
        raise fail(f"{args.repo} closed {PR_LIMIT}+ pull requests since {start:%Y-%m-%d}; use a shorter --days")
    refused, reworked = classify(pulls, start, end)
    changes = compare(previous, current)
    goals: dict[str, Any] | None = None
    if args.goals:
        goals = {"direction": False}
        if direction is not None:
            goals = goals_report(args, sources, direction, [current, previous])
    decisions = decisions_report(args, sources, levels, end, maintainers) if levels is not None else None
    if args.json:
        window = {"start": current["start"], "end": current["end"], "previous_start": previous["start"]}
        report = {
            "window": window,
            "metrics": [asdict(c) for c in changes],
            "refused": [asdict(p) for p in refused],
            "reworked": [asdict(p) for p in reworked],
        }
        if goals is not None:
            report["goals"] = goals
        if decisions is not None:
            report["decisions"] = decisions
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(f"{args.repo}: the {args.days} days to {end:%Y-%m-%d %H:%M} UTC, against the {args.days} days before")
    for c in changes:
        print(f"  {c.measure:<22} {c.previous:<28} -> {c.current}")
    for name, found in (("Refused", refused), ("Reworked", reworked)):
        print(f"{name}: {len(found) or 'none'}")
        for p in found:
            print(f"  #{p.number} {p.title} ({p.why}) {p.url}")
    if goals is not None:
        print("\n".join(goals_text(goals)))
    if decisions is not None:
        print("\n".join(decisions_text(decisions)))
    return 0


# -- goals (spec 027) -------------------------------------------------------------------------

DIRECTION = "docs/product.md"
DIRECTION_DIR = "docs/product"
QUALITY_BAR = "quality bar"
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})  # D-16, D-29
VERDICT = "Triage: "
# spec 024's verdict line: "Triage: **implement**. Serves: G-1, G-2." (or "Serves: quality bar.")
_NAME = r"(?:G-[1-9][0-9]*|quality bar)"
VERDICT_SERVES = re.compile(r"\bServes: (" + _NAME + r"(?:, ?" + _NAME + r")*)")
POSTPONED = "Triage: **postponed**: it serves no goal of the direction."
WONT_FIX = re.compile(r"^Triage: \*\*won't fix\*\*: it hits (N-[1-9][0-9]*)\b")
# A pull request's plan, read as pr_gate.py reads it: the one `## Plan` section's `Serves:`
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_PLAN_SERVES = re.compile(r"^\s*(?:[-*]\s+)?Serves:(.*)$")
_PLAN_QUALITY = re.compile(r"Q-[1-9][0-9]*")
_PLAN_QUALITY_IDS = re.compile(r"quality bar \(([^()]*)\)")
# A spec (docs/specs/NNN-<slug>.md): its `serves:` line and its `## Issues` items
_SPEC_NAME = re.compile(r"^\d{3,}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_SPEC_SERVES = re.compile(r"^serves:(.*)$")
_SPEC_ISSUE = re.compile(r"^- (?:([\w.-]+/[\w.-]+))?#(\d+)\b")
# Each registry metric (src/shipmill/product.py): metrics.py's measure and the key holding its value
METRIC_MEASURES = {
    "deploy_frequency": ("Deploy frequency", "value"),
    "lead_time_median": ("Lead time for changes", "value"),
    "lead_time_p90": ("Lead time for changes", "p90"),
    "change_failure_rate": ("Change failure rate", "value"),
    "time_to_restore_median": ("Time to restore", "value"),
    "issue_to_release_median": ("Issue to release", "value"),
    "issue_to_release_p90": ("Issue to release", "p90"),
    "human_touch": ("Human touch", "value"),
    "agent_share": ("Agent share", "value"),
    # Issue to release by stage (spec 066)
    "issue_to_agent_comment_median": ("Issue to first agent comment", "value"),
    "issue_to_agent_comment_p90": ("Issue to first agent comment", "p90"),
    "issue_to_pr_median": ("Issue to PR opened", "value"),
    "issue_to_pr_p90": ("Issue to PR opened", "p90"),
    "issue_to_pr_person_median": ("Issue to PR opened, person-filed", "value"),
    "issue_to_pr_person_p90": ("Issue to PR opened, person-filed", "p90"),
    "issue_to_pr_agent_median": ("Issue to PR opened, agent-filed", "value"),
    "issue_to_pr_agent_p90": ("Issue to PR opened, agent-filed", "p90"),
    "pr_to_merge_median": ("PR opened to merged", "value"),
    "pr_to_merge_p90": ("PR opened to merged", "p90"),
    "merge_to_release_median": ("Merged to release", "value"),
    "merge_to_release_p90": ("Merged to release", "p90"),
}
MET, NOT_MET, NO_DATA, NO_MEASURE = "met", "not met", "no data", "no measure"
# A lead-time metric's stages (spec 066), in order: a not-met goal names the one that grew most
ISSUE_STAGES = ("Issue to PR opened", "PR opened to merged", "Merged to release")
LEAD_TIME_STAGES = {
    "issue_to_release_median": ISSUE_STAGES,
    "issue_to_release_p90": ISSUE_STAGES,
    "lead_time_median": ISSUE_STAGES[1:],
    "lead_time_p90": ISSUE_STAGES[1:],
}
STATISTICS = {"value": "median", "p90": "p90"}

ISSUES = """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    issues(first: $size, after: $cursor, filterBy: {since: $since}, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number state stateReason closedAt
        comments(last: 50) {
          pageInfo { hasPreviousPage startCursor }
          nodes { body createdAt authorAssociation author { __typename login } }
        }
      }
    }
  }
}
"""
ISSUE_COMMENTS = """
query($owner: String!, $name: String!, $size: Int!, $cursor: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(last: $size, before: $cursor) {
        pageInfo { hasPreviousPage startCursor }
        nodes { body createdAt authorAssociation author { __typename login } }
      }
    }
  }
}
"""
MERGED = """
query($owner: String!, $name: String!, $size: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: $size, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url body updatedAt mergedAt
        commits(first: 100) { pageInfo { hasNextPage endCursor } nodes { commit { message } } }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Window:
    """One week: after start, up to and including end"""

    start: dt.datetime
    end: dt.datetime

    def __contains__(self, moment: dt.datetime) -> bool:
        return self.start < moment <= self.end


def weeks(end: dt.datetime, days: int, count: int) -> list[Window]:
    """count windows of days, back from end: this week first"""
    span = dt.timedelta(days=days)
    return [Window(end - (k + 1) * span, end - k * span) for k in range(count)]


def at_origin_head(sources: Sources, checkout: Path) -> None:
    """Exit 2 unless the checkout's HEAD is origin/HEAD's commit"""
    proc = sources.command(["git", "-C", str(checkout), "rev-parse", "HEAD", "origin/HEAD"])
    heads = proc.stdout.split()
    if proc.returncode != 0 or len(heads) != 2 or heads[0] != heads[1]:
        why = proc.stderr.strip() or "HEAD is not origin/HEAD's commit"
        raise fail(
            f"{checkout}: {why}; run `git -C {checkout} fetch origin` and "
            f"`git -C {checkout} checkout --detach origin/HEAD`, then gather again"
        )


def read_direction(sources: Sources, checkout: Path) -> dict[str, Any] | None:
    """The direction as `shipmill product show --json` gives it, None without docs/product.md;
    exit 2 when the checkout isn't at origin/HEAD or shipmill refuses the direction"""
    at_origin_head(sources, checkout)
    if not (checkout / DIRECTION).is_file():
        return None
    proc = sources.command([*sources.shipmill, "product", "show", "--json", "--repo", str(checkout)])
    if proc.returncode != 0:
        raise fail(
            f"shipmill product show refused {checkout / DIRECTION}: {proc.stderr.strip()}; "
            f"run `shipmill product check --repo {checkout}`"
        )
    direction: dict[str, Any] = json.loads(proc.stdout)
    if not isinstance(direction.get("goals"), list):
        raise fail(f"shipmill product show --json gave no goals list for {checkout}")
    return direction


def login_names(author: dict[str, Any] | None) -> set[str]:
    """An author's login as GraphQL and REST spell it, a Bot's with and without "[bot]", lowercase"""
    if not author or not author.get("login"):
        return set()
    name = str(author["login"]).lower()
    return {name, name + "[bot]"} if author.get("__typename") == "Bot" else {name}


def trusted(comment: dict[str, Any], bots: frozenset[str]) -> bool:
    """D-29's rule: an OWNER, MEMBER, or COLLABORATOR, or a --bot login"""
    if str(comment.get("authorAssociation") or "NONE") in TRUSTED:
        return True
    return bool(login_names(comment.get("author")) & {b.lower() for b in bots})


def first_line(body: str) -> str:
    return body.lstrip().split("\n", 1)[0].strip()


def latest_verdict(comments: list[dict[str, Any]], bots: frozenset[str]) -> dict[str, Any] | None:
    """The newest comment, of those oldest first, whose first line starts `Triage: ` by a trusted author"""
    for comment in reversed(comments):
        if first_line(comment["body"]).startswith(VERDICT) and trusted(comment, bots):
            return comment
    return None


def names(text: str) -> set[str]:
    """The comma-separated names of a `Serves:` or `serves:` line"""
    return {part.strip() for part in text.split(",") if part.strip()}


def verdict_serves(body: str) -> set[str]:
    """The goal ids and `quality bar` a verdict line names after `Serves: `"""
    found = VERDICT_SERVES.search(first_line(body))
    return names(found.group(1)) if found else set()


def plan_serves(body: str | None) -> set[str]:
    """What the body's one `## Plan` names in its one `Serves:` line; nothing without one"""
    plans: list[list[str]] = []
    current: list[str] | None = None
    fence: str | None = None
    for line in (body or "").splitlines():
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened is not None:
            fence = opened.group(1)
        else:
            heading = _HEADING.match(line)
            if heading is not None and len(heading.group(1)) <= 2:
                plan = len(heading.group(1)) == 2 and (heading.group(2) or "").strip() == "Plan"
                current = [] if plan else None
                if current is not None:
                    plans.append(current)
                continue
        if current is not None:
            current.append(line)
    if len(plans) != 1:
        return set()
    serves = [m.group(1) for m in (_PLAN_SERVES.match(line) for line in plans[0]) if m]
    if len(serves) != 1:
        return set()
    # #1016: a quality-bar id, alone or in `quality bar (Q-4, Q-6)`, counts as the quality bar
    named = names(_PLAN_QUALITY_IDS.sub(QUALITY_BAR, serves[0]))
    return {QUALITY_BAR if _PLAN_QUALITY.fullmatch(name) else name for name in named}


def spec_goals(checkout: Path, repo: str) -> dict[int, set[str]]:
    """Each build issue a spec lists under `## Issues`, with what its `serves:` line names"""
    found: dict[int, set[str]] = {}
    folder = checkout / "docs" / "specs"
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.md")):
        if not _SPEC_NAME.match(path.name):
            continue
        serves: set[str] = set()
        section: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
                continue
            heading = _SPEC_SERVES.match(line) if section is None else None
            if heading:
                serves = names(heading.group(1))
            item = _SPEC_ISSUE.match(line) if section == "Issues" and serves else None
            if item and (item.group(1) is None or item.group(1).lower() == repo.lower()):
                found.setdefault(int(item.group(2)), set()).update(serves)
    return found


def fetch_issues(sources: Sources, repo: str, since: dt.datetime, bots: frozenset[str]) -> list[dict[str, Any]]:
    """Issues updated since, each with its comments paged back to its latest trusted verdict"""
    owner, _, name = repo.partition("/")
    base: Variables = {"owner": owner, "name": name}
    sizes = {ISSUES: 50, ISSUE_COMMENTS: 100}
    variables: Variables = {**base, "since": since.isoformat().replace("+00:00", "Z")}
    issues = pages(sources.graphql, ISSUES, variables, sizes, ["issues"], "issues updated in the weeks")
    for issue in issues:
        comments = issue["comments"]
        seen: set[str] = set()
        while comments["pageInfo"]["hasPreviousPage"] and latest_verdict(comments["nodes"], bots) is None:
            cursor = comments["pageInfo"]["startCursor"]
            if not cursor or cursor in seen:
                raise fail(f"GitHub reported more comments on #{issue['number']}, but the cursor did not advance")
            seen.add(cursor)
            what = f"the comments of #{issue['number']}"
            page = sized(
                sources.graphql, ISSUE_COMMENTS, {**base, "number": issue["number"], "cursor": cursor}, sizes, what
            )
            older = page["issue"]["comments"]
            comments["nodes"] = older["nodes"] + comments["nodes"]
            comments["pageInfo"] = older["pageInfo"]
    return issues


def fetch_merged(sources: Sources, repo: str, since: dt.datetime) -> list[dict[str, Any]]:
    """Pull requests merged since, newest update first (a merge updates its pull request)"""
    owner, _, name = repo.partition("/")
    sizes = {MERGED: 50}
    found = pages(
        sources.graphql,
        MERGED,
        {"owner": owner, "name": name},
        sizes,
        ["pullRequests"],
        "merged pull requests",
        lambda n: timestamp(n["updatedAt"]) < since,
    )
    return [p for p in found if p["mergedAt"] and timestamp(p["mergedAt"]) > since]


@dataclass
class Served:
    """The work that served each goal id (and `quality bar`) in one week"""

    issues: dict[str, list[int]] = field(default_factory=dict)
    pulls: dict[str, list[int]] = field(default_factory=dict)

    def any(self, name: str) -> bool:
        return bool(self.issues.get(name) or self.pulls.get(name))

    def row(self, name: str) -> dict[str, list[int]]:
        return {"issues": self.issues.get(name, []), "pulls": self.pulls.get(name, [])}

    def counts(self, name: str) -> dict[str, int]:
        return {"issues": len(self.issues.get(name, [])), "pulls": len(self.pulls.get(name, []))}


def served(
    issues: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    windows: list[Window],
    specs: dict[int, set[str]],
    bots: frozenset[str],
) -> list[Served]:
    """Per week, the issues closed as completed and the pull requests merged under each name
    they serve, numbers ascending"""
    found = [Served() for _ in windows]
    for issue in issues:
        if issue["state"] != "CLOSED" or issue["stateReason"] != "COMPLETED" or not issue["closedAt"]:
            continue
        closed = timestamp(issue["closedAt"])
        verdict = latest_verdict(issue["comments"]["nodes"], bots)
        serves = (verdict_serves(verdict["body"]) if verdict else set()) | specs.get(issue["number"], set())
        for week, window in zip(found, windows, strict=True):
            if closed in window:
                for name in serves:
                    week.issues.setdefault(name, []).append(issue["number"])
    for pull in pulls:
        merged = timestamp(pull["mergedAt"])
        for week, window in zip(found, windows, strict=True):
            if merged in window:
                for name in plan_serves(pull["body"]):
                    week.pulls.setdefault(name, []).append(pull["number"])
    for week in found:
        for numbers in (*week.issues.values(), *week.pulls.values()):
            numbers.sort()
    return found


def off_direction(issues: list[dict[str, Any]], window: Window, bots: frozenset[str]) -> dict[str, Any]:
    """The issues whose latest trusted verdict, posted in the window, postponed them for no
    goal or declined them for a non-goal, and the most-cited non-goal (ties: the lowest id)"""
    postponed: list[int] = []
    wont_fix: list[dict[str, Any]] = []
    for issue in issues:
        verdict = latest_verdict(issue["comments"]["nodes"], bots)
        if verdict is None or timestamp(verdict["createdAt"]) not in window:
            continue
        line = first_line(verdict["body"])
        hit = WONT_FIX.match(line)
        if line.startswith(POSTPONED):
            postponed.append(issue["number"])
        elif hit:
            wont_fix.append({"number": issue["number"], "non_goal": hit.group(1)})
    cited: dict[str, int] = {}
    for w in wont_fix:
        cited[w["non_goal"]] = cited.get(w["non_goal"], 0) + 1
    top = min(cited, key=lambda n: (-cited[n], int(n[2:]))) if cited else None
    return {
        "postponed": sorted(postponed),
        "wont_fix": sorted(wont_fix, key=lambda w: w["number"]),
        "top_non_goal": top,
    }


def measure_value(measure: dict[str, Any], report: dict[str, Any]) -> tuple[float | None, str]:
    """The measure's value in its metric's unit for the report's window, and metrics.py's
    text for it (`median 2.4 d`); None and "no data" when metrics.py has none"""
    metric = measure["metric"]
    if metric not in METRIC_MEASURES:
        raise fail(f"a measure names {metric!r}, which retro.py doesn't read; update the skills")
    name, key = METRIC_MEASURES[metric]
    found = [m for m in report["measures"] if m["measure"] == name]
    if len(found) != 1:
        raise fail(f"metrics.py gave {len(found)} {name!r} measures, not one")
    value = found[0]
    if value["unit"] != measure["unit"]:
        raise fail(f"metrics.py gives {name} in {value['unit']}, the measure {measure['text']!r} in {measure['unit']}")
    if value["value"] is None:
        return None, value["text"]
    text = str(value["text"])
    if value["unit"] == "hours":  # "median 1.2 d, p90 3.0 d": the part for this value
        prefix = "p90 " if key == "p90" else "median "
        text = next((part for part in text.split(", ") if part.startswith(prefix)), text)
    return float(value[key]), text


def holds(value: float, comparison: str, target: float) -> bool:
    checks = {"<": value < target, "<=": value <= target, ">": value > target, ">=": value >= target}
    if comparison not in checks:
        raise fail(f"a measure's comparison is <, <=, >, or >=; got {comparison!r}")
    return checks[comparison]


def status(measure: dict[str, Any] | None, report: dict[str, Any]) -> tuple[str, float | None, str | None]:
    """met, not met, no data, or no measure; the value and metrics.py's text for it"""
    if measure is None:
        return NO_MEASURE, None, None
    value, text = measure_value(measure, report)
    if value is None:
        return NO_DATA, None, text
    return (MET if holds(value, measure["comparison"], float(measure["target"])) else NOT_MET), value, text


def stage_value(name: str, key: str, report: dict[str, Any]) -> float | None:
    """A stage's median (key "value") or p90 in hours from metrics.py's JSON; None for no data"""
    found = [m for m in report["measures"] if m["measure"] == name]
    if len(found) != 1:
        raise fail(f"metrics.py gave {len(found)} {name!r} measures, not one")
    if found[0]["unit"] != "hours":
        raise fail(f"metrics.py gives {name} in {found[0]['unit']}, not hours")
    return None if found[0]["value"] is None else float(found[0][key])


def grew_most(metric: str, current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any] | None:
    """Spec 066: among the lead-time metric's stages, the one whose same statistic grew most in
    hours from the week before; a stage with no data in either week is skipped, a tie goes to the
    earlier stage, and None when no stage can be compared"""
    key = METRIC_MEASURES[metric][1]
    best: dict[str, Any] | None = None
    for name in LEAD_TIME_STAGES[metric]:
        value, before = stage_value(name, key, current), stage_value(name, key, previous)
        if value is None or before is None:
            continue
        change = value - before
        if best is None or change > best["change"]:
            best = {"measure": name, "statistic": STATISTICS[key], "value": value, "previous": before, "change": change}
    return best


def met_streaks(goals: list[dict[str, Any]], report: Callable[[int], dict[str, Any]], limit: int) -> dict[str, int]:
    """Per measured goal, the weeks in a row back from this one it was met, up to limit;
    report(k) is metrics.py's JSON k weeks back, asked only while a goal is still met"""
    streaks = {g["id"]: 0 for g in goals if g.get("measure")}
    going = set(streaks)
    for k in range(limit):
        if not going:
            break
        week = report(k)
        for goal in goals:
            if goal["id"] in going:
                if status(goal["measure"], week)[0] == MET:
                    streaks[goal["id"]] += 1
                else:
                    going.discard(goal["id"])
    return streaks


def first_listed(sources: Sources, checkout: Path, goal: str) -> dt.datetime | None:
    """When the goal's item line first entered the direction's history, by git log"""
    cmd = ["git", "-C", str(checkout), "log", "--reverse", "--format=%cI", "-G", f"^- {goal}: "]
    proc = sources.command([*cmd, "--", DIRECTION, DIRECTION_DIR])
    if proc.returncode != 0:
        raise fail(f"git log in {checkout}: {proc.stderr.strip()}")
    lines = proc.stdout.split()
    return timestamp(lines[0]) if lines else None


def goals_report(
    args: argparse.Namespace, sources: Sources, direction: dict[str, Any], reports: list[dict[str, Any]]
) -> dict[str, Any]:
    """The JSON `goals` key of spec 027; reports holds metrics.py's runs for this week and the
    week before, and gains the earlier weeks it asks for"""
    bots = frozenset(args.bot)
    goals: list[dict[str, Any]] = direction["goals"]
    end = timestamp(reports[0]["end"])
    windows = weeks(end, args.days, max(2, args.stalled_weeks))
    issues = fetch_issues(sources, args.repo, windows[-1].start, bots)
    pulls = fetch_merged(sources, args.repo, windows[-1].start)
    work = served(issues, pulls, windows, spec_goals(args.checkout, args.repo), bots)

    def report(k: int) -> dict[str, Any]:
        while len(reports) <= k:
            reports.append(sources.metrics(reports[-1]["start"]))
        return reports[k]

    streaks = met_streaks(goals, report, max(2, args.met_weeks))
    listed = {g["id"] for g in goals}
    young = end - dt.timedelta(days=args.days * args.stalled_weeks)
    rows = []
    for goal in goals:
        measure = goal.get("measure")  # a shipmill before spec 027 gives no measure key
        state, value, text = status(measure, reports[0])
        unserved = 0
        while unserved < len(work) and not work[unserved].any(goal["id"]):
            unserved += 1
        stalled = False
        if unserved >= args.stalled_weeks:
            entered = first_listed(sources, args.checkout, goal["id"])
            stalled = entered is not None and entered <= young
        row = {
            "id": goal["id"],
            "text": goal["text"],
            "measure": measure,
            "status": state,
            "value": value,
            "value_text": text,
            "met_weeks": streaks.get(goal["id"], 0),
            **work[0].row(goal["id"]),
            "previous": work[1].counts(goal["id"]),
            "stalled": stalled,
            "weeks_unserved": unserved,
        }
        if measure is not None and state == NOT_MET and measure["metric"] in LEAD_TIME_STAGES:
            row["grew_most"] = grew_most(measure["metric"], reports[0], reports[1])
        rows.append(row)
    now, before = off_direction(issues, windows[0], bots), off_direction(issues, windows[1], bots)
    unlinked = []
    owner, _, name = args.repo.partition("/")
    for pull in sorted(pulls, key=lambda p: p["number"]):
        if timestamp(pull["mergedAt"]) not in windows[0] or plan_serves(pull["body"]) & (listed | {QUALITY_BAR}):
            continue
        pull_commits(sources.graphql, {"owner": owner, "name": name}, {PULL_COMMITS: 100}, pull)
        if agent_made(pull):
            unlinked.append({"number": pull["number"], "title": pull["title"], "url": pull["url"]})
    return {
        "direction": True,
        "goals": rows,
        "quality_bar": {**work[0].row(QUALITY_BAR), "previous": work[1].counts(QUALITY_BAR)},
        "off_direction": {
            **now,
            "previous": {
                "postponed": len(before["postponed"]),
                "wont_fix": len(before["wont_fix"]),
                "top_non_goal": before["top_non_goal"],
            },
        },
        "unlinked": unlinked,
    }


def numbered(numbers: list[int]) -> str:
    return " ".join(f"#{n}" for n in numbers) or "none"


def grew_most_text(grew: dict[str, Any] | None) -> str:
    """The goal row's `grew most:` line (spec 066)"""
    if grew is None:
        return "grew most: no stage to compare"
    return f"grew most: {grew['measure']}, {grew['statistic']} {span(grew['previous'])} to {span(grew['value'])}"


def goals_text(goals: dict[str, Any]) -> list[str]:
    if not goals["direction"]:
        return [f"No direction ({DIRECTION}): no per-goal report"]
    lines = [f"Goals ({DIRECTION}):"]
    for g in goals["goals"]:
        before = g["previous"]
        lines.append(f"  {g['id']}: {g['text']}")
        lines.append(
            f"    served: issues {numbered(g['issues'])}, pulls {numbered(g['pulls'])};"
            f" the week before {before['issues']} issues, {before['pulls']} pulls"
        )
        if g["measure"] is None:
            lines.append(f"    measure: {NO_MEASURE}")
        else:
            shown = f" ({g['value_text']})" if g["status"] != NO_DATA else ""
            lines.append(
                f"    measure {g['measure']['text']}: {g['status']}{shown}, met {g['met_weeks']} weeks in a row"
            )
        if "grew_most" in g:
            lines.append(f"    {grew_most_text(g['grew_most'])}")
        if g["stalled"]:
            lines.append(f"    stalled: nothing served it for {g['weeks_unserved']} weeks")
    q = goals["quality_bar"]
    lines.append(
        f"  Quality bar: issues {numbered(q['issues'])}, pulls {numbered(q['pulls'])};"
        f" the week before {q['previous']['issues']} issues, {q['previous']['pulls']} pulls"
    )
    o = goals["off_direction"]
    wont = " ".join(f"#{w['number']} ({w['non_goal']})" for w in o["wont_fix"]) or "none"
    p = o["previous"]
    lines.append(
        f"  Off direction: postponed for no goal {numbered(o['postponed'])}; won't fix {wont};"
        f" most cited {o['top_non_goal'] or 'none'}; the week before {p['postponed']} postponed,"
        f" {p['wont_fix']} won't fix, most cited {p['top_non_goal'] or 'none'}"
    )
    lines.append(f"  Unlinked agent pull requests: {len(goals['unlinked']) or 'none'}")
    lines += [f"    #{u['number']} {u['title']} {u['url']}" for u in goals["unlinked"]]
    return lines


# -- decisions (spec 030) ---------------------------------------------------------------------

# github-issue-triage's decisions.py holds the zone table (ids, defaults, floors) and reads [decisions]
DECISIONS_SCRIPT = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "decisions.py"
CONFIG = ".github/shipmill.toml"
DECIDED_MARK = re.compile(r"^<!-- shipmill:decided zone=([a-z][a-z-]*) until=\S+ -->$")
VETO_HANDLED_MARK = re.compile(r"^<!-- shipmill:veto-handled zone=([a-z][a-z-]*) -->$")
NEEDS_DECISION_MARK = "<!-- shipmill:needs-decision -->"
ZONE_MARK = re.compile(r"^<!-- shipmill:zone ([a-z][a-z-]*)(?: answer=(recommended|other))? -->$")
# A question's option (needs-decision.md, Asking): "1. <option> (recommended): <why>"
OPTION = re.compile(r"^\s*([1-9][0-9]*)\.\s+(.+)$")
RECOMMENDED = " (recommended)"
NUMBER_ALONE = re.compile(r"(?:option\s*)?#?([1-9][0-9]*)")  # "1", "1.", "Option 1", read after plain()
# "1. <text>", "1) <text>", "1: <text>", "Option 1: <text>": the option as listed, read after plain()
NUMBER_AND_TEXT = re.compile(r"(?:option\s*)?#?([1-9][0-9]*)[.):]\s+(.+)")
SESSION_ANSWER = "Answered in the session:"  # the relay's answer line (needs-decision.md)
# The relay grammar (needs-decision.md, Answered in the session; D-93): past the header, the answer
# line may say `own: <text>`, an optional `Basis:` line follows it, and a `Note:` line ends what is read
OWN = "own:"
BASIS = re.compile(r"Basis:\s*(item|round|standing)")
BASIS_START = "basis:"
NOTE_START = "note:"
FORMAT = "format"  # the reason a relay out of its grammar is not counted
WORD = re.compile(r"\w+")  # a word as relay_refusal compares an answer to an option, punctuation left out
# A relay's first line (D-68, D-70), the login bare or in a code span (D-61), and the agent marker
# (spec 050): copied from triage_state.py, which the skill scripts can't import from each other;
# a test checks they agree
LOGIN_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
DECISION_BY = re.compile(
    r"Decision by (?:@(" + LOGIN_PATTERN + r")(?=$|\s|[,;:)]|[.!?](?:\s|$))|`@(" + LOGIN_PATTERN + r")`(?![\w`-]))"
)
AGENT_MARKER = re.compile(r"<!-- shipmill:agent(?:\s[^>]*)?-->")
# The --role flags, as triage_state.py takes them (spec 036): only the maintainer's logins are read
MAINTAINER = "maintainer"
ROLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,44}")
USER = re.compile(LOGIN_PATTERN)
TEAM = re.compile(r"@" + LOGIN_PATTERN + r"/[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
COUNTS = ("decided", "vetoes", "asks", "answered", "recommended")
QUESTION_COUNTS = ("asks", "answered", "recommended")
OUTCOMES = ("decided", "vetoed", "reverted", "held")  # what became of a decided item (spec 058)
# The line GitHub's Revert button writes in a revert pull request's body, and its title
REVERTS = re.compile(r"^\s*Reverts (?:([\w.-]+/[\w.-]+))?#([1-9][0-9]*)\s*$")
REVERT_TITLE = 'Revert "{}"'
REOPENINGS = 100  # an issue's reopenings since the windows' start; more is refused, not truncated

THREAD_FIELDS = """
        number updatedAt
        comments(last: 50) {
          pageInfo { hasPreviousPage startCursor }
          nodes { body createdAt authorAssociation author { __typename login } }
        }
"""
ISSUE_THREADS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    issues(first: $size, after: $cursor, filterBy: {since: $since}, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {"""
    + THREAD_FIELDS
    + """        timelineItems(itemTypes: [REOPENED_EVENT], since: $since, first: """
    + str(REOPENINGS)
    + """) {
          pageInfo { hasNextPage }
          nodes { ... on ReopenedEvent { createdAt } }
        }
      }
    }
  }
}
"""
)
PULL_THREADS = (
    """
query($owner: String!, $name: String!, $size: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $size, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {"""
    + THREAD_FIELDS
    + """        title body mergedAt
      }
    }
  }
}
"""
)
PULL_COMMENTS = """
query($owner: String!, $name: String!, $size: Int!, $cursor: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      comments(last: $size, before: $cursor) {
        pageInfo { hasPreviousPage startCursor }
        nodes { body createdAt authorAssociation author { __typename login } }
      }
    }
  }
}
"""


def decisions_module() -> ModuleType:
    """github-issue-triage's decisions.py, for the zone table and its reading of [decisions]"""
    spec = importlib.util.spec_from_file_location("shipmill_decisions", DECISIONS_SCRIPT)
    if spec is None or spec.loader is None:
        raise fail(f"can't load {DECISIONS_SCRIPT}; reinstall the shipmill plugin")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Levels:
    """The policy gather judges by: each zone's level and floor, and the veto window"""

    levels: dict[str, str]
    floors: dict[str, str | None]
    veto_hours: int


def read_policy(sources: Sources, checkout: Path) -> Levels:
    """The [decisions] levels of the checkout's config, which must be at origin/HEAD: levels
    are read from the default branch (D-48); a malformed table exits 2"""
    at_origin_head(sources, checkout)
    module = decisions_module()
    try:
        found = module.policy(checkout / CONFIG)
    except module.LogError as refused:
        raise fail(str(refused)) from None
    floors = {zone: floor for zone, (_, floor) in module.ZONES.items()}
    return Levels(dict(found.levels), floors, int(found.veto_hours))


def fetch_threads(sources: Sources, repo: str, since: dt.datetime) -> list[dict[str, Any]]:
    """Issues and pull requests updated since, each with its comments paged back past since;
    an issue with its reopenings since then, a pull request with its title, body, and merge
    time (spec 058)"""
    owner, _, name = repo.partition("/")
    base: Variables = {"owner": owner, "name": name}
    sizes = {ISSUE_THREADS: 50, PULL_THREADS: 50, ISSUE_COMMENTS: 100, PULL_COMMENTS: 100}
    issues = pages(
        sources.graphql,
        ISSUE_THREADS,
        {**base, "since": since.isoformat().replace("+00:00", "Z")},
        sizes,
        ["issues"],
        "issues updated in the windows",
    )
    pulls = pages(
        sources.graphql,
        PULL_THREADS,
        base,
        sizes,
        ["pullRequests"],
        "pull requests updated in the windows",
        lambda n: timestamp(n["updatedAt"]) < since,
    )
    threads = []
    for kind, query, key, found in (
        ("issue", ISSUE_COMMENTS, "issue", issues),
        ("pull", PULL_COMMENTS, "pullRequest", pulls),
    ):
        for thread in found:
            if timestamp(thread["updatedAt"]) < since:
                continue
            comments = thread["comments"]
            seen: set[str] = set()
            while comments["pageInfo"]["hasPreviousPage"] and (
                not comments["nodes"] or timestamp(comments["nodes"][0]["createdAt"]) >= since
            ):
                cursor = comments["pageInfo"]["startCursor"]
                if not cursor or cursor in seen:
                    raise fail(f"GitHub reported more comments on #{thread['number']}, but the cursor did not advance")
                seen.add(cursor)
                variables: Variables = {**base, "number": thread["number"], "cursor": cursor}
                page = sized(sources.graphql, query, variables, sizes, f"the comments of #{thread['number']}")
                older = dig(page, [key, "comments"], f"the comments of #{thread['number']}")
                comments["nodes"] = older["nodes"] + comments["nodes"]
                comments["pageInfo"] = older["pageInfo"]
            found_thread: dict[str, Any] = {"kind": kind, "number": thread["number"], "comments": comments["nodes"]}
            if kind == "issue":
                timeline = thread["timelineItems"]
                if timeline["pageInfo"]["hasNextPage"]:
                    raise fail(f"#{thread['number']} was reopened {REOPENINGS}+ times since {since:%Y-%m-%d}")
                found_thread["reopened"] = [timestamp(e["createdAt"]) for e in timeline["nodes"]]
            else:
                found_thread.update(title=thread["title"], body=thread["body"], mergedAt=thread["mergedAt"])
            threads.append(found_thread)
    return threads


def marker(body: str) -> tuple[str, str, bool] | None:
    """The kind of decision marker a comment opens with (decided, vetoes, or asks), its zone,
    and whether its question's zone line reads answer=recommended; None for any other comment"""
    lines = body.lstrip().splitlines()
    first = lines[0].strip() if lines else ""
    decided, handled = DECIDED_MARK.match(first), VETO_HANDLED_MARK.match(first)
    if decided:
        return "decided", decided.group(1), False
    if handled:
        return "vetoes", handled.group(1), False
    zone = ZONE_MARK.match(lines[1].strip()) if first == NEEDS_DECISION_MARK and len(lines) > 1 else None
    if zone:
        return "asks", zone.group(1), zone.group(2) == "recommended"
    return None


def stated_answer(body: str) -> str | None:
    """The answer= a question's zone line states, recommended or other; None without one"""
    lines = body.lstrip().splitlines()
    zone = ZONE_MARK.match(lines[1].strip()) if len(lines) > 1 else None
    return zone.group(2) if zone else None


def maintainer_logins(values: list[str]) -> frozenset[str]:
    """The maintainer's logins, lowercased, from --role NAME=FILLER[,FILLER...] flags checked as
    triage_state.py's parse_roles checks them (one per role, maintainer among them); a team is
    no login and names nobody here. Empty without flags; exit 2 naming what is wrong"""
    if not values:
        return frozenset()
    roles: dict[str, list[str]] = {}
    for value in values:
        name, sep, fillers = value.partition("=")
        if not sep or not ROLE_NAME.fullmatch(name):
            raise fail(f"--role wants NAME=FILLER[,FILLER...] with NAME matching {ROLE_NAME.pattern}, got {value!r}")
        if name in roles:
            raise fail(f"--role {name} is given twice")
        if not fillers:
            raise fail(f"--role {name} has no fillers")
        roles[name] = []
        for filler in fillers.split(","):
            if USER.fullmatch(filler):
                roles[name].append(filler.lower())
            elif not TEAM.fullmatch(filler):
                raise fail(f"--role {name}: {filler!r} is neither a GitHub login nor @org/team")
    if MAINTAINER not in roles:
        raise fail(f"--role flags must include {MAINTAINER}=FILLER[,FILLER...]")
    return frozenset(roles[MAINTAINER])


def by_agent(body: str) -> bool:
    return any(AGENT_MARKER.fullmatch(line.strip()) for line in body.splitlines())


@dataclass(frozen=True)
class Relay:
    """A relay's body as the relay grammar reads it (D-93): its answer line past `Answered in the
    session:` and `own:` ("" with none), whether that line is the person's own words (`own:`),
    the `Basis:` it names (recorded only: it changes no zone's outcome), and why the relay is not
    counted (FORMAT), None when it is"""

    answer: str
    own: bool
    basis: str | None
    refused: str | None

    @property
    def option(self) -> str:
        """The answer as takes_recommended reads it: "" for the person's own words or a relay
        not counted, which take no option"""
        return "" if self.own or self.refused else self.answer


def parse_relay(body: str) -> Relay:
    """The one reading of a relay (D-93; pr_gate.py's whole_reply, the retro's count): past its
    first line, the header, and leaving out the agent marker, an optional `Answered in the
    session:` line (its rest, when it has one, is the answer line), the answer line (the first
    non-blank line: an option as listed, or `own: <text>`), an optional `Basis: item|round|
    standing` line, then nothing or a line starting `Note:`, after which nothing is read. Any
    other line before `Note:` (a paragraph, an HTML comment, a second `Basis:`), a malformed
    `Basis:`, or an empty `own:` refuses the relay with FORMAT. A header and one line reads as
    before: that line is the answer"""
    lines = [line.strip() for line in body.strip().splitlines()[1:]]
    lines = [line for line in lines if line and not AGENT_MARKER.fullmatch(line)]
    if lines and lines[0].startswith(SESSION_ANSWER):
        lines = [said for said in (lines[0][len(SESSION_ANSWER) :].strip(), *lines[1:]) if said]
    if not lines:
        return Relay("", False, None, None)
    answer, rest = lines[0], lines[1:]
    own = answer.casefold().startswith(OWN)
    if own:
        answer = answer[len(OWN) :].strip()
    basis = None
    if rest and rest[0].casefold().startswith(BASIS_START):
        found = BASIS.fullmatch(rest[0])
        basis = found.group(1) if found else None
        rest = rest[1:] if found else rest
    malformed = (own and not answer) or (bool(rest) and not rest[0].casefold().startswith(NOTE_START))
    return Relay(answer, own, basis, FORMAT if malformed else None)


def bare_words(text: str) -> list[str]:
    """Text's words as plain() reads them, punctuation stripped: `recommendation: more` and
    `recommendation and more` start with the same word (#1261)"""
    return WORD.findall(plain(text))


def option_names(question: str) -> list[list[str]]:
    """The words of each option's name in a question, as bare_words reads them: an option's
    text before ` (recommended)`, or before its first `: ` when it has no mark"""
    names = []
    for line in question.splitlines():
        option = OPTION.match(line)
        if option is None:
            continue
        text = option.group(2)
        name = text.split(RECOMMENDED, 1)[0] if RECOMMENDED in text else text.split(": ", 1)[0]
        names.append(bare_words(name))
    return names


def relay_refusal(question: str, relay: Relay) -> str | None:
    """Why pr_gate.py doesn't count a relay to the question (D-93), or None when it does: its
    own refusal, or an answer line of a number followed by words (`1. <words>`, read as
    takes_recommended reads it) that is no option as listed, its words naming no option's name,
    the start of one, or one followed by more words, word for word with punctuation stripped
    (bare_words); `own:` is never refused here"""
    if relay.refused is not None or relay.own:
        return relay.refused
    listed = NUMBER_AND_TEXT.fullmatch(plain(relay.answer))
    if listed is None:
        return None
    words = bare_words(listed.group(2))
    named = bool(words) and any(words[: len(name)] == name[: len(words)] for name in option_names(question) if name)
    return None if named else FORMAT


def relayed_answer(comment: dict[str, Any], bots: frozenset[str], maintainers: Container[str]) -> str | None:
    """D-68, D-70: from a comment by a --bot login whose first line is the relay `Decision by
    @<login>` naming a maintainer (the lowercased login in maintainers, asked only for a relay:
    pr_gate.py's reads GitHub then, spec 055), its answer as parse_relay reads it, past the
    template's `Answered in the session:` ("" with none, for the person's own words, and for a
    relay not counted, D-93); None for any other comment"""
    if not login_names(comment.get("author")) & {b.lower() for b in bots}:
        return None
    body = (comment.get("body") or "").strip()
    found = DECISION_BY.match(body.partition("\n")[0].strip())
    if found is None or (found[1] or found[2]).lower() not in maintainers:
        return None
    return parse_relay(body).option


def first_answer(later: list[dict[str, Any]], bots: frozenset[str], maintainers: frozenset[str]) -> str | None:
    """The answer to a question from the comments after it, as answer_at reads it, or None"""
    found = answer_at(later, bots, maintainers)
    return None if found is None else found[1]


def answers_at(
    later: list[dict[str, Any]], bots: frozenset[str], maintainers: Container[str]
) -> Iterator[tuple[int, str]]:
    """The answers to a question from the comments after it, oldest first, up to a newer trusted
    question, each with its index in later: a person's reply (an OWNER, MEMBER, or COLLABORATOR,
    readable, without the needs-decision marker or the agent marker, D-62), its first non-blank
    line; or a maintainer's relay, as relayed_answer reads it"""
    for i, comment in enumerate(later):
        body = comment.get("body") or ""
        if first_line(body) == NEEDS_DECISION_MARK and trusted(comment, bots):
            return
        relayed = relayed_answer(comment, bots, maintainers)
        if relayed is not None:
            yield i, relayed
            continue
        logins = login_names(comment.get("author"))
        person = bool(logins) and not logins & {b.lower() for b in bots}
        if person and str(comment.get("authorAssociation") or "NONE") in TRUSTED and not by_agent(body):
            yield i, first_line(body)


def answer_at(later: list[dict[str, Any]], bots: frozenset[str], maintainers: Container[str]) -> tuple[int, str] | None:
    """The first of answers_at, the answer the retro counts (S-030-18); None while there is none"""
    return next(answers_at(later, bots, maintainers), None)


def newest_answer_at(
    later: list[dict[str, Any]], bots: frozenset[str], maintainers: Container[str]
) -> tuple[int, str] | None:
    """The newest of answers_at, the answer pr_gate.py's acceptance judges (D-89, S-055-5): a
    later trusted reply replaces an earlier one; None while there is none"""
    found = None
    for answer in answers_at(later, bots, maintainers):
        found = answer
    return found


def plain(text: str) -> str:
    """Text as an answer is compared: no emphasis or code marks, one space, any case, no end stop"""
    return " ".join(text.replace("`", "").replace("*", "").split()).casefold().rstrip(".!").strip()


def takes_recommended(question: str, answer: str) -> bool:
    """Whether an answer takes the question's option marked (recommended) as it stands: its
    number alone ("1", "1.", "Option 1"), its text alone, or both as listed ("1. <text>",
    "1) <text>", "1: <text>", "Option 1: <text>", S-055-19); an answer that narrows or departs
    from it, another option, a number and a text naming different options, or one that can't
    be read, does not"""
    for line in question.splitlines():
        option = OPTION.match(line)
        if option is None or RECOMMENDED not in option.group(2):
            continue
        said = plain(answer)
        number = NUMBER_ALONE.fullmatch(said)
        name = plain(option.group(2).split(RECOMMENDED, 1)[0])
        if number is not None:
            return number.group(1) == option.group(1)
        texts = (name, name + RECOMMENDED)
        listed = NUMBER_AND_TEXT.fullmatch(said)
        both = listed is not None and listed.group(1) == option.group(1) and listed.group(2) in texts
        return bool(name) and (said in texts or both)
    return False


@dataclass(frozen=True)
class Tally:
    """What decision_counts finds: per window, per zone, the markers and questions; the markers
    naming no zone id; per window, the questions with no zone line and every question; and
    this window's questions with no zone line"""

    counts: list[dict[str, dict[str, int]]]
    unknown: list[dict[str, Any]]
    unzoned: list[dict[str, int]]
    every: list[dict[str, int]]
    unzoned_items: list[dict[str, Any]]


def decision_counts(
    threads: list[dict[str, Any]],
    windows: list[Window],
    zones: list[str],
    bots: frozenset[str],
    maintainers: frozenset[str] = frozenset(),
) -> Tally:
    """Per window, per zone, the trusted markers posted in it: decided markers, veto-handled
    markers, zoned needs-decision questions, those answered (the zone line's answer= when it
    has one, else the first answer after the question, a relay counting only when it names one
    of maintainers), and those answered with the recommended option; and the markers naming no
    zone id, so a mistyped zone shows instead of vanishing. A trusted question whose second
    line is no zone line is counted apart, read for its answer the same way (spec 058)"""
    counts = [{zone: dict.fromkeys(COUNTS, 0) for zone in zones} for _ in windows]
    unzoned = [dict.fromkeys(QUESTION_COUNTS, 0) for _ in windows]
    every = [dict.fromkeys(QUESTION_COUNTS, 0) for _ in windows]
    unknown: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for thread in threads:
        for i, comment in enumerate(thread["comments"]):
            found = marker(comment["body"])
            question = found is None and first_line(comment["body"]) == NEEDS_DECISION_MARK
            if (found is None and not question) or not trusted(comment, bots):
                continue
            kind, zone, recommended = found if found is not None else ("asks", None, False)
            answered = kind == "asks" and stated_answer(comment["body"]) is not None
            if kind == "asks" and stated_answer(comment["body"]) is None:
                answer = first_answer(thread["comments"][i + 1 :], bots, maintainers)
                answered = answer is not None
                recommended = answer is not None and takes_recommended(comment["body"], answer)
            posted = timestamp(comment["createdAt"])
            for k, (week, window) in enumerate(zip(counts, windows, strict=True)):
                if posted not in window:
                    continue
                if kind == "asks":
                    every[k]["asks"] += 1
                    every[k]["answered"] += int(answered)
                    every[k]["recommended"] += int(recommended)
                if zone is None:
                    unzoned[k]["asks"] += 1
                    unzoned[k]["answered"] += int(answered)
                    unzoned[k]["recommended"] += int(recommended)
                    if k == 0:
                        items.append({"kind": thread["kind"], "number": thread["number"]})
                    continue
                if zone not in week:
                    unknown.append({"kind": thread["kind"], "number": thread["number"], "zone": zone})
                    continue
                week[zone][kind] += 1
                week[zone]["answered"] += int(answered)
                week[zone]["recommended"] += int(recommended)
    return Tally(
        counts,
        sorted(unknown, key=lambda u: (u["number"], u["zone"])),
        unzoned,
        every,
        sorted(items, key=lambda u: (u["number"], u["kind"])),
    )


def rate(recommended: int, answered: int) -> int | None:
    """The percent of answered questions that took the recommended option, rounded down; None
    with no answered question"""
    return recommended * 100 // answered if answered else None


def reverted(
    thread: dict[str, Any], posted: dt.datetime, until: dt.datetime, merged: list[dict[str, Any]], repo: str
) -> bool:
    """Spec 058: whether the item a decided marker posted at posted sits on was undone by until:
    an issue reopened after it, or a merged pull request that another pull request merged after
    it reverts (a body line `Reverts <owner/repo>#N` or `Reverts #N`, or the title
    `Revert "<its title>"`)"""
    if thread["kind"] == "issue":
        return any(posted < moment <= until for moment in thread["reopened"])
    if not thread["mergedAt"]:
        return False
    for pull in merged:
        if pull["number"] == thread["number"] or not posted < timestamp(pull["mergedAt"]) <= until:
            continue
        if pull["title"] == REVERT_TITLE.format(thread["title"]):
            return True
        for line in (pull["body"] or "").splitlines():
            found = REVERTS.match(line)
            same_repo = found is not None and (found.group(1) is None or found.group(1).lower() == repo.lower())
            if found is not None and same_repo and int(found.group(2)) == thread["number"]:
                return True
    return False


def decided_outcomes(
    threads: list[dict[str, Any]],
    windows: list[Window],
    zones: list[str],
    bots: frozenset[str],
    repo: str,
    revert_days: int,
    end: dt.datetime,
) -> dict[str, dict[str, int]]:
    """Per zone, the trusted decided markers posted in the windows, and what became of each
    item they sit on: vetoed (a trusted veto-handled marker for the zone after it), else
    reverted within revert_days after it, else held once the marker is revert_days old; a
    younger one is counted in none of the three (spec 058)"""
    found = {zone: dict.fromkeys(OUTCOMES, 0) for zone in zones}
    span = dt.timedelta(days=revert_days)
    merged = [t for t in threads if t["kind"] == "pull" and t["mergedAt"]]
    for thread in threads:
        comments = thread["comments"]
        for i, comment in enumerate(comments):
            mark = marker(comment["body"])
            if mark is None or mark[0] != "decided" or mark[1] not in found or not trusted(comment, bots):
                continue
            posted = timestamp(comment["createdAt"])
            if not any(posted in window for window in windows):
                continue
            row = found[mark[1]]
            row["decided"] += 1
            if any(marker(c["body"]) == ("vetoes", mark[1], False) and trusted(c, bots) for c in comments[i + 1 :]):
                row["vetoed"] += 1
            elif reverted(thread, posted, posted + span, merged, repo):
                row["reverted"] += 1
            elif end - posted >= span:
                row["held"] += 1
    return found


def decision_proposals(
    policy: Levels,
    counts: list[dict[str, dict[str, int]]],
    raise_at: int,
    lower_after: int,
    lower_rate: int,
    lower_min: int,
) -> list[dict[str, str]]:
    """A zone at notify with raise_at vetoes or more this window goes up to ask (reverted
    items count for nothing); a zone at ask, above its floor, whose answered questions over the
    last lower_after windows number lower_min or more, at least lower_rate percent of them
    answered with the recommended option, goes down to notify (spec 058)"""
    found = []
    for zone, level in policy.levels.items():
        now = counts[0][zone]
        answered = sum(week[zone]["answered"] for week in counts[:lower_after])
        recommended = sum(week[zone]["recommended"] for week in counts[:lower_after])
        floor = policy.floors[zone]
        above_floor = floor is None or floor in ("act", "notify")
        if level == "notify" and now["vetoes"] >= raise_at:
            why = f"{now['vetoes']} vetoes this window, at least {raise_at}"
            found.append(proposal(zone, "notify", "ask", why))
        elif level == "ask" and above_floor and answered >= lower_min and recommended * 100 >= lower_rate * answered:
            why = (
                f"{recommended} of {answered} answered questions ({rate(recommended, answered)}%) over {lower_after}"
                f" windows took the recommended option, at least {lower_rate}% of at least {lower_min}"
            )
            found.append(proposal(zone, "ask", "notify", why))
    return found


def proposal(zone: str, before: str, after: str, why: str) -> dict[str, str]:
    title = f"Decision policy: {zone} from {before} to {after}"
    return {"zone": zone, "from": before, "to": after, "title": title, "why": why}


def decisions_report(
    args: argparse.Namespace, sources: Sources, policy: Levels, end: dt.datetime, maintainers: frozenset[str]
) -> dict[str, Any]:
    """The JSON `decisions` key of spec 030: per zone this window's counts, the questions over
    --lower-after windows with their rate, and what became of the decided items (spec 058);
    the questions with no zone line and every question; and the proposed level changes"""
    windows = weeks(end, args.days, max(1, args.lower_after))
    threads = fetch_threads(sources, args.repo, windows[-1].start)
    zones = list(policy.levels)
    bots = frozenset(args.bot)
    tally = decision_counts(threads, windows, zones, bots, maintainers)
    counts = tally.counts
    outcomes = decided_outcomes(threads, windows, zones, bots, args.repo, args.revert_days, end)
    rows = []
    for zone in zones:
        over = {key: sum(week[zone][key] for week in counts) for key in QUESTION_COUNTS}
        rows.append(
            {
                "zone": zone,
                "level": policy.levels[zone],
                "floor": policy.floors[zone],
                **counts[0][zone],
                **{f"{key}_over_windows": value for key, value in over.items()},
                "rate_over_windows": rate(over["recommended"], over["answered"]),
                **{f"{key}_over_windows": value for key, value in outcomes[zone].items()},
            }
        )
    return {
        "veto_hours": policy.veto_hours,
        "windows": len(windows),
        "zones": rows,
        "unzoned": {**questions(tally.unzoned), "items": tally.unzoned_items},
        "all": questions(tally.every),
        "proposals": decision_proposals(
            policy, counts, args.raise_at, args.lower_after, args.lower_rate, args.lower_min
        ),
        "unknown_zones": tally.unknown,
    }


def questions(per_window: list[dict[str, int]]) -> dict[str, int | None]:
    """This window's asks, answered, and recommended, the same over the windows, and the rate"""
    over = {key: sum(week[key] for week in per_window) for key in QUESTION_COUNTS}
    return {
        **per_window[0],
        **{f"{key}_over_windows": value for key, value in over.items()},
        "rate_over_windows": rate(over["recommended"], over["answered"]),
    }


def rate_text(value: int | None) -> str:
    return "no answered question" if value is None else f"rate {value}%"


def decisions_text(decisions: dict[str, Any]) -> list[str]:
    lines = [f"Decisions (veto window {decisions['veto_hours']} h; questions over {decisions['windows']} windows):"]
    for z in decisions["zones"]:
        lines.append(
            f"  {z['zone']} ({z['level']}): decided {z['decided']}, vetoes {z['vetoes']},"
            f" asks {z['asks']} ({z['recommended']} recommended);"
            f" over the windows {z['asks_over_windows']} asks ({z['recommended_over_windows']} recommended),"
            f" {z['answered_over_windows']} answered, {rate_text(z['rate_over_windows'])};"
            f" decided {z['decided_over_windows']} over the windows: {z['vetoed_over_windows']} vetoed,"
            f" {z['reverted_over_windows']} reverted, {z['held_over_windows']} held"
        )
    unzoned, every = decisions["unzoned"], decisions["all"]
    listed = ", ".join(f"#{item['number']}" for item in unzoned["items"]) or "none"
    lines.append(
        f"  no zone line: asks {unzoned['asks']} ({unzoned['answered']} answered,"
        f" {unzoned['recommended']} recommended): {listed}"
    )
    lines.append(
        f"  every question over the windows: asks {every['asks_over_windows']}"
        f" ({every['answered_over_windows']} answered, {every['recommended_over_windows']} recommended),"
        f" {rate_text(every['rate_over_windows'])}"
    )
    for u in decisions["unknown_zones"]:
        lines.append(f"  a marker on #{u['number']} names no zone id: {u['zone']}")
    lines.append(f"  Proposals: {len(decisions['proposals']) or 'none'}")
    lines += [f"    {p['title']} ({p['why']})" for p in decisions["proposals"]]
    return lines


# -- findings (spec 077) ----------------------------------------------------------------------

RECORD_MARKS = ("<!-- shipmill:review merge -->", "<!-- shipmill:review refuse -->")  # spec 055
# The proposal marker, the first line of a rule-proposal issue's body
PROPOSAL_MARK = re.compile(r"^<!-- shipmill:rule-proposal pulls=([1-9][0-9]*(?:,[1-9][0-9]*)*) place=([a-z]+) -->$")
PROPOSAL_LABEL = "rule-proposal"
SHIPMILL_LINE = re.compile(r"^\s*<!-- shipmill:[^>]*-->\s*$")  # a marker line, left out of an item's text
CITED = re.compile(r"(?<![\w-])([DINQ]-[1-9][0-9]*)(?![\w-])")
TEXT_LIMIT = 600
FINDINGS_DAYS = 28
DECLINED = frozenset({"not_planned", "duplicate"})  # GitHub files "duplicate" under not planned


@dataclass(frozen=True)
class Finding:
    """One thing a review raised: its kind (record, review, comment, refusal), author, the head it
    was raised on, a comment's path and line, the rule ids it cites, its text, and when"""

    kind: str
    author: str
    head: str
    path: str | None
    line: int | None
    cites: list[str]
    text: str
    at: str


def rest_author(record: dict[str, Any]) -> dict[str, Any]:
    """A REST record's author and association as trusted() reads a GraphQL comment's: an App's
    login without its "[bot]" suffix, typed Bot; no author when the login can't be read"""
    user = record.get("user") or {}
    login = str(user.get("login") or "")
    bot = user.get("type") == "Bot"
    author = {"__typename": "Bot" if bot else "User", "login": login.removesuffix("[bot]") if bot else login}
    return {"author": author if login else None, "authorAssociation": record.get("author_association")}


def bot_login(record: dict[str, Any], bots: frozenset[str]) -> bool:
    return bool(login_names(rest_author(record)["author"]) & {b.lower() for b in bots})


def persons(record: dict[str, Any], bots: frozenset[str]) -> bool:
    """Written by an OWNER, MEMBER, or COLLABORATOR who is no --bot login, without the agent
    marker (D-62); anyone else's is left out whole (D-16)"""
    author = rest_author(record)
    return (
        author["author"] is not None
        and str(author["authorAssociation"] or "NONE") in TRUSTED
        and not bot_login(record, bots)
        and not by_agent(str(record.get("body") or ""))
    )


def cleaned(body: str | None) -> str:
    """A body without shipmill's marker lines, stripped"""
    return "\n".join(line for line in (body or "").splitlines() if not SHIPMILL_LINE.match(line)).strip()


def cut(text: str) -> str:
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…"


def cited(text: str) -> list[str]:
    """The I-n, N-n, Q-n, and D-n ids a text cites, in the order they first appear"""
    return list(dict.fromkeys(CITED.findall(text)))


def raised(kind: str, record: dict[str, Any], head: str, at: str, path: str | None = None, line: Any = None) -> Finding:
    text = cleaned(record.get("body"))
    login = str(record["user"]["login"])
    return Finding(kind, login, head, path, None if line is None else int(line), cited(text), cut(text), at)


def api_list(repo: str, path: str, query: str = "") -> list[str]:
    """A `gh api` read of every page of a REST list, one record per line"""
    return ["api", "--paginate", f"repos/{repo}/{path}?{query}per_page=100", "--jq", ".[]"]


def pull_findings(
    read: Callable[[list[str]], Any], repo: str, pull: dict[str, Any], bots: frozenset[str]
) -> list[Finding]:
    """A closed pull request's items, oldest first"""
    number = pull["number"]
    found: list[Finding] = []
    for review in read(api_list(repo, f"pulls/{number}/reviews")):
        if review.get("state") == "PENDING":  # the reader's own unsubmitted review
            continue
        head, at = str(review["commit_id"]), str(review["submitted_at"])
        if bot_login(review, bots) and first_line(str(review.get("body") or "")) in RECORD_MARKS:
            found.append(raised("record", review, head, at))
        elif review["state"] == "CHANGES_REQUESTED" and persons(review, bots):
            found.append(raised("review", review, head, at))
    for comment in read(api_list(repo, f"pulls/{number}/comments")):
        if persons(comment, bots):
            line = comment.get("original_line")
            line = comment.get("line") if line is None else line
            head, at = str(comment["original_commit_id"]), str(comment["created_at"])
            found.append(raised("comment", comment, head, at, str(comment["path"]), line))
    if pull["mergedAt"] is None:
        closed = timestamp(pull["closedAt"])
        before = [
            c
            for c in read(api_list(repo, f"issues/{number}/comments"))
            if timestamp(c["created_at"]) <= closed and c.get("user") and trusted(rest_author(c), bots)
        ]
        if before:
            last = max(before, key=lambda c: timestamp(c["created_at"]))
            found.append(raised("refusal", last, str(pull["headRefOid"]), str(last["created_at"])))
    return sorted(found, key=lambda f: timestamp(f.at))


def proposal_state(issue: dict[str, Any]) -> str:
    if issue["state"] == "open":
        return "open"
    return "declined" if issue.get("state_reason") in DECLINED else "accepted"


def rule_proposals(read: Callable[[list[str]], Any], repo: str, bots: frozenset[str]) -> list[dict[str, Any]]:
    """Every rule-proposal issue, in any state and of any age, whose first body line is the
    proposal marker and whose author is a --bot login or an OWNER, MEMBER, or COLLABORATOR,
    newest first"""
    found = []
    for issue in read(api_list(repo, "issues", f"labels={PROPOSAL_LABEL}&state=all&")):
        if "pull_request" in issue or not issue.get("user") or not trusted(rest_author(issue), bots):
            continue
        mark = PROPOSAL_MARK.match(first_line(str(issue.get("body") or "")))
        if mark is None:
            continue
        found.append(
            {
                "number": int(issue["number"]),
                "title": str(issue["title"]),
                "url": str(issue.get("html_url") or ""),
                "pulls": [int(n) for n in mark.group(1).split(",")],
                "place": mark.group(2),
                "state": proposal_state(issue),
            }
        )
    return sorted(found, key=lambda p: -p["number"])


def findings(args: argparse.Namespace, read: Callable[[list[str]], Any], now: dt.datetime) -> int:
    """The review findings on the pull requests closed in the --days to now, and the proposals
    made so far; everything is read before anything is printed"""
    bots = frozenset(args.bot)
    start = now - dt.timedelta(days=args.days)
    fields = "number,title,url,mergedAt,closedAt,headRefOid"
    search = f"closed:>={start:%Y-%m-%d}"
    cmd = ["pr", "list", "-R", args.repo, "--state", "closed", "--search", search, "-L", str(PR_LIMIT)]
    pulls = read([*cmd, "--json", fields])
    if len(pulls) >= PR_LIMIT:
        raise fail(f"{args.repo} closed {PR_LIMIT}+ pull requests since {start:%Y-%m-%d}; use a shorter --days")
    closed = [p for p in pulls if p["closedAt"] is not None and start <= timestamp(p["closedAt"]) <= now]
    closed.sort(key=lambda p: (timestamp(p["closedAt"]), p["number"]), reverse=True)
    listed = []
    counter = 0
    for pull in closed:
        items = []
        for item in pull_findings(read, args.repo, pull, bots):
            counter += 1
            items.append({"id": f"F-{counter}", **asdict(item)})
        if items:
            listed.append(
                {
                    "number": pull["number"],
                    "title": pull["title"],
                    "url": pull["url"],
                    "merged": pull["mergedAt"] is not None,
                    "closed_at": pull["closedAt"],
                    "head": pull["headRefOid"],
                    "items": items,
                }
            )
    proposals = rule_proposals(read, args.repo, bots)
    window = {"start": iso_z(start), "end": iso_z(now), "days": args.days}
    if args.json:
        print(json.dumps({"window": window, "findings": listed, "proposed": proposals}, indent=2, sort_keys=True))
        return 0
    print("\n".join(findings_text(args.repo, args.days, now, listed, proposals)))
    return 0


def iso_z(moment: dt.datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def findings_text(
    repo: str, days: int, now: dt.datetime, listed: list[dict[str, Any]], proposals: list[dict[str, Any]]
) -> list[str]:
    lines = [f"{repo}: review findings on the pull requests closed in the {days} days to {now:%Y-%m-%d %H:%M} UTC"]
    if not listed:
        lines.append("  none")
    for pull in listed:
        how = "merged" if pull["merged"] else "closed without a merge"
        lines.append(f"#{pull['number']} {pull['title']} ({how} {pull['closed_at']}) {pull['url']}")
        for item in pull["items"]:
            where = f" {item['path']}" if item["path"] else ""
            where += f":{item['line']}" if item["path"] and item["line"] is not None else ""
            ids = f"; cites {', '.join(item['cites'])}" if item["cites"] else ""
            lines.append(f"  {item['id']} {item['kind']} by {item['author']} at {item['head']}{where}{ids}")
            lines += [f"      {line}" if line else "" for line in item["text"].splitlines()]
    lines.append(f"Proposed: {len(proposals) or 'none'}")
    for p in proposals:
        pulls = ", ".join(f"#{n}" for n in p["pulls"])
        lines.append(f"  #{p['number']} {p['state']}: {p['title']} (place {p['place']}; pulls {pulls}) {p['url']}")
    return lines


# -- dedupe ---------------------------------------------------------------------------------


def normal(title: str) -> str:
    """A title without case, punctuation, or extra spacing"""
    return " ".join(re.sub(r"[\W_]+", " ", title.casefold()).split())


def dedupe(titles: list[str], issues: list[dict[str, Any]]) -> list[Verdict]:
    """Each proposed title: the open issue whose title matches it, or none"""
    open_titles = {normal(i["title"]): i for i in sorted(issues, key=lambda i: int(i["number"]))}
    verdicts = []
    proposed: dict[str, str] = {}
    for title in titles:
        key = normal(title)
        if not key:
            raise fail(f"an empty proposal title: {title!r}")
        if key in proposed:  # both would read NEW and open twice
            raise fail(f"two proposals share a title: {proposed[key]!r} and {title!r}")
        proposed[key] = title
        match = open_titles.get(key)
        verdicts.append(Verdict(title, int(match["number"]), match["title"]) if match else Verdict(title, None, ""))
    return verdicts


def dedupe_command(args: argparse.Namespace) -> int:
    cmd = ["issue", "list", "-R", args.repo, "--state", "open", "-L", str(ISSUE_LIMIT), "--json", "number,title"]
    issues = gh(cmd)
    if len(issues) >= ISSUE_LIMIT:
        raise fail(f"{args.repo} has {ISSUE_LIMIT}+ open issues")
    verdicts = dedupe(args.title, issues)
    for v in verdicts:
        if args.json:
            print(json.dumps(asdict(v), sort_keys=True))
        elif v.duplicate is None:
            print(f"NEW        {v.title}")
        else:
            print(f"DUPLICATE  {v.title} (open as #{v.duplicate}: {v.existing})")
    return 1 if any(v.duplicate is not None for v in verdicts) else 0


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line, checked: a value out of range exits 2"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("gather", help="the two windows' metrics and the window's refused and reworked PRs")
    g.add_argument("repo", help="owner/name")
    g.add_argument("--days", type=int, default=7, help="each window, in days")
    g.add_argument("--environment", action="append", default=[], help="passed to metrics.py")
    g.add_argument("--incident-label", default="incident", help="[operate] incident_label")
    g.add_argument(
        "--bot",
        action="append",
        default=[],
        help="passed to metrics.py; with --goals or --decisions, a trusted comment author",
    )
    g.add_argument("--json", action="store_true")
    g.add_argument("--goals", action="store_true", help="add the report per goal of docs/product.md (spec 027)")
    g.add_argument(
        "--checkout",
        type=Path,
        default=Path("."),
        help="with --goals or --decisions: the repo's checkout, at origin/HEAD",
    )
    g.add_argument("--stalled-weeks", type=int, default=3, help="with --goals: weeks unserved that make a goal stalled")
    g.add_argument("--met-weeks", type=int, default=4, help="with --goals: weeks met in a row the report counts up to")
    g.add_argument("--decisions", action="store_true", help="add the report per zone of [decisions] (spec 030)")
    g.add_argument(
        "--raise-at", type=int, default=2, help="with --decisions: vetoes in the window that propose notify to ask"
    )
    g.add_argument(
        "--lower-after",
        type=int,
        default=4,
        help="with --decisions: the windows whose answered questions can propose ask to notify",
    )
    g.add_argument(
        "--lower-rate",
        type=int,
        default=90,
        help="with --decisions: the percent of answered questions, 1 to 100, that took the recommended option "
        "for ask to notify (spec 058)",
    )
    g.add_argument(
        "--lower-min",
        type=int,
        default=10,
        help="with --decisions: the answered questions a zone needs over --lower-after windows for ask to notify",
    )
    g.add_argument(
        "--revert-days",
        type=int,
        default=14,
        help="with --decisions: the days after a decided marker in which a revert or reopening counts against it",
    )
    g.add_argument(
        "--role",
        action="append",
        default=[],
        help="with --decisions: a role's resolved fillers, one flag per role, maintainer included, as "
        "`shipmill roles --flags` prints them; a --bot login's relay counts as an answer only when it "
        "names a maintainer (D-68, D-70)",
    )
    f = sub.add_parser("findings", help="what reviews raised on the closed PRs, and the rule proposals (spec 077)")
    f.add_argument("repo", help="owner/name")
    f.add_argument("--days", type=int, default=FINDINGS_DAYS, help="the window of closed pull requests, in days")
    f.add_argument("--bot", action="append", default=[], help="the App's login: its review records count")
    f.add_argument("--json", action="store_true")
    d = sub.add_parser("dedupe", help="each proposed title against the open issues")
    d.add_argument("repo", help="owner/name")
    d.add_argument("--title", action="append", required=True, help="a proposed issue's title")
    d.add_argument("--json", action="store_true", help="JSON lines")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error("repo must be owner/name")
    if args.command == "gather":
        if args.days < 1:
            parser.error("--days must be at least 1")
        if args.stalled_weeks < 1 or args.met_weeks < 1:
            parser.error("--stalled-weeks and --met-weeks must be at least 1")
        if args.raise_at < 1 or args.lower_after < 1:
            parser.error("--raise-at and --lower-after must be at least 1")
        if not 1 <= args.lower_rate <= 100:
            parser.error("--lower-rate must be 1 to 100")
        if args.lower_min < 1 or args.revert_days < 1:
            parser.error("--lower-min and --revert-days must be at least 1")
    if args.command == "findings" and args.days < 1:
        parser.error("--days must be at least 1; give a whole number of days, 28 by default")
    return args


def main() -> int:
    args = parse()
    if args.command == "gather":
        return gather(args, sources_for(args))
    if args.command == "findings":
        return findings(args, gh_read, dt.datetime.now(dt.timezone.utc))  # noqa: UP017 (runs under 3.10 too)
    return dedupe_command(args)


if __name__ == "__main__":
    sys.exit(main())
