#!/usr/bin/env python3
"""A goal plan's body (spec 028): its grammar, and its work items with the issues filed for them.

Usage: plans.py check FILE [--root DIR]
       plans.py items <owner/repo>#N [--bot-login LOGIN] [--json]

check reads a plan body from FILE and checks it against the grammar of
references/plan.md, reading the goal ids from DIR/docs/product.md (default: the current
directory), the way `shipmill product ids` lists them:

  - the first line is the marker <!-- shipmill:plan goal=G-<n> rev=<k> -->, G-<n> a goal
    the direction lists and <k> a revision from 1
  - then the level-two headings Goal, Work, Order, Milestone, and Notes, in this order;
    Notes may be absent, any other heading is an error
  - Work holds at least one item and only items `- W-<n> <feature|fix|existing>: <text>`,
    numbered W-1, W-2, ... in order, each id once; an `existing` item's text is one issue
    reference, #N or owner/repo#N; any item may end with `(after W-<k>[, W-<j>])`, naming
    items before it
  - Milestone holds one line: `none`, or a milestone title

Exit 0 on a well-formed body; 2 with one `FILE:LINE: rule` line on stderr per problem, or
when the direction is missing or malformed. check reads no forge: whether an `existing`
item's issue is open is the session's to see.

items reads plan issue #N of owner/repo and lists each item: its id, kind, text (without
its `(after ...)`), the items it comes after, and the issue in owner/repo whose body's first
line is its plan-item marker, <!-- shipmill:plan-item #N W-<n> -->, or none. A marker
counts only on an issue opened by an OWNER, MEMBER, or COLLABORATOR, or by the
--bot-login (D-29); pass --bot-login '<slug>[bot]' when [agents] app_id is set, since the
App files the items. Two issues carrying one marker: the older (lower number) is the
item's. The plan's goal isn't checked against the direction here (check does that). One
GraphQL call reads the plan, its sub-issues, and a search for the marker. With --json,
one JSON line per item: {"after": [...], "id": "W-1", "issue": 12 or null, "kind": ...,
"text": ...}.

Exit 0 on a listed plan; 2 on a body check refuses (the problems on stderr), no such
issue, or a gh failure. Needs the gh CLI, authenticated. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

HEADINGS = ("Goal", "Work", "Order", "Milestone", "Notes")
OPTIONAL = {"Notes"}
KINDS = ("feature", "fix", "existing")
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}

MARKER = re.compile(r"^<!-- shipmill:plan goal=(G-[1-9][0-9]*) rev=([1-9][0-9]*) -->$")
MARKER_FORM = "<!-- shipmill:plan goal=G-<n> rev=<k> -->"
ITEM = re.compile(r"^- W-([1-9][0-9]*) (feature|fix|existing): (\S.*)$")
ITEM_FORM = "- W-<n> <feature|fix|existing>: <text>"
AFTER = re.compile(r"^(.*?)[ \t]*\(after (W-[1-9][0-9]*(?:, W-[1-9][0-9]*)*)\)$")
AFTER_LIKE = re.compile(r"\(after\b[^()]*\)$")
ISSUE_REF = re.compile(r"^(?:[\w.-]+/[\w.-]+)?#[1-9][0-9]*$")
PLAN_REF = re.compile(r"^([\w.-]+)/([\w.-]+)#([1-9][0-9]*)$")

# The direction (spec 024), read as `shipmill product ids` reads it: each list section's
# `- <prefix>-<n>: <text>` items, a section moved to docs/product/<file>.md through its one
# `See [<section>](product/<file>.md).` line read from that file; a goal's `  measure: ...`
# line right under its item line (spec 027) holds no id and is skipped
DIRECTION = "docs/product.md"
DIRECTION_DIR = "docs/product/"
LIST_SECTIONS = {"Users": "U", "Goals": "G", "Non-goals": "N", "Quality bar": "Q"}
DIRECTION_SECTIONS = ("Mission", *LIST_SECTIONS)
DIRECTION_ITEM = re.compile(r"^- ([A-Za-z]+)-([1-9][0-9]*): \S.*$")
DIRECTION_MEASURE = re.compile(r"^  measure: \S.*$")
DIRECTION_MOVED = re.compile(r"^See \[([^\]]+)\]\(product/([A-Za-z0-9][A-Za-z0-9_-]*\.md)\)\.$")

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

Variables = dict[str, Any]
# Runs one GraphQL query with its variables and returns the parsed JSON response
Runner = Callable[[str, Variables], dict[str, Any]]


class PlanError(Exception):
    """Input plans.py can't read: it stops with exit 2 and the message"""


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


def sections(text: str) -> list[tuple[int, int, str | None, list[tuple[int, str]]]]:
    """Split at level-one and level-two headings outside fenced code; each entry is the
    heading's line, its level, its text, and the numbered lines under it. The first entry,
    line 0, level 0, headed None, holds the lines before the first heading"""
    found: list[tuple[int, int, str | None, list[tuple[int, str]]]] = [(0, 0, None, [])]
    fence: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened is not None:
            fence = opened.group(1)
        else:
            heading = _HEADING.match(line)
            if heading is not None and len(heading.group(1)) <= 2:
                found.append((number, len(heading.group(1)), (heading.group(2) or "").strip(), []))
                continue
        found[-1][3].append((number, line))
    return found


# -- the direction's goal ids


def goal_ids(root: Path) -> frozenset[str]:
    """Every goal id root/docs/product.md lists, a moved Goals section followed"""
    path = root / DIRECTION
    if not path.is_file():
        raise PlanError(f"no {DIRECTION} under {root}: a plan's goal is one the direction lists")
    ids: set[str] = set()
    for _, level, heading, body in sections(path.read_text(encoding="utf-8")):
        if level < 2:  # the text before the name, and the name
            continue
        if heading not in DIRECTION_SECTIONS:
            raise PlanError(f"{DIRECTION}: `## {heading}` is not a direction heading; run `shipmill product check`")
        prefix = LIST_SECTIONS.get(heading)
        if prefix is None:
            continue
        lines = [(n, line) for n, line in body if line.strip()]
        file, listed = DIRECTION, body
        if len(lines) == 1 and lines[0][1].startswith("See ["):
            moved = DIRECTION_MOVED.match(lines[0][1])
            if moved is None or moved.group(1) != heading:
                raise PlanError(f"{DIRECTION}:{lines[0][0]}: a broken `See [...]` line; run `shipmill product check`")
            file = DIRECTION_DIR + moved.group(2)
            linked = root / file
            if not linked.is_file():
                raise PlanError(f"{DIRECTION}:{lines[0][0]}: {file} doesn't exist; run `shipmill product check`")
            parts = sections(linked.read_text(encoding="utf-8"))
            if [(lv, h) for _, lv, h, _ in parts[1:]] != [(2, heading)] or any(line.strip() for _, line in parts[0][3]):
                raise PlanError(f"{file} holds only `## {heading}`; run `shipmill product check`")
            listed = parts[1][3]
        after_goal = False  # the line before was a goal's item line, which a measure line may follow
        for number, line in listed:
            if not line.strip():
                after_goal = False
                continue
            if after_goal and DIRECTION_MEASURE.match(line):  # spec 027: read no more from it
                after_goal = False
                continue
            item = DIRECTION_ITEM.match(line)
            if item is None or item.group(1) != prefix:
                raise PlanError(f"{file}:{number}: not a `- {prefix}-<n>: <text>` item; run `shipmill product check`")
            ids.add(f"{prefix}-{item.group(2)}")
            after_goal = prefix == "G"
    return frozenset(i for i in ids if i.startswith("G-"))


# -- the plan body's grammar


@dataclass(frozen=True)
class Item:
    id: str  # W-<n>
    kind: str  # feature, fix, or existing
    text: str  # without its (after ...)
    after: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class Plan:
    goal: str
    rev: int
    items: tuple[Item, ...]
    milestone: str | None  # None for `none`


def parse(body: str, goals: frozenset[str] | None) -> tuple[Plan | None, list[tuple[int, str]]]:
    """The plan a body holds and the problems found, each (line, rule); the plan is None
    when any problem was found. With goals None the marker's goal isn't checked against
    the direction"""
    problems: list[tuple[int, str]] = []
    lines = body.splitlines()
    first = lines[0].rstrip() if lines else ""
    marker = MARKER.match(first)
    goal, rev = "", 0
    if marker is None:
        problems.append((1, f"the first line is the marker `{MARKER_FORM}`"))
    else:
        goal, rev = marker.group(1), int(marker.group(2))
        if goals is not None and goal not in goals:
            problems.append((1, f"the marker names {goal}, which {DIRECTION} doesn't list as a goal"))

    parts = sections(body)
    for number, line in parts[0][3]:
        if number > 1 and line.strip():
            problems.append((number, "nothing but the marker comes before `## Goal`"))
            break
    found: dict[str, list[tuple[int, str]]] = {}
    missing: set[str] = set()  # reported missing where a later heading came instead
    expected = 0  # the index in HEADINGS the next heading may take, at the earliest
    for number, level, heading, section_body in parts[1:]:
        shown = f"`{'#' * level} {heading}`"
        if level != 2 or heading not in HEADINGS:
            problems.append((number, f"{shown} is not a plan heading: {', '.join(HEADINGS)}, as `## ` headings"))
            continue
        if heading in found:
            problems.append((number, f"a second {shown}; the plan holds one"))
            continue
        index = HEADINGS.index(heading)
        if index < expected:
            problems.append((number, f"{shown} is out of order; the headings are {', '.join(HEADINGS)}, in this order"))
        else:
            for skipped in HEADINGS[expected:index]:
                if skipped not in OPTIONAL:
                    problems.append((number, f"no `## {skipped}` before {shown}"))
                    missing.add(skipped)
            expected = index + 1
        found[heading] = section_body
    end = len(lines)
    for heading in HEADINGS:
        if heading not in found and heading not in OPTIONAL and heading not in missing:
            problems.append((end, f"no `## {heading}` section"))

    items = work_items(found.get("Work"), end, problems)
    milestone = milestone_line(found.get("Milestone"), end, problems)
    if problems:
        return None, sorted(problems, key=lambda problem: problem[0])
    return Plan(goal, rev, tuple(items), milestone), []


def work_items(body: list[tuple[int, str]] | None, end: int, problems: list[tuple[int, str]]) -> list[Item]:
    if body is None:
        return []
    items: list[Item] = []
    seen: set[str] = set()
    malformed = False
    for number, line in body:
        if not line.strip():
            continue
        item = ITEM.match(line)
        if item is None:
            problems.append((number, f"a Work line is an item `{ITEM_FORM}`"))
            malformed = True
            continue
        ident, kind, text = f"W-{item.group(1)}", item.group(2), item.group(3)
        if ident in seen:
            problems.append((number, f"{ident} is a duplicate item id; each id appears once"))
            continue
        if ident != f"W-{len(items) + 1}":
            problems.append((number, f"{ident} is out of sequence; items are numbered W-1, W-2, ... in order"))
        seen.add(ident)
        after: tuple[str, ...] = ()
        dependency = AFTER.match(text)
        if dependency is not None:
            text, after = dependency.group(1), tuple(dependency.group(2).split(", "))
            for earlier in after:
                if earlier not in seen or earlier == ident:
                    problems.append((number, f"{ident} comes after {earlier}, which isn't an item before it"))
        elif AFTER_LIKE.search(text):
            problems.append((number, f"{ident}'s `(after ...)` names earlier items as `(after W-<k>[, W-<j>])`"))
        if not text.strip():
            problems.append((number, f"{ident} has no text before its `(after ...)`"))
        elif kind == "existing" and not ISSUE_REF.match(text):
            problems.append((number, f"{ident} is `existing`: its text is one issue reference, #N or owner/repo#N"))
        items.append(Item(ident, kind, text, after, number))
    if not items and not malformed:
        problems.append((body[0][0] if body else end, "Work holds at least one item"))
    return items


def milestone_line(body: list[tuple[int, str]] | None, end: int, problems: list[tuple[int, str]]) -> str | None:
    if body is None:
        return None
    filled = [(n, line.strip()) for n, line in body if line.strip()]
    if len(filled) != 1:
        where = filled[1][0] if len(filled) > 1 else (body[0][0] if body else end)
        problems.append((where, f"Milestone holds one line, `none` or a milestone title, not {len(filled)}"))
        return None
    return None if filled[0][1] == "none" else filled[0][1]


# -- items: the plan issue and the issues carrying its markers


def item_marker(plan: int, ident: str) -> str:
    return f"<!-- shipmill:plan-item #{plan} {ident} -->"


ISSUE_NODE = "number body milestone { title } " + "author { __typename login } authorAssociation"
ITEMS_QUERY = (
    """
query($owner: String!, $name: String!, $number: Int!, $search: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number body
      subIssues(first: 100) { pageInfo { hasNextPage } nodes { """
    + ISSUE_NODE
    + """ repository { nameWithOwner } } }
    }
  }
  search(type: ISSUE, query: $search, first: 100) {
    issueCount
    nodes { ... on Issue { """
    + ISSUE_NODE
    + """ repository { nameWithOwner } } }
  }
}
"""
)


def gh_graphql(query: str, variables: Variables) -> dict[str, Any]:
    """The default runner: one ``gh api graphql`` call"""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise PlanError(f"gh api graphql failed: {proc.stderr.strip()}")
    response: dict[str, Any] = json.loads(proc.stdout)
    return response


def login(author: dict[str, Any] | None) -> str:
    """An author's login as REST and --bot-login spell it: a Bot's with "[bot]" """
    if not author:
        return "ghost"
    name = str(author.get("login") or "ghost")
    if author.get("__typename") == "Bot" and not name.endswith("[bot]"):
        name += "[bot]"
    return name


def trusted(node: dict[str, Any], bot_login: str | None) -> bool:
    """D-29: a marker counts from an OWNER, MEMBER, or COLLABORATOR, or the --bot-login"""
    if str(node.get("authorAssociation") or "NONE") in TRUSTED:
        return True
    return bot_login is not None and login(node.get("author")).lower() == bot_login.lower()


def first_line(body: str) -> str:
    return (body or "").split("\n", 1)[0].strip()


def split_ref(ref: str) -> tuple[str, str, int]:
    found = PLAN_REF.match(ref)
    if found is None:
        raise PlanError(f"a plan is named owner/repo#N, got {ref!r}")
    return found.group(1), found.group(2), int(found.group(3))


@dataclass(frozen=True)
class Carrier:
    """The issue carrying an item's plan-item marker, and the milestone it is in"""

    number: int
    milestone: str | None


def plan_items(ref: str, bot_login: str | None, run: Runner = gh_graphql) -> list[tuple[Item, int | None]]:
    """Each item of plan `ref`, with the issue of the plan's repository carrying its marker"""
    _, filed = plan_carriers(ref, bot_login, run)
    return [(item, None if carrier is None else carrier.number) for item, carrier in filed]


def plan_carriers(
    ref: str, bot_login: str | None, run: Runner = gh_graphql
) -> tuple[Plan, list[tuple[Item, Carrier | None]]]:
    """Plan `ref` and each of its items, with the issue of the plan's repository carrying its
    marker and that issue's milestone"""
    owner, name, number = split_ref(ref)
    search = f'repo:{owner}/{name} is:issue in:body "shipmill:plan-item #{number}"'
    response = run(ITEMS_QUERY, {"owner": owner, "name": name, "number": number, "search": search})
    if response.get("errors"):
        raise PlanError(f"GitHub GraphQL errors: {json.dumps(response['errors'])}")
    data = response.get("data") or {}
    issue = (data.get("repository") or {}).get("issue")
    if issue is None:
        raise PlanError(f"no issue {ref}")
    plan, problems = parse(issue.get("body") or "", None)
    if plan is None:
        raise PlanError("\n".join(f"{ref}:{line}: {rule}" for line, rule in problems))
    subs = issue["subIssues"]
    found = data.get("search") or {}
    if subs["pageInfo"]["hasNextPage"] or int(found.get("issueCount") or 0) > 100:
        raise PlanError(f"{ref} has more than 100 sub-issues or marker matches, which plans.py does not page")
    here = f"{owner}/{name}".lower()
    carriers: dict[str, Carrier] = {}
    for node in [*subs["nodes"], *(found.get("nodes") or [])]:
        if not node or str((node.get("repository") or {}).get("nameWithOwner", "")).lower() != here:
            continue
        if not trusted(node, bot_login):
            continue
        line = first_line(node.get("body") or "")
        for item in plan.items:
            if line == item_marker(number, item.id):
                known = carriers.get(item.id)
                if known is None or node["number"] < known.number:
                    milestone = (node.get("milestone") or {}).get("title")
                    carriers[item.id] = Carrier(node["number"], None if milestone is None else str(milestone))
    return plan, [(item, carriers.get(item.id)) for item in plan.items]


# -- the command line


def check_command(file: Path, root: Path) -> int:
    if not file.is_file():
        raise PlanError(f"no file {file}")
    goals = goal_ids(root)
    _, problems = parse(file.read_text(encoding="utf-8"), goals)
    for line, rule in problems:
        print(f"{file}:{line}: {rule}", file=sys.stderr)
    return 2 if problems else 0


def items_command(ref: str, bot_login: str | None, as_json: bool, run: Runner = gh_graphql) -> int:
    for item, issue in plan_items(ref, bot_login, run):
        if as_json:
            row = {"id": item.id, "kind": item.kind, "text": item.text, "after": list(item.after), "issue": issue}
            print(json.dumps(row, sort_keys=True))
        else:
            after = f"  (after {', '.join(item.after)})" if item.after else ""
            filed = f"#{issue}" if issue is not None else "none"
            print(f"{item.id:<5} {item.kind:<8} {filed:<7} {item.text}{after}")
    return 0


def main(argv: list[str] | None = None, run: Runner = gh_graphql) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a plan body against the grammar")
    check.add_argument("file", type=Path, help="the plan body")
    check.add_argument("--root", type=Path, default=Path("."), help="the checkout holding docs/product.md")
    items = sub.add_parser("items", help="list a plan's items and the issues filed for them")
    items.add_argument("plan", help="the plan issue, owner/repo#N")
    items.add_argument("--bot-login", help="the login shipmill's sessions write as (an App's <slug>[bot])")
    items.add_argument("--json", action="store_true", help="one JSON line per item")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check_command(args.file, args.root)
        return items_command(args.plan, args.bot_login, args.json, run)
    except PlanError as exc:
        fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
