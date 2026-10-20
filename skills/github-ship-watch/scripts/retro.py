#!/usr/bin/env python3
"""Gather a repo's weekly retro, and check its proposals against the open issues.

Usage: retro.py gather <owner/repo> [--days 7] [--environment NAME ...]
                       [--incident-label incident] [--bot LOGIN ...] [--json]
                       [--goals [--checkout DIR] [--stalled-weeks 3] [--met-weeks 4]]
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
         --met-weeks, only while a measured goal is still met); stalled when nothing served
         it in each of the last --stalled-weeks weeks, unless its id entered the direction
         (git log in DIR) fewer weeks ago. Then the `quality bar` row, the off-direction
         verdicts (postponed for no goal, won't fix for a non-goal, the most-cited N-n, ties
         to the lowest id), and the agent-made merged pull requests whose plan names no
         listed goal. A verdict comment counts only when its first line starts `Triage: ` and
         an OWNER, MEMBER, or COLLABORATOR or a --bot login wrote it (D-29)
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
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from metrics import PULL_COMMITS, Runner, Variables, agent_made, gh_graphql, pages, pull_commits, sized

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


def gh(cmd: list[str]) -> Any:
    proc = subprocess.run(["gh", *cmd], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise fail(f"gh {' '.join(cmd[:2])}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


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


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


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
    direction = read_direction(sources, args.checkout) if args.goals else None
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
}
MET, NOT_MET, NO_DATA, NO_MEASURE = "met", "not met", "no data", "no measure"

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


def read_direction(sources: Sources, checkout: Path) -> dict[str, Any] | None:
    """The direction as `shipmill product show --json` gives it, None without docs/product.md;
    exit 2 when the checkout isn't at origin/HEAD or shipmill refuses the direction"""
    proc = sources.command(["git", "-C", str(checkout), "rev-parse", "HEAD", "origin/HEAD"])
    heads = proc.stdout.split()
    if proc.returncode != 0 or len(heads) != 2 or heads[0] != heads[1]:
        why = proc.stderr.strip() or "HEAD is not origin/HEAD's commit"
        raise fail(
            f"{checkout}: {why}; run `git -C {checkout} fetch origin` and "
            f"`git -C {checkout} checkout --detach origin/HEAD`, then gather again"
        )
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
    return names(serves[0]) if len(serves) == 1 else set()


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
        rows.append(
            {
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
        )
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("gather", help="the two windows' metrics and the window's refused and reworked PRs")
    g.add_argument("repo", help="owner/name")
    g.add_argument("--days", type=int, default=7, help="each window, in days")
    g.add_argument("--environment", action="append", default=[], help="passed to metrics.py")
    g.add_argument("--incident-label", default="incident", help="[operate] incident_label")
    g.add_argument(
        "--bot", action="append", default=[], help="passed to metrics.py; with --goals, a trusted verdict author"
    )
    g.add_argument("--json", action="store_true")
    g.add_argument("--goals", action="store_true", help="add the report per goal of docs/product.md (spec 027)")
    g.add_argument("--checkout", type=Path, default=Path("."), help="with --goals: the repo's checkout, at origin/HEAD")
    g.add_argument("--stalled-weeks", type=int, default=3, help="with --goals: weeks unserved that make a goal stalled")
    g.add_argument("--met-weeks", type=int, default=4, help="with --goals: weeks met in a row the report counts up to")
    d = sub.add_parser("dedupe", help="each proposed title against the open issues")
    d.add_argument("repo", help="owner/name")
    d.add_argument("--title", action="append", required=True, help="a proposed issue's title")
    d.add_argument("--json", action="store_true", help="JSON lines")
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error("repo must be owner/name")
    if args.command == "gather":
        if args.days < 1:
            parser.error("--days must be at least 1")
        if args.stalled_weeks < 1 or args.met_weeks < 1:
            parser.error("--stalled-weeks and --met-weeks must be at least 1")
        return gather(args, sources_for(args))
    return dedupe_command(args)


if __name__ == "__main__":
    sys.exit(main())
