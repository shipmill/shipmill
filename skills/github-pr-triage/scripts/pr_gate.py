#!/usr/bin/env python3
"""Merge gate: is each PR open, mergeable, and green on every CI check that has finished?
And does it keep to the repo's direction (spec 024)?

- An agent's PR (authored by --bot-login, or every PR named with --agent) carries a
  `## Plan` section with `Serves:`, `Files:`, `Order:`, and `Proof:` lines, and its
  `Serves:` names goal ids docs/product.md lists, or `quality bar`; without a
  docs/product.md the plan isn't checked. A person's PR is never refused for its plan
- A PR whose files match a REVIEW.md Protected areas glob, or that edits docs/product.md
  or docs/product/, waits on the maintainer (needs-decision) until --maintainer-accepted
  says they accepted it

REVIEW.md and docs/product.md are read from the default branch of the checkout
(--checkout, default the current directory, at origin/HEAD, or at origin/<the PR's base
branch> when origin/HEAD isn't set), never from the PR. Outside a git checkout, or when
that branch holds neither file, the gate judges CI alone, as it did before spec 024. A
glob matches as decisions.py's scopes do: fnmatch, where `*` also matches `/`, or the path
sits under it (`skills/**`, `docs/product`), relative to the repo's root, and for a
subdirectory's REVIEW.md relative to its folder too.

A downstream check (spec 032), `downstream: <name>`, is a CheckRun in the rollup read like any
check, with no logic of its own: FAILURE, TIMED_OUT, or ACTION_REQUIRED fails, IN_PROGRESS is
pending, and a report-only one's NEUTRAL counts green.

Exit codes: 0 every PR is ready; 1 a check failed, or gh failed; 3 a check is still
pending (or --wait timed out); 4 a PR is not open or conflicts; 5 a PR needs the
maintainer's decision; 6 an agent's PR is refused for its plan; 2 bad arguments, a base
branch the checkout lacks, a git failure, or a REVIEW.md or docs/product.md the gate can't
read.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
READY, FAILED, PENDING, BLOCKED, NEEDS_DECISION, REFUSED = 0, 1, 3, 4, 5, 6
LABELS = {
    READY: "READY",
    FAILED: "FAILED",
    PENDING: "PENDING",
    BLOCKED: "BLOCKED",
    NEEDS_DECISION: "NEEDS_DECISION",
    REFUSED: "REFUSED",
}

DIRECTION = "docs/product.md"
DIRECTION_DIR = "docs/product/"
REVIEW = "REVIEW.md"
PROTECTED = "Protected areas"
LIST_SECTIONS = {"Users": "U", "Goals": "G", "Non-goals": "N", "Quality bar": "Q"}
DIRECTION_SECTIONS = ("Mission", *LIST_SECTIONS)
PLAN_FIELDS = ("Serves", "Files", "Order", "Proof")
QUALITY_BAR = "quality bar"

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ITEM = re.compile(r"^- ([A-Za-z]+)-([1-9][0-9]*): \S.*$")
_MEASURE = re.compile(r"^  measure: \S.*$")  # a goal's measure line (spec 027)
_MOVED = re.compile(r"^See \[([^\]]+)\]\(product/([A-Za-z0-9][A-Za-z0-9_-]*\.md)\)\.$")
_PROTECTED_ITEM = re.compile(r"- `([^`]*)`: (\S.*)")
_PLAN_FIELD = re.compile(r"^\s*(?:[-*]\s+)?(" + "|".join(PLAN_FIELDS) + r"):(.*)$")
_GOAL = re.compile(r"G-[1-9][0-9]*")


class GateError(Exception):
    """A state the gate can't judge: it stops with exit 2 and the message"""


@dataclass(frozen=True)
class Check:
    name: str
    done: bool
    conclusion: str


@dataclass(frozen=True)
class Gate:
    number: int
    state: str
    mergeable: str
    base: str
    head: str
    checks: tuple[Check, ...]
    refused: tuple[str, ...] = ()  # why an agent's PR is refused for its plan
    asks: tuple[str, ...] = ()  # why the PR waits on the maintainer

    @property
    def verdict(self) -> int:
        if self.state != "OPEN" or self.mergeable == "CONFLICTING":
            return BLOCKED
        if self.refused:
            return REFUSED
        if self.asks:
            return NEEDS_DECISION
        if any(c.done and c.conclusion not in GREEN for c in self.checks):
            return FAILED
        if not self.checks or any(not c.done for c in self.checks) or self.mergeable != "MERGEABLE":
            return PENDING
        return READY


@dataclass(frozen=True)
class Protected:
    glob: str
    why: str
    file: str  # the REVIEW.md that lists it

    def covers(self, path: str) -> bool:
        """The glob from the repo's root, or, in a subdirectory's REVIEW.md, from its folder
        too (`shipmill review protect --dir` writes it so); matching more is the safe side"""
        folder = self.file[: -len(REVIEW)]
        inner = path[len(folder) :] if folder and path.startswith(folder) else None
        return matches(self.glob, path) or (inner is not None and matches(self.glob, inner))


@dataclass(frozen=True)
class Base:
    """What the default branch holds: the direction's ids (None without docs/product.md)
    and every REVIEW.md, read for the files a PR changes"""

    ids: frozenset[str] | None
    reviews: dict[str, str]  # REVIEW.md path -> its text

    def protected(self, files: tuple[str, ...]) -> list[Protected]:
        wanted = {REVIEW}
        for path in files:
            parts = path.split("/")[:-1]
            wanted.update("/".join(parts[: i + 1]) + "/" + REVIEW for i in range(len(parts)))
        found: list[Protected] = []
        for name in sorted((n for n in self.reviews if n in wanted), key=lambda n: (n.count("/"), n)):
            found.extend(protected_areas(self.reviews[name], name))
        return found


def check_of(entry: dict) -> Check:
    """A CheckRun (status, conclusion) or a StatusContext (state)"""
    if "state" in entry and "status" not in entry:
        state = str(entry["state"])
        return Check(str(entry.get("context", "?")), state != "PENDING", state)
    status = str(entry.get("status", ""))
    return Check(str(entry.get("name", "?")), status == "COMPLETED", str(entry.get("conclusion") or ""))


def sections(text: str) -> list[tuple[int, str | None, list[tuple[int, str]]]]:
    """Split at level-one and level-two headings outside fenced code, as review.py does; the
    first entry, level 0 and headed None, holds the text before the first heading"""
    found: list[tuple[int, str | None, list[tuple[int, str]]]] = [(0, None, [])]
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
        elif opened is not None:
            fence = opened.group(1)
        else:
            heading = _HEADING.match(line)
            if heading is not None and len(heading.group(1)) <= 2:
                found.append((len(heading.group(1)), (heading.group(2) or "").strip(), []))
                continue
        found[-1][2].append((number, line))
    return found


def protected_areas(text: str, file: str) -> list[Protected]:
    """A REVIEW.md's Protected areas items, with review.py's line rule; a line that breaks
    it stops the gate, since a glob it can't read could guard anything"""
    found: list[Protected] = []
    for _, heading, body in sections(text):  # a level-one heading counts too, as in review.py
        if heading != PROTECTED:
            continue
        for number, line in body:
            if not line.strip():
                continue
            item = _PROTECTED_ITEM.fullmatch(line)
            if item is None or not item.group(1) or item.group(1) != item.group(1).strip():
                raise GateError(
                    f"{file}:{number}: a Protected areas item is one line ``- `<glob>`: <why>``; "
                    "fix it on the default branch (`shipmill review check`)"
                )
            found.append(Protected(item.group(1), item.group(2).strip(), file))
    return found


def matches(glob: str, path: str) -> bool:
    """fnmatch, where `*` also matches `/`, or the path sits under the glob's directory"""
    stem = glob.rstrip("*").rstrip("/")
    return path == glob or fnmatch.fnmatchcase(path, glob) or (bool(stem) and path.startswith(stem + "/"))


def direction_ids(read: Callable[[str], str | None]) -> frozenset[str]:
    """Every item id docs/product.md lists, moved sections followed; a list line that isn't
    `- <prefix>-<n>: <text>` with its section's prefix, or a broken link, stops the gate; a
    goal's `  measure: ...` line right under its item line is skipped (spec 027).
    `shipmill product check` holds the full grammar"""
    text = read(DIRECTION)
    if text is None:
        raise GateError(f"no {DIRECTION} on the default branch")
    ids: set[str] = set()
    for level, heading, body in sections(text):
        if level < 2:  # the text before the name, and the name
            continue
        if heading not in DIRECTION_SECTIONS:
            raise GateError(f"{DIRECTION}: `## {heading}` is not a direction heading; run `shipmill product check`")
        prefix = LIST_SECTIONS.get(heading)
        if prefix is None:
            continue
        lines = [(n, line.rstrip()) for n, line in body if line.strip()]
        file, listed = DIRECTION, body
        if len(lines) == 1 and lines[0][1].startswith("See ["):
            moved = _MOVED.match(lines[0][1])
            if moved is None or moved.group(1) != heading:
                raise GateError(f"{DIRECTION}:{lines[0][0]}: a broken `See [...]` line; run `shipmill product check`")
            file = DIRECTION_DIR + moved.group(2)
            linked = read(file)
            if linked is None:
                raise GateError(f"{DIRECTION}:{lines[0][0]}: {file} doesn't exist; run `shipmill product check`")
            parts = sections(linked)
            heads = [(lv, h) for lv, h, _ in parts[1:]]
            if heads != [(2, heading)] or any(line.strip() for _, line in parts[0][2]):
                raise GateError(f"{file} holds only `## {heading}`; run `shipmill product check`")
            listed = parts[1][2]
        after_goal = False  # the line before was a goal's item line, which a measure line may follow
        for number, raw in listed:
            line = raw.rstrip()
            if not line.strip():
                after_goal = False
                continue
            if after_goal and _MEASURE.match(line):  # spec 027: read no more from it
                after_goal = False
                continue
            item = _ITEM.match(line)
            if item is None or item.group(1) != prefix:
                raise GateError(f"{file}:{number}: not a `- {prefix}-<n>: <text>` item; run `shipmill product check`")
            ids.add(f"{prefix}-{item.group(2)}")
            after_goal = prefix == "G"
    return frozenset(ids)


def plan_problems(body: str, ids: frozenset[str]) -> list[str]:
    """Why a PR body's plan doesn't hold: no `## Plan` section, a missing field, or a
    `Serves:` naming something other than listed goal ids or `quality bar`"""
    plans = [lines for level, heading, lines in sections(body) if level == 2 and heading == "Plan"]
    if not plans:
        return ["no `## Plan` section; an agent's pull request carries its plan (Serves, Files, Order, Proof)"]
    if len(plans) > 1:
        return ["a second `## Plan` section; the body holds one"]
    fields: dict[str, list[str]] = {}
    for _, line in plans[0]:
        field = _PLAN_FIELD.match(line)
        if field is not None:
            fields.setdefault(field.group(1), []).append(field.group(2).strip())
    problems = [f"the plan has no `{name}:` line" for name in PLAN_FIELDS if name not in fields]
    problems += [f"the plan has {len(v)} `{k}:` lines; it holds one" for k, v in fields.items() if len(v) > 1]
    serves = fields.get("Serves", [""])[0]
    if "Serves" in fields and not serves:
        problems.append(f"`Serves:` is empty; it names goal ids from {DIRECTION}, or `{QUALITY_BAR}`")
    for name in (part.strip() for part in serves.split(",") if serves):
        if name == QUALITY_BAR:
            continue
        if not _GOAL.fullmatch(name):
            problems.append(f"`Serves:` names {name!r}; it names goal ids (G-n) or `{QUALITY_BAR}`")
        elif name not in ids:
            problems.append(f"`Serves:` names {name}, which {DIRECTION} doesn't list")
    return problems


def run(cmd: list[str], what: str) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise GateError(f"{what} failed: {proc.stderr.strip()}")
    return proc.stdout


def git(checkout: str, *args: str) -> str:
    return run(["git", "-C", checkout, *args], f"git {args[0]} in {checkout}")


NO_BASE = Base(None, {})  # nothing to read: the gate judges CI alone, as before spec 024


def quiet(checkout: str, *args: str) -> str | None:
    """A git call whose failure is an answer (no such ref, not a checkout): its output or None"""
    proc = subprocess.run(["git", "-C", checkout, *args], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def same_repo(url: str, repo: str) -> bool:
    """Whether origin's URL names -R's [HOST/]OWNER/NAME; GitHub's names ignore case"""
    tail = re.split(r"[:/]", re.sub(r"(\.git)?/*$", "", url.lower()))[-2:]
    return tail == repo.lower().strip("/").split("/")[-2:]


class Bases:
    """The default branch's REVIEW.md files and direction, read once per ref. Outside a git
    checkout, or in a checkout of another repo than -R names, there is nothing to read"""

    def __init__(self, checkout: str | None, repo: str | None) -> None:
        self.checkout = checkout or "."
        self.read: dict[str, Base] = {}
        self.inside = quiet(self.checkout, "rev-parse", "--is-inside-work-tree") == "true"
        if not self.inside and checkout is not None:
            raise GateError(f"--checkout {checkout} is not a git checkout")
        if self.inside and repo:
            url = quiet(self.checkout, "remote", "get-url", "origin") or ""
            if not same_repo(url, repo):
                print(
                    f"note: {self.checkout} is not a checkout of {repo}; REVIEW.md and the direction unread",
                    file=sys.stderr,
                )
                self.inside = False
        self.default = (
            quiet(self.checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") if self.inside else None
        )

    def base(self, base_branch: str) -> Base:
        """origin/HEAD, or the PR's own base branch at origin when origin/HEAD isn't set"""
        if not self.inside:
            return NO_BASE
        ref = self.default or f"origin/{base_branch}"
        if ref not in self.read:
            if quiet(self.checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is None:
                raise GateError(
                    f"neither origin/HEAD nor {ref} is in {self.checkout}: run `git -C {self.checkout} fetch origin`"
                )
            self.read[ref] = read_base(self.checkout, ref)
        return self.read[ref]


def read_base(checkout: str, ref: str) -> Base:
    names = [n for n in git(checkout, "ls-tree", "-r", "-z", "--name-only", ref).split("\0") if n]
    tree = set(names)

    def read(path: str) -> str | None:
        return git(checkout, "show", f"{ref}:{path}") if path in tree else None

    reviews = {n: git(checkout, "show", f"{ref}:{n}") for n in names if n.rsplit("/", 1)[-1] == REVIEW}
    ids = direction_ids(read) if DIRECTION in tree else None
    return Base(ids, reviews)


def author_of(entry: dict) -> str:
    """The login as REST and --bot-login spell it: gh prints an App's as `app/<slug>`"""
    login = str(entry.get("login") or "")
    if login.startswith("app/"):
        return login[len("app/") :] + "[bot]"
    if entry.get("is_bot") and not login.endswith("[bot]"):
        return login + "[bot]"
    return login


def fetch(number: int, repo: str | None) -> dict:
    cmd = ["gh", "pr", "view", str(number), "--json"]
    cmd.append("state,mergeable,baseRefName,headRefOid,statusCheckRollup,author,body,files,changedFiles")
    if repo:
        cmd += ["-R", repo]
    data = json.loads(gh(cmd, number))
    data["files"] = tuple(str(f["path"]) for f in data.get("files") or ())
    return data


def gh(cmd: list[str], number: int) -> str:
    """gh's output; a failure exits 1 with the message, as the gate always has"""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"pr_gate: gh failed for #{number}: {proc.stderr.strip()}")
    return proc.stdout


def all_files(data: dict, number: int, repo: str | None) -> tuple[str, ...]:
    """Every file the PR changes: gh pr view lists the first 100"""
    files: tuple[str, ...] = data["files"]
    if len(files) < int(data.get("changedFiles") or 0):
        diff = ["gh", "pr", "diff", str(number), "--name-only"] + (["-R", repo] if repo else [])
        files = tuple(line for line in gh(diff, number).splitlines() if line)
    return files


def judge(data: dict, number: int, base: Base, agent: bool, accepted: bool) -> Gate:
    checks = tuple(check_of(e) for e in data.get("statusCheckRollup") or ())
    files: tuple[str, ...] = data["files"]
    refused: list[str] = []
    if agent and base.ids is not None:
        refused = plan_problems(str(data.get("body") or ""), base.ids)
    asks: list[str] = []
    if not accepted and (base.ids is not None or base.reviews):
        edited = [f for f in files if f == DIRECTION or f.startswith(DIRECTION_DIR)]
        asks += [f"{f} edits the product's direction, which only the maintainer changes (D-34)" for f in edited]
        for area in base.protected(files):
            asks += [f"{f} matches `{area.glob}` ({area.file}): {area.why}" for f in files if area.covers(f)]
    return Gate(
        number,
        data["state"],
        data["mergeable"],
        data["baseRefName"],
        data["headRefOid"][:7],
        checks,
        tuple(refused),
        tuple(asks),
    )


def render(gate: Gate) -> str:
    green = sum(c.done and c.conclusion in GREEN for c in gate.checks)
    failed = [c for c in gate.checks if c.done and c.conclusion not in GREEN]
    pending = [c for c in gate.checks if not c.done]
    lines = [
        f"#{gate.number} {LABELS[gate.verdict]} state={gate.state} mergeable={gate.mergeable} base={gate.base} "
        f"head={gate.head} checks={len(gate.checks)} green={green} pending={len(pending)} failed={len(failed)}"
    ]
    lines += [f"  failed: {c.name} ({c.conclusion})" for c in failed]
    lines += [f"  pending: {c.name}" for c in pending]
    lines += [f"  refused: {reason}" for reason in gate.refused]
    lines += [f"  needs-decision: {reason}" for reason in gate.asks]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prs", nargs="+", type=int, help="PR numbers")
    parser.add_argument("-R", "--repo", help="owner/name; default: the current checkout's repo")
    parser.add_argument("--wait", action="store_true", help="poll until no check is pending")
    parser.add_argument("--interval", type=int, default=30, help="seconds between polls (default 30)")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds before --wait gives up (default 1800)")
    parser.add_argument(
        "--checkout",
        help="the repo's checkout, read at origin/HEAD, else at the PR's base branch on origin (default: ., "
        "and outside a checkout nothing is read)",
    )
    parser.add_argument("--bot-login", help="the login agents write as, such as <slug>[bot]; its PRs are agents'")
    parser.add_argument("--agent", action="store_true", help="every PR named is an agent's (a handover)")
    parser.add_argument(
        "--maintainer-accepted",
        action="store_true",
        help="the maintainer accepted these PRs' protected or direction changes; don't ask again",
    )
    args = parser.parse_args()
    if args.interval < 1 or args.timeout < 1:
        parser.error("--interval and --timeout must be positive")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login names a login, such as <slug>[bot]")
    deadline = time.monotonic() + args.timeout
    try:
        bases = Bases(args.checkout, args.repo)
        while True:
            gates = []
            for number in args.prs:
                data = fetch(number, args.repo)
                base = bases.base(str(data["baseRefName"]))
                if base.ids is not None or base.reviews:
                    data["files"] = all_files(data, number, args.repo)
                agent = args.agent or (
                    args.bot_login is not None and author_of(data.get("author") or {}) == args.bot_login
                )
                gates.append(judge(data, number, base, agent, args.maintainer_accepted))
            worst = max(g.verdict for g in gates)
            if not args.wait or worst != PENDING or time.monotonic() >= deadline:
                print("\n".join(render(g) for g in gates))
                return worst
            time.sleep(args.interval)
    except GateError as exc:
        print(f"pr_gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
