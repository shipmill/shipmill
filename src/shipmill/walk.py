"""A gate tick's change check and its walk of the work tiers (spec 046, D-58).

The change check asks GitHub, in one GraphQL query and one read of each watched workflow's
newest runs, whether anything changed since the cursor of the last walk (cursor.json in the gate's state
directory). Only on a change does the tick read the state, and then tier by tier, in order,
stopping at the first item no session was handed within retry_hours (handed.json); the timed
sections it reads from the last sweep (sweep.json), which runs every [agents] sweep_hours.
"""

import datetime as dt
import enum
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
from shipmill.land_window import LandWindow
from shipmill.permission_notice import Notice
from shipmill.upgrades import Proposals

CURSOR = "cursor.json"  # the last walk's cursor and the change check's signature
SWEEP = "sweep.json"  # the last sweep's rows
HANDED = "handed.json"  # each handed item's fingerprint, its session, and when
KNOWN = "known.json"  # what the change check read, for watch_state.py --known
CURSOR_OVERLAP = dt.timedelta(minutes=5)  # an update GitHub indexed late is seen next tick
PAGE = 100  # issue_updates' subjects per aliased query (S-061-7)
# #1458: the change check's page of open issues, pull requests, and incidents; GitHub charges a
# query by its worst-case requests (its nested connections times their pages), so a page of 100
# cost 6 points a tick and a page of 20 costs 1
CHANGE_PAGE = 20
RUNS = 10  # the newest runs of each watched workflow the change check reads
LANDED = 10  # the default branch's newest commits whose merged pull requests the change check reads (spec 048)
SEQUENTIAL = 2  # at most this many watched workflows are read one after the other
# #853: a person's item, as triage_state.py's HUMAN_LABEL and ROLE_PREFIX read it (spec 017, spec 036)
HUMAN_LABEL = "human"
ROLE_PREFIX = "role:"
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?")  # watch_state.py's LOGIN
# #914: a pull request's author as GraphQL prints it, an Enterprise Managed User's login with its
# _shortcode too (octocat_acme); never a "/", so only a Bot's reads as app/<slug>
AUTHOR = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?")
# D-67 (#914): watch_state.py's row for the App's own draft with nothing open on it, a session's to resume
AGENT_DRAFT = "AGENT_DRAFT"
BASE_RED = "BASE_RED"  # spec 079: watch_state.py's row for a default branch base_red.py reads anything but GREEN
LAND_DUE = "LAND_DUE"  # spec 056: watch_state.py's head of the land window's queue, due to land
# land-stage items: a walk takes them only when land isn't observe
LANDING = frozenset({LAND_DUE, PRS_OPEN, AGENT_DRAFT})

# The tiers a walk reads in order, each its kinds in the order a walk takes them: the state,
# or ISSUES and its triage state. A kind no tier names is read in tier 6 (S-046-12)
TIERS: dict[int, tuple[str, ...]] = {
    1: ("INCIDENT_OPEN", "OPERATE_FAILED"),
    2: (BASE_RED, "BOT_FAILED", "NOT_PUBLISHED", "WORK_BRANCH_STALE", "BOT_STALLED"),  # BASE_RED first (spec 079)
    3: (LAND_DUE, PRS_OPEN, AGENT_DRAFT),
    4: ("VETOED", f"{ISSUES} DECIDED"),
    5: ("UPGRADE_PENDING", "UPSTREAM_DUE"),
    6: tuple(
        f"{ISSUES} {state}"
        for state in (
            "NEW",
            "UNBLOCKED",
            "SPEC_UNSPLIT",  # spec 053: watch_state.py's approved spec nobody split, triage's to split
            "NEEDS_PR",
            "SUSPECT_CLOSE",
            "VERIFY_CLOSED",
            "DONE_NOT_CLOSED",
            "OFF_MILESTONE",
            "VERIFY_DUE",
            "CHECK_FAILED",
            "STALE_HANDOFF",  # #1313: a person's item whose parent closed: close it or say why it waits
            "ASSIGN_DUE",
            "HANDOFF_DUE",
            "NO_ASSIGNEE",
            "UNFILLED",
            "MALFORMED_DEPENDS",
            "HOLD_UNLINKED",
            "CYCLE",
            "SPEC_REFUSED",
            "RELAY_REFUSED",  # #1302: a relay out of its grammar with the label off, triage asks again
            "REVISIT",
        )
    ),
    # spec 074: an accepted opportunity for the spec gate, then the requests handed to intake
    7: ("DIRECTION_PENDING", "PLANS", "SPEC_DUE", "FEEDBACK_DUE"),
}
UNPLACED = 6  # the tier of a kind no tier names
READ = (1, 2, 3, 4, 6)  # the tiers a walk reads from GitHub; 5 and 7 come from the sweep
# the timed sections; D-69 (#921) retired UNANNOUNCED, so a sweep.json row of it is never an item
SWEPT = frozenset(
    {"BOT_STALLED", "UPGRADE_PENDING", "UPSTREAM_DUE", "DIRECTION_PENDING", "PLANS", "SPEC_DUE", "FEEDBACK_DUE"}
)
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


EXPEDITED = frozenset({3, 6})  # spec 070: the tiers whose expedite rows come before the standard ones
WEIGHED = frozenset({4, 6})  # spec 086: the tiers whose rows go by their highest held first


def order(findings: Iterable[Finding]) -> list[Finding]:
    """A walk's fixed order (S-046-12): the tier, the kind's place in it, then the subject. In
    tiers 3 and 6 an expedite row comes before every standard row (S-070-4), and each group
    keeps that order; tiers 1 and 2 still come first. In tiers 4 and 6 a row whose issues hold
    more open issues comes first within its group (spec 086), a row without impact reading 0,
    so with no impact the order is S-046-12's"""

    def key(f: Finding) -> tuple[int, bool, int, int, int, str, str]:
        tier = tier_of(f)
        kinds = TIERS.get(tier, ())
        place = kinds.index(f.kind) if f.kind in kinds else len(kinds)
        number = int(f.subject[1:]) if re.fullmatch(r"#\d+", f.subject) else 0  # #9 before #10
        weight = -f.held if tier in WEIGHED else 0
        return tier, not (f.expedite and tier in EXPEDITED), weight, place, number, f.subject, f.detail

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
    """cursor.json: the last walk's start less CURSOR_OVERLAP, the change check's signature, and
    whether the last tier 2 read printed a BASE_RED row, so the default branch's last reading
    wasn't GREEN (spec 079); None when unknown, as in a file written before it, which a tick
    reads as not GREEN: one base_red.py read more, never one missed"""

    at: dt.datetime
    signature: str
    base_red: bool | None = None

    @classmethod
    def load(cls, path: Path) -> Cursor | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) - {"base_red"} != {"at", "signature"}:
                raise ValueError("expected exactly at and signature, and base_red or not")
            if not isinstance(data["signature"], str) or not data["signature"]:
                raise ValueError("signature must be a non-empty string")
            base_red = data.get("base_red")
            if base_red is not None and not isinstance(base_red, bool):
                raise ValueError("base_red must be true, false, or null")
            return cls(moment(data["at"], "at"), data["signature"], base_red)
        except ValueError as exc:  # json.JSONDecodeError is one
            raise malformed(path, exc) from None

    def save(self, path: Path) -> None:
        found: dict[str, object] = {"at": self.at.isoformat(), "signature": self.signature}
        write(path, found | ({} if self.base_red is None else {"base_red": self.base_red}))


@dataclass(frozen=True, slots=True)
class Swept:
    """sweep.json: when the last sweep started, its rows, the newest release tag the change
    check read then (kept for the file's form; D-69 retired the UNANNOUNCED it once covered),
    and what its config-upgrade proposal did (spec 047), None when it ran none, and its
    permission notice (spec 060), None when it ran none; a file written before spec 047 has no
    upgrades, one before spec 060 no permissions"""

    at: dt.datetime
    rows: tuple[Finding, ...]
    tag: str | None
    upgrades: Proposals | None = None
    permissions: Notice | None = None

    @classmethod
    def load(cls, path: Path) -> Swept | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) - {"upgrades", "permissions"} != {"at", "rows", "tag"}:
                raise ValueError("expected exactly at, rows, and tag, and upgrades and permissions or not")
            if data["tag"] is not None and not isinstance(data["tag"], str):
                raise ValueError("tag must be a string or null")
            if not isinstance(data["rows"], list):
                raise ValueError("rows must be a list")
            rows = tuple(row_of(r) for r in data["rows"])
            upgrades = Proposals.of(data["upgrades"]) if "upgrades" in data else None
            permissions = Notice.of(data["permissions"]) if "permissions" in data else None
            return cls(moment(data["at"], "at"), rows, data["tag"], upgrades, permissions)
        except (KeyError, TypeError, ValueError) as exc:
            raise malformed(path, exc) from None

    def save(self, path: Path) -> None:
        data: dict[str, object] = {
            "at": self.at.isoformat(),
            "rows": [record_of(f) for f in self.rows],
            "tag": self.tag,
        }
        if self.upgrades is not None:
            data["upgrades"] = self.upgrades.record()
        if self.permissions is not None:
            data["permissions"] = self.permissions.record()
        write(path, data)

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


# -- subjects (spec 061) ----------------------------------------------------------------------

SUBJECTED = frozenset({PRS_OPEN, AGENT_DRAFT, "VETOED"})  # with each ISSUES row of a triage state
NUMBER = re.compile(r"#(\d+)")
SUBJECT_KEY = re.compile(r"[A-Z][A-Z_]*(?: [A-Z][A-Z_]*)? #\d+")  # a subject's hand, `<kind> #<N>`


def subjects(item: Finding) -> tuple[int, ...] | None:
    """The issues and pull requests an item of tier 3, 4, or 6 names (spec 061): the `#N` of
    a PRS_OPEN, AGENT_DRAFT, or VETOED row's detail, or of an ISSUES row's after its triage
    state, digits the gate parsed (D-16). None for every other item, and for a detail with any
    other word in it (SPEC_UNSPLIT names a spec, not an issue): it is handed by its fingerprint"""
    if item.state == ISSUES and item.kind != ISSUES:
        words = item.detail.split(" ")[1:]
    elif item.state in SUBJECTED:
        words = item.detail.split(" ")
    else:
        return None
    found = [NUMBER.fullmatch(w) for w in words]
    if not words or not all(found):
        return None
    return tuple(dict.fromkeys(int(m.group(1)) for m in found if m is not None))


def subject_key(item: Finding, number: int) -> str:
    """A handed subject's key in handed.json: `ISSUES VERIFY_DUE #842`, `PRS_OPEN #12`"""
    return f"{item.kind} #{number}"


def cut(item: Finding, numbers: Sequence[int]) -> Finding:
    """The item cut to these of its subjects: its detail keeps only their `#N`, after an ISSUES
    row's triage state, a PRS_OPEN row only their heads, and its impact only theirs (spec 086)"""
    state = f"{item.detail.split(' ', 1)[0]} " if item.state == ISSUES else ""
    heads = tuple((n, sha) for n, sha in item.heads if n in numbers)
    impact = tuple((n, held) for n, held in item.impact if n in numbers)
    return replace(item, detail=state + " ".join(f"#{n}" for n in numbers), heads=heads, impact=impact)


@dataclass(frozen=True, slots=True)
class Head:
    """A pull request's head SHA and its check rollup state (None: no checks), as the change
    check read it"""

    sha: str
    rollup: str | None


@dataclass(frozen=True, slots=True)
class Pull:
    """An open pull request as the change check read it: its head, when GitHub last updated it,
    and whether it is labelled needs-decision (#1447), from the same query's labels"""

    head: Head
    updated: dt.datetime
    asked: bool = False


class End(enum.StrEnum):
    """How a handed session ended, read from its stream-json log once it is gone (spec 089,
    D-100): ok, its last `result` has is_error false; limit, a usage limit stopped it; auth, its
    credential was refused; error, anything else"""

    OK = "ok"
    LIMIT = "limit"
    AUTH = "auth"
    ERROR = "error"


# spec 089 (S-089-11): an item whose session ended error is handed again after these delays, one
# per error end in a row on it; the end after the last holds it for retry_hours, as DEAD_STREAK
BACKOFF = (dt.timedelta(minutes=15), dt.timedelta(hours=1), dt.timedelta(hours=4))


@dataclass(frozen=True, slots=True)
class Hand:
    """One hand in handed.json: the session it went to, and when; for a pull request subject
    the head it had then (spec 061); idle once a walk past retry_hours found nothing changed on
    its subject since; ended, how its session ended, None while it runs (spec 089); errors, the
    error ends in a row on its key, carried to the hand that replaces it, and until, when an
    error end's backoff hands it again, in place of retry_hours (S-089-11)"""

    session: str
    at: dt.datetime
    head: Head | None = None
    idle: bool = False
    ended: End | None = None
    errors: int = 0
    until: dt.datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.errors, bool) or not isinstance(self.errors, int) or self.errors < 0:
            raise ValueError(f"errors must be a count, got {self.errors!r}")
        if self.until is not None and (self.ended is not End.ERROR or self.errors < 1):
            raise ValueError("only a hand whose session ended error is held until a time")

    def record(self) -> dict[str, object]:
        found: dict[str, object] = {"session": self.session, "at": self.at.isoformat()}
        if self.head is not None:
            found |= {"head": self.head.sha, "rollup": self.head.rollup}
        found |= {"idle": True} if self.idle else {}
        found |= {} if self.ended is None else {"ended": self.ended.value}
        found |= {"errors": self.errors} if self.errors else {}
        return found | ({} if self.until is None else {"until": self.until.isoformat()})

    def within(self, now: dt.datetime, retry: dt.timedelta) -> bool:
        """The hand still holds its key: until its backoff's until, else retry_hours after at"""
        return now < self.retried(retry)

    def retried(self, retry: dt.timedelta) -> dt.datetime:
        """When its key is handed again: its backoff's until, else retry_hours after at"""
        return self.until if self.until is not None else self.at + retry

    def backed_off(self, died: dt.datetime, retry: dt.timedelta) -> Hand:
        """Its session ended error at died (S-089-11): one more in the run, held for the next
        delay of BACKOFF after the death, or for retry_hours once the run is past it"""
        errors = self.errors + 1
        delay = BACKOFF[errors - 1] if errors <= len(BACKOFF) else retry
        return replace(self, errors=errors, until=died + delay, idle=False)


HAND_KEYS = frozenset({"session", "at"})
HAND_EXTRA = frozenset({"idle", "ended", "errors", "until"})
PULL_KEYS = frozenset({"head", "rollup"})
ENDS = ", ".join(e.value for e in End)
CAUSED = frozenset({End.LIMIT, End.AUTH})  # ends that drop their hand, the wait the credential's pause (S-089-4)


def hand_of(key: str, entry: object) -> Hand:
    """One hand as handed.json holds it; one without ended, as written before spec 089 or
    while its session runs, loads with ended None (S-089-2)"""
    if not isinstance(entry, dict) or not HAND_KEYS <= set(entry) <= HAND_KEYS | PULL_KEYS | HAND_EXTRA:
        raise ValueError(
            f"{key}: expected session and at, head and rollup or neither, and idle, ended, errors, until or not"
        )
    if not isinstance(entry["session"], str) or not entry["session"]:
        raise ValueError(f"{key}: session must be a non-empty string")
    head = None
    if set(entry) & PULL_KEYS:
        sha, state = entry.get("head"), entry.get("rollup")
        if not set(entry) >= PULL_KEYS or not isinstance(sha, str) or not sha:
            raise ValueError(f"{key}: a pull request's hand needs a head SHA and its rollup")
        if state is not None and not isinstance(state, str):
            raise ValueError(f"{key}: rollup must be a string or null")
        head = Head(sha, state)
    idle = entry.get("idle", False)
    if not isinstance(idle, bool):
        raise ValueError(f"{key}: idle must be true or false")
    if idle and SUBJECT_KEY.fullmatch(key) is None:
        raise ValueError(f"{key}: only a subject's hand is idle")
    ended = None
    if "ended" in entry:
        if not isinstance(entry["ended"], str) or entry["ended"] not in End:
            raise ValueError(f"{key}: ended must be one of {ENDS}, got {entry['ended']!r}")
        ended = End(entry["ended"])
    errors = entry.get("errors", 0)
    if isinstance(errors, bool) or not isinstance(errors, int) or errors < 1 and "errors" in entry:
        raise ValueError(f"{key}: errors must be a positive count, got {errors!r}")
    until = moment(entry["until"], f"{key}.until") if "until" in entry else None
    if until is not None and (ended is not End.ERROR or errors < 1):
        raise ValueError(f"{key}: only a hand whose session ended error, with errors, has until")
    return Hand(entry["session"], moment(entry["at"], f"{key}.at"), head, idle, ended, errors, until)


@dataclass(frozen=True, slots=True)
class Handed:
    """handed.json, in the gate's state directory beside cursor.json (D-58, N-2): a JSON object
    of hands, each a key and an object.

    The key is an item's fingerprint (S-046-13) for an item of tier 1, 2, 5, or 7, or one with
    no subjects; for an item of tier 3, 4, or 6 it is one subject, `<kind> #<N>`, such as
    `ISSUES VERIFY_DUE #842` or `PRS_OPEN #12` (spec 061). The object holds `session` (the id of
    the session handed it) and `at` (when, an ISO 8601 time with its offset); a pull request
    subject's also `head` (its head SHA) and `rollup` (its head's check rollup state, or null
    with no checks) from the change check; `"idle": true` once a walk past retry_hours found
    its subject unchanged since `at` (absent otherwise); and `ended`, how its session ended (ok,
    limit, auth, or error), once a tick found the session gone (absent while it runs, spec 089).
    It is a cache of the gate's own launches: deleted, every subject reads not taken and is
    handed once more"""

    hands: Mapping[str, Hand] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Handed:
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            return cls({key: hand_of(key, entry) for key, entry in data.items()})
        except ValueError as exc:
            raise malformed(path, exc) from None

    def save(self, path: Path) -> None:
        write(path, {k: h.record() for k, h in sorted(self.hands.items())})

    def taken(self, item: Finding, now: dt.datetime, retry: dt.timedelta) -> Hand | None:
        """The hand of an item handed within retry with the same fingerprint, or None"""
        hand = self.hands.get(item_key(item))
        return hand if hand is not None and hand.within(now, retry) else None

    def expired(self, now: dt.datetime, retry: dt.timedelta) -> bool:
        """An entry whose retry_hours ran out: a change on the gate's side (S-046-2); an idle
        hand is none, as a change to its subject shows in the change check itself (spec 061)"""
        return any(not h.within(now, retry) and not h.idle for h in self.hands.values())

    def kept(self, now: dt.datetime, retry: dt.timedelta) -> Handed:
        """After a walk that read every tier and handed nothing: the hands within retry, and the
        idle ones, which stay past it (spec 061). A hand whose session ended error drops past its
        hold too: the walk met its key and didn't hand it, so it is no item's now (a pull request
        under observe), and kept, its expiry would make every tick walk (S-089-11)"""
        return Handed({k: h for k, h in self.hands.items() if h.within(now, retry) or h.idle})

    def stopped(self, now: dt.datetime, retry: dt.timedelta) -> Handed:
        """After a walk that stopped at an item: as kept, and every subject's hand, since the
        walk didn't meet the items after it to find them idle or changed"""
        return Handed(
            {
                k: h
                for k, h in self.hands.items()
                if h.within(now, retry) or SUBJECT_KEY.fullmatch(k) is not None or h.ended is End.ERROR
            }
        )

    def found(self, rows: Iterable[Finding]) -> Handed:
        """The hands of items a walk that read every tier still found (#926): one gone, as a
        pull request whose needs-decision question waits, loses its hand, so when it returns
        with the same fingerprint, the answer in, it is handed on the next tick; a subject the
        walk no longer finds, closed or out of its triage state, loses its own (spec 061)"""
        keys = set()
        for row in rows:
            keys.add(item_key(row))
            keys.update(subject_key(row, n) for n in subjects(row) or ())
        return Handed({k: h for k, h in self.hands.items() if k in keys})

    def without(self, session: str) -> Handed:
        """A dead session's handing doesn't count (S-046-15)"""
        return Handed({k: h for k, h in self.hands.items() if h.session != session})

    def unasked(self, session: str, pulls: Mapping[int, Pull]) -> Handed:
        """#1447: an ended session's hands of pull request subjects the change check reads
        labelled needs-decision and updated since the hand come off: it asked there, so the next
        walk meets the pull request as waiting, or, the answer already in, hands it at once
        instead of after retry_hours. Every other hand stays as it is (D-87): one whose pull
        request nobody wrote on since the hand (a labelled one the session left untouched would
        otherwise be handed after every session), an idle one, another session's, an issue
        subject's, and an item's fingerprint"""

        def asked(key: str, hand: Hand) -> bool:
            if hand.session != session or hand.idle or SUBJECT_KEY.fullmatch(key) is None:
                return False
            pull = pulls.get(int(key.rsplit("#", 1)[1]))
            return pull is not None and pull.asked and not untouched(hand, pull.updated)

        return Handed({k: h for k, h in self.hands.items() if not asked(k, h)})

    def handing(self, item: Finding, session: str, now: dt.datetime, pulls: Mapping[int, Pull] | None = None) -> Handed:
        """A launch's hands: one per subject of the (cut) item, a pull request's with its head
        from the change check (S-061-1), else the item's fingerprint; each carries the run of
        error ends of the hand it replaces (S-089-11)"""
        numbers = subjects(item)
        if numbers is None:
            key = item_key(item)
            return Handed({**self.hands, key: Hand(session, now, errors=self.errors(key))})
        found = pulls or {}
        new = {}
        for n in numbers:
            pull = found.get(n)
            key = subject_key(item, n)
            new[key] = Hand(session, now, None if pull is None else pull.head, errors=self.errors(key))
        return Handed({**self.hands, **new})

    def carrying(self, session: str, errors: int) -> Handed:
        """The hands of session whose end isn't recorded yet carry at least errors error ends
        before it: the run gate.json's launch held, as a launch recorded it before spec 089 kept
        the run on the hands (S-089-11)"""
        return Handed(
            {
                k: replace(h, errors=max(h.errors, errors)) if h.session == session and h.ended is None else h
                for k, h in self.hands.items()
            }
        )

    def errors(self, key: str) -> int:
        """The run of error ends a new hand of key carries from the one it replaces (S-089-11)"""
        hand = self.hands.get(key)
        return 0 if hand is None else hand.errors

    def ending(self, end: Callable[[str], End | None]) -> Handed:
        """Spec 089 (S-089-2): once no session of the gate runs, each hand without an end
        records its session's, read once per session by end; a hand with one keeps it, and one
        whose session end can't read (None, an interactive one's) stays without"""
        ends: dict[str, End | None] = {}
        for hand in self.hands.values():
            if hand.ended is None and hand.session not in ends:
                ends[hand.session] = end(hand.session)
        return Handed(
            {k: h if h.ended is not None else replace(h, ended=ends[h.session]) for k, h in self.hands.items()}
        )

    def settled(self, recorded: Iterable[str], died: Callable[[Hand], dt.datetime], retry: dt.timedelta) -> Handed:
        """Spec 089: a hand whose session ended limit or auth drops, whichever session gate.json
        names by then (S-089-4), and whichever tick recorded its end: one saved with it, as
        0.167.0's capped run of limit ends did, drops on the next (#1602). On the tick that
        records the ends of these keys, one that ended error is held for its backoff, the next
        delay of its run after its session's end (died, S-089-11), and one that ended ok ends its
        run; an error or ok hand whose end an earlier tick recorded stays as that tick left it"""
        fresh = set(recorded)
        found: dict[str, Hand] = {}
        for k, h in self.hands.items():
            if h.ended in CAUSED:
                continue
            if k not in fresh or h.ended is None:
                found[k] = h
            elif h.ended is End.ERROR:
                found[k] = h.backed_off(died(h), retry)
            else:
                found[k] = replace(h, errors=0)
        return Handed(found)

    def marked(self, keys: Iterable[str]) -> Handed:
        """These hands marked idle"""
        idle = set(keys)
        return Handed({k: replace(h, idle=True) if k in idle else h for k, h in self.hands.items()})

    def unmarked(self, keys: Iterable[str]) -> Handed:
        """These hands no longer marked idle"""
        busy = set(keys)
        return Handed({k: replace(h, idle=False) if k in busy else h for k, h in self.hands.items()})


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
    logins (#853): they wait on that person, not on CI or a session. drafts: the open drafts
    whose head is in the repo, whoever opened them (#914), so a tick never reads "no open pull
    request" while one is open"""

    ci: tuple[int, ...] = ()
    landing: tuple[int, ...] = ()
    failing: tuple[int, ...] = ()
    landed: Landed | None = None
    with_person: tuple[tuple[int, tuple[str, ...]], ...] = ()
    drafts: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Changes:
    """What the change check found: the signature (everything but the updated items), the open
    issues and pull requests updated at or after the cursor, whether one of them is labelled
    needs-decision, the newest release's tag, and what watch_state.py --known reads. forced: a
    source that can't tell, so every tick is a change. flight: the work in flight, from the
    same query (spec 048); None from a source that reads no pull requests, as rows a test hands.
    window: with a pull request queued for the land window, the window opened or its spacing
    let the next held merge through since the cursor (spec 056, window_change). pulls: every
    open pull request the query read, by number, with its head and updatedAt (spec 061)"""

    signature: str
    updated: tuple[int, ...] = ()
    asked: bool = False
    tag: str | None = None
    known: Mapping[str, object] = field(default_factory=dict)
    forced: bool = False
    flight: Flight | None = None
    window: bool = False
    pulls: Mapping[int, Pull] = field(default_factory=dict)


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
        f"number updatedAt isDraft isCrossRepository headRefOid body {LABELS} {ASSIGNEES} author {{ __typename login }}"
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
    page = head.format(page=CHANGE_PAGE, after=cursor)
    return f"{name}: {page} {{ pageInfo {{ hasNextPage endCursor }} nodes {{ {nodes} }} }}"


# the default branch's last LANDED commits, each with the pull request it came in by (spec 048)
HISTORY = (
    f"... on Commit {{ history(first: {LANDED}) {{ nodes {{ associatedPullRequests(first: 1)"
    " { nodes { number mergedAt } } } } }"
)
# spec 079: the default head's check rollup, so a check finishing there is a change the gate sees
BASE_ROLLUP = "... on Commit { statusCheckRollup { state } }"


def change_query(names: Sequence[str], after: Mapping[str, str] | None = None, first: bool = True) -> str:
    """The change check's one query (S-046-3): the default branch with its head's check rollup
    (S-079-7) and its last LANDED commits' merged pull requests (S-048-21), the newest release,
    and the connections; a later page asks only for the connections that have more"""
    pages = " ".join(connection(n, None if after is None else after.get(n)) for n in names)
    target = f"target {{ oid {BASE_ROLLUP} {HISTORY} }}"
    head = f"defaultBranchRef {{ name {target} }} latestRelease {{ tagName }} " if first else ""
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
    """The change check: one GraphQL query, paged only past CHANGE_PAGE open issues, pull requests, or
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


def pr_author(node: Mapping[str, Any]) -> dict[str, object] | None:
    """A pull request's author as gh pr list prints it, which watch_state.py --known reads (D-67,
    #914): an App's login as app/<slug> with is_bot, a person's as their login; null for a
    deleted account. Every open pull request has an author, so its login is read as GitHub
    spells any (AUTHOR, an Enterprise Managed User's with its _shortcode): one the gate can't
    read would fail every tick"""
    author = node["author"]
    if author is None:
        return None
    login = author.get("login") if isinstance(author, dict) else None
    if not isinstance(login, str) or AUTHOR.fullmatch(login) is None:
        raise ReleaseError(f"gh api graphql printed #{node['number']}'s author as something other than a login")
    bot = author.get("__typename") == "Bot"
    return {"login": f"app/{login}" if bot else login, "is_bot": bot}


def person_item(node: Mapping[str, Any]) -> bool:
    """#853: a pull request that is a person's item, as triage_state.py reads an issue: labelled
    human or role:<name>, compared case-insensitively"""
    return any(n.lower() == HUMAN_LABEL or n.lower().startswith(ROLE_PREFIX) for n in label_names(node))


def rollup(node: Mapping[str, Any]) -> str | None:
    commits = node["commits"]["nodes"]
    status = commits[0]["commit"]["statusCheckRollup"] if commits else None
    return None if status is None else str(status["state"])


BASE_READ = "base_read"  # known.json's key: whether tier 2 runs base_red.py (spec 079)
BASE_GREEN = frozenset({None, "SUCCESS"})  # a default head's rollups the signature leaves out (spec 079)


def base_rollup(default: Mapping[str, Any]) -> str | None:
    """The default head's check rollup state (S-079-7), None for a head with no checks; an
    answer without the field is one the gate can't read, never a green head"""
    target = default["target"]
    if not isinstance(target, dict) or "statusCheckRollup" not in target:
        raise ReleaseError(f"gh api graphql printed no check rollup for the default head: {str(default)[:300]}")
    status = target["statusCheckRollup"]
    if status is None:
        return None
    if not isinstance(status, dict) or not isinstance(status.get("state"), str):
        raise ReleaseError(f"gh api graphql printed the default head's check rollup as {str(status)[:200]}")
    return str(status["state"])


def base_read(changes: Changes, cursor: Cursor | None) -> Changes:
    """The change check's answer with tier 2's base_red.py read asked for also when the last
    reading wasn't GREEN, or isn't known (no cursor, or one written before spec 079), so a
    branch going green again reads once more and its question's `green again` row shows. A
    source without the key (rows a test hands) is left as it is"""
    if BASE_READ not in changes.known or (cursor is not None and cursor.base_red is False):
        return changes
    return replace(changes, known={**changes.known, BASE_READ: True})


def base_reading(tiers: Sequence[int], rows: Iterable[Finding], cursor: Cursor | None) -> bool | None:
    """The last reading for the next cursor: whether a walk that read tier 2 found a BASE_RED
    row; one that didn't read tier 2 keeps the cursor's"""
    if 2 not in tiers:
        return None if cursor is None else cursor.base_red
    return any(r.state == BASE_RED for r in rows)


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
    base = base_rollup(default)
    signed: dict[str, object] = {
        "head": default["target"]["oid"],
        "tag": tag,
        "pulls": [
            [p["number"], p["headRefOid"], p["isDraft"], rollup(p), label_names(p), p["isCrossRepository"]]
            for p in pulls
        ],
        "incidents": [i["number"] for i in incidents],
        "runs": [run_state(runs, w) for w in workflows],
    }
    # S-079-7: the default head's rollup, so a check failing on an unchanged head is a change; a
    # green head, or one with no checks, signs nothing, so a cursor written before still matches it
    if base not in BASE_GREEN:
        signed["base"] = base
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
                "author": pr_author(p),
                "body": str(p.get("body") or ""),  # spec 041: its Depends on lines hold it
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
        # spec 079: tier 2 reads base_red.py when the head's rollup fails; the tick adds the last reading
        BASE_READ: base in FAILS_CI,
    }
    numbers = tuple(sorted({int(n["number"]) for n in updated}))
    opened = {
        int(p["number"]): Pull(
            Head(str(p["headRefOid"]), rollup(p)),
            moment(p["updatedAt"], "updatedAt"),
            DECISION_LABEL in label_names(p),
        )
        for p in pulls
    }
    return Changes(signature, numbers, asked, tag, known, flight=flight_of(pulls, default), pulls=opened)


def issue_query(numbers: Sequence[int]) -> str:
    """One query for these subjects' updatedAt (spec 061), aliased once per number; a pull
    request no longer open (a vetoed one) answers as one"""
    aliases = " ".join(
        f"i{n}: issueOrPullRequest(number: {n}) {{ ... on Issue {{ updatedAt }} ... on PullRequest {{ updatedAt }} }}"
        for n in numbers
    )
    return f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {aliases} }} }}"


def issue_updates(repo: str, numbers: Iterable[int], graphql: GraphQL) -> dict[int, dt.datetime]:
    """Each subject's updatedAt on GitHub, in one GraphQL query per PAGE of them (S-061-7); none
    for no number. One GitHub answers null for (gone) is left out: it reads as changed"""
    owner, _, name = repo.partition("/")
    wanted = sorted(set(numbers))
    found: dict[int, dt.datetime] = {}
    for start in range(0, len(wanted), PAGE):
        chunk = wanted[start : start + PAGE]
        data = repository(graphql(issue_query(chunk), {"owner": owner, "name": name}), "the subjects' updatedAt")
        for n in chunk:
            node = data.get(f"i{n}")
            if node is None:
                continue
            if not isinstance(node, dict) or "updatedAt" not in node:
                raise ReleaseError(f"gh api graphql printed {str(node)[:200]} for #{n}, not its updatedAt")
            found[n] = moment(node["updatedAt"], f"#{n}'s updatedAt")
    return found


# spec 089: a session that leaves a subject unchanged because it waits on another item names it
# in a comment on the subject whose first line is this marker, posted as the --bot-login
WAITED_REPO = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+"  # owner/name, safe inside a query
WAITS_ON = re.compile(rf"<!-- shipmill:waits-on ({WAITED_REPO})#([1-9]\d*) -->")
WAIT_COMMENTS = 50  # the newest comments of a subject read for its marker


@dataclass(frozen=True, slots=True)
class Waited:
    """The item a subject's newest waits-on marker names: its repo (owner/name) and number"""

    repo: str
    number: int

    def __post_init__(self) -> None:
        if re.fullmatch(WAITED_REPO, self.repo) is None or self.number < 1:
            raise ValueError(f"a waited item is owner/name#N, got {self.repo!r}#{self.number!r}")

    @property
    def named(self) -> str:
        return f"{self.repo}#{self.number}"


def waits_query(numbers: Sequence[int]) -> str:
    """One query for these subjects' newest comments, with their authors (spec 089)"""
    comments = f"comments(last: {WAIT_COMMENTS}) {{ nodes {{ author {{ __typename login }} body }} }}"
    aliases = " ".join(
        f"i{n}: issueOrPullRequest(number: {n}) {{ ... on Issue {{ {comments} }} ... on PullRequest {{ {comments} }} }}"
        for n in numbers
    )
    return f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {aliases} }} }}"


def by_bot(author: object, bot: str) -> bool:
    """A comment's GraphQL author is the --bot-login: an App's login as GraphQL spells it, without
    the [bot] its REST login carries, or the login itself"""
    if not isinstance(author, dict) or not isinstance(author.get("login"), str):
        return False
    login = author["login"]
    return login == bot or (author.get("__typename") == "Bot" and f"{login}[bot]" == bot)


def waits_on(repo: str, numbers: Iterable[int], bot: str, graphql: GraphQL) -> dict[int, Waited]:
    """Spec 089 (S-089-12): each subject's newest comment by the bot whose first line is a
    waits-on marker, and the item it names; a subject without one is left out, and a marker
    by anyone else counts for nothing. One query per PAGE of subjects"""
    owner, _, name = repo.partition("/")
    wanted = sorted(set(numbers))
    found: dict[int, Waited] = {}
    for start in range(0, len(wanted), PAGE):
        chunk = wanted[start : start + PAGE]
        data = repository(graphql(waits_query(chunk), {"owner": owner, "name": name}), "the subjects' comments")
        for n in chunk:
            node = data.get(f"i{n}")
            if node is None:
                continue
            for comment in reversed(nodes_of(node, "comments")):
                if not isinstance(comment, dict) or not isinstance(comment.get("body"), str):
                    raise ReleaseError(f"gh api graphql printed a comment on #{n} without a body: {str(comment)[:200]}")
                marker = WAITS_ON.fullmatch(comment["body"].partition("\n")[0].strip())
                if marker is not None and by_bot(comment.get("author"), bot):
                    found[n] = Waited(marker[1], int(marker[2]))
                    break
    return found


def waited_query(items: Sequence[Waited]) -> str:
    """One query for these items' updatedAt, each in its own repo, read by its URL: GitHub answers
    a resource() it can't resolve (gone, or a repo the token can't read) with null alone, where a
    repository() or issueOrPullRequest() it can't resolve adds a NOT_FOUND error, on which gh api
    graphql exits 1 and the tick would fail on every walk while the marker stands. A URL's owner
    reads only as GitHub spells it: a marker naming it in another case wakes nothing"""
    updated = "... on Issue { updatedAt } ... on PullRequest { updatedAt }"
    aliases = " ".join(
        f'w{i}: resource(url: "https://github.com/{w.repo}/issues/{w.number}") {{ {updated} }}'
        for i, w in enumerate(items)
    )
    return f"query {{ {aliases} }}"


def waited_updates(items: Iterable[Waited], graphql: GraphQL) -> dict[Waited, dt.datetime]:
    """The updatedAt of the items markers name, one query per PAGE of them; an item GitHub
    answers null for (gone, or a repo the token can't read) is left out: nothing woke"""
    wanted = sorted(set(items), key=lambda w: (w.repo, w.number))
    found: dict[Waited, dt.datetime] = {}
    for start in range(0, len(wanted), PAGE):
        chunk = wanted[start : start + PAGE]
        answer = graphql(waited_query(chunk), {})
        data = answer.get("data") if isinstance(answer, dict) else None
        if not isinstance(data, dict):
            raise ReleaseError(f"gh api graphql printed no data for the items subjects wait on: {str(answer)[:300]}")
        for i, w in enumerate(chunk):
            node = data.get(f"w{i}")
            if node is None:
                continue
            if not isinstance(node, dict) or "updatedAt" not in node:
                raise ReleaseError(f"gh api graphql printed {str(node)[:200]} for {w.named}, not its updatedAt")
            found[w] = moment(node["updatedAt"], f"{w.named}'s updatedAt")
    return found


def waits(repo: str, numbers: Iterable[int], bot: str, graphql: GraphQL) -> dict[int, dt.datetime]:
    """Spec 089: for each subject whose newest bot marker names an item, that item's updatedAt"""
    marked = waits_on(repo, numbers, bot, graphql)
    updated = waited_updates(marked.values(), graphql) if marked else {}
    return {n: updated[w] for n, w in marked.items() if w in updated}


def queued(changes: Changes, label: str) -> bool:
    """Whether an open non-draft pull request the change check read carries the land window's
    queued_label (spec 056): its labels are in the same query, so this reads nothing more"""
    prs = changes.known.get("prs", [])
    if not isinstance(prs, list):
        raise ReleaseError(f"the change check's pull requests are {str(prs)[:200]}, not a list")
    return any(not p["isDraft"] and any(x["name"] == label for x in p["labels"]) for p in prs)


def window_change(
    window: LandWindow,
    queued: bool,
    since: dt.datetime | None,
    now: dt.datetime,
    last_held_merge: Callable[[], dt.datetime | None],
) -> bool:
    """S-056-11: with a pull request queued, a change when the window is open now and it opened
    after since, or its spacing let the next held merge through after since (last_held_merge plus
    spacing_minutes, read only then: the one GitHub read of `shipmill window`'s). since is the
    last walk's start: the window runs on the gate's clock, so no tick after that walk reads the
    same opening again, and an open window is no change by itself"""
    if not queued or since is None or since >= now or not window.is_open(now):
        return False
    before = window.state(since)
    if not before.open or (before.closes is not None and before.closes <= now):
        return True  # closed at since, or closed and opened again since
    if window.spacing_minutes == 0:
        return False
    last = last_held_merge()
    if last is None:
        return False
    return since < last + dt.timedelta(minutes=window.spacing_minutes) <= now


WAITS_ON_CI = frozenset({None, "PENDING", "EXPECTED"})  # a head with no checks yet waits on them too
LANDS = frozenset({"SUCCESS"})
FAILS_CI = frozenset({"FAILURE", "ERROR"})


def flight_of(pulls: Sequence[Mapping[str, Any]], default: Mapping[str, Any]) -> Flight:
    """The work in flight, from what the change check read and nothing more (S-048-22, D-58):
    the open pull requests a session can land, by their head's rollup, a person's with whom it
    waits on (#853), the drafts (#914), and the last landed one.
    It is kept out of the signature: the commits move only with the default head, already in it"""
    ci: list[int] = []
    landing: list[int] = []
    failing: list[int] = []
    people: list[tuple[int, tuple[str, ...]]] = []
    drafts: list[int] = []
    for p in pulls:
        if p["isCrossRepository"]:
            continue
        if p["isDraft"]:
            drafts.append(int(p["number"]))
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
    return Flight(tuple(ci), tuple(landing), tuple(failing), last_landed(default), tuple(people), tuple(drafts))


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
    """Where a walk reads the state: the change check, one tier, the sweep, the updatedAt of
    issue subjects past retry_hours (spec 061), and, for subjects past it, the updatedAt of the
    item each one's newest waits-on marker by the bot names (waited, spec 089)"""

    def changes(self, since: dt.datetime | None) -> Changes: ...
    def tier(self, number: int, changes: Changes) -> list[Finding]: ...
    def sweep(self, changes: Changes) -> list[Finding]: ...
    def issues(self, numbers: Sequence[int]) -> Mapping[int, dt.datetime]: ...
    def waited(self, numbers: Sequence[int]) -> Mapping[int, dt.datetime]: ...


@dataclass(frozen=True, slots=True)
class Rows:
    """A source of rows read whole, as a test hands them: every tick is a change, a tier is its
    rows (with NEEDS_DECISION in the waiting tier), and the sweep the timed sections' rows; it
    knows no subject's updatedAt, so none reads idle, and no marker"""

    rows: tuple[Finding, ...]

    def changes(self, since: dt.datetime | None) -> Changes:
        return Changes("rows", forced=True)

    def issues(self, numbers: Sequence[int]) -> Mapping[int, dt.datetime]:
        return {}

    def waited(self, numbers: Sequence[int]) -> Mapping[int, dt.datetime]:
        return {}

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
    the walk left it. subject: the key of the first handed item's first subject when it has
    subjects (spec 061), hand being that subject's hand. cut: the subjects of an item cut to
    those not taken, () for an item handed whole. handed: handed.json with the hands this walk
    found idle marked so"""

    item: Finding | None
    tier: int | None
    taken: Finding | None
    hand: Hand | None
    tiers: tuple[int, ...]
    rows: tuple[Finding, ...]
    swept: Swept
    subject: str | None = None
    cut: tuple[int, ...] = ()
    handed: Handed = Handed()


def idle(hand: Hand, number: int, pulls: Mapping[int, Pull], issues: Mapping[int, dt.datetime]) -> bool:
    """Nothing changed on a subject since its hand (spec 061): its updatedAt earlier than the
    hand's at less CURSOR_OVERLAP, and an open pull request's head and rollup the hand's. One
    whose updatedAt the gate couldn't read reads changed: one more session, never a missed one"""
    pull = pulls.get(number)
    if pull is not None:
        return hand.head == pull.head and untouched(hand, pull.updated)
    updated = issues.get(number)
    return updated is not None and untouched(hand, updated)


def woken(hand: Hand, waited: dt.datetime | None) -> bool:
    """Spec 089 (S-089-12): the item the subject's newest waits-on marker by the bot names was
    updated after the hand, so the subject is no longer idle; False with no such marker"""
    return waited is not None and waited > hand.at


def untouched(hand: Hand, updated: dt.datetime) -> bool:
    """A subject's updatedAt earlier than its hand's at less CURSOR_OVERLAP: nobody wrote on it
    since the hand"""
    return updated < hand.at - CURSOR_OVERLAP


def walk(
    source: Source,
    changes: Changes,
    swept: Swept,
    handed: Handed,
    now: dt.datetime,
    retry: dt.timedelta,
    lands: bool,
    dead: str | None = None,
) -> Walked:
    """Read the tiers in order and stop at the first item not handed within retry: tiers 1, 3,
    4, and 6 from their own read, tier 2 from its read and the sweep's BOT_STALLED, 5 and 7
    from the sweep; a sweep row of a kind no longer swept (an UNANNOUNCED written before D-69)
    is never an item.
    An item is a row that needs an agent, but a land-stage one (LAND_DUE, the land window's queue
    head, spec 056; PRS_OPEN; and AGENT_DRAFT, whose session marks a draft ready, #914) only when
    land isn't observe.
    An item with subjects (spec 061) is taken whole when its fingerprint was handed within
    retry, as a handed.json from before spec 061 holds it; else it is the item cut to its
    subjects not taken, a subject taken when handed within retry or idle past it, and no item
    when every one is; a hand of the dead session (dead, a capped one whose hands handed keeps)
    is never idle (spec 061), nor is one whose session ended anything but ok (S-089-3), nor one
    whose newest waits-on marker by the bot names an item updated since the hand (S-089-12). The
    updatedAt of a tier's issue subjects past retry, and the markers of its subjects past retry,
    are each read once for the tier, in one query per PAGE, and not at all when it has none"""
    read: list[int] = []
    rows: list[Finding] = []
    taken: tuple[Finding, Hand, str | None] | None = None
    marked: list[str] = []
    met: set[str] = set()  # the subjects this walk met
    for number in TIERS:
        found: list[Finding] = []
        own: list[Finding] = []  # this tier's own read, which may hold an earlier tier's kind
        if number in READ:
            own = source.tier(number, changes)
            found += own
        found += [r for r in swept.rows if r.state in SWEPT and tier_of(r) == number]
        read.append(number)
        rows += found
        # A tier's read may name an earlier tier's kind (tier 6's DECIDED, relayed with the label
        # off, which tier 4 never reads): it is taken here; the sweep's rows only in their own tier
        mine = [f for f in found if tier_of(f) == number or (f in own and tier_of(f) < number)]
        items = order(f for f in mine if (f.agent and f.state not in LANDING) or (lands and f.state in LANDING))
        issues = source.issues(past) if (past := past_issues(items, changes, handed, now, retry)) else {}
        woke = source.waited(late) if (late := past_subjects(items, handed, now, retry)) else {}
        for item in items:
            hand = handed.taken(item, now, retry)
            numbers = subjects(item)
            if hand is not None:
                taken = taken or (item, hand, None)
                continue
            if numbers is None:
                kept = handed.marked(marked).unmarked(unmet(handed, met, changes))
                return Walked(item, number, None, None, tuple(read), tuple(rows), swept, handed=kept)
            left: list[int] = []
            first: tuple[str, Hand] | None = None
            for n in numbers:
                key = subject_key(item, n)
                met.add(key)
                given = handed.hands.get(key)
                if given is None:
                    left.append(n)
                elif given.within(now, retry):
                    first = first or (key, given)
                elif (
                    given.ended in (None, End.OK)
                    and given.session != dead
                    and idle(given, n, changes.pulls, issues)
                    and not woken(given, woke.get(n))
                ):
                    marked.append(key)
                    first = first or (key, replace(given, idle=True))
                else:
                    left.append(n)  # changed since its hand: handed again, its hand replaced
            if left:
                whole = len(left) == len(numbers)
                return Walked(
                    item if whole else cut(item, left),
                    number,
                    None,
                    None,
                    tuple(read),
                    tuple(rows),
                    swept,
                    cut=() if whole else tuple(left),
                    handed=handed.marked(marked).unmarked(unmet(handed, met, changes)),
                )
            if first is not None:
                taken = taken or (item, first[1], first[0])
    first_item, hand, taken_key = (None, None, None) if taken is None else taken
    # a walk that read every tier met every item: an idle hand it didn't meet is no item's now
    marks = handed.marked(marked)
    kept = Handed({k: h for k, h in marks.hands.items() if not h.idle or k in met})
    return Walked(None, None, first_item, hand, tuple(read), tuple(rows), swept, taken_key, (), kept)


def unmet(handed: Handed, met: set[str], changes: Changes) -> list[str]:
    """The idle hands a walk that stopped at an item didn't meet, whose subject the change check
    shows changed since the cursor (updated, or a pull request's head moved): their mark comes
    off, so they count as past retry_hours again and the next walk reads them, since the next
    change check, from the new cursor, no longer shows that change. With a source that can't
    tell (forced), every one"""
    found = []
    for key, hand in handed.hands.items():
        if not hand.idle or key in met:
            continue
        number = int(key.rsplit("#", 1)[1])
        pull = changes.pulls.get(number)
        moved = pull is not None and pull.head != hand.head
        if changes.forced or number in changes.updated or moved:
            found.append(key)
    return found


def past_subjects(items: Sequence[Finding], handed: Handed, now: dt.datetime, retry: dt.timedelta) -> list[int]:
    """The subjects, issues and pull requests, of a tier's items whose hands are past retry and
    could read idle (their session ended ok, or has no end), not taken whole: the ones whose
    waits-on marker the walk reads (spec 089)"""
    found = set()
    for item in items:
        if handed.taken(item, now, retry) is not None:
            continue
        for n in subjects(item) or ():
            hand = handed.hands.get(subject_key(item, n))
            if hand is not None and not hand.within(now, retry) and hand.ended in (None, End.OK):
                found.add(n)
    return sorted(found)


def past_issues(
    items: Sequence[Finding], changes: Changes, handed: Handed, now: dt.datetime, retry: dt.timedelta
) -> list[int]:
    """The issue subjects of a tier's items whose hands are past retry, not taken whole: the
    ones whose updatedAt the walk reads; a pull request's comes from the change check"""
    found = set()
    for item in items:
        if handed.taken(item, now, retry) is not None:
            continue
        for n in subjects(item) or ():
            hand = handed.hands.get(subject_key(item, n))
            if hand is not None and not hand.within(now, retry) and n not in changes.pulls:
                found.add(n)
    return sorted(found)
