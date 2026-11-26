#!/usr/bin/env python3
"""Report many repos' issue-to-release pipelines at once: ship-watch's states across a fleet.

Usage: fleet.py report --fleet FILE [--metrics] [--json]
       fleet.py queue --fleet FILE [--login LOGIN] [--bot-login LOGIN] [--order age|impact] [--json]
       fleet.py overview --fleet FILE [--login LOGIN] [--bot-login LOGIN] [--jobs N] [--json]

A fleet file lists the repos, in TOML:

  [[repos]]
  repo = "shipmill/shipmill"

  [[repos]]
  repo = "owner/other"
  incident_label = "sev"   # optional; the label that repo's incidents carry (default: its config's)

The file is refused (exit 2, with a message naming the file and the problem) when it is
missing, isn't TOML, has no [[repos]], has an entry without `repo`, has a key other than
`repo` and `incident_label`, names a repo not in owner/name form, or lists a repo twice.
On Python 3.10, where tomllib doesn't exist, the file is read in the plain form above
([[repos]] tables of quoted strings, comments, blank lines) and anything else is refused.

report runs watch_state.py for each repo, on a fresh clone (`gh repo clone`, blobless, in a
temporary folder removed afterwards) with the repo's incident_label passed as
--incident-label, and prints one table: the repo, then each row's state, subject, and
detail as watch_state.py prints them. The rows watch_state.py counts as action come first,
across all repos, then the report-only rows, each group in the fleet file's order. A repo
whose config has [trends] reports its DRIFT rows (spec 078) among its report-only rows: never
an action, so they leave the exit code as it was.

A repo's incident label is the fleet entry's incident_label, else the [operate]
incident_label of the clone's .github/shipmill.toml, else "incident". The watch and the
metrics use the same one: fleet.py reads the clone's config with watch_state.py's own
reader, so a config the watch refuses is refused for the metrics too.

  --metrics   adds metrics.py's measures for each repo, over the same 30 days to the
              run's start, counting the repo's incident label's issues: a second table,
              one column per repo, each cell the measure's text as metrics.py prints it
              ("no data" stays "no data"). A repo whose check failed has no column
  --json      the same report as one JSON object: {"repos": [{"repo", "rows": [{"state",
              "subject", "detail"}]}]}, each repo's rows in watch_state.py's order; with
              --metrics each repo also holds "metrics", metrics.py --json's object (null
              when its check failed)

A repo whose check fails (the clone, watch_state.py, or metrics.py exits 2: not found, no
access, a gh error; or, with --metrics, its config's incident label can't be read) gets one
REPO_ERROR row, its subject the step that failed and its detail the error's first line; the
other repos are still reported.

Exit 0 when no repo has an action row, 1 when any has, 2 after printing everything when a
repo's check failed, and 2 on a malformed fleet file. Reads only: the repairs stay with
each repo's own watch pass. Needs git, an authenticated gh, and uvx, as watch_state.py
does. Python 3.10+, standard library only.

queue (spec 069) reads the same fleet file with the same refusals and prints only what waits
on the maintainer, across every repo, oldest first. On the same fresh clone, watch_state.py
runs with --no-host, --no-trends (no DRIFT row is a queue item), --trusted-only, and the
--bot-login (the gate's App, <slug>[bot]), and
names the items; one batched GraphQL read per repo (50 items each) reads them as GitHub has
them now:
  QUESTION    an open item in NEEDS_DECISION, still labelled needs-decision, whose question
              has no trusted reply; waiting since the newest needs-decision marker comment by
              a trusted author, else the label's newest event, else its opening
  TO_MERGE    an open pull request in PRS_PARKED's TO_MERGE part, still labelled
              shipmill-ready; since the label's newest event, else its opening
  PROMOTION   an open "Ready to promote" proposal issue in PROMOTION_DUE; since its opening
triage_state.py --json --trusted-only (with the --bot-login) and, in the clone,
intake_state.py --json (with the --bot-login, and --plans when the clone has
docs/product.md, as the watch runs it) name these, read the same way. Each runs with the
clone's roles as the watch does: the --role flags `shipmill roles --flags` prints, run in the
clone with the CLI the plugin pins (spec 036; to intake_state.py only with --plans), so a plan
answer the --bot-login relays for the maintainer counts (D-68). With no maintainer in the
clone's [agents.roles], `shipmill roles` takes SHIPMILL_MAINTAINER when set, else the host's gh
login:
  YOUR_ITEM   an open item triage_state.py reads WITH_PERSON whose "assignees" include the
              reader (logins compared ignoring case); one assigned only to other logins or
              only to a team is none; since the time its note gives ("since <time>")
  UPSTREAM    an open report triage_state.py reads UPSTREAM_UNOWNED, still labelled upstream:
              nobody linked it to an issue in another repo or took it (#1487), so the
              maintainer reports it where it belongs; since the label's newest event, else
              its opening. triage_state.py runs with the --home the watch passes (the
              clone's [product] home, or the repo itself in the home repo, whose config has
              [product] repos), so in a product the coordinator's report is none
  OPPORTUNITY an open opportunity intake_state.py reads OPPORTUNITY_OPEN; since its opening
  PLAN        an open plan issue intake_state.py reads PLAN_OPEN; since its newest revision:
              the newest <!-- shipmill:plan-revised rev=k --> comment by the --bot-login
              whose rev is higher than the one before it, else its opening. A plan re-checked
              after its hold was met (its line's hold has a met_at, spec 098) waits since the
              later of that and the hold's met_at; a held plan (PLAN_HELD) and one whose
              re-check is due (PLAN_HOLD_MET) are no row
  NO_REASON   a closed opportunity intake_state.py reads NO_REASON; since its close
GitHub's GraphQL reads the open pull requests (25 a read, each with its newest 100 comments and
first 100 files), and pr_gate.py's readers judge them:
  SPEC_TO_MERGE  an open, non-draft pull request whose body's first line is `Spec for #N`
              (spec_refs) that no question holds (its newest needs-decision question has a
              trusted answer, or it has none) and that nothing lands by itself: no trusted answer
              taking the recommended option (whole_reply, takes_recommended; a relay counts naming
              a maintainer of the clone's roles, in its grammar) and no newest decided comment of
              the --bot-login at accepted-spec. One of those would land is a row still when it
              edits docs/product.md or docs/product/ (direction_edits), or its files run past
              100, since only the maintainer merges it (D-34). An item another row lists is in
              that row only. Since its newest ready-for-review, else its opening
ACCEPTED, HANDED_OFF, DECLINED, PLAN_ACCEPTED, and every other state of the two scripts are
no row. An item in QUESTION is in no other row. An item whose author is neither an OWNER, MEMBER, or
COLLABORATOR nor the --bot-login (save the release workflow's upgrade issue, D-30) is in none.
Each line: the repo, the kind, #N, what is asked (a fixed phrase, then the title), and how
long it has waited (3d 4h, 5h, 12m), oldest first across repos, a tie to the fleet file's
order, then the number. --login names the reader (default: `gh api user`'s login). --json
prints {"login", "items": [{"repo", "kind", "number", "url", "asked", "title", "since",
"waited_minutes"}], "errors": [{"repo", "step", "error"}]}. A repo whose clone, roles read,
watch, triage_state.py, intake_state.py, or GitHub read fails gets one REPO_ERROR line after
the queue, naming the step and the error's first line; a repo is never read without its roles.
Exit 0 on an empty queue, 1 with a row, 2 after printing everything when a repo's read
failed, and 2 on a malformed fleet file. Reads only.

  --order age|impact  age (the default) is the order above, with no other read. impact
              (spec 086) runs, after the repos' reads, one github-issue-triage
              chains.py impact --json --trusted-only (with the --bot-login) with a --repo for
              every repo of the fleet file, so counts run across the fleet's repos. Each row
              gains holds, how many open issues wait on its item (its row's held; 0 when the
              walk lists none), and the rows sort by holds, most first, then in the order
              above. Each line puts "holds K" before the wait; --json's items gain "holds"
              and its object "order": "impact". A walk that fails, or prints what isn't its
              rows, keeps the order above, prints one IMPACT_ERROR line with the error's first
              line after the queue (--json: "order": "age" and "impact_error"), and exits 2

overview (#1479) prints what report (without --metrics) and queue print, each repo read once:
one clone, on which report's watch and queue's reads run as those commands run them. The
queue's watch still runs on its own, since --trusted-only and the --bot-login change how the
watch reads an item, not only which rows it prints. The repos are read concurrently, at most
--jobs N at once (default 4); the output keeps the fleet file's order, and the queue stays
oldest first. The text is report's table, a blank line, then queue's lines; --json prints
{"report": <report --json>, "queue": <queue --json>}. A repo whose clone fails gets its
REPO_ERROR in both. Exit 2 when report or queue would exit 2, else 1 when either would exit
1, else 0. Reads only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, TypeVar

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the plain form is read line by line instead
    tomllib = None

SCRIPTS = Path(__file__).resolve().parent
WATCH_STATE = SCRIPTS / "watch_state.py"
METRICS = SCRIPTS / "metrics.py"
# watch_state.py's ACTION: the states that make it exit 1 (tests/test_fleet.py keeps the two equal)
ACTION = frozenset(
    {
        "BOT_FAILED",
        "BOT_STALLED",
        "BOT_PLAN_FAILED",
        "WORK_BRANCH_STALE",
        "NOT_PUBLISHED",
        "ISSUES",
        "PLANS",
        "OPERATE_FAILED",
        "UNHEALTHY",
        "PROMOTION_DUE",
        "INCIDENT_OPEN",
        "POSTMORTEM_DUE",
        "NEEDS_DECISION",
        "BRANCH_DELETE_OFF",
        "SHIPMILL_OUTDATED",
        "GATE_NO_APP",
        "DIRECTION_MISSING",
        "GATE_SESSIONS_DEAD",
        "GATE_CHECKOUT_MISSING",  # #1155
        "SKILL_SHADOWED",
        "PLUGIN_SHADOWING",
        "UPGRADE_PENDING",
        "DIRECTION_PENDING",
        "CHAIN_NO_GATE",
        "CHAIN_CYCLE",
        "CHAIN_UNREADABLE",
        "MILESTONE_OVERTAKEN",
        "MILESTONE_RELEASED",  # spec 068
        "UPSTREAM_DUE",
        "UPSTREAM_ASKED",
        "UPSTREAM_UNREADABLE",
        "VETOED",
        "AGENT_DRAFT",  # D-67: the App's own draft, resumed by a session (#914)
        "LAND_DUE",  # spec 056: the land window's queue head
        "CLASS_CONFLICT",  # spec 070: an accepted opportunity's class waits on the maintainer
        "FIXED_DATE_AT_RISK",
        "FIXED_DATE_NO_DATE",
        "SPEC_DUE",  # spec 074: accepted opportunities for the spec gate
        "FEEDBACK_DUE",  # spec 074: handed-over requests for an intake pass
        "BASE_RED",  # spec 079: a red default branch
    }
)
REPO_ERROR = "REPO_ERROR"
# watch_state.py's one state whose row is report-only by a level: FEEDBACK_DUE under [autonomy]
# intake = "observe", which it prints with "agent": false (spec 074)
REPORT_ONLY_BY_LEVEL = "FEEDBACK_DUE"
ROW_KEYS = {"state", "subject", "detail", "agent"}  # a watch_state.py --json line
FIX_KEY = "fix"  # and its fix (spec 011), a string or null, which this report doesn't print
HEADS_KEY = "heads"  # and a PRS_OPEN row's heads, number to sha, for the gate's fingerprint (#546): not printed
KEYS = ("repo", "incident_label")  # the keys of a [[repos]] entry
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/(?!\.+$)[A-Za-z0-9._-]+$")  # owner/name; a name isn't only dots
# the plain form Python 3.10 reads: a [[repos]] header or key = "string", each with an optional comment
PLAIN_HEADER = re.compile(r"^\[\[\s*repos\s*\]\]\s*(?:#.*)?$")
PLAIN_KEY = re.compile(r"""^([A-Za-z0-9_-]+)\s*=\s*(?:"([^"\\]*)"|'([^']*)')\s*(?:#.*)?$""")


def script(path: Path) -> ModuleType:
    """A sibling script as a module (its main() isn't run), loaded by path so fleet.py works from any folder"""
    spec = importlib.util.spec_from_file_location(f"fleet_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


# watch_state.py's config reader: the metrics read a repo's incident label as the watch does
WS = script(WATCH_STATE)
# pr_gate.py's readers: the queue reads a spec pull request's question, answer, decided comment,
# and direction edits as the merge gate does (S-069-4)
PR_GATE = SCRIPTS.parents[1] / "github-pr-triage" / "scripts" / "pr_gate.py"
PG = script(PR_GATE)


class Refused(SystemExit):
    """Bad input: the message goes to stderr, and the run exits 2"""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Entry:
    """One repo of the fleet"""

    repo: str
    incident_label: str | None  # None: the repo's own config decides (default "incident")


def parse_plain(text: str, path: Path) -> dict[str, Any]:
    """The plain form of a fleet file, read as tomllib would read it, for Python 3.10"""
    raw: dict[str, Any] = {}
    table = raw
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if PLAIN_HEADER.match(stripped):
            table = {}
            raw.setdefault("repos", []).append(table)
            continue
        found = PLAIN_KEY.match(stripped)
        if found is None:
            raise Refused(
                f"error: {path}: line {number}: can't read {stripped!r} on Python 3.10: "
                'write [[repos]] tables of key = "string" lines, or use Python 3.11+'
            )
        key = found.group(1)
        if key in table:
            raise Refused(f"error: {path}: line {number}: {key} is set twice")
        table[key] = found.group(2) if found.group(2) is not None else found.group(3)
    return raw


def parse(text: str, path: Path) -> dict[str, Any]:
    """The fleet file as TOML: tomllib on Python 3.11+, the plain form on 3.10"""
    if tomllib is None:
        return parse_plain(text, path)
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"error: {path}: not TOML: {exc}") from None


def entry(table: object, index: int, path: Path) -> Entry:
    """One [[repos]] table, checked"""
    where = f"error: {path}: repos[{index}]"
    if not isinstance(table, dict):
        raise Refused(f"{where} is not a table")
    unknown = sorted(set(table) - set(KEYS))
    if unknown:
        raise Refused(f"{where} has an unknown key {unknown[0]!r}: only repo and incident_label")
    if "repo" not in table:
        raise Refused(f"{where} has no repo")
    repo = table["repo"]
    if not isinstance(repo, str) or not REPO.match(repo):
        raise Refused(f"{where}: repo {repo!r} is not in owner/name form")
    label = table.get("incident_label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise Refused(f"{where}: incident_label must be a non-empty string")
    return Entry(repo, label)


def load(path: Path) -> list[Entry]:
    """The fleet file's repos, in order; Refused when the file is malformed"""
    if not path.is_file():
        raise Refused(f"error: {path}: no such file")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise Refused(f"error: {path}: not TOML: {exc}") from None
    raw = parse(text, path)
    unknown = sorted(set(raw) - {"repos"})
    if unknown:
        raise Refused(f"error: {path}: unknown key {unknown[0]!r}: a fleet file holds only [[repos]] tables")
    tables = raw.get("repos")
    if not isinstance(tables, list) or not tables:
        raise Refused(f"error: {path}: no [[repos]]")
    entries = [entry(table, i, path) for i, table in enumerate(tables)]
    seen: set[str] = set()
    for e in entries:
        key = e.repo.lower()  # GitHub's owner and repo names ignore case
        if key in seen:
            raise Refused(f"error: {path}: lists {e.repo} twice")
        seen.add(key)
    return entries


def watch_command(e: Entry, checkout: Path) -> list[str]:
    """watch_state.py for one repo, on its checkout, as JSON lines"""
    cmd = [sys.executable, str(WATCH_STATE), e.repo, "--repo-dir", str(checkout), "--json"]
    if e.incident_label is not None:
        cmd += ["--incident-label", e.incident_label]
    return cmd


def clone_command(e: Entry, checkout: Path) -> list[str]:
    """A blobless clone of the repo's default branch, with its tags, as watch_state.py reads it"""
    return ["gh", "repo", "clone", e.repo, str(checkout), "--", "--filter=blob:none", "--quiet"]


def incident_label(e: Entry, checkout: Path) -> str:
    """The label the repo's incidents carry, decided as watch_state.py decides it: the fleet
    entry's, else the clone's [operate] incident_label, else "incident". The config is read
    and checked with watch_state.py's reader either way, so it refuses what the watch refuses"""
    policy = WS.policy_file(checkout)
    if policy is None:
        return e.incident_label or WS.INCIDENT_LABEL
    text = (checkout / policy).read_text(encoding="utf-8")
    return str(WS.config(text, policy, e.incident_label).incident_label)


def metrics_command(e: Entry, until: str, label: str) -> list[str]:
    """metrics.py for one repo over the 30 days to until, as JSON, counting label's issues as incidents"""
    return [sys.executable, str(METRICS), e.repo, "--json", "--until", until, "--incident-label", label]


# -- the report ----------------------------------------------------------------------------


class Runner(Protocol):
    """Runs a command, in cwd when given (intake_state.py --plans reads the clone's direction)"""

    def __call__(self, cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]: ...


def run(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False, cwd=cwd)


@dataclass(frozen=True)
class Row:
    """One watch row; report_only marks a FEEDBACK_DUE read under [autonomy] intake = "observe",
    which watch_state.py prints with "agent": false (spec 074): reported, never an action"""

    state: str
    subject: str
    detail: str
    report_only: bool = False

    @property
    def action(self) -> bool:
        """watch_state.py's Row.action: a state in ACTION, save a report-only one"""
        return self.state in ACTION and not self.report_only

    def json(self) -> dict[str, str]:
        return {"state": self.state, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RepoReport:
    repo: str
    rows: tuple[Row, ...]
    metrics: dict[str, Any] | None  # metrics.py --json's object; None when not asked or failed

    @property
    def failed(self) -> bool:
        return any(r.state == REPO_ERROR for r in self.rows)

    def json(self, with_metrics: bool) -> dict[str, Any]:
        found: dict[str, Any] = {"repo": self.repo, "rows": [r.json() for r in self.rows]}
        if with_metrics:
            found["metrics"] = self.metrics
        return found


def error_row(step: str, proc: subprocess.CompletedProcess[str]) -> Row:
    """REPO_ERROR for a failed step: the first line of what it wrote to stderr"""
    lines = [line.strip() for line in (proc.stderr or "").splitlines() if line.strip()]
    return Row(REPO_ERROR, step, lines[0] if lines else f"{step} exited {proc.returncode}")


def decoded(text: str, what: str) -> object:
    """A script's JSON output; Refused when it isn't JSON (exit 2: a traceback's 1 reads as an action)"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise Refused(f"error: {what} printed {text[:200]!r}, not JSON") from None


def watch_rows(repo: str, out: str) -> list[Row]:
    """watch_state.py --json's lines, one row each"""
    rows = []
    for line in out.splitlines():
        found = decoded(line, f"watch_state.py for {repo}")
        if (
            not isinstance(found, dict)
            or set(found) - {FIX_KEY, HEADS_KEY} != ROW_KEYS
            or not isinstance(found["agent"], bool)
            or not isinstance(found.get(FIX_KEY), (str, type(None)))
            or not isinstance(found.get(HEADS_KEY, {}), dict)
        ):
            raise Refused(f"error: watch_state.py for {repo} printed {line!r}, not a row")
        state = str(found["state"])
        # spec 074: watch_state.py's report-only FEEDBACK_DUE is the one it prints as no agent's
        report_only = state == REPORT_ONLY_BY_LEVEL and not found["agent"]
        rows.append(Row(state, str(found["subject"]), str(found["detail"]), report_only))
    return rows


def clone(e: Entry, runner: Runner, workdir: Path) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """The repo's fresh clone in workdir, and how the clone went"""
    checkout = workdir / e.repo
    checkout.parent.mkdir(parents=True, exist_ok=True)
    return checkout, runner(clone_command(e, checkout))


def check(e: Entry, runner: Runner, workdir: Path, until: str | None) -> RepoReport:
    """One repo's watch rows (and metrics, given until), or its REPO_ERROR row"""
    checkout, cloned = clone(e, runner, workdir)
    if cloned.returncode != 0:
        return RepoReport(e.repo, (error_row("gh repo clone", cloned),), None)
    return check_clone(e, runner, checkout, until)


def check_clone(e: Entry, runner: Runner, checkout: Path, until: str | None) -> RepoReport:
    """check's read of the repo's clone: the full watch, and with until the metrics"""
    watched = runner(watch_command(e, checkout))
    if watched.returncode not in (0, 1):
        return RepoReport(e.repo, (error_row("watch_state.py", watched),), None)
    rows = watch_rows(e.repo, watched.stdout)
    if until is None:
        return RepoReport(e.repo, tuple(rows), None)
    try:
        label = incident_label(e, checkout)
    except WS.Refused as refused:  # watch_state.py has refused this config already; kept a row if that changes
        return RepoReport(e.repo, (*rows, Row(REPO_ERROR, "incident label", str(refused))), None)
    measured = runner(metrics_command(e, until, label))
    if measured.returncode != 0:
        return RepoReport(e.repo, (*rows, error_row("metrics.py", measured)), None)
    found = decoded(measured.stdout, f"metrics.py for {e.repo}")
    if not isinstance(found, dict) or not isinstance(found.get("measures"), list):
        raise Refused(f"error: metrics.py for {e.repo} printed no measures")
    return RepoReport(e.repo, tuple(rows), found)


def report(entries: list[Entry], runner: Runner, workdir: Path, until: str | None) -> list[RepoReport]:
    """Every repo of the fleet, in order; until (the metrics window's end) only with --metrics"""
    return [check(e, runner, workdir, until) for e in entries]


def leads(row: Row) -> bool:
    """A row the table puts first: an action, or a repo whose check failed"""
    return row.action or row.state == REPO_ERROR


def table(reports: list[RepoReport]) -> list[str]:
    """One line per row, the repo named on each: actions (and failed checks) first, across all repos"""
    width = max(len(r.repo) for r in reports)
    rows = [(r.repo, row) for r in reports for row in r.rows]
    first = [x for x in rows if leads(x[1])]
    rest = [x for x in rows if not leads(x[1])]
    return [f"{repo:<{width}} {row.state:<14} {row.subject:<16} {row.detail}".rstrip() for repo, row in first + rest]


def metrics_table(reports: list[RepoReport]) -> list[str]:
    """The measures side by side: one row per measure, one column per repo that has them"""
    measured = [(r.repo, r.metrics) for r in reports if r.metrics is not None]
    if not measured:
        return []
    columns: list[tuple[str, dict[str, str]]] = []
    names: list[str] = []
    for repo, found in measured:
        texts = {str(m["measure"]): str(m["text"]) for m in found["measures"]}
        if names and list(texts) != names:
            raise Refused(f"error: metrics.py for {repo} measured {list(texts)}, not {names}")
        names = list(texts)
        columns.append((repo, texts))
    first = measured[0][1]
    end = dt.datetime.fromisoformat(str(first["end"])).astimezone(dt.timezone.utc)  # noqa: UP017 (3.10)
    head = f"Metrics: the {first['days']} days to {end:%Y-%m-%d %H:%M} UTC"
    widths = [max(len("Measure"), *(len(n) for n in names))]
    widths += [max(len(repo), *(len(t) for t in texts.values())) for repo, texts in columns]
    lines = [["Measure", *(repo for repo, _ in columns)]]
    lines += [[name, *(texts[name] for _, texts in columns)] for name in names]
    cells = (" ".join(f"{cell:<{w}}" for cell, w in zip(line, widths, strict=True)).rstrip() for line in lines)
    return [head, *cells]


def exit_code(reports: list[RepoReport]) -> int:
    if any(r.failed for r in reports):
        return 2
    return 1 if any(row.action for r in reports for row in r.rows) else 0


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)  # noqa: UP017 (3.10 has no dt.UTC)


# -- the queue (spec 069): what waits on the maintainer, across the fleet ---------------------

QUESTION = "QUESTION"
TO_MERGE = "TO_MERGE"
PROMOTION = "PROMOTION"
YOUR_ITEM = "YOUR_ITEM"
OPPORTUNITY = "OPPORTUNITY"
PLAN = "PLAN"
NO_REASON = "NO_REASON"
SPEC_TO_MERGE = "SPEC_TO_MERGE"
UPSTREAM = "UPSTREAM"  # #1487: triage_state.py's UPSTREAM_UNOWNED, an upstream report nobody linked or took
# what each kind asks of the maintainer: the fixed phrase the row's title follows
ASKED = {
    QUESTION: "answer the needs-decision question",
    SPEC_TO_MERGE: "merge the spec pull request",
    TO_MERGE: "merge the pull request",
    PROMOTION: "approve the promotion",
    YOUR_ITEM: "do your item",
    OPPORTUNITY: "accept or decline the opportunity",
    PLAN: "answer the goal plan",
    NO_REASON: "record why the opportunity was declined",
    UPSTREAM: "report it where it belongs",
}
KIND_WIDTH = max(len(kind) for kind in ASKED)  # the kind column, as wide as OPPORTUNITY
# intake_state.py's --json states the queue lists, by the line's kind, and the row each is
INTAKE_KINDS = {
    ("opportunity", "OPPORTUNITY_OPEN"): OPPORTUNITY,
    ("opportunity", "NO_REASON"): NO_REASON,
    ("plan", "PLAN_OPEN"): PLAN,
    ("plan", "PLAN_OVERDUE"): PLAN,  # spec 106: past its answer date, it still waits on your answer
}
WITH_PERSON_SINCE = re.compile(r"\bsince (\S+)")  # triage_state.py's WITH_PERSON note: "... since <time> ..."
# intake_state.py's REVISED (tests/test_fleet_queue.py keeps the two equal): a plan's revision comment
REVISED = re.compile(r"^<!-- shipmill:plan-revised rev=([1-9][0-9]*) -->$")
# the watch's rows the queue reads: NEEDS_DECISION's "#N ...", PRS_PARKED's "TO_MERGE #N ..."
# part, and PROMOTION_DUE's proposal part, whose detail starts "#N " (a deployment's never does)
NUMBERS = re.compile(r"#(\d+)")
TO_MERGE_PART = re.compile(r"(?:^|; )TO_MERGE ((?:#\d+ ?)+)")
PROPOSAL_DETAIL = re.compile(r"^#(\d+) ")
CHUNK = 50  # items per GraphQL read: one read per 50 items of a repo
FIELDS = """number title url state createdAt closedAt body authorAssociation author { __typename login }
labels(first: 100) { nodes { name } }
comments(last: 100) { nodes { author { __typename login } authorAssociation body createdAt } }
timelineItems(itemTypes: [LABELED_EVENT], last: 100) { nodes { ... on LabeledEvent { createdAt label { name } } } }"""
ITEM_KEYS = ("number", "title", "url", "state", "createdAt", "body", "authorAssociation", "author", "labels")


@dataclass(frozen=True)
class Item:
    """One row of the queue: what waits on the maintainer, and since when"""

    repo: str
    kind: str
    number: int
    url: str
    title: str
    since: dt.datetime
    holds: int | None = None  # --order impact's count of open issues waiting on it (spec 086); None without

    def waited(self, now: dt.datetime) -> int:
        return max(0, int((now - self.since).total_seconds() // 60))

    def json(self, now: dt.datetime) -> dict[str, Any]:
        found: dict[str, Any] = {
            "repo": self.repo,
            "kind": self.kind,
            "number": self.number,
            "url": self.url,
            "asked": ASKED[self.kind],
            "title": self.title,
            "since": self.since.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017 (3.10)
            "waited_minutes": self.waited(now),
        }
        return found if self.holds is None else {**found, "holds": self.holds}


@dataclass(frozen=True)
class RepoError:
    repo: str
    step: str
    error: str

    def json(self) -> dict[str, str]:
        return {"repo": self.repo, "step": self.step, "error": self.error}


def first_line(proc: subprocess.CompletedProcess[str], step: str) -> str:
    """A failed step's first line on stderr, or its exit when it wrote none"""
    lines = [line.strip() for line in (proc.stderr or "").splitlines() if line.strip()]
    return lines[0] if lines else f"{step} exited {proc.returncode}"


def queue_watch_command(e: Entry, checkout: Path, bot_login: str | None) -> list[str]:
    """watch_state.py for one repo's queue: the watch's trust (--trusted-only and the
    --bot-login, D-16), none of this host's rows, and no trends read: a DRIFT row is no item (spec 078)"""
    cmd = [*watch_command(e, checkout), "--no-host", "--no-trends", "--trusted-only"]
    return cmd + (["--bot-login", bot_login] if bot_login is not None else [])


def roles_command(checkout: Path) -> list[str]:
    """The pinned CLI's `shipmill roles --flags` on the clone, as the watch runs the CLI: the
    clone's [agents.roles] resolved, the maintainer included (spec 036, #1409)"""
    return [*WS.shipmill_cli(), "--repo", str(checkout), "roles", "--flags"]


def role_values(text: str, repo: str) -> list[str]:
    """The NAME=FILLER[,FILLER...] values of `shipmill roles --flags`' one line, `--role VALUE`
    pairs; Refused when it prints anything else (exit 2: never a queue read without its roles)"""
    words = text.split()
    words = words if len(words) % 2 == 0 else []  # an odd count is malformed, refused below
    pairs = list(zip(words[::2], words[1::2], strict=True))
    if not pairs or any(flag != "--role" or value.startswith("-") for flag, value in pairs):
        raise Refused(f"error: shipmill roles --flags for {repo} printed {text[:200]!r}, not --role NAME=FILLER flags")
    return [value for _, value in pairs]


def role_flags(roles: Sequence[str]) -> list[str]:
    """Each role's value as its own --role, as the watch passes them"""
    return [item for value in roles for item in ("--role", value)]


def triage_command(e: Entry, bot_login: str | None, roles: Sequence[str] = (), home: str | None = None) -> list[str]:
    """triage_state.py for one repo's person's items and unowned upstream reports, with the
    watch's trust (D-16), the clone's roles (spec 036), and the --home the watch passes (spec
    038): with one, the coordinator routes the reports (#1487)"""
    cmd = [sys.executable, str(WS.TRIAGE_STATE), e.repo, "--json", "--trusted-only"]
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    return cmd + role_flags(roles) + (["--home", home] if home is not None else [])


def clone_home(checkout: Path, repo: str) -> str | None:
    """The --home of the clone's triage, read with watch_state.py's reader: its [product] home
    in a component, the repo itself in the home repo (#1487); None without a config"""
    policy = WS.policy_file(checkout)
    if policy is None:
        return None
    home: str | None = WS.triage_home((checkout / policy).read_text(encoding="utf-8"), policy, repo)
    return home


def intake_command(e: Entry, bot_login: str | None, plans: bool, roles: Sequence[str] = ()) -> list[str]:
    """intake_state.py for one repo's opportunities, and with plans its plans, run in the
    clone, where it reads the config and the direction; the --bot-login's triage comments and
    revisions count. plans only when the clone has docs/product.md, as the watch runs it:
    --plans fails without a direction. With plans the clone's roles go as --role flags, so a
    plan answer the --bot-login relays for the maintainer counts (D-68); without, none, which
    intake_state.py would refuse"""
    cmd = [sys.executable, str(WS.INTAKE_STATE), e.repo, *(["--plans"] if plans else []), "--json"]
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    return cmd + (role_flags(roles) if plans else [])


def json_lines(text: str, what: str) -> list[dict[str, Any]]:
    """A script's --json lines, each an object; Refused when one isn't"""
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        row = decoded(line, what)
        if not isinstance(row, dict):
            raise Refused(f"error: {what} printed {line[:200]!r}, not a JSON object")
        found.append(row)
    return found


def number_of(line: dict[str, Any], what: str) -> int:
    number = line.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise Refused(f"error: {what} printed {line!r} without an item's number")
    return number


def person_items(text: str, repo: str, login: str) -> dict[int, dt.datetime]:
    """triage_state.py --json's WITH_PERSON items whose assignees include the reader, each
    with the time its note gives (S-069-2); one assigned only to others or to a team is none"""
    what = f"triage_state.py for {repo}"
    found: dict[int, dt.datetime] = {}
    for line in json_lines(text, what):
        if line.get("state") != "WITH_PERSON":
            continue
        people = line.get("assignees")
        if not isinstance(people, list) or not all(isinstance(p, str) for p in people):
            raise Refused(f"error: {what} printed a WITH_PERSON line without its assignees: {line!r}")
        if not any(WS.TRIAGE.same_login(p, login) for p in people):
            continue
        since = WITH_PERSON_SINCE.search(str(line.get("note") or ""))
        if since is None:
            raise Refused(f"error: {what} printed a WITH_PERSON line without its since: {line!r}")
        found[number_of(line, what)] = WS.TRIAGE.timestamp(since.group(1))
    return found


def upstream_items(text: str, repo: str) -> list[int]:
    """triage_state.py --json's UPSTREAM_UNOWNED reports: nobody linked or took them (#1487)"""
    what = f"triage_state.py for {repo}"
    return [number_of(line, what) for line in json_lines(text, what) if line.get("state") == "UPSTREAM_UNOWNED"]


def intake_items(text: str, repo: str) -> dict[int, str]:
    """intake_state.py --plans --json's opportunities and plan issues the queue lists, each
    with its kind (S-069-3): OPPORTUNITY_OPEN, PLAN_OPEN, and NO_REASON; any other state is none"""
    what = f"intake_state.py for {repo}"
    found: dict[int, str] = {}
    for line in json_lines(text, what):
        kind = INTAKE_KINDS.get((str(line.get("kind")), str(line.get("state"))))
        if kind is not None:
            found[number_of(line, what)] = kind
    return found


def plan_holds_met(text: str, repo: str) -> dict[int, dt.datetime]:
    """intake_state.py --plans --json's PLAN_OPEN plans re-checked after their hold was met,
    each with the hold's met_at (spec 098): the PLAN row waits since the later of its newest
    revision and that; a PLAN_OPEN line with no hold, or a hold not met, is none"""
    what = f"intake_state.py for {repo}"
    found: dict[int, dt.datetime] = {}
    for line in json_lines(text, what):
        if INTAKE_KINDS.get((str(line.get("kind")), str(line.get("state")))) != PLAN or "hold" not in line:
            continue
        hold = line["hold"]
        if not isinstance(hold, dict) or not isinstance(hold.get("until"), str) or "met_at" not in hold:
            raise Refused(f"error: {what} printed a plan whose hold has no until and met_at: {line!r}")
        met_at = hold["met_at"]
        if met_at is None:
            continue
        if not isinstance(met_at, str):
            raise Refused(f"error: {what} printed a plan whose hold's met_at is no time: {line!r}")
        found[number_of(line, what)] = WS.TRIAGE.timestamp(met_at)
    return found


def wanted(rows: list[Row]) -> dict[int, str]:
    """The watch rows' items the queue lists, each number with its kind; an item in QUESTION
    is in no other kind (S-069-6)"""
    kinds: dict[int, str] = {}
    for row in rows:
        if row.state == "PROMOTION_DUE" and (found := PROPOSAL_DETAIL.match(row.detail)) is not None:
            kinds.setdefault(int(found.group(1)), PROMOTION)
        elif row.state == "PRS_PARKED" and (part := TO_MERGE_PART.search(row.detail)) is not None:
            for n in NUMBERS.findall(part.group(1)):
                kinds.setdefault(int(n), TO_MERGE)
    for row in rows:
        if row.state == "NEEDS_DECISION":
            for n in NUMBERS.findall(row.detail):
                kinds[int(n)] = QUESTION
    return kinds


def items_query(numbers: Sequence[int]) -> str:
    """One GraphQL read of the items by number, an alias each (issue or pull request alike)"""
    aliases = "\n".join(f"i{n}: issueOrPullRequest(number: {n}) {{ __typename ...I ...P }}" for n in numbers)
    return (
        "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {\n"
        f"{aliases}\n}} }}\nfragment I on Issue {{ {FIELDS} }}\nfragment P on PullRequest {{ {FIELDS} }}"
    )


def items_command(repo: str, numbers: Sequence[int]) -> list[str]:
    owner, name = repo.split("/", 1)
    query = items_query(numbers)
    return ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]


def nodes(found: object, key: str, where: str) -> list[dict[str, Any]]:
    """A connection's nodes, checked"""
    if not isinstance(found, dict) or not isinstance(found.get(key), dict):
        raise Refused(f"error: {where}: no {key}")
    listed = found[key].get("nodes")
    if not isinstance(listed, list) or not all(isinstance(n, dict) for n in listed):
        raise Refused(f"error: {where}: {key} has no nodes")
    return listed


def trusted_item(node: dict[str, Any], bot_login: str | None) -> bool:
    """The watch's trust (D-16, D-30): an item an OWNER, MEMBER, or COLLABORATOR opened, or the
    --bot-login, or the release workflow's own upgrade issue; nobody else's is on the queue"""
    author = WS.TRIAGE.login(node["author"])
    if WS.TRIAGE.trusted(author, str(node["authorAssociation"]), bot_login):
        return True
    return node["__typename"] == "Issue" and bool(WS.TRIAGE.workflow_upgrade(node))


def labelled_since(node: dict[str, Any], label: str, where: str) -> dt.datetime | None:
    """The newest event adding label, or None"""
    times = [
        WS.TRIAGE.timestamp(str(event["createdAt"]))
        for event in nodes(node, "timelineItems", where)
        if isinstance(event.get("label"), dict) and event["label"].get("name") == label
    ]
    return max(times) if times else None


def asked_since(comments: list[dict[str, Any]], bot_login: str | None) -> dt.datetime | None:
    """The newest needs-decision marker comment by a trusted author (an outsider's never counts)"""
    times = [
        WS.TRIAGE.timestamp(str(c["createdAt"]))
        for c in comments
        if WS.TRIAGE.marked(str(c["body"] or ""))
        and WS.TRIAGE.trusted(WS.TRIAGE.login(c.get("author")), str(c.get("authorAssociation") or "NONE"), bot_login)
    ]
    return max(times) if times else None


def revised_since(comments: list[dict[str, Any]], bot_login: str | None, opened: dt.datetime) -> dt.datetime:
    """A plan's newest revision, as intake_state.py's plan_answer reads it: the newest
    plan-revised comment by the --bot-login whose rev is higher than the one before it, else
    its opening; anyone else's revises nothing"""
    since, rev = opened, 0
    for c in sorted(comments, key=lambda c: WS.TRIAGE.timestamp(str(c["createdAt"]))):
        revised = REVISED.match(WS.TRIAGE.first_line(str(c["body"] or "")))
        at = WS.TRIAGE.timestamp(str(c["createdAt"]))
        by_bot = bot_login is not None and WS.TRIAGE.same_login(WS.TRIAGE.login(c.get("author")), bot_login)
        if revised is not None and by_bot and int(revised.group(1)) > rev and at >= since:
            since, rev = at, int(revised.group(1))
    return since


def queue_item(
    repo: str, kind: str, node: dict[str, Any], bot_login: str | None, given: dt.datetime | None = None
) -> Item | None:
    """The row for one item as GitHub has it now, or None: closed (open, for NO_REASON),
    untrusted (S-069-9), its label gone, or its question answered since the watch read it
    (S-069-1). given is the time a state script already gave it: YOUR_ITEM's hand-off, or a
    PLAN's met hold (spec 098), which it waits since when later than its newest revision"""
    where = f"gh api graphql for {repo}#{node.get('number')}"
    missing = [k for k in ITEM_KEYS if k not in node]
    if missing or node.get("__typename") not in ("Issue", "PullRequest"):
        raise Refused(f"error: {where}: not an issue or pull request with {missing or ITEM_KEYS}")
    labels = {str(label["name"]) for label in nodes(node, "labels", where)}
    if node["state"] != ("CLOSED" if kind == NO_REASON else "OPEN") or not trusted_item(node, bot_login):
        return None
    opened = WS.TRIAGE.timestamp(str(node["createdAt"]))
    if kind == NO_REASON:
        if not node.get("closedAt"):
            raise Refused(f"error: {where}: closed with no closedAt")
        since = WS.TRIAGE.timestamp(str(node["closedAt"]))
    elif kind == PLAN:
        revised = revised_since(nodes(node, "comments", where), bot_login, opened)
        since = revised if given is None else max(revised, given)
    elif kind == YOUR_ITEM:
        since = given or opened
    elif kind == QUESTION:
        comments = nodes(node, "comments", where)
        thread = [
            (WS.TRIAGE.login(c.get("author")), str(c.get("authorAssociation") or "NONE"), str(c["body"] or ""))
            for c in comments
        ]
        if WS.TRIAGE.DECISION_LABEL not in labels or not WS.TRIAGE.waits_on_decision(thread, bot_login):
            return None
        since = asked_since(comments, bot_login) or labelled_since(node, WS.TRIAGE.DECISION_LABEL, where) or opened
    elif kind == TO_MERGE:
        if WS.READY_LABEL not in labels:
            return None
        since = labelled_since(node, WS.READY_LABEL, where) or opened
    elif kind == UPSTREAM:
        if WS.TRIAGE.UPSTREAM_LABEL not in labels:
            return None
        since = labelled_since(node, WS.TRIAGE.UPSTREAM_LABEL, where) or opened
    else:
        since = opened
    return Item(repo, kind, int(node["number"]), str(node["url"]), str(node["title"]), since)


def read_items(
    repo: str,
    kinds: dict[int, str],
    runner: Runner,
    bot_login: str | None,
    given: dict[int, dt.datetime] | None = None,
) -> list[Item] | RepoError:
    """The queue's rows of one repo, from batched GraphQL reads, or the read's REPO_ERROR;
    given holds the times a state script already gave (YOUR_ITEM's, and a PLAN's met hold)"""
    given = given or {}
    found: list[Item] = []
    numbers = sorted(kinds)
    for start in range(0, len(numbers), CHUNK):
        chunk = numbers[start : start + CHUNK]
        proc = runner(items_command(repo, chunk))
        if proc.returncode != 0:
            return RepoError(repo, "gh api graphql", first_line(proc, "gh api graphql"))
        data = decoded(proc.stdout, f"gh api graphql for {repo}")
        inner = data.get("data") if isinstance(data, dict) else None
        repository = inner.get("repository") if isinstance(inner, dict) else None
        if not isinstance(repository, dict):
            raise Refused(f"error: gh api graphql for {repo} printed no repository")
        for n in chunk:
            node = repository.get(f"i{n}")
            if not isinstance(node, dict):
                return RepoError(repo, "gh api graphql", f"#{n} is no issue or pull request")
            item = queue_item(repo, kinds[n], node, bot_login, given.get(n))
            if item is not None:
                found.append(item)
    return found


# -- SPEC_TO_MERGE (S-069-4): an open spec pull request nothing lands by itself -------------------

PULLS_PAGE = 25  # open pull requests per GraphQL read, each with its newest 100 comments and 100 files
PULL_FIELDS = """__typename number title url state isDraft createdAt body authorAssociation author { __typename login }
files(first: 100) { pageInfo { hasNextPage } nodes { path } }
comments(last: 100) { pageInfo { hasPreviousPage }
nodes { author { __typename login } authorAssociation body createdAt } }
timelineItems(itemTypes: [READY_FOR_REVIEW_EVENT], last: 1) { nodes { ... on ReadyForReviewEvent { createdAt } } }"""
PULLS_QUERY = (
    "query($owner: String!, $name: String!, $cursor: String) { repository(owner: $owner, name: $name) {\n"
    f"pullRequests(states: OPEN, first: {PULLS_PAGE}, after: $cursor) {{ pageInfo {{ hasNextPage endCursor }}\n"
    f"nodes {{ {PULL_FIELDS} }} }} }} }}"
)


def pulls_command(repo: str, cursor: str | None) -> list[str]:
    """One page of the repo's open pull requests, read only"""
    owner, name = repo.split("/", 1)
    cmd = ["gh", "api", "graphql", "-f", f"query={PULLS_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}"]
    return cmd + (["-f", f"cursor={cursor}"] if cursor is not None else [])


def open_pulls(repo: str, runner: Runner) -> list[dict[str, Any]] | RepoError:
    """Every open pull request of the repo, a page at a time, or the read's REPO_ERROR"""
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        proc = runner(pulls_command(repo, cursor))
        if proc.returncode != 0:
            return RepoError(repo, "gh api graphql", first_line(proc, "gh api graphql"))
        data = decoded(proc.stdout, f"gh api graphql for {repo}'s pull requests")
        inner = data.get("data") if isinstance(data, dict) else None
        repository = inner.get("repository") if isinstance(inner, dict) else None
        where = f"gh api graphql for {repo}'s pull requests"
        found += nodes(repository, "pullRequests", where)
        page = repository["pullRequests"].get("pageInfo") if isinstance(repository, dict) else None
        if not isinstance(page, dict) or not isinstance(page.get("hasNextPage"), bool):
            raise Refused(f"error: {where}: no pageInfo")
        if not page["hasNextPage"]:
            return found
        cursor = str(page["endCursor"])


def spec_pull(node: dict[str, Any]) -> bool:
    """A spec pull request: its body's first line is `Spec for #N`, read by pr_gate.py's spec_refs"""
    return bool(PG.spec_refs(PG.retro().first_line(str(node.get("body") or ""))))


def lands_itself(comments: list[dict[str, Any]], bot_login: str | None, maintainers: frozenset[str]) -> bool | None:
    """Whether the spec pull request's thread lands it without the maintainer (D-49, D-88), read
    by pr_gate.py's readers: the newest trusted answer to its newest needs-decision question
    takes the recommended option (pr_gate.py's whole_reply, retro.py's takes_recommended; a relay
    the --bot-login posts counts only naming a maintainer and in its grammar), or the
    --bot-login's newest decided comment names the zone accepted-spec. None while its newest
    question has no trusted answer: a question holds it"""
    rt = PG.retro()
    bots = frozenset({bot_login}) if bot_login else frozenset()
    asked = PG.newest_question(comments, bots)
    if asked is not None:
        later = comments[asked + 1 :]
        answer = rt.newest_answer_at(later, bots, maintainers)
        if answer is None:
            return None
        reply = later[answer[0]]
        relay = rt.parse_relay(str(reply["body"]))
        refused = PG.by_bots(reply, bots) and rt.relay_refusal(comments[asked]["body"], relay) is not None
        said = PG.whole_reply(reply, bots)
        if not refused and said is not None and rt.takes_recommended(comments[asked]["body"], said):
            return True
    if not bot_login:
        return False  # with no --bot-login, no decided comment counts (pr_gate.py's NO_BOT)
    decided = [
        PG.DECIDED_FIRST.fullmatch(rt.first_line(c["body"]))
        for c in comments
        if bot_login.lower() in rt.login_names(c.get("author"))
    ]
    zones = [found.group(1) for found in decided if found is not None]
    return bool(zones) and zones[-1] == PG.ACCEPTED_SPEC


def spec_item(repo: str, node: dict[str, Any], bot_login: str | None, maintainers: frozenset[str]) -> Item | None:
    """The SPEC_TO_MERGE row of one open pull request, or None (S-069-4): a draft, not a spec
    pull request, untrusted (S-069-9), a question holding it, or one that lands by itself, save
    one that edits docs/product.md or docs/product/, which only the maintainer merges (D-34).
    It has waited since its newest ready-for-review event, else its opening"""
    where = f"gh api graphql for {repo}#{node.get('number')}"
    missing = [k for k in (*ITEM_KEYS, "isDraft") if k != "labels" and k not in node]
    if missing or node.get("__typename") != "PullRequest":
        raise Refused(f"error: {where}: not a pull request with {missing or ITEM_KEYS}")
    if node["state"] != "OPEN" or node["isDraft"] or not spec_pull(node) or not trusted_item(node, bot_login):
        return None
    try:
        comments, _ = PG.comments_of(node, where)
    except PG.GateError as error:
        raise Refused(f"error: {error}") from None
    lands = lands_itself(comments, bot_login, maintainers)
    if lands is None:
        return None
    paths = [str(f.get("path")) for f in nodes(node, "files", where)]
    page = node["files"].get("pageInfo")
    # past the first 100 files a direction edit can't be ruled out, so the maintainer merges it
    cut_off = not isinstance(page, dict) or page.get("hasNextPage") is not False
    if lands and not cut_off and not PG.direction_edits(paths):
        return None
    ready = [
        WS.TRIAGE.timestamp(str(e["createdAt"])) for e in nodes(node, "timelineItems", where) if e.get("createdAt")
    ]
    since = max(ready) if ready else WS.TRIAGE.timestamp(str(node["createdAt"]))
    return Item(repo, SPEC_TO_MERGE, int(node["number"]), str(node["url"]), str(node["title"]), since)


def spec_items(
    repo: str, runner: Runner, bot_login: str | None, maintainers: frozenset[str], taken: Sequence[int]
) -> list[Item] | RepoError:
    """The repo's SPEC_TO_MERGE rows, save the items another row already holds (QUESTION's first)"""
    pulls = open_pulls(repo, runner)
    if isinstance(pulls, RepoError):
        return pulls
    found = [spec_item(repo, node, bot_login, maintainers) for node in pulls]
    return [i for i in found if i is not None and i.number not in taken]


def queue_repo(e: Entry, runner: Runner, workdir: Path, bot_login: str | None, login: str) -> list[Item] | RepoError:
    """One repo's rows: the watch, triage_state.py, and intake_state.py on a fresh clone name
    the items, GitHub times them; an item in QUESTION is in no other row (S-069-6). The clone's
    roles are read first, and a failed read is the repo's REPO_ERROR, never a queue without them"""
    checkout, cloned = clone(e, runner, workdir)
    if cloned.returncode != 0:
        return RepoError(e.repo, "gh repo clone", first_line(cloned, "gh repo clone"))
    return queue_clone(e, runner, checkout, bot_login, login)


def queue_clone(e: Entry, runner: Runner, checkout: Path, bot_login: str | None, login: str) -> list[Item] | RepoError:
    """queue_repo's read of the repo's clone: its roles, the trusted watch, the state scripts,
    and GitHub's items and spec pull requests"""
    read_roles = WS.pinned(roles_command(checkout), lambda cmd: runner(cmd, cwd=checkout))
    if read_roles.returncode != 0:
        return RepoError(e.repo, "shipmill roles --flags", first_line(read_roles, "shipmill roles --flags"))
    roles = role_values(read_roles.stdout, e.repo)
    watched = runner(queue_watch_command(e, checkout, bot_login))
    if watched.returncode not in (0, 1):
        return RepoError(e.repo, "watch_state.py", first_line(watched, "watch_state.py"))
    triaged = runner(triage_command(e, bot_login, roles, clone_home(checkout, e.repo)))
    if triaged.returncode not in (0, 1):
        return RepoError(e.repo, "triage_state.py", first_line(triaged, "triage_state.py"))
    intake = runner(intake_command(e, bot_login, (checkout / WS.DIRECTION).is_file(), roles), cwd=checkout)
    if intake.returncode not in (0, 1):
        return RepoError(e.repo, "intake_state.py", first_line(intake, "intake_state.py"))
    kinds = wanted(watch_rows(e.repo, watched.stdout))
    mine = person_items(triaged.stdout, e.repo, login)
    unowned = [(n, UPSTREAM) for n in upstream_items(triaged.stdout, e.repo)]
    for n, kind in [*((n, YOUR_ITEM) for n in mine), *intake_items(intake.stdout, e.repo).items(), *unowned]:
        kinds.setdefault(n, kind)
    given = {**plan_holds_met(intake.stdout, e.repo), **mine}  # a number in both is YOUR_ITEM, as kinds has it
    found = read_items(e.repo, kinds, runner, bot_login, given) if kinds else []
    if isinstance(found, RepoError):
        return found
    listed = [i.number for i in found]  # a spec pull request another row lists, QUESTION's first, is in that row only
    specs = spec_items(e.repo, runner, bot_login, PG.retro().maintainer_logins(roles), listed)
    return specs if isinstance(specs, RepoError) else found + specs


def reader(given: str | None, runner: Runner) -> str:
    """The reader: --login, else the authenticated gh user's login"""
    if given is None:
        proc = runner(["gh", "api", "user", "--jq", ".login"])
        if proc.returncode != 0:
            raise Refused(f"error: gh api user: {first_line(proc, 'gh api user')}")
        given = proc.stdout.strip()
    if not WS.LOGIN.match(given):
        raise Refused(f"error: {given!r} is not a GitHub login")
    return given


def waited_text(minutes: int) -> str:
    """How long a row has waited: 3d 4h, 5h, or 12m"""
    days, rest = divmod(minutes, 24 * 60)
    if days:
        return f"{days}d {rest // 60}h"
    return f"{rest // 60}h" if rest >= 60 else f"{rest}m"


def queue_lines(items: list[Item], errors: list[RepoError], now: dt.datetime) -> list[str]:
    """One line per row, oldest first, then one REPO_ERROR line per repo whose read failed"""
    width = max([len(i.repo) for i in items] + [len(e.repo) for e in errors], default=0)
    lines = [
        f"{i.repo:<{width}} {i.kind:<{KIND_WIDTH}} {'#' + str(i.number):<6} {ASKED[i.kind]}: {i.title}"
        f"{'' if i.holds is None else f' holds {i.holds}'} ({waited_text(i.waited(now))})"
        for i in items
    ]
    if not items:
        lines.append("nothing waits on the maintainer")
    return lines + [f"{e.repo:<{width}} REPO_ERROR {e.step}: {e.error}" for e in errors]


def gathered(found: Sequence[list[Item] | RepoError]) -> tuple[list[Item], list[RepoError]]:
    """The repos' reads, in the fleet file's order, as the queue's rows oldest first (a tie to
    the fleet file's order, then the number) and the failed repos' errors"""
    items: list[tuple[int, Item]] = []
    errors: list[RepoError] = []
    for index, read in enumerate(found):
        if isinstance(read, RepoError):
            errors.append(read)
        else:
            items += [(index, i) for i in read]
    return [i for _, i in sorted(items, key=lambda x: (x[1].since, x[0], x[1].number))], errors


def queue_json(login: str, items: list[Item], errors: list[RepoError], now: dt.datetime) -> dict[str, Any]:
    return {"login": login, "items": [i.json(now) for i in items], "errors": [e.json() for e in errors]}


def queue_code(items: list[Item], errors: list[RepoError]) -> int:
    if errors:
        return 2
    return 1 if items else 0


# -- --order impact (spec 086): the queue by what each item holds back ------------------------

AGE = "age"
IMPACT = "impact"
IMPACT_ERROR = "IMPACT_ERROR"


def impact_command(entries: Sequence[Entry], bot_login: str | None) -> list[str]:
    """One chains.py impact over every open issue of every fleet repo, so an item's count takes
    in its waiters across the fleet; with the watch's trust (--trusted-only and the --bot-login,
    D-16), so an outsider's Depends on line adds nothing"""
    cmd = [sys.executable, str(WS.CHAINS), "impact", "--json", "--trusted-only"]
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    return cmd + [arg for e in entries for arg in ("--repo", e.repo)]


def impact_counts(text: str) -> dict[tuple[str, int], int]:
    """chains.py impact --json's rows, each item (its repo in lower case, its number) with its
    held; ValueError naming what it printed when that isn't {"rows": [...]} of such rows"""
    try:
        found = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"chains.py impact printed {text[:200]!r}, not JSON") from None
    if not isinstance(found, dict) or not isinstance(found.get("rows"), list):
        raise ValueError(f'chains.py impact printed {text[:200]!r}, not {{"rows": [...]}}')
    counts: dict[tuple[str, int], int] = {}
    for row in found["rows"]:
        ref = WS.CHAIN_REF.match(str(row.get("ref"))) if isinstance(row, dict) else None
        held = row.get("held") if isinstance(row, dict) else None
        if ref is None or not isinstance(held, int) or isinstance(held, bool) or held < 1:
            raise ValueError(f"chains.py impact printed {json.dumps(row)[:200]}, not a row with its ref and held")
        counts[ref["repo"].lower(), int(str(row["ref"]).rsplit("#", 1)[1])] = held
    return counts


def by_impact(items: list[Item], counts: dict[tuple[str, int], int]) -> list[Item]:
    """The rows, each with its holds (0 for an item the walk lists no row for), most first;
    a tie keeps the order they came in (oldest first)"""
    held = [replace(i, holds=counts.get((i.repo.lower(), i.number), 0)) for i in items]
    return sorted(held, key=lambda i: -(i.holds or 0))


def impacted(items: list[Item], entries: Sequence[Entry], runner: Runner, bot_login: str | None) -> list[Item] | str:
    """The rows by impact, or the failed walk's first line, which keeps them oldest first"""
    proc = runner(impact_command(entries, bot_login))
    if proc.returncode != 0:
        return first_line(proc, "chains.py impact")
    try:
        return by_impact(items, impact_counts(proc.stdout))
    except ValueError as malformed:
        return str(malformed)


def queue(args: argparse.Namespace, runner: Runner, clock: Callable[[], dt.datetime]) -> int:
    """fleet.py queue: every repo's rows in one list, oldest first, or with --order impact by
    what each holds back; reads only"""
    entries = load(args.fleet)
    login = reader(args.login, runner)
    with tempfile.TemporaryDirectory(prefix="fleet-") as workdir:
        ordered, errors = gathered([queue_repo(e, runner, Path(workdir), args.bot_login, login) for e in entries])
    failed: str | None = None
    if args.order == IMPACT:
        found = impacted(ordered, entries, runner, args.bot_login)
        ordered, failed = (ordered, found) if isinstance(found, str) else (found, None)
    now = clock()
    if args.json:
        shown = queue_json(login, ordered, errors, now)
        if args.order == IMPACT:
            shown = {**shown, "order": AGE if failed is not None else IMPACT}
            shown = shown if failed is None else {**shown, "impact_error": failed}
        print(json.dumps(shown, indent=2, sort_keys=True))
    else:
        lines = queue_lines(ordered, errors, now)
        print("\n".join(lines + ([f"{IMPACT_ERROR} chains.py impact: {failed}"] if failed is not None else [])))
    return 2 if failed is not None else queue_code(ordered, errors)


# -- the overview (#1479): the report and the queue in one pass, one clone per repo -------------

JOBS = 4  # repos read at once by default


T = TypeVar("T")
R = TypeVar("R")


def in_order(read: Callable[[T], R], entries: Sequence[T], jobs: int) -> list[R]:  # noqa: UP047 (3.10)
    """read of each entry, at most jobs at once, the results in the entries' order; a read that
    raises (a Refused) raises here, once the reads already started have ended and the rest are dropped"""
    pool = ThreadPoolExecutor(max_workers=jobs)
    try:
        return list(pool.map(read, entries))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


@dataclass(frozen=True)
class RepoOverview:
    """One repo's report and queue, read from one clone"""

    report: RepoReport
    queue: list[Item] | RepoError


def overview_repo(e: Entry, runner: Runner, workdir: Path, bot_login: str | None, login: str) -> RepoOverview:
    """One clone, then the report's full watch and the queue's read on it. The queue's watch
    still runs on its own: --trusted-only and the --bot-login change how the watch reads an
    item (a fork's pull request, a question's thread), so its rows can't be filtered from the
    full watch's"""
    checkout, cloned = clone(e, runner, workdir)
    if cloned.returncode != 0:
        failed = RepoError(e.repo, "gh repo clone", first_line(cloned, "gh repo clone"))
        return RepoOverview(RepoReport(e.repo, (error_row("gh repo clone", cloned),), None), failed)
    return RepoOverview(check_clone(e, runner, checkout, None), queue_clone(e, runner, checkout, bot_login, login))


def overview(args: argparse.Namespace, runner: Runner, clock: Callable[[], dt.datetime]) -> int:
    """fleet.py overview: report's rows and queue's items, each repo read once; reads only"""
    entries = load(args.fleet)
    login = reader(args.login, runner)
    with tempfile.TemporaryDirectory(prefix="fleet-") as workdir:
        found = in_order(lambda e: overview_repo(e, runner, Path(workdir), args.bot_login, login), entries, args.jobs)
    reports = [f.report for f in found]
    ordered, errors = gathered([f.queue for f in found])
    now = clock()
    if args.json:
        both = {"report": {"repos": [r.json(False) for r in reports]}, "queue": queue_json(login, ordered, errors, now)}
        print(json.dumps(both, indent=2, sort_keys=True))
    else:
        print("\n".join([*table(reports), "", *queue_lines(ordered, errors, now)]))
    return max(exit_code(reports), queue_code(ordered, errors))


def jobs(text: str) -> int:
    """--jobs: a positive number of repos read at once"""
    try:
        found = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if found < 1:
        raise argparse.ArgumentTypeError(f"{found} is not a positive number")
    return found


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    rep = commands.add_parser("report", help="every repo's watch rows in one table")
    rep.add_argument("--fleet", required=True, type=Path, help="the fleet file")
    rep.add_argument("--metrics", action="store_true", help="add each repo's metrics.py measures")
    rep.add_argument("--json", action="store_true", help="one JSON object instead of a table")
    que = commands.add_parser("queue", help="what waits on the maintainer across the fleet, oldest first")
    que.add_argument("--fleet", required=True, type=Path, help="the fleet file")
    que.add_argument("--login", help="the reader (default: the authenticated gh user)")
    que.add_argument("--bot-login", help="the gate's App, <slug>[bot], whose items are trusted (D-16)")
    que.add_argument(
        "--order",
        choices=(AGE, IMPACT),
        default=AGE,
        help="age: oldest first (default); impact: most open issues held first, then oldest (spec 086)",
    )
    que.add_argument("--json", action="store_true", help="one JSON object instead of a list")
    ove = commands.add_parser("overview", help="the report and the queue in one pass, each repo read once")
    ove.add_argument("--fleet", required=True, type=Path, help="the fleet file")
    ove.add_argument("--login", help="the reader (default: the authenticated gh user)")
    ove.add_argument("--bot-login", help="the gate's App, <slug>[bot], whose items are trusted (D-16)")
    ove.add_argument("--jobs", type=jobs, default=JOBS, help=f"repos read at once (default {JOBS})")
    ove.add_argument("--json", action="store_true", help="one JSON object instead of the two tables")
    return parser


def main(argv: Sequence[str] | None = None, runner: Runner = run, clock: Callable[[], dt.datetime] = utc_now) -> int:
    parser = arguments()
    args = parser.parse_args(argv)
    if args.command in ("queue", "overview"):
        if args.bot_login is not None and not WS.LOGIN.match(args.bot_login):
            parser.error("--bot-login must be a GitHub login, such as <slug>[bot]")
        return queue(args, runner, clock) if args.command == "queue" else overview(args, runner, clock)
    entries = load(args.fleet)
    until = clock().isoformat() if args.metrics else None
    with tempfile.TemporaryDirectory(prefix="fleet-") as workdir:
        reports = report(entries, runner, Path(workdir), until)
    if args.json:
        print(json.dumps({"repos": [r.json(args.metrics) for r in reports]}, indent=2, sort_keys=True))
    else:
        found = metrics_table(reports) if args.metrics else []
        print("\n".join(table(reports) + ([""] + found if found else [])))
    return exit_code(reports)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as refused:
        sys.stderr.write(f"{refused}\n")
        raise
