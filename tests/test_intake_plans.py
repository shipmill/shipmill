"""intake_state.py --plans: the goals a plan is due for (spec 028, #510), without gh or the network"""

import importlib.util
import re
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


def at(hour: int) -> str:
    return f"2026-10-01T{hour:02d}:00:00Z"


def comment(
    body: str, hour: int = 10, *, association: str = "NONE", author: str = "someone", bot: bool = False
) -> dict[str, Any]:
    return {
        "body": body,
        "createdAt": at(hour),
        "author": {"__typename": "Bot" if bot else "User", "login": author},
        "authorAssociation": association,
    }


def issue(
    number: int,
    *comments: str | dict[str, Any],
    title: str = "",
    body: str = "",
    labels: tuple[str, ...] = (),
    state: str = "OPEN",
    reason: str | None = None,
    association: str = "NONE",
    author: str = "someone",
    bot: bool = False,
    edited: str | None = None,
    thumbs: int = 0,
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title or f"Issue {number}",
        "url": f"https://github.com/o/r/issues/{number}",
        "state": state,
        "stateReason": reason,
        "createdAt": at(9),
        "lastEditedAt": edited,
        "closedAt": None if state == "OPEN" else "2026-10-02T10:00:00Z",
        "body": body,
        "author": {"__typename": "Bot" if bot else "User", "login": author},
        "authorAssociation": association,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "reactions": {"totalCount": thumbs},
        "comments": {
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
            "nodes": [comment(c) if isinstance(c, str) else c for c in comments],
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
        carriers: list[dict[str, Any]] | None = None,
        milestones: dict[int, str | None] | None = None,
    ) -> None:
        self.opened = opened or []
        self.opportunities = opportunities or []
        self.plans = plans or []
        self.pulls = pulls or []
        self.specs = specs or {}
        self.carriers = carriers or []  # the issues the plan-item marker search finds
        self.milestones = milestones or {}  # each existing item's milestone
        self.asked: list[str] = []

    @staticmethod
    def page(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.asked.append(query)
        if "search(type: ISSUE" in query:
            (plan_issue,) = [p for p in self.plans if p["number"] == variables["number"]]
            subs = {"pageInfo": {"hasNextPage": False}, "nodes": []}
            found = {"issueCount": len(self.carriers), "nodes": self.carriers}
            repo_issue = {"number": plan_issue["number"], "body": plan_issue["body"], "subIssues": subs}
            return {"data": {"repository": {"issue": repo_issue}, "search": found}}
        numbers = [int(n) for n in re.findall(r"\be(\d+): issue\(", query)]
        if numbers:
            titles = {n: self.milestones[n] for n in numbers}
            aliased = {f"e{n}": {"milestone": {"title": t} if t else None} for n, t in titles.items()}
            return {"data": {"repository": aliased}}
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
    return {r.goal: (r.state, r.note) for r in found if r.kind == "goal"}


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
    plan_row = ist.PlanRow("G-1", "PLAN_ANSWERED", "Plan for G-1", "edit", 20, "plan")
    assert ist.show_plan(plan_row) == "#20    PLAN_ANSWERED    Plan for G-1  [G-1; edit]"


# -- a plan issue's states (#514)


def full_plan(goal: str = "G-1", milestone: str = "none", rev: int = 1) -> str:
    return (
        f"<!-- shipmill:plan goal={goal} rev={rev} -->\n## Goal\n\n{goal}: Releases go out on their own\n\n"
        "Trigger: no-work\nMeasure: none yet\n\n## Work\n\n- W-1 existing: #212\n- W-2 feature: A release cut\n"
        "- W-3 fix: The lane stalls (after W-2)\n- W-4 existing: other/x#5\n\n## Order\n\nThe feature first.\n\n"
        f"## Milestone\n\n{milestone}\n"
    )


def open_plan(number: int, *comments: str | dict[str, Any], body: str = "", **kwargs: Any) -> dict[str, Any]:
    opener: dict[str, Any] = {"author": "shipmill-app", "bot": True, **kwargs}
    return issue(number, *comments, title=f"Plan {number}", body=body or full_plan(), labels=("goal-plan",), **opener)


def owner(body: str, hour: int, association: str = "OWNER") -> dict[str, Any]:
    return comment(body, hour, association=association, author="maintainer")


def revised(rev: int, hour: int, *, by_bot: bool = True) -> dict[str, Any]:
    body = f"<!-- shipmill:plan-revised rev={rev} -->\nRevised as asked."
    if by_bot:
        return comment(body, hour, author="shipmill-app", bot=True)
    return comment(body, hour, author="drive-by", association="CONTRIBUTOR")


def plan_states(
    ist: ModuleType,
    fake: Fake,
    *,
    bot_login: str | None = BOT,
    filing: Any = None,
) -> dict[int, tuple[str, str]]:
    """Each plan issue's row as (state, note); without a filing reader, every accepted plan
    reads PLAN_ACCEPTED with the note `unfiled`"""
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
        bot_login=bot_login,
        wip=None,
        room=lambda limit: 1,
        run=fake,
        filing=filing if filing is not None else (lambda issue, plan: ("PLAN_ACCEPTED", "unfiled")),
    )
    return {r.number: (r.state, r.note) for r in found if r.kind == "plan"}


def state_of(ist: ModuleType, plan_issue: dict[str, Any], **kwargs: Any) -> tuple[str, str]:
    return plan_states(ist, Fake(plans=[plan_issue]), **kwargs)[plan_issue["number"]]


def test_s028_8_a_plan_with_no_trusted_answer_reads_open(ist: ModuleType) -> None:
    assert state_of(ist, open_plan(20)) == ("PLAN_OPEN", "")
    others = open_plan(
        20,
        comment("accept", 10, association="CONTRIBUTOR", author="drive-by"),
        comment("decline", 11, association="NONE", author="stranger"),
        comment("accept", 12, association="FIRST_TIME_CONTRIBUTOR", author="new"),
        comment("accept", 13, association="MEMBER", author="shipmill-app", bot=True),  # the --bot-login
        thumbs=7,  # a reaction is never read
    )
    assert state_of(ist, others) == ("PLAN_OPEN", "")


def test_s028_8_the_sessions_own_comments_are_never_an_answer(ist: ModuleType) -> None:
    own = open_plan(
        20,
        owner("Triage: **plan**. Serves: G-1.", 10),
        owner("<!-- shipmill:needs-decision -->\n@maintainer which way?", 11),
    )
    assert state_of(ist, own) == ("PLAN_OPEN", "")


def test_s028_8_a_trusted_comment_older_than_the_newest_revision_is_stale(ist: ModuleType) -> None:
    assert state_of(ist, open_plan(20, owner("Split W-2", 10), revised(2, 11))) == ("PLAN_OPEN", "")
    before_opening = open_plan(20, owner("accept", 9))  # not newer than the opening body
    assert state_of(ist, before_opening) == ("PLAN_OPEN", "")


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
@pytest.mark.parametrize("first", ["accept", "Accept.", "ACCEPT", "  accept  "])
def test_s028_9_an_accept_reads_accepted(ist: ModuleType, association: str, first: str) -> None:
    accepted = open_plan(20, owner(f"{first}\nThanks.", 10, association))
    assert state_of(ist, accepted) == ("PLAN_ACCEPTED", "unfiled")


@pytest.mark.parametrize(
    ("first", "note"),
    [
        ("decline", "decline"),
        ("Decline: not this quarter", "decline"),
        ("declined, too broad", "decline"),
        ("accept.. but split W-2", "edit"),
        ("accepted", "edit"),
        ("accept W-2 only", "edit"),
        ("Please split W-2 in two", "edit"),
        ("I don't accept this", "edit"),
    ],
)
def test_s028_9_a_decline_or_any_other_answer_reads_answered(ist: ModuleType, first: str, note: str) -> None:
    assert state_of(ist, open_plan(20, owner(first, 10))) == ("PLAN_ANSWERED", note)


def test_s028_9_the_newest_trusted_answer_decides(ist: ModuleType) -> None:
    assert state_of(ist, open_plan(20, owner("accept", 10), owner("decline", 11))) == ("PLAN_ANSWERED", "decline")
    later = open_plan(20, owner("Split W-2", 10), owner("accept", 11), comment("decline", 12))
    assert state_of(ist, later) == ("PLAN_ACCEPTED", "unfiled")


def test_s028_9_a_higher_revision_makes_an_earlier_answer_stale(ist: ModuleType) -> None:
    edited = open_plan(20, owner("Split W-2", 10), revised(2, 11))
    assert state_of(ist, edited) == ("PLAN_OPEN", "")
    answered_again = open_plan(20, owner("Split W-2", 10), revised(2, 11), owner("accept", 12))
    assert state_of(ist, answered_again) == ("PLAN_ACCEPTED", "unfiled")
    replayed = open_plan(20, owner("Split W-2", 10), revised(2, 11), owner("Drop W-3", 12), revised(2, 13))
    assert state_of(ist, replayed) == ("PLAN_ANSWERED", "edit")  # rev 2 again is not a higher rev
    third = open_plan(20, revised(2, 10), owner("Drop W-3", 12), revised(3, 13))
    assert state_of(ist, third) == ("PLAN_OPEN", "")


def test_s028_9_only_a_trusted_author_revises(ist: ModuleType) -> None:
    forged = open_plan(20, owner("accept", 10), revised(2, 11, by_bot=False))
    assert state_of(ist, forged) == ("PLAN_ACCEPTED", "unfiled")
    no_login = open_plan(20, owner("Split W-2", 10), revised(2, 11))
    assert state_of(ist, no_login, bot_login=None) == ("PLAN_ANSWERED", "edit")  # the App's comment, unknown


def test_s028_10_an_accept_older_than_the_last_edit_reads_open(ist: ModuleType) -> None:
    stale = open_plan(20, owner("accept", 10), edited="2026-10-01T10:00:01Z")
    assert state_of(ist, stale) == ("PLAN_OPEN", "edited after accept")
    for edited in ("2026-10-01T10:00:00Z", "2026-10-01T09:59:59Z", None):  # not after the accept
        assert state_of(ist, open_plan(20, owner("accept", 10), edited=edited)) == ("PLAN_ACCEPTED", "unfiled")
    reaccepted = open_plan(20, owner("accept", 10), owner("accept", 12), edited=at(11))
    assert state_of(ist, reaccepted) == ("PLAN_ACCEPTED", "unfiled")


def test_s028_10_an_edit_after_an_edit_or_decline_answer_changes_nothing(ist: ModuleType) -> None:
    assert state_of(ist, open_plan(20, owner("decline", 10), edited=at(11))) == ("PLAN_ANSWERED", "decline")


def carrier(number: int, item: str, *, milestone: str | None = None, trusted: bool = True) -> dict[str, Any]:
    author = {"__typename": "Bot", "login": "shipmill-app"} if trusted else {"__typename": "User", "login": "x"}
    return {
        "number": number,
        "body": f"<!-- shipmill:plan-item #20 {item} -->\nThe item.",
        "milestone": {"title": milestone} if milestone else None,
        "author": author,
        "authorAssociation": "NONE",
        "repository": {"nameWithOwner": "o/r"},
    }


def filed(ist: ModuleType, milestone: str, carriers: list[dict[str, Any]], existing: str | None = None) -> Any:
    accepted = open_plan(20, owner("accept", 10), body=full_plan(milestone=milestone))
    fake = Fake(plans=[accepted], carriers=carriers, milestones={212: existing})
    return plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake))[20], fake


def test_s028_11_an_accepted_plan_reads_accepted_until_every_item_is_filed(ist: ModuleType) -> None:
    assert filed(ist, "none", [])[0] == ("PLAN_ACCEPTED", "not filed: W-2, W-3")
    assert filed(ist, "none", [carrier(301, "W-2")])[0] == ("PLAN_ACCEPTED", "not filed: W-3")
    outsider = [carrier(301, "W-2"), carrier(302, "W-3", trusted=False)]  # D-29: not its marker
    assert filed(ist, "none", outsider)[0] == ("PLAN_ACCEPTED", "not filed: W-3")
    done, fake = filed(ist, "none", [carrier(301, "W-2"), carrier(302, "W-3")])
    assert done == ("PLAN_FILED", "filed: #301, #302")
    assert not any(re.search(r"\be\d+: issue\(", q) for q in fake.asked)  # `none` reads no milestone


def test_s028_11_a_named_milestone_holds_every_item_of_this_repo(ist: ModuleType) -> None:
    both = [carrier(301, "W-2", milestone="v1"), carrier(302, "W-3", milestone="v1")]
    assert filed(ist, "v1", both, existing="v1")[0] == ("PLAN_FILED", "filed: #301, #302")
    assert filed(ist, "v1", both, existing=None)[0] == ("PLAN_ACCEPTED", "not in milestone v1: #212")
    outside = [carrier(301, "W-2", milestone="v0"), carrier(302, "W-3", milestone="v1")]
    assert filed(ist, "v1", outside, existing="v1")[0] == ("PLAN_ACCEPTED", "not in milestone v1: #301")
    unfiled = [carrier(301, "W-2")]
    expected = ("PLAN_ACCEPTED", "not filed: W-3; not in milestone v1: #212, #301")
    assert filed(ist, "v1", unfiled, existing="v2")[0] == expected
    _, fake = filed(ist, "v1", both, existing="v1")
    asked = [q for q in fake.asked if re.search(r"\be\d+: issue\(", q)]
    assert len(asked) == 1 and "e212: issue(" in asked[0] and "e5:" not in asked[0]  # other/x#5 isn't this repo's


def test_s028_12_an_open_plan_check_refuses_reads_malformed(ist: ModuleType) -> None:
    no_kind = full_plan().replace("- W-4 existing:", "- W-4 chore:")
    assert state_of(ist, open_plan(20, body=no_kind)) == (
        "PLAN_MALFORMED",
        "line 14: a Work line is an item `- W-<n> <feature|fix|existing>: <text>`",
    )
    unlisted = open_plan(20, owner("accept", 10), body=full_plan(goal="G-9"))  # an accept doesn't help
    assert state_of(ist, unlisted) == (
        "PLAN_MALFORMED",
        "line 1: the marker names G-9, which docs/product.md doesn't list as a goal",
    )
    two = full_plan().replace("## Order", "## Plan")
    state, note = state_of(ist, open_plan(20, body=two))
    assert state == "PLAN_MALFORMED" and note.startswith("line 16: `## Plan` is not a plan heading")
    assert note.endswith(" more)")


def test_s028_12_a_plan_with_a_broken_marker_is_still_a_plan(ist: ModuleType) -> None:
    broken = open_plan(20, body=full_plan().replace(" rev=1", ""))
    assert state_of(ist, broken)[0] == "PLAN_MALFORMED"
    by_maintainer = open_plan(21, body=full_plan().replace(" rev=1", ""), author="maintainer", bot=False)
    assert state_of(ist, by_maintainer)[0] == "PLAN_MALFORMED"  # its first line opens the marker
    unmarked = open_plan(22, body="Please plan G-1")  # the App's own issue with no marker
    state, note = state_of(ist, unmarked)
    assert state == "PLAN_MALFORMED"
    assert note.startswith("line 1: the first line is the marker `<!-- shipmill:plan goal=G-<n> rev=<k> -->`")
    request = issue(23, title="Plan G-1", labels=("goal-plan",), association="OWNER", body="Please plan G-1")
    assert plan_states(ist, Fake([request], plans=[request])) == {}  # a request, not a plan


def test_s028_12_a_plan_closed_as_not_planned_reads_declined_with_the_reason(ist: ModuleType) -> None:
    declined = open_plan(20, owner("Decline: not this quarter\nMore later.", 10), state="CLOSED", reason="NOT_PLANNED")
    assert state_of(ist, declined) == ("PLAN_DECLINED", "not this quarter")
    closing = {**comment("Closing as declined.", author="shipmill-app", bot=True), "createdAt": "2026-10-02T09:59:00Z"}
    bare = open_plan(20, owner("decline", 10), closing, state="CLOSED", reason="NOT_PLANNED")
    assert state_of(ist, bare) == ("PLAN_DECLINED", "Closing as declined.")
    silent = open_plan(20, state="CLOSED", reason="NOT_PLANNED")
    assert state_of(ist, silent) == ("PLAN_DECLINED", "closed as not planned with no reason")
    malformed = open_plan(20, body="broken", state="CLOSED", reason="NOT_PLANNED")
    assert state_of(ist, malformed) == ("PLAN_DECLINED", "closed as not planned with no reason")
    done = open_plan(20, state="CLOSED", reason="COMPLETED")
    assert plan_states(ist, Fake(plans=[done])) == {}


def test_plan_rows_needing_action_exit_1(ist: ModuleType) -> None:
    assert {"PLAN_DUE", "PLAN_MALFORMED", "PLAN_ANSWERED", "PLAN_ACCEPTED"} == ist.PLAN_ACTION


def test_a_plans_older_comments_are_paged_back(ist: ModuleType) -> None:
    paged = open_plan(20, comment("+1", 12))
    paged["comments"]["pageInfo"] = {"hasPreviousPage": True, "startCursor": "c1"}
    older = {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": [owner("accept", 10)]}

    class Older(Fake):
        def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            if "before: $cursor" in query:
                assert variables["cursor"] == "c1" and variables["number"] == 20
                return {"data": {"repository": {"issue": {"comments": older}}}}
            return super().__call__(query, variables)

    assert plan_states(ist, Older(plans=[paged]))[20] == ("PLAN_ACCEPTED", "unfiled")
