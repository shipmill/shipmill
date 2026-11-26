"""Spec 092: work the gate parks wakes by itself. The two [agents] keys, an idle hand's waits in
handed.json, and the change check's read of the items idle hands wait on"""

import datetime as dt
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.gate import Action, StateRead, WatchState, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import HANDED, End, Hand, Handed, Head, Pull, Waited, WaitedItem, waited_items

from .test_config import agents, refusal
from .test_gate import checkout
from .test_gate_walk import LATER, NOW, REPO, Source, cfg, handed, tick
from .test_watch_gate_idle import ws

__all__ = ["checkout", "ws"]  # the fixtures, imported for the tests below

SHA = "a" * 40
HEAD = Head(SHA, "SUCCESS")
BEFORE = NOW - dt.timedelta(hours=25)  # a hand past retry_hours (24)
PRS = Finding("PRS_OPEN", REPO, "#3", False, ((3, SHA),), "land")
UPSTREAM = Waited("o/r", 5)


def unchanged() -> dict[int, Pull]:
    return {3: Pull(HEAD, BEFORE - dt.timedelta(hours=1))}


# -- S-092-1: the two [agents] keys


def test_s092_1_idle_days_and_parked_days_default_to_3_and_7() -> None:
    omitted = agents("")
    assert (omitted.idle_days, omitted.parked_days) == (3, 7)


@pytest.mark.parametrize("key", ["idle_days", "parked_days"])
@pytest.mark.parametrize("value", [0, 1, 90])
def test_s092_1_the_keys_read_integers_from_0_to_90(key: str, value: int) -> None:
    assert getattr(agents(f"{key} = {value}\n"), key) == value


@pytest.mark.parametrize("key", ["idle_days", "parked_days"])
@pytest.mark.parametrize(
    ("value", "refused"),
    [
        ("-1", "must be in 0..90, got -1"),
        ("91", "must be in 0..90, got 91"),
        ("true", "must be an integer, got True"),
        ('"3"', "must be an integer, got '3'"),
        ("2.5", "must be an integer, got 2.5"),
    ],
)
def test_s092_1_a_value_outside_0_to_90_or_not_an_integer_fails_naming_the_key(
    key: str, value: str, refused: str
) -> None:
    assert refusal(lambda: agents(f"{key} = {value}\n")) == f"shipmill.toml [agents]: {key} {refused}"


# -- S-092-2: an idle hand records what its subject waits on


def seed(git: Git, hand: Hand) -> None:
    Handed({"PRS_OPEN #3": hand}).save(state_dir(git) / HANDED)


def test_s092_2_a_walk_marking_a_hand_idle_records_the_item_its_marker_names(checkout: Git) -> None:
    seed(checkout, Hand("s0", BEFORE, HEAD))
    source = Source({3: [PRS]}, pulls=unchanged(), named={3: UPSTREAM})  # GitHub answers null: no wake
    decision = tick(checkout, source, NOW, cfg())
    assert decision.action is Action.UNCHANGED
    assert handed(checkout)["PRS_OPEN #3"] == {
        "session": "s0",
        "at": BEFORE.isoformat(),
        "head": SHA,
        "rollup": "SUCCESS",
        "idle": True,
        "waits": "o/r#5",
    }


def test_s092_2_a_walk_marking_a_hand_idle_without_a_marker_records_no_waits(checkout: Git) -> None:
    seed(checkout, Hand("s0", BEFORE, HEAD))
    tick(checkout, Source({3: [PRS]}, pulls=unchanged()), NOW, cfg())
    hand = handed(checkout)["PRS_OPEN #3"]
    assert hand["idle"] is True and "waits" not in hand


def test_s092_2_a_hand_without_idle_never_carries_waits(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only an idle hand waits on an item"):
        Hand("s0", BEFORE, waits=UPSTREAM)
    idle = Handed({"PRS_OPEN #3": Hand("s0", BEFORE, HEAD, idle=True, waits=UPSTREAM)})
    assert idle.unmarked(["PRS_OPEN #3"]).hands["PRS_OPEN #3"].waits is None
    ended = Hand("s0", BEFORE, HEAD, idle=True, ended=End.ERROR, waits=UPSTREAM)
    assert ended.backed_off(NOW, dt.timedelta(hours=24)).waits is None
    path = tmp_path / HANDED
    path.write_text(json.dumps({"PRS_OPEN #3": {"session": "s0", "at": BEFORE.isoformat(), "waits": "o/r#5"}}))
    with pytest.raises(ReleaseError, match=re.escape(f"{path} is malformed") + ".*only an idle hand has waits"):
        Handed.load(path)


@pytest.mark.parametrize("waits", ["o/r", "o/r#0", "#5", "o/r#5x", "o#5", "o/r # 5", 5, None, ""])
def test_s092_2_a_waits_not_of_the_form_owner_repo_n_fails_to_load_naming_the_path(
    tmp_path: Path, waits: object
) -> None:
    path = tmp_path / HANDED
    entry = {"session": "s0", "at": BEFORE.isoformat(), "idle": True, "waits": waits}
    path.write_text(json.dumps({"ISSUES NEW #3": entry}), encoding="utf-8")
    with pytest.raises(ReleaseError, match=re.escape(f"{path} is malformed") + ".*waits must be <owner/repo>#<N>"):
        Handed.load(path)


def test_s092_2_waits_round_trips_and_a_handed_json_from_before_loads(tmp_path: Path) -> None:
    path = tmp_path / HANDED
    Handed({"ISSUES NEW #3": Hand("s0", BEFORE, idle=True, waits=UPSTREAM)}).save(path)
    assert Handed.load(path).hands["ISSUES NEW #3"].waits == UPSTREAM
    path.write_text(json.dumps({"ISSUES NEW #3": {"session": "s0", "at": BEFORE.isoformat(), "idle": True}}))
    assert Handed.load(path).hands["ISSUES NEW #3"] == Hand("s0", BEFORE, idle=True)


def test_s092_2_the_watch_reads_a_hand_with_waits_and_refuses_a_malformed_one(ws: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / HANDED
    Handed({"ISSUES NEW #3": Hand("s0", BEFORE, idle=True, waits=UPSTREAM)}).save(path)
    (row,) = ws.idle_rows(path, NOW)
    assert row.subject == "ISSUES NEW #3"
    for entry, refused in (
        ({"session": "s0", "at": BEFORE.isoformat(), "idle": True, "waits": "o/r"}, "waits must be"),
        ({"session": "s0", "at": BEFORE.isoformat(), "waits": "o/r#5"}, "only an idle hand has waits"),
    ):
        path.write_text(json.dumps({"ISSUES NEW #3": entry}), encoding="utf-8")
        with pytest.raises(ws.Refused, match=re.escape(str(path)) + ".*" + refused) as caught:
            ws.idle_rows(path, NOW)
        assert caught.value.code == 2


# -- S-092-3 and S-092-4: the change check reads what idle subjects wait on


def parked(git: Git, source: Source) -> None:
    """A first tick that walks (no cursor yet) and marks #3 idle, waiting on o/r#5"""
    seed(git, Hand("s0", BEFORE, HEAD))
    first = tick(git, source, NOW, cfg(sweep_hours=48))
    assert first.action is Action.UNCHANGED and handed(git)["PRS_OPEN #3"]["waits"] == "o/r#5"
    source.reads.clear()


def test_s092_3_a_tick_whose_waited_item_changed_walks_and_hands_the_subject_again(checkout: Git) -> None:
    source = Source({3: [PRS]}, pulls=unchanged(), named={3: UPSTREAM})
    source.items[UPSTREAM] = WaitedItem(BEFORE - dt.timedelta(hours=1), False)
    parked(checkout, source)
    source.items[UPSTREAM] = WaitedItem(BEFORE + dt.timedelta(hours=2), True)  # the upstream report closed
    decision = tick(checkout, source, LATER, cfg(sweep_hours=48))
    assert decision.action is Action.LAUNCH
    assert source.reads[:2] == ["changes", "waited items o/r#5"] and "tier 3" in source.reads
    hand = handed(checkout)["PRS_OPEN #3"]
    assert hand["session"] != "s0" and "idle" not in hand and "waits" not in hand


def test_s092_3_a_tick_whose_waited_item_didnt_change_reads_quiet(checkout: Git) -> None:
    source = Source({3: [PRS]}, pulls=unchanged(), named={3: UPSTREAM})
    source.items[UPSTREAM] = WaitedItem(BEFORE - dt.timedelta(hours=1), False)
    parked(checkout, source)
    decision = tick(checkout, source, LATER, cfg(sweep_hours=48))
    assert decision.action is Action.QUIET
    assert source.reads == ["changes", "waited items o/r#5"]
    assert handed(checkout)["PRS_OPEN #3"]["waits"] == "o/r#5"


def test_s092_3_the_change_check_takes_the_mark_and_waits_off_a_stirred_hand() -> None:
    hands = Handed(
        {
            "PRS_OPEN #3": Hand("s0", BEFORE, HEAD, idle=True, waits=UPSTREAM),
            "ISSUES NEW #4": Hand("s0", BEFORE, idle=True, waits=Waited("o/r", 6)),
            "ISSUES NEW #7": Hand("s0", BEFORE, idle=True),
        }
    )
    read = {
        UPSTREAM: WaitedItem(BEFORE + dt.timedelta(minutes=1), False),
        Waited("o/r", 6): WaitedItem(BEFORE, False),  # not after the hand
    }
    assert hands.waiting() == [UPSTREAM, Waited("o/r", 6)]
    assert hands.stirred(read) == ["PRS_OPEN #3"]
    assert hands.unmarked(hands.stirred(read)).hands["PRS_OPEN #3"] == Hand("s0", BEFORE, HEAD)


def test_s092_4_no_idle_hand_with_waits_runs_no_such_query(checkout: Git) -> None:
    source = Source({3: [PRS]}, pulls=unchanged())  # no marker: the idle hand has no waits
    seed(checkout, Hand("s0", BEFORE, HEAD))
    tick(checkout, source, NOW, cfg(sweep_hours=48))
    source.reads.clear()
    assert tick(checkout, source, LATER, cfg(sweep_hours=48)).action is Action.QUIET
    assert source.reads == ["changes"]


def test_s092_4_an_item_github_answers_null_for_is_no_change(checkout: Git) -> None:
    source = Source({3: [PRS]}, pulls=unchanged(), named={3: UPSTREAM})  # nothing in items: null
    parked(checkout, source)
    assert tick(checkout, source, LATER, cfg(sweep_hours=48)).action is Action.QUIET
    assert source.reads == ["changes", "waited items o/r#5"]


class Counted:
    """Answers each resource() alias: o/r#N updated at NOON and open, o/gone#N null"""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, query: str, variables: Mapping[str, str]) -> dict[str, Any]:
        self.queries.append(query)
        found = re.findall(r'(w\d+): resource\(url: "https://github\.com/([^/"]+/[^/"]+)/issues/(\d+)"\)', query)
        node = {"updatedAt": "2026-10-27T12:00:00Z", "closed": False}
        return {"data": {alias: None if repo == "o/gone" else node for alias, repo, _ in found}}


def test_s092_4_the_change_check_reads_the_items_in_one_query_per_100() -> None:
    graphql = Counted()
    items = [Waited("o/r", n) for n in range(1, 151)] + [Waited("o/gone", 1)]
    found = waited_items(items, graphql)
    assert len(graphql.queries) == 2
    assert all("updatedAt closed" in q for q in graphql.queries)
    assert len(found) == 150 and Waited("o/gone", 1) not in found
    assert found[Waited("o/r", 1)] == WaitedItem(dt.datetime(2026, 10, 27, 12, tzinfo=dt.UTC), False)


def test_s092_4_the_gates_read_is_one_gh_api_graphql_call(checkout: Git) -> None:
    calls: list[list[str]] = []

    def gh(cmd: list[str], workspace: Path) -> str:
        calls.append(cmd)
        return json.dumps({"data": {"w0": {"updatedAt": "2026-10-27T12:00:00Z", "closed": True}}})

    read = WatchState(REPO, checkout.root, StateRead(), state_dir(checkout), NOW, gh).waited_items([UPSTREAM])
    assert read == {UPSTREAM: WaitedItem(dt.datetime(2026, 10, 27, 12, tzinfo=dt.UTC), True)}
    assert len(calls) == 1 and calls[0][:3] == ["gh", "api", "graphql"]


# -- S-092-6: an idle hand waiting on an open item is never due


def test_s092_6_an_idle_hand_whose_waits_names_an_open_item_is_never_due() -> None:
    hand = Hand("s0", NOW - dt.timedelta(days=400), idle=True, waits=UPSTREAM)
    open_ = {UPSTREAM: WaitedItem(NOW - dt.timedelta(days=1), False)}
    assert not hand.due(NOW, 3, open_)
    assert not hand.due(NOW, 3, {})  # an item not read as closed (null) waits as an open one


def test_s092_6_one_whose_waits_names_a_closed_item_is_due_as_one_without_waits() -> None:
    closed = {UPSTREAM: WaitedItem(NOW - dt.timedelta(days=1), True)}
    for age, due in ((dt.timedelta(days=3), True), (dt.timedelta(days=2, hours=23), False)):
        bare = Hand("s0", NOW - age, idle=True)
        waiting = Hand("s0", NOW - age, idle=True, waits=UPSTREAM)
        assert bare.due(NOW, 3, {}) is due
        assert waiting.due(NOW, 3, closed) is due
    old = Hand("s0", NOW - dt.timedelta(days=30), idle=True, waits=UPSTREAM)
    assert not old.due(NOW, 0, closed)  # idle_days = 0: never on time
    assert not Hand("s0", NOW - dt.timedelta(days=30)).due(NOW, 3, {})  # not idle
