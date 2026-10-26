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

The decision policy (spec 030): when that branch's .github/shipmill.toml has an [agents]
table, the zones come from `shipmill --repo <checkout> decide classify --pr N --ref <the
branch> --json`, run as `uvx shipmill==<the version in the plugin's plugin.json>` (or `uvx
--from <tool> shipmill` with --tool), in place of the direction and Protected areas checks
above; the plan check stays. Each zone by its level, read from that branch, never the PR:

- never: MAINTAINER_ONLY, `  maintainer-only: <zone>: <reason>`; --maintainer-accepted
  doesn't lift it, since only the maintainer merges it, by hand (D-48)
- ask: NEEDS_DECISION, `  needs-decision: <zone>: <reason>`, until --maintainer-accepted
- notify: the verdict stays, with `  notify: <zone>: <reason>`; the skill posts the decided
  comment before it merges
- act: nothing

Without [agents] on that branch the gate judges as it did before spec 030.

A draft PR belongs to whoever opened it (D-52): the gate reads it as DRAFT, whatever its checks,
plan, or zones, and reads neither its files nor its zones. It enters triage once marked ready.

Exit codes: 0 every PR is ready; 1 a check failed, or gh failed; 3 a check is still
pending (or --wait timed out); 4 a PR is not open or conflicts; 5 a PR needs the
maintainer's decision; 6 an agent's PR is refused for its plan; 7 a PR only the maintainer
merges, by hand (a `never` zone); 8 a draft PR, left to its author (D-52); 2 bad arguments,
a base branch the checkout lacks, a git failure, a REVIEW.md, docs/product.md, or config the
gate can't read, or a `shipmill decide classify` that fails or prints what the gate can't
read. With several PRs the exit code is
the worst verdict's, ranked 0, 1, 3, 4, 8, 5, 7, 6.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
READY, FAILED, PENDING, BLOCKED, NEEDS_DECISION, REFUSED, MAINTAINER_ONLY, DRAFT = 0, 1, 3, 4, 5, 6, 7, 8
LABELS = {
    READY: "READY",
    FAILED: "FAILED",
    PENDING: "PENDING",
    BLOCKED: "BLOCKED",
    NEEDS_DECISION: "NEEDS_DECISION",
    REFUSED: "REFUSED",
    MAINTAINER_ONLY: "MAINTAINER_ONLY",
    DRAFT: "DRAFT",
}
# the worst verdict last: MAINTAINER_ONLY ranks above NEEDS_DECISION and below REFUSED (spec 030); DRAFT,
# its author's, ranks above BLOCKED and below the verdicts that ask something of the maintainer (D-52)
RANK = (READY, FAILED, PENDING, BLOCKED, DRAFT, NEEDS_DECISION, MAINTAINER_ONLY, REFUSED)

# github-ship-watch's watch_state.py: one reading of the config's [agents] and of the plugin's
# pinned CLI for every skill script
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
# github-issue-triage's decisions.py: the zone table's one copy, its ZONES and LEVELS
DECISIONS = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "decisions.py"
CONFIG = ".github/shipmill.toml"

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
    never: tuple[str, ...] = ()  # the never zones: only the maintainer merges it, by hand (spec 030)
    notices: tuple[str, ...] = ()  # the notify zones: decided without waiting, the verdict kept
    draft: bool = False  # its author's until marked ready (D-52)

    @property
    def verdict(self) -> int:
        if self.state != "OPEN":
            return BLOCKED
        if self.draft:
            return DRAFT
        if self.mergeable == "CONFLICTING":
            return BLOCKED
        if self.refused:
            return REFUSED
        if self.never:
            return MAINTAINER_ONLY
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
    """What the default branch holds: the direction's ids (None without docs/product.md),
    every REVIEW.md, read for the files a PR changes, and whether its config has [agents]
    (spec 030: then `shipmill decide classify` at ref names the zones)"""

    ids: frozenset[str] | None
    reviews: dict[str, str]  # REVIEW.md path -> its text
    agents: bool = False
    ref: str | None = None  # the ref it was read at

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
    config = read(CONFIG)
    return Base(ids, reviews, config is not None and has_agents(config, f"{CONFIG} at {ref}"), ref)


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateError(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


_MODULES: dict[str, ModuleType] = {}


def module(name: str, path: Path) -> ModuleType:
    """A sibling skill's script, loaded once and only when the gate needs it"""
    if name not in _MODULES:
        _MODULES[name] = load(name, path)
    return _MODULES[name]


def watch_state() -> ModuleType:
    return module("shipmill_watch_state", WATCH_STATE)


def has_agents(text: str, where: str) -> bool:
    """Whether the config has an [agents] table, read as watch_state.py reads it"""
    ws = watch_state()
    try:
        return ws.agents_table(text, Path(where)) is not None
    except ws.Refused as refused:
        raise GateError(str(refused).removeprefix("error: ")) from None


@dataclass(frozen=True)
class Zone:
    """A zone `shipmill decide classify` detects, at the base's level, with why"""

    zone: str
    level: str
    reason: str

    def line(self) -> str:
        return f"{self.zone}: {self.reason}"


class Classifier:
    """`shipmill decide classify --pr N --ref <base> --json` in the checkout, once per PR head"""

    def __init__(self, checkout: str, tool: str | None) -> None:
        self.checkout = checkout
        self.tool = tool
        self.found: dict[tuple[int, str, str], tuple[Zone, ...]] = {}

    def zones(self, number: int, ref: str, head: str) -> tuple[Zone, ...]:
        key = (number, ref, head)
        if key not in self.found:
            self.found[key] = self.run(number, ref)
        return self.found[key]

    def run(self, number: int, ref: str) -> tuple[Zone, ...]:
        ws = watch_state()
        try:
            cli: list[str] = ws.shipmill_cli(self.tool)
        except ws.Refused as refused:
            raise GateError(str(refused).removeprefix("error: ")) from None
        cmd = [*cli, "--repo", self.checkout, "decide", "classify", "--pr", str(number), "--ref", ref, "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise GateError(
                f"{cmd[0]} is not on PATH: the gate reads the zones with `shipmill decide classify`; install uv, "
                "https://docs.astral.sh/uv/"
            ) from None
        if proc.returncode != 0:
            why = proc.stderr.strip() or proc.stdout.strip()
            raise GateError(f"`{' '.join(cmd)}` failed for #{number}: {why}; {self.fix(cli)}")
        return parse_zones(proc.stdout, number)

    def fix(self, cli: list[str]) -> str:
        """What to do when classify fails: the shipmill --tool names, or the release the plugin pins"""
        if self.tool is not None:
            return f"check that --tool {self.tool} is a shipmill uvx can run"
        return (
            f"{cli[-1]} is the release the plugin pins: if PyPI doesn't serve it yet, wait for its publish, "
            "or pass --tool <path or URL> to run another shipmill"
        )


def parse_zones(text: str, number: int) -> tuple[Zone, ...]:
    """classify's JSON zones, each a known zone at a known level; anything else stops the gate"""
    decisions = module("shipmill_decisions", DECISIONS)
    what = f"`shipmill decide classify --pr {number} --json`"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GateError(f"{what} printed no JSON: {exc}") from None
    listed = data.get("zones") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        raise GateError(f"{what} printed no zones list")
    found = []
    for entry in listed:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("zone", "level", "reason")):
            raise GateError(f"{what} printed a zone that isn't {{zone, level, reason}}: {entry!r}")
        if entry["zone"] not in decisions.ZONES or entry["level"] not in decisions.LEVELS:
            raise GateError(
                f"{what} printed zone {entry['zone']!r} at {entry['level']!r}, which this gate doesn't know"
            )
        found.append(Zone(entry["zone"], entry["level"], entry["reason"]))
    return tuple(found)


def author_of(entry: dict) -> str:
    """The login as REST and --bot-login spell it: gh prints an App's as `app/<slug>`"""
    login = str(entry.get("login") or "")
    if login.startswith("app/"):
        return login[len("app/") :] + "[bot]"
    if entry.get("is_bot") and not login.endswith("[bot]"):
        return login + "[bot]"
    return login


# the fields the gate reads; the github-pr-triage eval cases record this read, so a change here
# re-records it there (#673)
FIELDS = "state,isDraft,mergeable,baseRefName,headRefOid,statusCheckRollup,author,body,files,changedFiles"


def fetch(number: int, repo: str | None) -> dict:
    cmd = ["gh", "pr", "view", str(number), "--json", FIELDS]
    if repo:
        cmd += ["-R", repo]
    data = json.loads(gh(cmd, number))
    data["files"] = tuple(str(f["path"]) for f in data.get("files") or ())
    return data


def gh(cmd: list[str], number: int, env: dict[str, str] | None = None) -> str:
    """gh's output; a failure exits 1 with the message, as the gate always has"""
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        sys.exit(f"pr_gate: gh failed for #{number}: {proc.stderr.strip()}")
    return proc.stdout


def all_files(data: dict, number: int, repo: str | None) -> tuple[str, ...]:
    """Every file the PR changes: gh pr view lists the first 100, so past them the files API is
    read, which pages where `gh pr diff` refuses a diff over 300 files (#630). Each file is its
    path after the change, as gh pr view's `path` is; the API lists at most 3000, and a partial
    list stops the gate rather than being judged"""
    files: tuple[str, ...] = data["files"]
    changed = int(data.get("changedFiles") or 0)
    if len(files) >= changed:
        return files
    # gh fills {owner}/{repo} in from GH_REPO, which takes what -R takes, else from the cwd's repo, as gh pr view does
    cmd = ["gh", "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{number}/files?per_page=100", "--jq", ".[]"]
    env = None
    if repo:
        env = {**os.environ, "GH_REPO": repo}
        host = re.fullmatch(r"([^/:]+)/[^/]+/[^/]+", repo.strip("/"))  # [HOST/]OWNER/NAME: gh api's host is its own
        cmd[2:2] = ["--hostname", host.group(1)] if host else []
    listed = gh(cmd, number, env)
    files = tuple(str(json.loads(line)["filename"]) for line in listed.splitlines() if line.strip())
    if len(files) < changed:
        sys.exit(
            f"pr_gate: #{number} changes {changed} files but GitHub lists {len(files)} (its files API stops at "
            "3000); the gate judges no partial list: review and land it by hand"
        )
    return files


def judge(
    data: dict, number: int, base: Base, agent: bool, accepted: bool, zones: tuple[Zone, ...] | None = None
) -> Gate:
    """zones, classify's for the PR, are given when the base's config has [agents] (spec 030);
    they replace the direction and Protected areas checks. A draft is judged for nothing else (D-52)"""
    checks = tuple(check_of(e) for e in data.get("statusCheckRollup") or ())
    if data["isDraft"]:
        return Gate(
            number, data["state"], data["mergeable"], data["baseRefName"], data["headRefOid"][:7], checks, draft=True
        )
    files: tuple[str, ...] = data["files"]
    refused: list[str] = []
    if agent and base.ids is not None:
        refused = plan_problems(str(data.get("body") or ""), base.ids)
    asks: list[str] = []
    never: list[str] = []
    notices: list[str] = []
    if zones is not None:
        never = [z.line() for z in zones if z.level == "never"]  # --maintainer-accepted never lifts it (D-48)
        asks = [] if accepted else [z.line() for z in zones if z.level == "ask"]
        notices = [z.line() for z in zones if z.level == "notify"]
    elif not accepted and (base.ids is not None or base.reviews):
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
        tuple(never),
        tuple(notices),
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
    lines += [f"  maintainer-only: {reason}" for reason in gate.never]
    lines += [f"  needs-decision: {reason}" for reason in gate.asks]
    lines += [f"  notify: {reason}" for reason in gate.notices]
    if gate.verdict == DRAFT:
        lines.append("  draft: left to its author until marked ready (D-52)")
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
        help="the maintainer accepted these PRs' protected or direction changes, or their ask zones; don't ask "
        "again (a never zone stays: the maintainer merges it by hand)",
    )
    parser.add_argument(
        "--tool",
        help="with [agents] on the base: where uvx gets shipmill for `decide classify` (default: "
        "shipmill==<the plugin.json version>)",
    )
    args = parser.parse_args()
    if args.interval < 1 or args.timeout < 1:
        parser.error("--interval and --timeout must be positive")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login names a login, such as <slug>[bot]")
    deadline = time.monotonic() + args.timeout
    try:
        bases = Bases(args.checkout, args.repo)
        classifier = Classifier(bases.checkout, args.tool)
        while True:
            gates = []
            for number in args.prs:
                data = fetch(number, args.repo)
                base = bases.base(str(data["baseRefName"]))
                if data["isDraft"]:  # its author's: neither its files nor its zones are read (D-52)
                    gates.append(judge(data, number, base, False, args.maintainer_accepted))
                    continue
                if base.ids is not None or base.reviews:
                    data["files"] = all_files(data, number, args.repo)
                agent = args.agent or (
                    args.bot_login is not None and author_of(data.get("author") or {}) == args.bot_login
                )
                zones = None
                if base.agents and base.ref is not None:
                    zones = classifier.zones(number, base.ref, str(data["headRefOid"]))
                gates.append(judge(data, number, base, agent, args.maintainer_accepted, zones))
            worst = max((g.verdict for g in gates), key=RANK.index)
            if not args.wait or worst != PENDING or time.monotonic() >= deadline:
                print("\n".join(render(g) for g in gates))
                return worst
            time.sleep(args.interval)
    except GateError as exc:
        print(f"pr_gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
