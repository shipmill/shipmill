#!/usr/bin/env python3
"""Report many repos' issue-to-release pipelines at once: ship-watch's states across a fleet.

Usage: fleet.py report --fleet FILE [--metrics] [--json]
       fleet.py queue --fleet FILE [--login LOGIN] [--bot-login LOGIN] [--json]

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
across all repos, then the report-only rows, each group in the fleet file's order.

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
runs with --no-host, --trusted-only, and the --bot-login (the gate's App, <slug>[bot]), and
names the items; one batched GraphQL read per repo (50 items each) reads them as GitHub has
them now:
  QUESTION    an open item in NEEDS_DECISION, still labelled needs-decision, whose question
              has no trusted reply; waiting since the newest needs-decision marker comment by
              a trusted author, else the label's newest event, else its opening
  TO_MERGE    an open pull request in PRS_PARKED's TO_MERGE part, still labelled
              shipmill-ready; since the label's newest event, else its opening
  PROMOTION   an open "Ready to promote" proposal issue in PROMOTION_DUE; since its opening
An item in QUESTION is in no other row. An item whose author is neither an OWNER, MEMBER, or
COLLABORATOR nor the --bot-login (save the release workflow's upgrade issue, D-30) is in none.
Each line: the repo, the kind, #N, what is asked (a fixed phrase, then the title), and how
long it has waited (3d 4h, 5h, 12m), oldest first across repos, a tie to the fleet file's
order, then the number. --login names the reader (default: `gh api user`'s login). --json
prints {"login", "items": [{"repo", "kind", "number", "url", "asked", "title", "since",
"waited_minutes"}], "errors": [{"repo", "step", "error"}]}. A repo whose clone, watch, or
GitHub read fails gets one REPO_ERROR line after the queue, naming the step and the error's
first line. Exit 0 on an empty queue, 1 with a row, 2 after printing everything when a repo's
read failed, and 2 on a malformed fleet file. Reads only.
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
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

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
    }
)
REPO_ERROR = "REPO_ERROR"
ROW_KEYS = {"state", "subject", "detail", "agent"}  # a watch_state.py --json line
FIX_KEY = "fix"  # and its fix (spec 011), a string or null, which this report doesn't print
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

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


@dataclass(frozen=True)
class Row:
    state: str
    subject: str
    detail: str

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
            or set(found) - {FIX_KEY} != ROW_KEYS
            or not isinstance(found["agent"], bool)
            or not isinstance(found.get(FIX_KEY), (str, type(None)))
        ):
            raise Refused(f"error: watch_state.py for {repo} printed {line!r}, not a row")
        rows.append(Row(str(found["state"]), str(found["subject"]), str(found["detail"])))
    return rows


def check(e: Entry, runner: Runner, workdir: Path, until: str | None) -> RepoReport:
    """One repo's watch rows (and metrics, given until), or its REPO_ERROR row"""
    checkout = workdir / e.repo
    checkout.parent.mkdir(parents=True, exist_ok=True)
    cloned = runner(clone_command(e, checkout))
    if cloned.returncode != 0:
        return RepoReport(e.repo, (error_row("gh repo clone", cloned),), None)
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
    return row.state in ACTION or row.state == REPO_ERROR


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
    return 1 if any(row.state in ACTION for r in reports for row in r.rows) else 0


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)  # noqa: UP017 (3.10 has no dt.UTC)


# -- the queue (spec 069): what waits on the maintainer, across the fleet ---------------------

QUESTION = "QUESTION"
TO_MERGE = "TO_MERGE"
PROMOTION = "PROMOTION"
# what each kind asks of the maintainer: the fixed phrase the row's title follows
ASKED = {
    QUESTION: "answer the needs-decision question",
    TO_MERGE: "merge the pull request",
    PROMOTION: "approve the promotion",
}
# the watch's rows the queue reads: NEEDS_DECISION's "#N ...", PRS_PARKED's "TO_MERGE #N ..."
# part, and PROMOTION_DUE's proposal part, whose detail starts "#N " (a deployment's never does)
NUMBERS = re.compile(r"#(\d+)")
TO_MERGE_PART = re.compile(r"(?:^|; )TO_MERGE ((?:#\d+ ?)+)")
PROPOSAL_DETAIL = re.compile(r"^#(\d+) ")
CHUNK = 50  # items per GraphQL read: one read per 50 items of a repo
FIELDS = """number title url state createdAt body authorAssociation author { __typename login }
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

    def waited(self, now: dt.datetime) -> int:
        return max(0, int((now - self.since).total_seconds() // 60))

    def json(self, now: dt.datetime) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "kind": self.kind,
            "number": self.number,
            "url": self.url,
            "asked": ASKED[self.kind],
            "title": self.title,
            "since": self.since.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017 (3.10)
            "waited_minutes": self.waited(now),
        }


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
    --bot-login, D-16), and none of this host's rows"""
    cmd = [*watch_command(e, checkout), "--no-host", "--trusted-only"]
    return cmd + (["--bot-login", bot_login] if bot_login is not None else [])


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


def queue_item(repo: str, kind: str, node: dict[str, Any], bot_login: str | None) -> Item | None:
    """The row for one item as GitHub has it now, or None: closed, untrusted (S-069-9), its label
    gone, or its question answered since the watch read it (S-069-1)"""
    where = f"gh api graphql for {repo}#{node.get('number')}"
    missing = [k for k in ITEM_KEYS if k not in node]
    if missing or node.get("__typename") not in ("Issue", "PullRequest"):
        raise Refused(f"error: {where}: not an issue or pull request with {missing or ITEM_KEYS}")
    labels = {str(label["name"]) for label in nodes(node, "labels", where)}
    if node["state"] != "OPEN" or not trusted_item(node, bot_login):
        return None
    opened = WS.TRIAGE.timestamp(str(node["createdAt"]))
    if kind == QUESTION:
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
    else:
        since = opened
    return Item(repo, kind, int(node["number"]), str(node["url"]), str(node["title"]), since)


def read_items(repo: str, kinds: dict[int, str], runner: Runner, bot_login: str | None) -> list[Item] | RepoError:
    """The queue's rows of one repo, from batched GraphQL reads, or the read's REPO_ERROR"""
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
            item = queue_item(repo, kinds[n], node, bot_login)
            if item is not None:
                found.append(item)
    return found


def queue_repo(e: Entry, runner: Runner, workdir: Path, bot_login: str | None) -> list[Item] | RepoError:
    """One repo's rows: the watch on a fresh clone names the items, GitHub times them"""
    checkout = workdir / e.repo
    checkout.parent.mkdir(parents=True, exist_ok=True)
    cloned = runner(clone_command(e, checkout))
    if cloned.returncode != 0:
        return RepoError(e.repo, "gh repo clone", first_line(cloned, "gh repo clone"))
    watched = runner(queue_watch_command(e, checkout, bot_login))
    if watched.returncode not in (0, 1):
        return RepoError(e.repo, "watch_state.py", first_line(watched, "watch_state.py"))
    kinds = wanted(watch_rows(e.repo, watched.stdout))
    return read_items(e.repo, kinds, runner, bot_login) if kinds else []


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
        f"{i.repo:<{width}} {i.kind:<10} {'#' + str(i.number):<6} {ASKED[i.kind]}: {i.title}"
        f" ({waited_text(i.waited(now))})"
        for i in items
    ]
    if not items:
        lines.append("nothing waits on the maintainer")
    return lines + [f"{e.repo:<{width}} REPO_ERROR {e.step}: {e.error}" for e in errors]


def queue(args: argparse.Namespace, runner: Runner, clock: Callable[[], dt.datetime]) -> int:
    """fleet.py queue: every repo's rows in one list, oldest first; reads only"""
    entries = load(args.fleet)
    login = reader(args.login, runner)
    items: list[tuple[int, Item]] = []
    errors: list[RepoError] = []
    with tempfile.TemporaryDirectory(prefix="fleet-") as workdir:
        for index, e in enumerate(entries):
            found = queue_repo(e, runner, Path(workdir), args.bot_login)
            if isinstance(found, RepoError):
                errors.append(found)
            else:
                items += [(index, i) for i in found]
    ordered = [i for _, i in sorted(items, key=lambda x: (x[1].since, x[0], x[1].number))]
    now = clock()
    if args.json:
        found_json = {"login": login, "items": [i.json(now) for i in ordered], "errors": [e.json() for e in errors]}
        print(json.dumps(found_json, indent=2, sort_keys=True))
    else:
        print("\n".join(queue_lines(ordered, errors, now)))
    if errors:
        return 2
    return 1 if ordered else 0


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
    que.add_argument("--json", action="store_true", help="one JSON object instead of a list")
    return parser


def main(argv: Sequence[str] | None = None, runner: Runner = run, clock: Callable[[], dt.datetime] = utc_now) -> int:
    parser = arguments()
    args = parser.parse_args(argv)
    if args.command == "queue":
        if args.bot_login is not None and not WS.LOGIN.match(args.bot_login):
            parser.error("--bot-login must be a GitHub login, such as <slug>[bot]")
        return queue(args, runner, clock)
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
