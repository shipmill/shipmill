"""intake_state.py --plans reads a goal plan the maintainer held until a condition (spec 098,
#1729), without gh or the network"""

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

from .test_intake_plans import (
    BOT,
    GOALS,
    MAINTAINERS,
    SCRIPT,
    Fake,
    at,
    comment,
    open_plan,
    owner,
    relay,
)


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_hold", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# the plan opens at 09:00 on 2026-10-01; comments are at that day's hours
BEFORE = dt.datetime(2026, 10, 1, 23, 59, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 10, 2, 12, tzinfo=dt.UTC)
Item = tuple[str, str, int]


class Held(Fake):
    """Fake, also answering a held item's read and the tags read"""

    def __init__(
        self,
        *args: Any,
        items: dict[Item, dict[str, Any] | None] | None = None,
        tags: list[tuple[str, str]] | None = None,
        errors: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.items = items or {}
        self.tags = tags or []  # (name, time), oldest first
        self.errors = errors  # what an item read answers with, instead of its node
        self.reads: list[Item | str] = []

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "issueOrPullRequest(" in query:
            key = (variables["owner"], variables["name"], variables["number"])
            self.reads.append(key)
            if self.errors is not None:
                return {"data": {"repository": None}, "errors": self.errors}
            node = self.items.get(key)
            return {"data": {"repository": {"issueOrPullRequest": node}}}
        if 'refPrefix: "refs/tags/"' in query:
            self.reads.append("tags")
            nodes = [{"name": n, "target": {"tagger": {"date": t}}} for n, t in self.tags]
            return {"data": {"repository": {"tags": {"nodes": nodes}}}}
        return super().__call__(query, variables)


def rows(ist: ModuleType, fake: Fake, now: dt.datetime = NOW, **kwargs: Any) -> dict[int, dict[str, Any]]:
    """Each plan issue's --json line, by number"""
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=fake,
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        goals=lambda: [ist.Goal(i, t) for i, t in GOALS],
        marker="Triage:",
        bot_login=kwargs.pop("bot_login", BOT),
        wip=None,
        room=lambda limit: 1,
        run=fake,
        filing=lambda issue, plan: ("PLAN_ACCEPTED", "unfiled"),
        now=now,
        **kwargs,
    )
    return {r.number: ist.plan_json(r) for r in found if r.kind == "plan"}


def held(ist: ModuleType, *comments: str | dict[str, Any], now: dt.datetime = NOW, **kwargs: Any) -> dict[str, Any]:
    """Plan #20's --json line with these comments"""
    fake_args = {k: kwargs.pop(k) for k in ("items", "tags", "errors") if k in kwargs}
    found: dict[str, Any] = rows(ist, Held(plans=[open_plan(20, *comments)], **fake_args), now, **kwargs)[20]
    return found


def state(row: dict[str, Any]) -> tuple[str, str]:
    return row["state"], row["note"]


def recheck(hour: int, *, bot: bool = True, day: int = 2) -> dict[str, Any]:
    body = "<!-- shipmill:plan-recheck -->\nNothing in this plan is done or stale.\n\n<!-- shipmill:agent -->"
    found = comment(body, hour, author="shipmill-app", bot=True) if bot else owner(body, hour)
    found["createdAt"] = f"2026-10-{day:02d}T{hour:02d}:00:00Z"
    return found


OPEN_ITEM = {"state": "OPEN", "closedAt": None}


def closed(when: str, state: str = "CLOSED") -> dict[str, Any]:
    return {"state": state, "closedAt": when}


@pytest.mark.parametrize(
    ("first", "until", "items"),
    [
        ("hold until 2026-12-15", "2026-12-15", {}),
        ("Hold until 2026-12-15.", "2026-12-15", {}),
        ("hold until #12", "#12", {("o", "r", 12): OPEN_ITEM}),
        ("HOLD UNTIL o/r#12", "o/r#12", {("o", "r", 12): OPEN_ITEM}),
        ("hold until other/x#5.", "other/x#5", {("other", "x", 5): OPEN_ITEM}),
        ("hold until release", "release", {}),
        ("Hold until release.", "release", {}),
    ],
)
def test_s098_1_a_hold_reads_held_until_its_condition(
    ist: ModuleType, first: str, until: str, items: dict[Item, Any]
) -> None:
    row = held(ist, owner(f"{first}\nAfter the release settles.", 10), items=items)
    assert state(row) == ("PLAN_HELD", f"until {until}")
    assert row["hold"] == {"until": until, "met_at": None}


def test_s098_1_held_is_no_action_so_a_run_with_only_it_exits_0(ist: ModuleType) -> None:
    assert "PLAN_HELD" not in ist.PLAN_ACTION
    assert "PLAN_HOLD_MET" in ist.PLAN_ACTION
    row = ist.PlanRow("G-1", "PLAN_HELD", "Plan 20", "until release", 20, "plan", BOT, "NONE")
    assert not any(p.state in ist.PLAN_ACTION for p in [row])


def test_s098_2_a_date_hold_is_met_at_that_days_midnight_utc(ist: ModuleType) -> None:
    hold = owner("hold until 2026-12-15", 10)
    midnight = dt.datetime(2026, 12, 15, tzinfo=dt.UTC)
    before = held(ist, hold, now=midnight - dt.timedelta(seconds=1))
    assert state(before) == ("PLAN_HELD", "until 2026-12-15")
    for now in (midnight, midnight + dt.timedelta(days=3)):
        row = held(ist, hold, now=now)
        assert state(row) == ("PLAN_HOLD_MET", "hold met: 2026-12-15; re-check due")
        assert row["hold"] == {"until": "2026-12-15", "met_at": "2026-12-15T00:00:00Z"}


def test_s098_2_a_date_already_past_is_met_at_once(ist: ModuleType) -> None:
    row = held(ist, owner("hold until 2026-09-01", 10))
    assert state(row) == ("PLAN_HOLD_MET", "hold met: 2026-09-01; re-check due")


@pytest.mark.parametrize("closing", ["CLOSED", "MERGED"])
@pytest.mark.parametrize(
    ("first", "key", "ref"),
    [("hold until #12", ("o", "r", 12), "#12"), ("hold until other/x#5", ("other", "x", 5), "other/x#5")],
)
def test_s098_3_an_item_hold_is_met_once_the_item_closes(
    ist: ModuleType, closing: str, first: str, key: Item, ref: str
) -> None:
    hold = owner(first, 10)
    fake = Held(plans=[open_plan(20, hold)], items={key: OPEN_ITEM})
    assert state(rows(ist, fake)[20]) == ("PLAN_HELD", f"until {ref}")
    assert fake.reads == [key]  # one read for the held item
    row = held(ist, hold, items={key: closed("2026-10-01T14:30:00+02:00", closing)})
    assert state(row) == ("PLAN_HOLD_MET", f"hold met: {ref} closed; re-check due")
    assert row["hold"] == {"until": ref, "met_at": "2026-10-01T12:30:00Z"}
    already = held(ist, hold, items={key: closed("2026-09-30T08:00:00Z", closing)})  # closed before the hold
    assert state(already) == ("PLAN_HOLD_MET", f"hold met: {ref} closed; re-check due")


def test_s098_4_a_release_hold_is_met_by_a_stable_tag_after_the_hold(ist: ModuleType) -> None:
    hold = owner("hold until release", 10)
    older = [("v1.0.0", "2026-10-01T09:30:00Z")]  # before the hold
    pre = [*older, ("v1.1.0-rc.1", "2026-10-01T11:00:00Z"), ("v1.1.0rc1", "2026-10-01T11:30:00Z")]
    assert state(held(ist, hold, tags=older)) == ("PLAN_HELD", "until release")
    assert state(held(ist, hold, tags=pre)) == ("PLAN_HELD", "until release")  # a pre-release counts for nothing
    shipped = [*pre, ("v1.1.0", "2026-10-01T13:00:00+01:00"), ("v1.2.0", "2026-10-02T09:00:00Z")]
    row = held(ist, hold, tags=shipped)
    assert state(row) == ("PLAN_HOLD_MET", "hold met: v1.1.0; re-check due")
    assert row["hold"] == {"until": "release", "met_at": "2026-10-01T12:00:00Z"}


def test_s098_4_stable_is_triage_states_and_the_flag_is_too(ist: ModuleType) -> None:
    path = SCRIPT.parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
    spec = importlib.util.spec_from_file_location("triage_state_hold", path)
    assert spec is not None and spec.loader is not None
    triage = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = triage
    spec.loader.exec_module(triage)
    assert ist.STABLE.pattern == triage.STABLE.pattern
    assert ist.TAG_NODES == triage.TAG_NODES
    # --stable-tag-regex: CalVer tags count, and the default's vX.Y.Z don't
    hold = owner("hold until release", 10)
    calver = [("v1.1.0", "2026-10-01T11:00:00Z"), ("2026.10", "2026-10-01T12:00:00Z")]
    fake = Held(plans=[open_plan(20, hold)], tags=calver)
    row = rows(ist, fake, stable=ist.re.compile(r"^\d{4}\.\d{2}"))[20]
    assert state(row) == ("PLAN_HOLD_MET", "hold met: 2026.10; re-check due")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "o/r", "--plans", "--stable-tag-regex", "("],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2 and "--stable-tag-regex" in proc.stderr


def test_s098_4_the_tags_are_read_once_a_run(ist: ModuleType) -> None:
    plans = [open_plan(20, owner("hold until release", 10)), open_plan(21, owner("hold until release", 11))]
    fake = Held(plans=plans, tags=[("v2.0.0", "2026-10-01T10:30:00Z")])
    found = rows(ist, fake)
    assert [found[n]["state"] for n in (20, 21)] == ["PLAN_HOLD_MET", "PLAN_HELD"]
    assert fake.reads == ["tags"]


def test_s098_5_only_a_held_row_has_a_hold_key(ist: ModuleType) -> None:
    held_row = held(ist, owner("hold until 2026-12-15", 10))
    assert held_row["hold"] == {"until": "2026-12-15", "met_at": None}
    met = held(ist, owner("hold until #12", 10), items={("o", "r", 12): closed("2026-10-01T12:00:00Z")})
    assert met["hold"] == {"until": "#12", "met_at": "2026-10-01T12:00:00Z"}
    rechecked = held(ist, owner("hold until 2026-10-02", 10), recheck(10))
    assert rechecked["state"] == "PLAN_OPEN"
    assert rechecked["hold"] == {"until": "2026-10-02", "met_at": "2026-10-02T00:00:00Z"}
    for others in (
        held(ist),
        held(ist, owner("accept", 10)),
        held(ist, owner("decline", 10)),
        held(ist, owner("Split W-2", 10)),
        held(ist, owner("hold until next week", 10)),
        held(ist, owner("hold until #404", 10), items={("o", "r", 404): None}),
    ):
        assert "hold" not in others
    line = json.dumps(held_row, sort_keys=True)
    assert json.loads(line)["hold"]["met_at"] is None  # null in the JSON line


@pytest.mark.parametrize(
    "author",
    [
        {"association": "CONTRIBUTOR", "author": "drive-by"},
        {"association": "NONE", "author": "stranger"},
        {"association": "FIRST_TIME_CONTRIBUTOR", "author": "new"},
        {"association": "MEMBER", "author": "shipmill-app", "bot": True},  # the --bot-login, no relay
    ],
)
def test_s098_6_an_untrusted_hold_changes_nothing(ist: ModuleType, author: dict[str, Any]) -> None:
    hold = comment("hold until 2026-12-15", 11, **author)
    assert state(held(ist, hold)) == ("PLAN_OPEN", "")
    assert state(held(ist, owner("decline", 10), hold)) == ("PLAN_ANSWERED", "decline")


def test_s098_6_a_relayed_hold_naming_a_maintainer_reads_held(ist: ModuleType) -> None:
    row = held(ist, relay("hold until release", 10), maintainers=MAINTAINERS)
    assert state(row) == ("PLAN_HELD", "until release")
    anyone = held(ist, relay("hold until release", 10, named="`@someone`"), maintainers=MAINTAINERS)
    assert state(anyone) == ("PLAN_OPEN", "")
    no_roles = held(ist, relay("hold until release", 10))
    assert state(no_roles) == ("PLAN_OPEN", "")


@pytest.mark.parametrize(
    "first",
    [
        "hold until 2026-13-01",
        "hold until 2026-02-30",
        "hold until 2026-12-15 #12",
        "hold until release or #12",
        "hold until next week",
        "hold until",
        "Hold until.",
        "hold until #0",
    ],
)
def test_s098_7_a_malformed_hold_reads_open_never_answered(ist: ModuleType, first: str) -> None:
    row = held(ist, owner(f"{first}\nLet's wait.", 10))
    assert state(row) == ("PLAN_OPEN", f"hold not read: {first}")


def test_s098_7_hold_until_is_never_an_edit(ist: ModuleType) -> None:
    assert ist.answer_kind("hold until whenever") == "hold"
    assert ist.answer_kind("Hold until release") == "hold"
    assert ist.answer_kind("hold on, split W-2") == "edit"
    assert ist.answer_kind("holding until W-2 is split") == "edit"


@pytest.mark.parametrize(
    "errors",
    [
        [{"type": "NOT_FOUND", "message": "Could not resolve to a Repository"}],
        [{"type": "FORBIDDEN", "message": "Resource not accessible"}],
    ],
)
def test_s098_8_an_item_github_answers_null_for_holds_nothing(ist: ModuleType, errors: list[dict[str, Any]]) -> None:
    gone = held(ist, owner("hold until #404", 10), items={("o", "r", 404): None})
    assert state(gone) == ("PLAN_OPEN", "hold not read: #404 can't be read")
    hidden = held(ist, owner("hold until secret/x#3", 10), errors=errors)
    assert state(hidden) == ("PLAN_OPEN", "hold not read: secret/x#3 can't be read")


def test_s098_8_any_other_failed_read_exits_2(ist: ModuleType) -> None:
    with pytest.raises(SystemExit) as exited:
        held(ist, owner("hold until #12", 10), errors=[{"type": "RATE_LIMITED", "message": "slow down"}])
    assert exited.value.code == 2


@pytest.mark.parametrize(
    ("later", "expected"),
    [
        ("accept", ("PLAN_ACCEPTED", "unfiled")),
        ("decline: not now", ("PLAN_ANSWERED", "decline")),
        ("Split W-2", ("PLAN_ANSWERED", "edit")),
        ("hold until 2026-12-15", ("PLAN_HELD", "until 2026-12-15")),
    ],
)
def test_s098_9_a_newer_answer_replaces_the_hold(ist: ModuleType, later: str, expected: tuple[str, str]) -> None:
    assert state(held(ist, owner("hold until release", 10), owner(later, 11))) == expected
    # and a hold replaces an older answer
    assert state(held(ist, owner(later, 10), owner("hold until release", 11))) == ("PLAN_HELD", "until release")


def test_s098_9_a_hand_edit_after_a_hold_leaves_it_held(ist: ModuleType) -> None:
    edited = open_plan(20, owner("hold until release", 10), edited=at(12))
    assert state(rows(ist, Held(plans=[edited]))[20]) == ("PLAN_HELD", "until release")
    met = open_plan(20, owner("hold until 2026-09-01", 10), edited=at(12))
    assert state(rows(ist, Held(plans=[met]))[20]) == ("PLAN_HOLD_MET", "hold met: 2026-09-01; re-check due")


def test_s098_15_the_bot_logins_recheck_after_met_at_reads_open(ist: ModuleType) -> None:
    hold = owner("hold until 2026-10-02", 10)  # met at 2026-10-02T00:00Z
    assert state(held(ist, hold)) == ("PLAN_HOLD_MET", "hold met: 2026-10-02; re-check due")
    after = held(ist, hold, recheck(8))
    assert state(after) == ("PLAN_OPEN", "hold met: 2026-10-02")
    assert after["hold"] == {"until": "2026-10-02", "met_at": "2026-10-02T00:00:00Z"}


def test_s098_15_anyone_elses_or_an_older_recheck_changes_nothing(ist: ModuleType) -> None:
    hold = owner("hold until 2026-10-02", 10)
    due = ("PLAN_HOLD_MET", "hold met: 2026-10-02; re-check due")
    assert state(held(ist, hold, recheck(8, bot=False))) == due  # a maintainer's marker
    assert state(held(ist, hold, recheck(23, day=1))) == due  # before met_at
    item = owner("hold until #12", 10)
    closing = {("o", "r", 12): closed("2026-10-02T10:00:00Z")}
    assert state(held(ist, item, recheck(9), items=closing)) == ("PLAN_HOLD_MET", "hold met: #12 closed; re-check due")
    assert state(held(ist, item, recheck(11), items=closing)) == ("PLAN_OPEN", "hold met: #12 closed")
    assert state(held(ist, hold, recheck(8), bot_login=None)) == due  # no --bot-login, no re-check


def test_s098_15_a_recheck_of_an_earlier_hold_is_not_this_ones(ist: ModuleType) -> None:
    """A past date is met before the hold was posted: only a re-check after the hold counts"""
    first = owner("hold until 2026-09-01", 10)
    again = owner("hold until 2026-09-15", 12)
    found = held(ist, first, recheck(11, day=1), again)
    assert state(found) == ("PLAN_HOLD_MET", "hold met: 2026-09-15; re-check due")


def test_s098_15_the_recheck_marker_is_never_an_answer(ist: ModuleType) -> None:
    hold = owner("hold until 2026-10-02", 10)
    assert state(held(ist, hold, recheck(8, bot=False))) == ("PLAN_HOLD_MET", "hold met: 2026-10-02; re-check due")
    assert state(held(ist, recheck(8, bot=False))) == ("PLAN_OPEN", "")


def test_s098_15_text_output_names_the_state(ist: ModuleType) -> None:
    row = ist.PlanRow("G-1", "PLAN_HOLD_MET", "Plan 20", "hold met: v1.2.0; re-check due", 20, "plan")
    assert ist.show_plan(row) == "#20    PLAN_HOLD_MET    Plan 20  [G-1; hold met: v1.2.0; re-check due]"


def test_a_held_plan_is_an_open_plan_so_its_goal_reads_no_plan_due(ist: ModuleType) -> None:
    fake = Held(plans=[open_plan(20, owner("hold until release", 10))])
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=fake,
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        goals=lambda: [ist.Goal(i, t) for i, t in GOALS],
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=fake,
        now=BEFORE,
    )
    goals = {r.goal for r in found if r.kind == "goal"}
    assert "G-1" not in goals
