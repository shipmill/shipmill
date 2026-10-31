"""A gate tick's change check and its walk of the work tiers (spec 046, D-58).

The change check asks GitHub, in one GraphQL query and one read of each watched workflow's
newest runs, whether anything changed since the cursor of the last walk (cursor.json in the gate's state
directory). Only on a change does the tick read the state, and then tier by tier, in order,
stopping at the first item no session was handed within retry_hours (handed.json); the timed
sections it reads from the last sweep (sweep.json), which runs every [agents] sweep_hours.
"""

import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from shipmill.errors import ReleaseError
from shipmill.findings import ISSUES, PRS_OPEN, Finding, fingerprint

CURSOR = "cursor.json"  # the last walk's cursor and the change check's signature
SWEEP = "sweep.json"  # the last sweep's rows
HANDED = "handed.json"  # each handed item's fingerprint, its session, and when
KNOWN = "known.json"  # what the change check read, for watch_state.py --known
CURSOR_OVERLAP = dt.timedelta(minutes=5)  # an update GitHub indexed late is seen next tick
PAGE = 100  # the change check's page of open issues, pull requests, and incidents
RUNS = 10  # the newest runs of each watched workflow the change check reads
LANDED = 10  # the default branch's newest commits whose merged pull requests the change check reads (spec 048)
SEQUENTIAL = 2  # at most this many watched workflows are read one after the other
# #853: a person's item, as triage_state.py's HUMAN_LABEL and ROLE_PREFIX read it (spec 017, spec 036)
HUMAN_LABEL = "human"
ROLE_PREFIX = "role:"
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?")  # watch_state.py's LOGIN

# The tiers a walk reads in order, each its kinds in the order a walk takes them: the state,
# or ISSUES and its triage state. A kind no tier names is read in tier 6 (S-046-12)
TIERS: dict[int, tuple[str, ...]] = {
    1: ("INCIDENT_OPEN", "OPERATE_FAILED"),
    2: ("BOT_FAILED", "NOT_PUBLISHED", "WORK_BRANCH_STALE", "BOT_STALLED"),
    3: (PRS_OPEN,),
    4: ("VETOED", f"{ISSUES} DECIDED"),
    5: ("UPGRADE_PENDING", "UPSTREAM_DUE"),
    6: tuple(
        f"{ISSUES} {state}"
        for state in (
            "NEW",
            "UNBLOCKED",
            "NEEDS_PR",
            "SUSPECT_CLOSE",
            "VERIFY_CLOSED",
            "DONE_NOT_CLOSED",
            "OFF_MILESTONE",
            "VERIFY_DUE",
            "CHECK_FAILED",
            "ASSIGN_DUE",
            "HANDOFF_DUE",
            "NO_ASSIGNEE",
            "UNFILLED",
            "MALFORMED_DEPENDS",
            "CYCLE",
            "SPEC_REFUSED",
            "REVISIT",
        )
    ),
    7: ("DIRECTION_PENDING", "PLANS"),
    8: ("UNANNOUNCED",),
}
UNPLACED = 6  # the tier of a kind no tier names
READ = (1, 2, 3, 4, 6)  # the tiers a walk reads from GitHub; 5, 7, and 8 come from the sweep
SWEPT = frozenset({"BOT_STALLED", "UPGRADE_PENDING", "UPSTREAM_DUE", "DIRECTION_PENDING", "PLANS", "UNANNOUNCED"})
DECISION_LABEL = "needs-decision"  # github-issue-triage's needs-decision.md
WAITING_TIER = 4  # the tier whose read holds the items waiting on a decision

# the release workflow's caller, as watch_state.py's bot_workflow finds it, and an operate caller
RELEASE_CALLER = re.compile(r"shipmill|release-lanes|\./\.github/workflows/prepare\.yml")
OPERATE_USES = re.compile(
    r"^\s*(?:-\s*)?uses:\s*[\"']?(?:[\w.-]+/[\w.-]+/\.github/workflows/operate\.ya?ml@|\./\.github/workflows/operate\.ya?ml)",
    re.MULTILINE,
)
GOOD = frozenset({"success", "skipped", "neutral"})


def tier_of(finding: Finding) -> int:
    kind = finding.kind
    return next((n for n, kinds in TIERS.items() if kind in kinds), UNPLACED)


def order(findings: Iterable[Finding]) -> list[Finding]:
    """A walk's fixed order (S-046-12): the tier, the kind's place in it, then the subject"""

    def key(f: Finding) -> tuple[int, int, int, str, str]:
        kinds = TIERS.get(tier_of(f), ())
        place = kinds.index(f.kind) if f.kind in kinds else len(kinds)
        number = int(f.subject[1:]) if re.fullmatch(r"#\d+", f.subject) else 0  # #9 before #10
        return tier_of(f), place, number, f.subject, f.detail

    return sorted(findings, key=key)


AGEING = frozenset({"INCIDENT_OPEN"})  # a detail that names how long it has been open, so changes every tick


def item_key(item: Finding) -> str:
    """The fingerprint handed.json and gate.json keep for an item (S-046-13): its own, less a
    detail that only ages, so an incident open 2 h is the item that was open 1 h"""
    return fingerprint([replace(item, detail="") if item.state in AGEING else item])


def span(tiers: Sequence[int]) -> str:
    """The tiers a walk read, as the decision line names them: `1-3`, or `1`"""
    if not tiers:
        return "none"
    return str(tiers[0]) if len(tiers) == 1 else f"{tiers[0]}-{tiers[-1]}"


def moment(value: object, what: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{what} must be a timestamp string")
    found = dt.datetime.fromisoformat(value)
    if found.tzinfo is None:
        raise ValueError(f"{what} has no time zone")
    return found


def write(path: Path, data: object) -> None:
    """Written to a temporary file and moved into place, so a tick never leaves half a file"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def malformed(path: Path, exc: Exception) -> ReleaseError:
    """A state file the gate can't read; its fix, deleting it, goes in tick.json (spec 048)"""
    return ReleaseError(f"{path} is malformed ({exc}); delete it to start over", f"rm {path}")


# -- the records ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cursor:
    """cursor.json: the last walk's start less CURSOR_OVERLAP, and the change check's signature"""

    at: dt.datetime
    signature: str

    @classmethod
    def load(cls, path: Path) -> Cursor | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) != {"at", "signature"}:
                raise ValueError("expected exactly at and signature")
            if not isinstance(data["signature"], str) or not data["signature"]:
                raise ValueError("signature must be a non-empty string")
            return cls(moment(data["at"], "at"), data["signature"])
        except ValueError as exc:  # json.JSONDecodeError is one
            raise malformed(path, exc) from None

    def save(self, path: Path) -> None:
        write(path, {"at": self.at.isoformat(), "signature": self.signature})


@dataclass(frozen=True, slots=True)
class Swept:
    """sweep.json: when the last sweep started, its rows, and the release tag its UNANNOUNCED
    covers, which a new tag's own check moves (S-046-9)"""

    at: dt.datetime
    rows: tuple[Finding, ...]
    tag: str | None

    @classmethod
    def load(cls, path: Path) -> Swept | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) != {"at", "rows", "tag"}:
                raise ValueError("expected exactly at, rows, and tag")
            if data["tag"] is not None and not isinstance(data["tag"], str):
                raise ValueError("tag must be a string or null")
            if not isinstance(data["rows"], list):
                raise ValueError("rows must be a list")
            rows = tuple(row_of(r) for r in data["rows"])
            return cls(moment(data["at"], "at"), rows, data["tag"])
        except (KeyError, TypeError, ValueError) as exc:
            raise malformed(path, exc) from None

    def save(self, path: Path) -> None:
        write(path, {"at": self.at.isoformat(), "rows": [record_of(f) for f in self.rows], "tag": self.tag})

    def due(self, now: dt.datetime, hours: int) -> bool:
        return now - self.at >= dt.timedelta(hours=hours)


def record_of(f: Finding) -> dict[str, object]:
    return {"state": f.state, "subject": f.subject, "detail": f.detail, "agent": f.agent, "fix": f.fix}


def row_of(data: object) -> Finding:
    if not isinstance(data, dict) or set(data) != {"state", "subject", "detail", "agent", "fix"}:
        raise ValueError(f"a row needs exactly state, subject, detail, agent, and fix, got {data!r}")
    texts = [data[key] for key in ("state", "subject", "detail")]
    if not all(isinstance(t, str) for t in texts) or not isinstance(data["agent"], bool):
        raise ValueError(f"a row needs string state, subject, and detail, and a boolean agent: {data!r}")
    if data["fix"] is not None and not isinstance(data["fix"], str):
        raise ValueError(f"a row's fix must be a string or null: {data!r}")
    return Finding(data["state"], data["subject"], data["detail"], data["agent"], (), data["fix"])


@dataclass(frozen=True, slots=True)
class Hand:
    """One handed item in handed.json: the session it went to, and when"""

    session: str
    at: dt.datetime


@dataclass(frozen=True, slots=True)
class Handed:
    """handed.json: each item a session was handed, by its fingerprint (S-046-13)"""

    hands: Mapping[str, Hand] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Handed:
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            hands = {}
            for key, entry in data.items():
                if not isinstance(entry, dict) or set(entry) != {"session", "at"}:
                    raise ValueError(f"{key}: expected exactly session and at")
                if not isinstance(entry["session"], str) or not entry["session"]:
                    raise ValueError(f"{key}: session must be a non-empty string")
                hands[key] = Hand(entry["session"], moment(entry["at"], f"{key}.at"))
            return cls(hands)
        except ValueError as exc:
            raise malformed(path, exc) from None

    def save(self, path: Path) -> None:
        write(path, {k: {"session": h.session, "at": h.at.isoformat()} for k, h in sorted(self.hands.items())})

    def taken(self, item: Finding, now: dt.datetime, retry: dt.timedelta) -> Hand | None:
        """The hand of an item handed within retry with the same fingerprint, or None"""
        hand = self.hands.get(item_key(item))
        return hand if hand is not None and now - hand.at < retry else None

    def expired(self, now: dt.datetime, retry: dt.timedelta) -> bool:
        """An entry whose retry_hours ran out: a change on the gate's side (S-046-2)"""
        return any(now - h.at >= retry for h in self.hands.values())

    def kept(self, now: dt.datetime, retry: dt.timedelta) -> Handed:
        return Handed({k: h for k, h in self.hands.items() if now - h.at < retry})

    def without(self, session: str) -> Handed:
        """A dead session's handing doesn't count (S-046-15)"""
        return Handed({k: h for k, h in self.hands.items() if h.session != session})

    def handing(self, item: Finding, session: str, now: dt.datetime) -> Handed:
        return Handed({**self.hands, item_key(item): Hand(session, now)})


# -- the change check --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Landed:
    """A pull request merged into the default branch, and when"""

    number: int
    at: dt.datetime

    def record(self) -> dict[str, object]:
        return {"number": self.number, "at": self.at.isoformat()}


@dataclass(frozen=True, slots=True)
class Flight:
    """What the change check read of the work in flight (spec 048): the open non-draft pull
    requests whose head is in the repo, by their head's check rollup (waiting on CI, waiting to
    land, failing CI), and the newest merged among the default branch's last LANDED commits.
    with_person: the ones that are a person's item with an assignee, each with its assignees'
    logins (#853): they wait on that person, not on CI or a session"""

    ci: tuple[int, ...] = ()
    landing: tuple[int, ...] = ()
    failing: tuple[int, ...] = ()
    landed: Landed | None = None
    with_person: tuple[tuple[int, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class Changes:
    """What the change check found: the signature (everything but the updated items), the open
    issues and pull requests updated at or after the cursor, whether one of them is labelled
    needs-decision, the newest release's tag, and what watch_state.py --known reads. forced: a
    source that can't tell, so every tick is a change. flight: the work in flight, from the
    same query (spec 048); None from a source that reads no pull requests, as rows a test hands"""

    signature: str
    updated: tuple[int, ...] = ()
    asked: bool = False
    tag: str | None = None
    known: Mapping[str, object] = field(default_factory=dict)
    forced: bool = False
    flight: Flight | None = None


GraphQL = Callable[[str, Mapping[str, str]], dict[str, Any]]  # (query, variables) -> its data
RestRead = Callable[[str], Any]  # a gh api path -> its JSON


def watched(root: Path) -> tuple[str, ...]:
    """The workflows whose runs the change check reads, by file name: the release workflow, as
    watch_state.py's bot_workflow finds it, and each workflow that calls operate.yml"""
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return ()
    found = []
    caller = workflows / "release.yml"
    if caller.is_file() and RELEASE_CALLER.search(caller.read_text(encoding="utf-8")):
        found.append(caller.name)
    elif (workflows / "release-bot.yml").is_file():
        found.append("release-bot.yml")
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        if OPERATE_USES.search(path.read_text(encoding="utf-8")):
            found.append(path.name)
    return tuple(found)


LABELS = "labels(first: 50) { nodes { name } }"
ASSIGNEES = "assignees(first: 10) { nodes { login } }"  # GitHub allows 10 per item
CONNECTIONS = {
    "updated": (
        "issues(states: OPEN, first: {page}{after}, filterBy: {{since: $since}})",
        f"number {LABELS}",
    ),
    "pulls": (
        "pullRequests(states: OPEN, first: {page}{after}, orderBy: {{field: CREATED_AT, direction: DESC}})",
        f"number updatedAt isDraft isCrossRepository headRefOid {LABELS} {ASSIGNEES}"
        " commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }",
    ),
    "incidents": (
        "issues(states: OPEN, labels: [$label], first: {page}{after})",
        f"number title createdAt author {{ login }} {LABELS}"
        " closedByPullRequestsReferences(first: 20) { nodes { number } }",
    ),
}


def connection(name: str, after: str | None) -> str:
    head, nodes = CONNECTIONS[name]
    cursor = "" if after is None else f", after: {json.dumps(after)}"
    return (
        f"{name}: {head.format(page=PAGE, after=cursor)} {{ pageInfo {{ hasNextPage endCursor }} nodes {{ {nodes} }} }}"
    )


# the default branch's last LANDED commits, each with the pull request it came in by (spec 048)
HISTORY = (
    f"... on Commit {{ history(first: {LANDED}) {{ nodes {{ associatedPullRequests(first: 1)"
    " { nodes { number mergedAt } } } } }"
)


def change_query(names: Sequence[str], after: Mapping[str, str] | None = None, first: bool = True) -> str:
    """The change check's one query (S-046-3): the default branch with its last LANDED commits'
    merged pull requests (S-048-21), the newest release, and the connections; a later page asks
    only for the connections that have more"""
    pages = " ".join(connection(n, None if after is None else after.get(n)) for n in names)
    head = f"defaultBranchRef {{ name target {{ oid {HISTORY} }} }} latestRelease {{ tagName }} " if first else ""
    declared = ", ".join(f"${v}: {VARIABLES[v]}" for v in query_variables(names))
    return f"query({declared}) {{ repository(owner: $owner, name: $name) {{ {head}{pages} }} }}"


VARIABLES = {"owner": "String!", "name": "String!", "since": "DateTime!", "label": "String!"}


def query_variables(names: Sequence[str]) -> tuple[str, ...]:
    """The variables a query over these connections uses: GitHub refuses one declared and
    unused, so a later page with no updated issues or incidents declares neither"""
    used = {"since"} if "updated" in names else set()
    used |= {"label"} if "incidents" in names else set()
    return ("owner", "name", *(v for v in ("since", "label") if v in used))


def check(
    repo: str,
    since: dt.datetime | None,
    label: str,
    workflows: Sequence[str],
    graphql: GraphQL,
    rest: RestRead,
    now: dt.datetime,
) -> Changes:
    """The change check: one GraphQL query, paged only past PAGE open issues, pull requests, or
    incidents, and one read of each watched workflow's newest runs. Without a cursor, every item is new
    and none is read as updated: the tick walks anyway"""
    owner, _, name = repo.partition("/")
    stamp = (now if since is None else since).astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    variables = {"owner": owner, "name": name, "since": stamp, "label": label}
    names = tuple(CONNECTIONS)
    data = repository(graphql(change_query(names), variables), "the change check")
    nodes = {n: list(nodes_of(data, n)) for n in names}
    more = {n: data[n]["pageInfo"] for n in names}
    while pending := {n: str(p["endCursor"]) for n, p in more.items() if p["hasNextPage"]}:
        wanted = {k: variables[k] for k in query_variables(tuple(pending))}
        page = repository(graphql(change_query(tuple(pending), pending, first=False), wanted), "a page")
        for n in pending:
            nodes[n] += nodes_of(page, n)
        more = {n: page[n]["pageInfo"] for n in pending}
    return changes_of(data, nodes, watched_runs(repo, workflows, rest), since)


def watched_runs(repo: str, workflows: Sequence[str], rest: RestRead) -> list[dict[str, Any]]:
    """Each watched workflow's newest RUNS runs, one read of its own runs each (S-046-3), so a
    burst of other workflows' runs never hides them; more than two are read concurrently. A
    failed read, such as a workflow file GitHub doesn't know, fails the check"""

    def read(workflow: str) -> list[dict[str, Any]]:
        return workflow_runs(rest(f"repos/{repo}/actions/workflows/{workflow}/runs?per_page={RUNS}"), (workflow,))

    if len(workflows) <= SEQUENTIAL:
        answers = [read(w) for w in workflows]
    else:
        with ThreadPoolExecutor(max_workers=len(workflows)) as pool:
            answers = list(pool.map(read, workflows))
    return [run for answer in answers for run in answer]


def repository(answer: dict[str, Any], what: str) -> dict[str, Any]:
    found = answer.get("data", {}).get("repository") if isinstance(answer, dict) else None
    if not isinstance(found, dict):
        raise ReleaseError(f"gh api graphql printed no repository for {what}: {str(answer)[:300]}")
    return found


def nodes_of(data: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    found = data.get(name)
    if not isinstance(found, dict) or not isinstance(found.get("nodes"), list):
        raise ReleaseError(f"gh api graphql printed no {name} connection: {str(found)[:300]}")
    return list(found["nodes"])


def label_names(node: Mapping[str, Any]) -> list[str]:
    return sorted(str(label["name"]) for label in node["labels"]["nodes"])


def assignee_logins(node: Mapping[str, Any]) -> list[str]:
    found = node["assignees"]["nodes"]
    if not all(isinstance(a, dict) and isinstance(a.get("login"), str) and LOGIN.fullmatch(a["login"]) for a in found):
        raise ReleaseError(f"gh api graphql printed #{node['number']}'s assignees as something other than logins")
    return [str(a["login"]) for a in found]


def person_item(node: Mapping[str, Any]) -> bool:
    """#853: a pull request that is a person's item, as triage_state.py reads an issue: labelled
    human or role:<name>, compared case-insensitively"""
    return any(n.lower() == HUMAN_LABEL or n.lower().startswith(ROLE_PREFIX) for n in label_names(node))


def rollup(node: Mapping[str, Any]) -> str | None:
    commits = node["commits"]["nodes"]
    status = commits[0]["commit"]["statusCheckRollup"] if commits else None
    return None if status is None else str(status["state"])


def workflow_runs(answer: Any, workflows: Sequence[str]) -> list[dict[str, Any]]:
    """The newest runs of the watched workflows, as watch_state.py --known reads them"""
    if not isinstance(answer, dict) or not isinstance(answer.get("workflow_runs"), list):
        raise ReleaseError(f"gh api .../runs printed no workflow_runs: {str(answer)[:300]}")
    runs = []
    for run in answer["workflow_runs"]:
        workflow = Path(str(run["path"]).split("@", 1)[0]).name
        if workflow in workflows:
            runs.append(
                {
                    "workflow": workflow,
                    "id": int(run["id"]),
                    "status": str(run["status"]),
                    "conclusion": run["conclusion"],
                    "createdAt": str(run["created_at"]),
                    "url": str(run["html_url"]),
                }
            )
    return runs


def run_state(runs: Sequence[Mapping[str, Any]], workflow: str) -> list[object]:
    """What of a workflow's runs makes a change (S-046-2): the newest finished run that isn't
    cancelled, by its id when it failed. A run still going is none, and a success after a
    success is none, so a scheduled operate run every 10 minutes is quiet"""
    mine = sorted((r for r in runs if r["workflow"] == workflow), key=lambda r: r["id"], reverse=True)
    done = [r for r in mine if r["status"] == "completed" and r["conclusion"] != "cancelled"]
    if not done:
        return [workflow, None]
    newest = done[0]
    return [workflow, "ok" if newest["conclusion"] in GOOD else f"{newest['conclusion']} {newest['id']}"]


def changes_of(
    data: Mapping[str, Any],
    nodes: Mapping[str, list[dict[str, Any]]],
    runs: list[dict[str, Any]],
    since: dt.datetime | None,
) -> Changes:
    default = data["defaultBranchRef"]
    release = data["latestRelease"]
    tag = None if release is None else str(release["tagName"])
    pulls = sorted(nodes["pulls"], key=lambda p: int(p["number"]))
    incidents = sorted(nodes["incidents"], key=lambda i: int(i["number"]))
    workflows = sorted({str(r["workflow"]) for r in runs})
    signed = {
        "head": default["target"]["oid"],
        "tag": tag,
        "pulls": [
            [p["number"], p["headRefOid"], p["isDraft"], rollup(p), label_names(p), p["isCrossRepository"]]
            for p in pulls
        ],
        "incidents": [i["number"] for i in incidents],
        "runs": [run_state(runs, w) for w in workflows],
    }
    signature = hashlib.sha256(json.dumps(signed, sort_keys=True).encode()).hexdigest()[:16]
    updated = list(nodes["updated"])
    if since is not None:
        updated += [p for p in pulls if dt.datetime.fromisoformat(p["updatedAt"]) >= since]
    else:
        updated = []
    asked = any(DECISION_LABEL in label_names(n) for n in updated)
    known = {
        "default_branch": str(default["name"]),
        "held": False,  # the gate walks only without a hold (D-15)
        "prs": [
            {
                "number": p["number"],
                "isDraft": p["isDraft"],
                "isCrossRepository": p["isCrossRepository"],
                "labels": [{"name": n} for n in label_names(p)],
                "headRefOid": p["headRefOid"],
                "assignees": [{"login": login} for login in assignee_logins(p)],
            }
            for p in pulls
        ],
        "incidents": [
            {
                "number": i["number"],
                "title": i["title"],
                "createdAt": i["createdAt"],
                "author": (i["author"] or {}).get("login", "ghost"),
                "labels": label_names(i),
                "closing_prs": [c["number"] for c in i["closedByPullRequestsReferences"]["nodes"]],
            }
            for i in incidents
        ],
        "runs": [{k: r[k] for k in ("workflow", "status", "conclusion", "createdAt", "url")} for r in runs],
    }
    numbers = tuple(sorted({int(n["number"]) for n in updated}))
    return Changes(signature, numbers, asked, tag, known, flight=flight_of(pulls, default))


WAITS_ON_CI = frozenset({None, "PENDING", "EXPECTED"})  # a head with no checks yet waits on them too
LANDS = frozenset({"SUCCESS"})
FAILS_CI = frozenset({"FAILURE", "ERROR"})


def flight_of(pulls: Sequence[Mapping[str, Any]], default: Mapping[str, Any]) -> Flight:
    """The work in flight, from what the change check read and nothing more (S-048-22, D-58):
    the open pull requests a session can land, by their head's rollup, a person's with whom it
    waits on (#853), and the last landed one.
    It is kept out of the signature: the commits move only with the default head, already in it"""
    ci: list[int] = []
    landing: list[int] = []
    failing: list[int] = []
    people: list[tuple[int, tuple[str, ...]]] = []
    for p in pulls:
        if p["isDraft"] or p["isCrossRepository"]:
            continue
        if person_item(p) and (logins := assignee_logins(p)):
            people.append((int(p["number"]), tuple(logins)))  # #853: it waits on them, as watch_state.py reads it
            continue
        state = rollup(p)
        if state in WAITS_ON_CI:
            ci.append(int(p["number"]))
        elif state in LANDS:
            landing.append(int(p["number"]))
        elif state in FAILS_CI:
            failing.append(int(p["number"]))
        else:
            raise ReleaseError(f"gh api graphql printed check rollup {state!r} for #{p['number']}")
    return Flight(tuple(ci), tuple(landing), tuple(failing), last_landed(default), tuple(people))


def last_landed(default: Mapping[str, Any]) -> Landed | None:
    """The newest mergedAt among the merged pull requests of the default branch's last LANDED
    commits (S-048-21); None when none of them came in by one"""
    history = default["target"].get("history")
    if not isinstance(history, dict) or not isinstance(history.get("nodes"), list):
        raise ReleaseError(f"gh api graphql printed no history for the default branch: {str(default)[:300]}")
    merged = []
    for commit in history["nodes"]:
        try:
            for pr in commit["associatedPullRequests"]["nodes"]:
                if pr["mergedAt"] is not None:
                    merged.append(Landed(int(pr["number"]), moment(pr["mergedAt"], "mergedAt")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ReleaseError(
                f"gh api graphql printed {str(commit)[:300]} for a commit of the default branch"
            ) from exc
    return max(merged, key=lambda found: found.at, default=None)


# -- the walk ----------------------------------------------------------------------------------


class Source(Protocol):
    """Where a walk reads the state: the change check, one tier, and the sweep"""

    def changes(self, since: dt.datetime | None) -> Changes: ...
    def tier(self, number: int, changes: Changes) -> list[Finding]: ...
    def sweep(self, changes: Changes) -> list[Finding]: ...


@dataclass(frozen=True, slots=True)
class Rows:
    """A source of rows read whole, as a test hands them: every tick is a change, a tier is its
    rows (with NEEDS_DECISION in the waiting tier), and the sweep the timed sections' rows"""

    rows: tuple[Finding, ...]

    def changes(self, since: dt.datetime | None) -> Changes:
        return Changes("rows", forced=True)

    def tier(self, number: int, changes: Changes) -> list[Finding]:
        found = [r for r in self.rows if r.state not in SWEPT and tier_of(r) == number]
        waiting = [r for r in self.rows if r.state == "NEEDS_DECISION"] if number == WAITING_TIER else []
        return found + waiting

    def sweep(self, changes: Changes) -> list[Finding]:
        return [r for r in self.rows if r.state in SWEPT]


@dataclass(frozen=True, slots=True)
class Walked:
    """What a walk found (S-046-4): the item it hands, with its tier, or the first item it
    found handed; the tiers it read in order, every row they printed, and the sweep record as
    the walk left it"""

    item: Finding | None
    tier: int | None
    taken: Finding | None
    hand: Hand | None
    tiers: tuple[int, ...]
    rows: tuple[Finding, ...]
    swept: Swept


def walk(
    source: Source,
    changes: Changes,
    swept: Swept,
    handed: Handed,
    now: dt.datetime,
    retry: dt.timedelta,
    lands: bool,
) -> Walked:
    """Read the tiers in order and stop at the first item not handed within retry: tiers 1, 3,
    4, and 6 from their own read, tier 2 from its read and the sweep's BOT_STALLED, 5 and 7
    from the sweep, and 8 from the sweep, after a new tag's own UNANNOUNCED check (S-046-9).
    An item is a row that needs an agent, or PRS_OPEN when land isn't observe"""
    read: list[int] = []
    rows: list[Finding] = []
    taken: tuple[Finding, Hand] | None = None
    for number in TIERS:
        found: list[Finding] = []
        own: list[Finding] = []  # this tier's own read, which may hold an earlier tier's kind
        if number in READ:
            own = source.tier(number, changes)
            found += own
        if number == 8 and changes.tag is not None and changes.tag != swept.tag:
            fresh = [r for r in source.tier(8, changes) if r.state == "UNANNOUNCED"]
            kept = [r for r in swept.rows if not (r.state == "UNANNOUNCED" and r.subject == changes.tag)]
            swept = Swept(swept.at, (*kept, *fresh), changes.tag)
        found += [r for r in swept.rows if tier_of(r) == number]
        read.append(number)
        rows += found
        # A tier's read may name an earlier tier's kind (tier 6's DECIDED, relayed with the label
        # off, which tier 4 never reads): it is taken here; the sweep's rows only in their own tier
        mine = [f for f in found if tier_of(f) == number or (f in own and tier_of(f) < number)]
        items = order(f for f in mine if f.agent or (lands and f.state == PRS_OPEN))
        for item in items:
            hand = handed.taken(item, now, retry)
            if hand is None:
                return Walked(item, number, None, None, tuple(read), tuple(rows), swept)
            taken = taken or (item, hand)
    first, hand = (None, None) if taken is None else taken
    return Walked(None, None, first, hand, tuple(read), tuple(rows), swept)
