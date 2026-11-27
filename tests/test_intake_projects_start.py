"""An overdue plan stops the product's new starts, and held projects start in turn (spec 106,
#1740): PLAN_WAITS `plan <owner/repo>#P overdue` and PROJECT_START_DUE; without the network"""

import datetime as dt
from pathlib import Path
from types import ModuleType
from typing import Any

from .test_intake_plans import BOT, ist, open_plan, owner
from .test_intake_projects import check, head, sub

__all__ = ["ist"]  # the module fixture

ACCEPTED = dt.datetime(2026, 10, 1, 10, tzinfo=dt.UTC)


def row(ist: ModuleType, node: dict[str, Any]) -> Any:
    return ist.project_row(node, BOT)


def item(
    number: int, plan: int, work: int, labelled: str = "2026-10-01T00:00:00Z", held: bool = True
) -> dict[str, Any]:
    """A filed plan item's head: its plan-item marker, its parent the plan, held without a check"""
    node = head(number, () if held else (check(), sub(number + 100)))
    node["body"] = f"<!-- shipmill:plan-item #{plan} W-{work} -->\nThe item."
    node["parent"] = {"number": plan}
    node["timelineItems"]["nodes"] = [{"createdAt": labelled, "label": {"name": "project"}, "actor": None}]
    return node


def loose(number: int, labelled: str) -> dict[str, Any]:
    """A head labelled by hand, with no plan"""
    node = head(number)
    node["timelineItems"]["nodes"] = [{"createdAt": labelled, "label": {"name": "project"}, "actor": None}]
    return node


def plans(ist: ModuleType, overdue: tuple[str, ...] = (), **accepted: dt.datetime) -> Any:
    """ProductPlans: accepted keyed `repo_P`, such as o_r_20 for o/r#20"""
    found = {}
    for key, at in accepted.items():
        owner_, name, number = key.split("_")
        found[(f"{owner_}/{name}", int(number))] = at
    return ist.ProductPlans(overdue, found)


def states(rows: list[Any]) -> dict[int, str]:
    return {r.number: r.state for r in rows}


# -- S-106-9 --------------------------------------------------------------------------------


def test_s106_9_an_overdue_plan_holds_every_no_work_plan_but_a_request(ist: ModuleType) -> None:
    rows = [
        ist.PlanRow("G-1", "PLAN_DUE", "Goal 1", "no-work"),
        ist.PlanRow("G-2", "PLAN_WAITS", "Goal 2", "no-work; waits for room"),
        ist.PlanRow("G-3", "PLAN_DUE", "Goal 3", "requested in #25", 25),
        ist.PlanRow("G-4", "PLAN_OPEN", "Plan", "answer by 2026-10-08", 30, "plan"),
    ]
    found = {r.goal: (r.state, r.note) for r in ist.overdue_waits(rows, ("o/api#7", "o/r#30"))}
    assert found == {
        "G-1": ("PLAN_WAITS", "plan o/api#7 overdue"),
        "G-2": ("PLAN_WAITS", "plan o/api#7 overdue"),
        "G-3": ("PLAN_DUE", "requested in #25"),
        "G-4": ("PLAN_OPEN", "answer by 2026-10-08"),
    }
    assert ist.overdue_waits(rows, ()) == rows


def test_s106_9_the_products_plans_are_read_for_overdue_and_accept_time(ist: ModuleType) -> None:
    now = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)  # past an unanswered plan's 2026-10-08
    unanswered, accepted = open_plan(30), open_plan(31, owner("accept", 10))
    held = open_plan(32, owner("hold until 2027-01-01", 10))
    other = open_plan(7)
    found = ist.read_product_plans(
        {"o/r": [unanswered, accepted, held], "o/api": [other]}, now, BOT, "Triage:", frozenset()
    )
    assert found.overdue == ("o/api#7", "o/r#30")  # held: no date; accepted: answered
    assert found.accepted == {("o/r", 31): dt.datetime(2026, 10, 1, 10, tzinfo=dt.UTC)}


def test_s106_9_no_head_starts_while_a_plan_is_overdue(ist: ModuleType) -> None:
    heads = {"o/r": [row(ist, item(40, 31, 1))]}
    assert states(ist.start_due(heads, "o/r", None, plans(ist, ("o/api#7",), o_r_31=ACCEPTED))) == {40: "PROJECT_HELD"}


# -- S-106-14 -------------------------------------------------------------------------------


def test_s106_14_no_head_starts_while_the_products_slots_are_full(ist: ModuleType) -> None:
    full = ist.Projects("o/home", 2, 2)  # one active and one in focus, in any repos
    heads = {"o/r": [row(ist, item(40, 31, 1)), row(ist, item(41, 31, 2, held=False))]}
    assert states(ist.start_due(heads, "o/r", full, plans(ist, o_r_31=ACCEPTED))) == {
        40: "PROJECT_HELD",
        41: "PROJECT_ACTIVE",
    }


def test_s106_14_one_slot_starts_the_oldest_accepted_plans_first_item(ist: ModuleType) -> None:
    one = ist.Projects("o/home", 2, 1)
    later = ACCEPTED + dt.timedelta(days=1)
    heads = {
        "o/r": [row(ist, item(42, 31, 2)), row(ist, item(43, 32, 1)), row(ist, loose(44, "2026-09-01T00:00:00Z"))],
        "o/api": [row(ist, item(9, 5, 3))],
    }
    product = plans(ist, o_r_31=later, o_r_32=later + dt.timedelta(days=1), o_api_5=ACCEPTED)
    # o/api#9's plan was accepted first: it is the product's turn, and o/r's pass starts none of its own
    assert states(ist.start_due(heads, "o/r", one, product)) == {
        42: "PROJECT_HELD",
        43: "PROJECT_HELD",
        44: "PROJECT_HELD",
    }
    assert states(ist.start_due(heads, "o/api", one, product)) == {9: "PROJECT_START_DUE"}
    # with two slots, the next is o/r#31's first item by Work order, before a head with no plan
    two = ist.Projects("o/home", 3, 1)
    assert states(ist.start_due(heads, "o/r", two, product)) == {
        42: "PROJECT_START_DUE",
        43: "PROJECT_HELD",
        44: "PROJECT_HELD",
    }
    started = ist.start_due(heads, "o/r", two, product)[0]
    assert (started.holder, started.base, started.note, "PROJECT_START_DUE" in ist.PROJECT_ACTION) == (
        "agent",
        "PROJECT_HELD",
        "its turn to start",
        True,
    )


def test_s106_14_heads_with_no_plan_start_by_when_they_were_labelled(ist: ModuleType) -> None:
    heads = {"o/r": [row(ist, loose(50, "2026-10-05T00:00:00Z")), row(ist, loose(51, "2026-10-02T00:00:00Z"))]}
    one = ist.Projects("o/r", 1, 0)
    assert states(ist.start_due(heads, "o/r", one, plans(ist))) == {50: "PROJECT_HELD", 51: "PROJECT_START_DUE"}


def test_s106_14_without_the_key_every_held_head_starts(ist: ModuleType) -> None:
    heads = {"o/r": [row(ist, item(40, 31, 1)), row(ist, loose(44, "2026-09-01T00:00:00Z"))]}
    assert states(ist.start_due(heads, "o/r", None, plans(ist))) == {40: "PROJECT_START_DUE", 44: "PROJECT_START_DUE"}


def test_s106_14_a_heads_work_order_comes_from_its_plan_item_marker(ist: ModuleType) -> None:
    read = row(ist, item(40, 31, 3))
    assert (read.parent, read.work, read.labelled) == (31, 3, "2026-10-01T00:00:00Z")
    other_plan = item(40, 31, 3)
    other_plan["parent"] = {"number": 99}  # its marker names another plan: no place in this one's Work
    assert row(ist, other_plan).work is None


# -- S-106-15 -------------------------------------------------------------------------------


def test_s106_15_the_skill_gives_project_start_dues_step() -> None:
    skill = (Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "SKILL.md").read_text(encoding="utf-8")
    step = next(line for line in skill.splitlines() if line.startswith("**PROJECT_START_DUE: start the project"))
    for words in (
        "before any part",
        "`chains.py link",
        "--child",
        "titled `Check: <what will be true>`",
        "a `## Check` a person other than the builder can run",
        "remove the `held` label",
    ):
        assert words in step, words


def test_s106_9_the_checkouts_own_plans_read_as_plans_prints_them(ist: ModuleType) -> None:
    """a plan of the checkout re-checked after its hold was met and past its answer date reads
    overdue here as in --plans; another repo's held plan reads held"""
    from .test_intake_plans import comment

    hold = owner("hold until 2026-10-05", 10)
    recheck = comment(
        "<!-- shipmill:plan-recheck -->\nNothing in this plan is done or stale.", 0, author="shipmill-app", bot=True
    )
    recheck["createdAt"] = "2026-10-06T10:00:00Z"
    now = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    issues = {"o/r": [open_plan(30, hold, recheck)], "o/api": [open_plan(7, hold, recheck)]}
    own = ("o/r", ist.gh_holds("o/r", lambda query, variables: {}, now), frozenset({"G-1"}))
    found = ist.read_product_plans(issues, now, BOT, "Triage:", frozenset(), own)
    assert found.overdue == ("o/r#30",)  # re-checked 2026-10-06: due 2026-10-13
    assert ist.read_product_plans(issues, now, BOT, "Triage:", frozenset()).overdue == ()  # no reader: held


def test_s106_25_the_first_line_names_the_products_overdue_plans(ist: ModuleType) -> None:
    """What a held head waits for: the product's overdue plans on --json's first line, while any is"""
    assert ist.first_line("propose", None, None, ("o/r#3", "o/s#8")) == {
        "autonomy": "propose",
        "overdue": ["o/r#3", "o/s#8"],
    }
    assert ist.first_line("propose", None, None) == {"autonomy": "propose"}
