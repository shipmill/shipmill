"""intake_state.py holds new requests while the product has no room under [agents] outcomes
(spec 101): HELD at room 0, held first once room comes back, and `propose` past the limit"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_intake_outcomes import BOT, HELD, Checkout
from .test_intake_state import Fake, issue, opportunity, said

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "intake_state.py"
APP = ("NONE", "shipmill-app", "Bot")  # the --bot-login, as GitHub returns its author
STRANGER = ("NONE", "stranger", "User")
MEMBER = ("MEMBER", "maintainer", "User")
HANDED = "Triage: **opportunity**. Handed to product intake\n<!-- shipmill:agent -->"


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_held", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request(number: int, *comments: tuple[str, str, tuple[str, str, str]]) -> dict[str, Any]:
    """A request issue with its comments, each (body, createdAt, (association, login, typename))"""
    found = issue(number)
    found["comments"]["nodes"] = [said(body, at, *who) for body, at, who in comments]
    return found


def held(at: str, who: tuple[str, str, str] = APP, body: str = HELD) -> tuple[str, str, tuple[str, str, str]]:
    return body, at, who


def read(ist: ModuleType, opened: list[dict[str, Any]], room: int | None) -> list[tuple[int, str, str]]:
    """The feedback rows, in the order they print, as (number, state, note)"""
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        bot_login=BOT,
        run=Fake(opened, []),
    )
    return [(r.number, r.state, r.note) for r in ist.rows(intake, room)]


def test_s101_6_a_held_request_reads_held_at_room_0(ist: ModuleType) -> None:
    found = read(ist, [request(2, held("2026-11-24T10:00:00Z"))], 0)
    assert found == [(2, "HELD", "held since 2026-11-24")]


def test_s101_6_the_held_comment_must_be_newer_than_the_newest_trusted_triage_comment(ist: ModuleType) -> None:
    handed_after = request(2, held("2026-11-20T10:00:00Z"), (HANDED, "2026-11-21T10:00:00Z", APP))
    handed_before = request(3, (HANDED, "2026-11-19T10:00:00Z", APP), held("2026-11-20T10:00:00Z"))
    # a stranger's `Triage:` comment is no triage comment (D-16): it clears nothing
    stranger_triage = request(4, held("2026-11-20T10:00:00Z"), (HANDED, "2026-11-21T10:00:00Z", STRANGER))
    found = read(ist, [handed_after, handed_before, stranger_triage], 0)
    assert sorted(found) == [
        (2, "NEW_FEEDBACK", "issue"),
        (3, "HELD", "held since 2026-11-20"),
        (4, "HELD", "held since 2026-11-20"),
    ]


def test_s101_6_the_newest_held_comment_dates_the_hold(ist: ModuleType) -> None:
    found = read(ist, [request(2, held("2026-11-20T10:00:00Z"), held("2026-11-23T23:30:00-02:00"))], 0)
    assert found == [(2, "HELD", "held since 2026-11-24")]  # its date in UTC


def test_s101_6_a_held_row_never_makes_the_run_exit_1(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path, "[agents]\noutcomes = 3\n")
    waiting = [opportunity(10, "- #1"), opportunity(11, "- #3"), opportunity(12, "- #4")]  # three in flight
    gh = {"opened": [request(2, held("2026-11-24T10:00:00Z"))], "opportunities": waiting}
    (checkout.bin / "gh.json").write_text(json.dumps(gh))
    text = checkout.run()
    assert text.returncode == 0, text.stderr
    assert "#2     HELD             Issue 2  [+1 0; held since 2026-11-24]" in text.stdout.splitlines()
    lines = checkout.run("--json")
    assert lines.returncode == 0, lines.stderr
    first, *rows = (json.loads(line) for line in lines.stdout.splitlines())
    assert first["outcomes"] == {"limit": 3, "in_flight": 3, "room": 0}
    assert [(r["number"], r["state"], r["note"]) for r in rows if r["kind"] == "issue"] == [
        (2, "HELD", "held since 2026-11-24")
    ]


@pytest.mark.parametrize(
    "comment",
    [
        held("2026-11-24T10:00:00Z", STRANGER),
        held("2026-11-24T10:00:00Z", ("CONTRIBUTOR", "someone", "User")),
        held("2026-11-24T10:00:00Z", ("NONE", "other-app", "Bot")),
        held("2026-11-24T10:00:00Z", APP, "<!-- shipmill:intake-held -->\nWaits for room."),
        held("2026-11-24T10:00:00Z", MEMBER, "<!-- shipmill:intake-held -->\nWaits for room."),
        held("2026-11-24T10:00:00Z", APP, "Waits for room.\n<!-- shipmill:intake-held -->\n<!-- shipmill:agent -->"),
    ],
    ids=["stranger", "contributor", "another bot", "no agent marker", "a member's, no marker", "marker not first"],
)
def test_s101_7_an_untrusted_or_unmarked_held_comment_holds_nothing(
    ist: ModuleType, comment: tuple[str, str, tuple[str, str, str]]
) -> None:
    assert read(ist, [request(2, comment)], 0) == [(2, "NEW_FEEDBACK", "issue")]


def test_s101_7_a_trusted_persons_session_holds_too(ist: ModuleType) -> None:
    """The spec admits an OWNER, MEMBER, or COLLABORATOR beside the --bot-login, the agent
    marker telling a session's text from the person's (D-62)"""
    for who in (MEMBER, ("OWNER", "owner", "User"), ("COLLABORATOR", "helper", "User")):
        assert read(ist, [request(2, held("2026-11-24T10:00:00Z", who))], 0) == [(2, "HELD", "held since 2026-11-24")]


def test_s101_8_room_back_reads_held_requests_new_feedback_oldest_held_first(ist: ModuleType) -> None:
    opened = [
        issue(1),
        request(2, held("2026-11-24T10:00:00Z")),
        request(3, held("2026-11-22T10:00:00Z")),
        issue(4),
        request(5, held("2026-11-23T10:00:00Z")),
    ]
    assert read(ist, opened, 2) == [
        (3, "NEW_FEEDBACK", "held since 2026-11-22"),
        (5, "NEW_FEEDBACK", "held since 2026-11-23"),
        (2, "NEW_FEEDBACK", "held since 2026-11-24"),
        (4, "NEW_FEEDBACK", "issue"),  # then the rest in the order they printed before
        (1, "NEW_FEEDBACK", "issue"),
    ]
    # at room 0 the held ones wait, oldest first; without a limit every one reads as before (S-101-3)
    assert read(ist, opened, 0) == [
        (4, "NEW_FEEDBACK", "issue"),
        (1, "NEW_FEEDBACK", "issue"),
        (3, "HELD", "held since 2026-11-22"),
        (5, "HELD", "held since 2026-11-23"),
        (2, "HELD", "held since 2026-11-24"),
    ]
    assert read(ist, opened, None) == [(n, "NEW_FEEDBACK", "issue") for n in (5, 4, 3, 2, 1)]


def test_s101_8_a_held_request_keeps_its_hand_off_time(ist: ModuleType) -> None:
    opened = [request(2, (HANDED, "2026-11-20T10:00:00Z", APP), held("2026-11-21T10:00:00Z"))]
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        bot_login=BOT,
        run=Fake(opened, []),
    )
    (row,) = ist.rows(intake, 1)
    assert (row.state, ist.json_row(row)["handed"]) == ("NEW_FEEDBACK", "2026-11-20T10:00:00Z")


@pytest.mark.parametrize("reply", ["propose", "Propose.", "PROPOSE\nthis one first, please"])
def test_s101_9_a_trusted_propose_reply_asks_for_it_by_name(ist: ModuleType, reply: str) -> None:
    opened = [request(2, held("2026-11-22T10:00:00Z"), (reply, "2026-11-23T10:00:00Z", MEMBER))]
    assert read(ist, opened, 0) == [(2, "NEW_FEEDBACK", "asked by name")]
    assert read(ist, opened, None) == [(2, "NEW_FEEDBACK", "issue")]  # no limit, nothing read (S-101-3)


@pytest.mark.parametrize(
    "reply",
    [
        ("propose", "2026-11-23T10:00:00Z", ("MEMBER", "shipmill-app", "Bot")),  # the --bot-login
        ("propose\n<!-- shipmill:agent -->", "2026-11-23T10:00:00Z", MEMBER),  # an agent's text
        ("propose", "2026-11-23T10:00:00Z", STRANGER),
        ("propose", "2026-11-23T10:00:00Z", ("CONTRIBUTOR", "someone", "User")),
        ("propose", "2026-11-21T10:00:00Z", MEMBER),  # older than the held comment
        ("propose this one", "2026-11-23T10:00:00Z", MEMBER),
        ("Please propose", "2026-11-23T10:00:00Z", MEMBER),
    ],
    ids=["bot login", "agent marker", "stranger", "contributor", "older", "more words", "not first"],
)
def test_s101_9_any_other_reply_changes_nothing(ist: ModuleType, reply: tuple[str, str, tuple[str, str, str]]) -> None:
    opened = [request(2, held("2026-11-22T10:00:00Z"), reply)]
    assert read(ist, opened, 0) == [(2, "HELD", "held since 2026-11-22")]


def test_s101_9_a_reply_whose_author_cant_be_read_is_an_agents(ist: ModuleType) -> None:
    ghost = said("propose", "2026-11-23T10:00:00Z")
    ghost["author"] = None
    found = request(2, held("2026-11-22T10:00:00Z"))
    found["comments"]["nodes"].append(ghost)
    assert read(ist, [found], 0) == [(2, "HELD", "held since 2026-11-22")]
