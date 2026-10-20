"""intake_state.py --plans: the goals a plan is due for (spec 028, #510), without gh or the network"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "intake_state.py"
BOT = "shipmill-app[bot]"


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_plans", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def issue(
    number: int,
    *comments: str,
    title: str = "",
    body: str = "",
    labels: tuple[str, ...] = (),
    state: str = "OPEN",
    reason: str | None = None,
    association: str = "NONE",
    author: str = "someone",
    bot: bool = False,
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title or f"Issue {number}",
        "url": f"https://github.com/o/r/issues/{number}",
        "state": state,
        "stateReason": reason,
        "closedAt": None if state == "OPEN" else "2026-10-02T10:00:00Z",
        "body": body,
        "author": {"__typename": "Bot" if bot else "User", "login": author},
        "authorAssociation": association,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "reactions": {"totalCount": 0},
        "comments": {
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
            "nodes": [{"body": c, "createdAt": "2026-10-01T10:00:00Z"} for c in comments],
        },
    }


def plan(number: int, goal: str, **kwargs: Any) -> dict[str, Any]:
    body = f"<!-- shipmill:plan goal={goal} rev=1 -->\n## Goal\n\n{goal}: text\n"
    opener: dict[str, Any] = {"author": "shipmill-app", "bot": True, **kwargs}
    return issue(number, body=body, labels=("goal-plan",), **opener)


def spec(status: str, served: str) -> str:
    return f"# S-030: A thing\n\nstatus: {status}\nserves: {served}\n\n## Problem\n\nserves: G-9\n"


class Fake:
    """GitHub, answering each query from fixtures; records the queries it was asked"""

    def __init__(
        self,
        opened: list[dict[str, Any]] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
        plans: list[dict[str, Any]] | None = None,
        pulls: list[str] | None = None,
        specs: dict[str, str] | None = None,
    ) -> None:
        self.opened = opened or []
        self.opportunities = opportunities or []
        self.plans = plans or []
        self.pulls = pulls or []
        self.specs = specs or {}
        self.asked: list[str] = []

    @staticmethod
    def page(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.asked.append(query)
        if "labels: [$label]" in query:
            chosen = self.plans if variables["label"] == "goal-plan" else self.opportunities
            repo: dict[str, Any] = {"issues": self.page(chosen)}
        elif "issues(states: OPEN" in query:
            repo = {"hasDiscussionsEnabled": False, "issues": self.page(self.opened)}
        elif "pullRequests(" in query:
            entries = [{"name": n, "object": {"text": t}} for n, t in self.specs.items()]
            pulls = [{"number": 100 + i, "body": b} for i, b in enumerate(self.pulls)]
            repo = {"specs": {"entries": entries}, "pullRequests": self.page(pulls)}
        else:
            raise AssertionError(f"unexpected query: {query}")
        return {"data": {"repository": repo}}


GOALS = [("G-1", "Releases go out on their own"), ("G-2", "Agents keep a quality bar"), ("G-3", "People hear")]


def due(
    ist: ModuleType,
    fake: Fake,
    *,
    wip: int | None = None,
    room: int = 1,
    goals: list[tuple[str, str]] = GOALS,
    bot_login: str | None = BOT,
) -> dict[str, tuple[str, str]]:
    """Each goal's plan row as (state, note); records the WIP limits the room was read for"""
    asked: list[int] = []

    def read_room(limit: int) -> int:
        asked.append(limit)
        return room

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
        goals=lambda: [ist.Goal(i, t) for i, t in goals],
        marker="Triage:",
        bot_login=bot_login,
        wip=wip,
        room=read_room,
        run=fake,
    )
    assert len(asked) <= 1  # the room is read once at most
    return {r.goal: (r.state, r.note) for r in found}


def test_s028_1_a_goal_nothing_serves_reads_no_work(ist: ModuleType) -> None:
    assert due(ist, Fake()) == {g: ("PLAN_DUE", "no-work") for g, _ in GOALS}


def test_s028_1_each_kind_of_open_work_serves_its_goal(ist: ModuleType) -> None:
    triaged = issue(5, "Triage: **feature**. Serves: G-1, G-2. A thing")
    pull = "## Plan\n\n- Serves: G-3\n- Files: x\n- Order: y\n- Proof: z\n"
    assert due(ist, Fake([triaged])) == {"G-3": ("PLAN_DUE", "no-work")}
    assert due(ist, Fake(pulls=[pull])) == {"G-1": ("PLAN_DUE", "no-work"), "G-2": ("PLAN_DUE", "no-work")}
    opp = issue(7, body="Serves: G-2\n\n## Problem\n\nSlow.\n", labels=("opportunity",))
    assert set(due(ist, Fake(opportunities=[opp]))) == {"G-1", "G-3"}
    specs = {"030-a.md": spec("draft", "G-1"), "031-b.md": spec("approved", "G-2, G-3")}
    assert due(ist, Fake(specs=specs)) == {}


def test_s028_1_closed_built_or_unrelated_work_serves_nothing(ist: ModuleType) -> None:
    fake = Fake(
        [
            issue(5, "Triage: **feature**. Serves: G-1.", "Triage: **implement**. A fix"),  # newest verdict counts
            issue(6, "I think this serves G-2", body="Serves: G-2"),  # not a triage comment
            issue(8, "Triage: **opportunity**. Serves no goal."),
        ],
        opportunities=[issue(7, body="Serves: G-3", labels=("opportunity",), state="CLOSED", reason="COMPLETED")],
        pulls=["Serves: G-1\n\n## Summary\n\n- Serves: G-2\n"],  # no `## Plan`
        specs={
            "030-a.md": spec("built", "G-1"),
            "TEMPLATE.md": spec("draft", "G-2"),
            "031-b.md": "# S-031: B\n\nstatus: draft\n\n## Notes\n\nserves: G-3\n",
        },
    )
    assert due(ist, fake) == {g: ("PLAN_DUE", "no-work") for g, _ in GOALS}


def test_s028_1_an_open_plan_item_serves_its_plans_goal(ist: ModuleType) -> None:
    accepted = plan(20, "G-1", state="CLOSED", reason="COMPLETED")
    item = issue(21, body="<!-- shipmill:plan-item #20 W-1 -->\nA feature.", author="shipmill-app", bot=True)
    assert set(due(ist, Fake([item], plans=[accepted]))) == {"G-2", "G-3"}
    member = issue(22, body="<!-- shipmill:plan-item #20 W-2 -->\nA fix.", association="MEMBER")
    assert set(due(ist, Fake([member], plans=[accepted]), bot_login=None)) == {"G-2", "G-3"}
    stranger = issue(23, body="<!-- shipmill:plan-item #20 W-1 -->\nA feature.")  # D-29: no marker of theirs
    assert set(due(ist, Fake([stranger], plans=[accepted]))) == {"G-1", "G-2", "G-3"}


def test_s028_2_no_work_is_not_raised_after_a_declined_newest_plan(ist: ModuleType) -> None:
    declined = plan(20, "G-1", state="CLOSED", reason="NOT_PLANNED")
    assert set(due(ist, Fake(plans=[declined]))) == {"G-2", "G-3"}
    redone = plan(30, "G-1", state="CLOSED", reason="COMPLETED")  # a newer plan, done: proposed again
    assert set(due(ist, Fake(plans=[declined, redone]))) == {"G-1", "G-2", "G-3"}
    newer_declined = plan(40, "G-1", state="CLOSED", reason="NOT_PLANNED")
    assert set(due(ist, Fake(plans=[redone, newer_declined]))) == {"G-2", "G-3"}


def test_s028_2_a_request_still_proposes_after_a_decline(ist: ModuleType) -> None:
    declined = plan(20, "G-1", state="CLOSED", reason="NOT_PLANNED")
    request = issue(25, title="Plan G-1 again", labels=("goal-plan",), association="OWNER")
    assert due(ist, Fake([request], plans=[declined]))["G-1"] == ("PLAN_DUE", "requested in #25")


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_s028_3_a_trusted_goal_plan_issue_is_a_request(ist: ModuleType, association: str) -> None:
    request = issue(25, title="Plan for G-2, please", labels=("goal-plan",), association=association)
    served = issue(5, "Triage: **feature**. Serves: G-2.")  # a request plans a served goal too
    assert due(ist, Fake([request, served]))["G-2"] == ("PLAN_DUE", "requested in #25")


@pytest.mark.parametrize("association", ["CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE"])
def test_s028_3_anyone_elses_goal_plan_issue_is_no_request(ist: ModuleType, association: str) -> None:
    request = issue(25, title="Plan G-2", labels=("goal-plan",), association=association, author="drive-by")
    served = issue(5, "Triage: **feature**. Serves: G-2.")
    assert "G-2" not in due(ist, Fake([request, served]))


def test_s028_3_a_request_names_exactly_one_listed_goal(ist: ModuleType) -> None:
    served = issue(5, "Triage: **feature**. Serves: G-1, G-2, G-3.")
    for title in ("Plan G-1 and G-2", "Plan G-9", "Plan a goal", "Plan XG-1", "Plan G-10"):
        request = issue(25, title=title, labels=("goal-plan",), association="OWNER")
        assert due(ist, Fake([request, served])) == {}, title
    unlabelled = issue(25, title="Plan G-1", association="OWNER")
    assert due(ist, Fake([unlabelled, served])) == {}
    marked = issue(25, title="Plan for G-1", labels=("goal-plan",), association="OWNER", body=plan(1, "G-1")["body"])
    assert "G-1" not in due(ist, Fake([marked, served]))  # an open plan, not a request (S-028-5)


def test_s028_3_two_requests_make_one_row_naming_the_oldest(ist: ModuleType) -> None:
    newer = issue(30, title="Plan G-1", labels=("goal-plan",), association="OWNER")
    older = issue(25, title="G-1 needs a plan", labels=("goal-plan",), association="MEMBER")
    served = issue(5, "Triage: **feature**. Serves: G-1, G-2, G-3.")
    assert due(ist, Fake([older, newer, served])) == {"G-1": ("PLAN_DUE", "requested in #25")}


def test_s028_4_no_work_waits_for_room_and_a_request_never_does(ist: ModuleType) -> None:
    request = issue(25, title="Plan G-3", labels=("goal-plan",), association="OWNER")
    fake = Fake([request])
    assert due(ist, fake, wip=2, room=1) == {
        "G-3": ("PLAN_DUE", "requested in #25"),
        "G-1": ("PLAN_DUE", "no-work"),
        "G-2": ("PLAN_DUE", "no-work"),
    }
    assert due(ist, fake, wip=2, room=0) == {
        "G-3": ("PLAN_DUE", "requested in #25"),
        "G-1": ("PLAN_WAITS", "no-work; waits for room"),
        "G-2": ("PLAN_WAITS", "no-work; waits for room"),
    }
    assert due(ist, fake, room=0) == due(ist, fake, wip=2, room=1)  # no --wip, no limit


def test_s028_4_the_room_is_triage_states(ist: ModuleType, tmp_path: Path) -> None:
    """The default room reader passes --wip to triage_state.py and reads its last JSON line"""
    stub = tmp_path / "triage_state.py"
    stub.write_text(
        "import json, sys\n"
        "assert sys.argv[1:] == ['o/r', '--wip', '3', '--json', '--bot-login', 'b[bot]'], sys.argv\n"
        "print(json.dumps({'number': 1, 'state': 'IN_PROGRESS'}))\n"
        "print(json.dumps({'wip': 3, 'in_progress': 3, 'room': 0, 'ready': []}))\n"
        "sys.exit(1)\n"
    )
    assert ist.triage_room("o/r", "b[bot]", stub)(3) == 0
    stub.write_text("import sys\nsys.exit(2)\n")
    with pytest.raises(SystemExit) as caught:
        ist.triage_room("o/r", None, stub)(3)
    assert caught.value.code == 2


def test_s028_4_the_room_is_read_only_when_a_goal_waits_on_it(ist: ModuleType) -> None:
    served = issue(5, "Triage: **feature**. Serves: G-1, G-2, G-3.")

    def never(limit: int) -> int:
        raise AssertionError("triage_state.py ran with nothing waiting")

    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(),
        categories=None,
        autonomy="propose",
        run=Fake([served]),
    )
    goals = [ist.Goal(i, t) for i, t in GOALS]
    found = ist.fetch_plans(
        "o/r", intake, goals=lambda: goals, marker="Triage:", bot_login=None, wip=1, room=never, run=Fake([served])
    )
    assert found == []


def test_s028_5_an_open_plan_issue_means_no_plan_due(ist: ModuleType) -> None:
    open_plan = plan(20, "G-1")
    request = issue(25, title="Plan G-1", labels=("goal-plan",), association="OWNER")
    assert set(due(ist, Fake([open_plan, request], plans=[open_plan]))) == {"G-2", "G-3"}
    by_hand = plan(21, "G-2", author="maintainer", bot=False)  # whoever opened it
    assert set(due(ist, Fake(plans=[open_plan, by_hand]), wip=1, room=0)) == {"G-3"}


def test_plans_add_two_queries_to_intakes(ist: ModuleType) -> None:
    fake = Fake()
    due(ist, fake)
    assert len(fake.asked) == 4  # open issues, opportunities, then pull requests with specs, plan issues


def test_the_goals_are_read_strictly(ist: ModuleType) -> None:
    text = '{"goals": [{"id": "G-1", "text": "Ship", "measure": null}]}'
    assert ist.parse_goals(text) == [ist.Goal("G-1", "Ship")]
    for bad in ("not json", "[]", '{"goals": {}}', '{"goals": [{"id": "Q-1", "text": "x"}]}', '{"goals": [{}]}'):
        with pytest.raises(SystemExit):
            ist.parse_goals(bad)


def test_the_plan_rows_print_after_the_opportunity_rows(ist: ModuleType) -> None:
    row = ist.PlanRow("G-1", "PLAN_DUE", "Releases go out on their own", "requested in #25", 25)
    assert ist.show_plan(row) == "G-1    PLAN_DUE         Releases go out on their own  [requested in #25]"
