"""intake_state.py --plans: the goals a plan is due for (spec 028, #510), without gh or the network"""

import importlib.util
import re
import subprocess
import sys
from collections.abc import Mapping
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


def triaged(body: str) -> dict[str, Any]:
    """A triage comment by a member: only a trusted one serves a goal (D-16, #1384)"""
    return comment(body, association="MEMBER", author="maintainer")


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


def reported(plan_issue: dict[str, Any], missing: str = "- nothing") -> dict[str, Any]:
    """The plan closed as completed, with the App's outcome comment after its close (spec 097)"""
    body = f"<!-- shipmill:plan-outcome -->\nThe work closed.\n\nHolds:\n- nothing\n\nStill missing:\n{missing}\n"
    outcome = {**comment(body, author="shipmill-app", bot=True), "createdAt": "2026-10-02T10:05:00Z"}
    plan_issue["comments"]["nodes"].append(outcome)
    return plan_issue


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
        states: Mapping[int, tuple[str, str | None]] | None = None,
        parents: Mapping[int, tuple[str, int] | None] | None = None,
    ) -> None:
        self.opened = opened or []
        self.opportunities = opportunities or []
        self.plans = plans or []
        self.pulls = pulls or []
        self.specs = specs or {}
        self.carriers = carriers or []  # the issues the plan-item marker search finds
        self.milestones = milestones or {}  # each existing item's milestone
        self.states = states or {}  # each item's issue (state, stateReason), open when not given (spec 097)
        # each existing item's parent (owner/name, number), None for none; when not given, the
        # plan whose items were read last, so an existing item is its sub-issue (#1706)
        self.parents = parents or {}
        self.plan = 0
        self.asked: list[str] = []

    @staticmethod
    def page(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.asked.append(query)
        if "search(type: ISSUE" in query:
            (plan_issue,) = [p for p in self.plans if p["number"] == variables["number"]]
            self.plan = plan_issue["number"]
            subs = {"pageInfo": {"hasNextPage": False}, "nodes": []}
            found = {"issueCount": len(self.carriers), "nodes": self.carriers}
            repo_issue = {"number": plan_issue["number"], "body": plan_issue["body"], "subIssues": subs}
            return {"data": {"repository": {"issue": repo_issue}, "search": found}}
        numbers = [int(n) for n in re.findall(r"\be(\d+): issue\(", query)]
        if numbers:
            titles = {n: self.milestones[n] for n in numbers}
            aliased = {f"e{n}": {"milestone": {"title": t} if t else None} for n, t in titles.items()}
            return {"data": {"repository": aliased}}
        states = [int(n) for n in re.findall(r"\bs(\d+): issue\(", query)]
        if states:
            found_states = {n: self.states.get(n, ("OPEN", None)) for n in states}
            nodes = {f"s{n}": {"state": s, "stateReason": r} for n, (s, r) in found_states.items()}
            return {"data": {"repository": nodes}}
        parented = [int(n) for n in re.findall(r"\bp(\d+): issue\(", query)]
        if parented:
            found_parents = {n: self.parents.get(n, ("o/r", self.plan)) for n in parented}
            parent_nodes = {
                f"p{n}": {"parent": None if p is None else {"number": p[1], "repository": {"nameWithOwner": p[0]}}}
                for n, p in found_parents.items()
            }
            return {"data": {"repository": parent_nodes}}
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
    request = issue(5, triaged("Triage: **feature**. Serves: G-1, G-2. A thing"))
    pull = "## Plan\n\n- Serves: G-3\n- Files: x\n- Order: y\n- Proof: z\n"
    assert due(ist, Fake([request])) == {"G-3": ("PLAN_DUE", "no-work")}
    assert due(ist, Fake(pulls=[pull])) == {"G-1": ("PLAN_DUE", "no-work"), "G-2": ("PLAN_DUE", "no-work")}
    opp = issue(7, body="Serves: G-2\n\n## Problem\n\nSlow.\n", labels=("opportunity",))
    assert set(due(ist, Fake(opportunities=[opp]))) == {"G-1", "G-3"}
    specs = {"030-a.md": spec("draft", "G-1"), "031-b.md": spec("approved", "G-2, G-3")}
    assert due(ist, Fake(specs=specs)) == {}


def test_s028_1_closed_built_or_unrelated_work_serves_nothing(ist: ModuleType) -> None:
    fake = Fake(
        [
            # the newest verdict counts
            issue(5, triaged("Triage: **feature**. Serves: G-1."), triaged("Triage: **implement**. A fix")),
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
    accepted = reported(plan(20, "G-1", state="CLOSED", reason="COMPLETED"))  # S-097-6: with its outcome
    item = issue(21, body="<!-- shipmill:plan-item #20 W-1 -->\nA feature.", author="shipmill-app", bot=True)
    assert set(due(ist, Fake([item], plans=[accepted]))) == {"G-2", "G-3"}
    member = issue(22, body="<!-- shipmill:plan-item #20 W-2 -->\nA fix.", association="MEMBER")
    assert set(due(ist, Fake([member], plans=[accepted]), bot_login=None)) == {"G-2", "G-3"}
    stranger = issue(23, body="<!-- shipmill:plan-item #20 W-1 -->\nA feature.")  # D-29: no marker of theirs
    assert set(due(ist, Fake([stranger], plans=[accepted]))) == {"G-1", "G-2", "G-3"}


def test_s028_2_no_work_is_not_raised_after_a_declined_newest_plan(ist: ModuleType) -> None:
    declined = plan(20, "G-1", state="CLOSED", reason="NOT_PLANNED")
    assert set(due(ist, Fake(plans=[declined]))) == {"G-2", "G-3"}
    redone = reported(plan(30, "G-1", state="CLOSED", reason="COMPLETED"))  # newer, done, outcome posted: again
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
    served = issue(5, triaged("Triage: **feature**. Serves: G-2."))  # a request plans a served goal too
    assert due(ist, Fake([request, served]))["G-2"] == ("PLAN_DUE", "requested in #25")


@pytest.mark.parametrize("association", ["CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE"])
def test_s028_3_anyone_elses_goal_plan_issue_is_no_request(ist: ModuleType, association: str) -> None:
    request = issue(25, title="Plan G-2", labels=("goal-plan",), association=association, author="drive-by")
    served = issue(5, triaged("Triage: **feature**. Serves: G-2."))
    assert "G-2" not in due(ist, Fake([request, served]))


def test_s028_3_a_request_names_exactly_one_listed_goal(ist: ModuleType) -> None:
    served = issue(5, triaged("Triage: **feature**. Serves: G-1, G-2, G-3."))
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
    served = issue(5, triaged("Triage: **feature**. Serves: G-1, G-2, G-3."))
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
    served = issue(5, triaged("Triage: **feature**. Serves: G-1, G-2, G-3."))

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


HOME_REFUSED = (
    "shipmill: acme/home's product direction can't be read, so nothing of this component's is given either: "
    "the read token can't be minted: no key; fix: put the App's key at ~/.shipmill/app.pem, "
    "or pass --local to read only this checkout's docs/product.md (spec 071)\n"
)
OWN_GOALS = '{"goals": [{"id": "G-1", "text": "Ship", "measure": null, "serves": []}]}'


def component_uvx(ran: list[list[str]]) -> Any:
    """A stub uvx in a component whose product home can't be read: `shipmill product show`
    exits 2 with spec 071's refusal (S-071-7) unless --local is passed"""

    def execute(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        if "--local" not in cmd:
            return subprocess.CompletedProcess(cmd, 2, "", HOME_REFUSED)
        return subprocess.CompletedProcess(cmd, 0, OWN_GOALS, "")

    return execute


def test_plans_read_the_components_own_goals_so_an_unreadable_home_never_stops_them(ist: ModuleType) -> None:
    """#1417: parse_goals reads only the direction's own goals, so --plans runs `product show`
    with --local (S-071-8) and a product home it can't read no longer stops the script"""
    ran: list[list[str]] = []
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        run=Fake(),
    )
    found = ist.fetch_plans(
        "o/r",
        intake,
        goals=ist.uvx_goals("shipmill==1.2.3", component_uvx(ran)),
        marker="Triage:",
        bot_login=BOT,
        wip=None,
        room=lambda limit: 1,
        run=Fake(),
    )
    assert [(r.goal, r.state, r.note) for r in found] == [("G-1", "PLAN_DUE", "no-work")]
    assert ran == [
        ["uvx", "--from", "shipmill==1.2.3", "shipmill", "product", "show", "--section", "goals", "--json", "--local"]
    ]


@pytest.mark.parametrize(
    ("code", "out", "err"),
    [
        (2, "", "shipmill: docs/product.md:3: a goal item is G-n: text\n"),  # this repo's own direction
        (1, "", "shipmill: something else\n"),
        (0, "not json", ""),
    ],
)
def test_any_product_show_failure_still_exits_2(ist: ModuleType, code: int, out: str, err: str) -> None:
    def execute(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, code, out, err)

    with pytest.raises(SystemExit) as stopped:
        ist.uvx_goals("shipmill==1.2.3", execute)()
    assert stopped.value.code == 2


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


def revised(rev: int, hour: int, *, association: str | None = None) -> dict[str, Any]:
    """A plan-revised comment by the --bot-login, or with an association by a person"""
    body = f"<!-- shipmill:plan-revised rev={rev} -->\nRevised as asked."
    if association is None:
        return comment(body, hour, author="shipmill-app", bot=True)
    return comment(body, hour, author="maintainer", association=association)


def plan_states(
    ist: ModuleType,
    fake: Fake,
    *,
    bot_login: str | None = BOT,
    filing: Any = None,
    maintainers: frozenset[str] = frozenset(),
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
        maintainers=maintainers,
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
        ("accept.. but split W-2", "unclear accept: words past the ids"),  # spec 096: an unclear accept
        ("accepted", "edit"),
        ("accept W-2 only", "unclear accept: words past the ids"),
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


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR", "NONE"])
def test_s028_9_only_the_bot_login_revises(ist: ModuleType, association: str) -> None:
    by_person = open_plan(20, owner("accept", 10), revised(2, 11, association=association))
    assert state_of(ist, by_person) == ("PLAN_ACCEPTED", "unfiled")  # no revision, and no answer either
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


# -- an answer given in a session, relayed by the App (#917, D-68)

MAINTAINERS = frozenset({"maintainer"})
AGENT = "\n\n<!-- shipmill:agent -->"


def relay(answer: str, hour: int, *, named: str = "`@maintainer`", bot: bool = True) -> dict[str, Any]:
    """The needs-decision relay of an answer, as `shipmill gh` posts it with the agent marker"""
    body = f"Decision by {named}, relayed by Claude Code\n\n{answer}{AGENT}"
    if bot:
        return comment(body, hour, author="shipmill-app", bot=True)
    return comment(body, hour, author="maintainer", association="OWNER")


@pytest.mark.parametrize("named", ["`@maintainer`", "@maintainer", "@Maintainer", "`@MAINTAINER`"])
@pytest.mark.parametrize("answer", ["accept", "Accept.", "  ACCEPT  "])
def test_s028_18_a_relayed_accept_naming_a_maintainer_reads_accepted(ist: ModuleType, named: str, answer: str) -> None:
    relayed = open_plan(20, relay(answer, 10, named=named))
    assert state_of(ist, relayed, maintainers=MAINTAINERS) == ("PLAN_ACCEPTED", "unfiled")


@pytest.mark.parametrize(
    ("answer", "note"),
    [
        ("decline: not this quarter", "decline"),
        ("Decline", "decline"),
        ("Split W-2 in two", "edit"),
        ("accept W-2 only", "unclear accept: words past the ids"),  # spec 096: an unclear accept
    ],
)
def test_s028_18_a_relayed_decline_or_edit_reads_answered(ist: ModuleType, answer: str, note: str) -> None:
    relayed = open_plan(20, relay(answer, 10))
    assert state_of(ist, relayed, maintainers=MAINTAINERS) == ("PLAN_ANSWERED", note)


def test_s028_18_the_answer_is_the_first_non_blank_line_after_the_relay(ist: ModuleType) -> None:
    body = "Decision by @maintainer, relayed by Claude Code\n\n\n  accept\nThe rest is context." + AGENT
    spaced = open_plan(20, comment(body, 10, author="shipmill-app", bot=True))
    assert state_of(ist, spaced, maintainers=MAINTAINERS) == ("PLAN_ACCEPTED", "unfiled")
    empty = open_plan(
        20, comment("Decision by @maintainer, relayed by Claude Code" + AGENT, 10, author="shipmill-app", bot=True)
    )
    assert state_of(ist, empty, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")  # the marker is no answer


def test_s028_18_a_relayed_declines_reason_leaves_the_agent_marker_out(ist: ModuleType) -> None:
    closed = {"state": "CLOSED", "reason": "NOT_PLANNED"}
    reasoned = open_plan(20, relay("decline: not this quarter", 10), **closed)
    assert state_of(ist, reasoned, maintainers=MAINTAINERS) == ("PLAN_DECLINED", "not this quarter")
    bare = open_plan(20, relay("decline", 10), **closed)
    assert state_of(ist, bare, maintainers=MAINTAINERS) == ("PLAN_DECLINED", "closed as not planned with no reason")


def test_d93_a_relayed_plan_answer_ends_at_a_note_line(ist: ModuleType) -> None:
    """#1261: a `Note:` line ends what is read of a relay, as retro.py's parse_relay reads one"""
    closed = {"state": "CLOSED", "reason": "NOT_PLANNED"}
    noted = open_plan(20, relay("decline\n\nNote: the maintainer said so in chat", 10), **closed)
    assert state_of(ist, noted, maintainers=MAINTAINERS) == ("PLAN_DECLINED", "closed as not planned with no reason")
    reasoned = open_plan(20, relay("decline: not this quarter\n\nnote: checked\n\nmore", 10), **closed)
    assert state_of(ist, reasoned, maintainers=MAINTAINERS) == ("PLAN_DECLINED", "not this quarter")
    only = open_plan(20, relay("Note: nothing was answered", 10))
    assert state_of(ist, only, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")  # no answer before it
    inline = open_plan(20, relay("decline Note: inline\n\nNote: x", 10), **closed)
    assert state_of(ist, inline, maintainers=MAINTAINERS) == ("PLAN_DECLINED", "Note: inline")  # ends nothing
    split = relay("Split W-2 in two\nKeep W-3\n\nNote: relayed from the session", 10)
    assert ist.relayed_answer(split, BOT, "Triage:", MAINTAINERS) == "Split W-2 in two\nKeep W-3"


def test_s028_18_a_relay_older_than_the_newest_revision_is_stale(ist: ModuleType) -> None:
    stale = open_plan(20, relay("Split W-2", 10), revised(2, 11))
    assert state_of(ist, stale, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")
    again = open_plan(20, relay("Split W-2", 10), revised(2, 11), relay("accept", 12))
    assert state_of(ist, again, maintainers=MAINTAINERS) == ("PLAN_ACCEPTED", "unfiled")


def test_s028_18_the_newest_answer_decides_relayed_or_not(ist: ModuleType) -> None:
    later_owner = open_plan(20, relay("accept", 10), owner("decline", 11))
    assert state_of(ist, later_owner, maintainers=MAINTAINERS) == ("PLAN_ANSWERED", "decline")
    later_relay = open_plan(20, owner("Split W-2", 10), relay("accept", 11))
    assert state_of(ist, later_relay, maintainers=MAINTAINERS) == ("PLAN_ACCEPTED", "unfiled")


def test_s028_18_an_edit_after_a_relayed_accept_reads_open(ist: ModuleType) -> None:
    stale = open_plan(20, relay("accept", 10), edited="2026-10-01T10:00:01Z")
    assert state_of(ist, stale, maintainers=MAINTAINERS) == ("PLAN_OPEN", "edited after accept")


@pytest.mark.parametrize("named", ["`@collaborator`", "@maintainer-x", "`@maintainerx`", "@someone"])
def test_s028_18_a_relay_naming_anyone_else_changes_nothing(ist: ModuleType, named: str) -> None:
    other = open_plan(
        20, comment("ok", 9, association="COLLABORATOR", author="collaborator"), relay("accept", 10, named=named)
    )
    assert state_of(ist, other, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")


def test_s028_18_without_a_maintainer_role_no_relay_counts(ist: ModuleType) -> None:
    assert state_of(ist, open_plan(20, relay("accept", 10))) == ("PLAN_OPEN", "")
    no_login = open_plan(20, relay("accept", 10))
    assert state_of(ist, no_login, bot_login=None, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")


def test_s028_18_only_the_bot_logins_relay_is_one(ist: ModuleType) -> None:
    # anyone else's relay line is a comment like any other: a trusted one's is an edit, an outsider's nothing
    by_owner = open_plan(20, relay("accept", 10, bot=False))
    assert state_of(ist, by_owner, maintainers=MAINTAINERS) == ("PLAN_ANSWERED", "edit")
    body = "Decision by `@maintainer`, relayed by Claude Code\n\naccept"
    outsider = open_plan(20, comment(body, 10, association="CONTRIBUTOR", author="drive-by"))
    assert state_of(ist, outsider, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")


@pytest.mark.parametrize(
    "body",
    [
        "accept" + AGENT,
        "I relayed it: Decision by `@maintainer`, relayed by Claude Code\n\naccept",
        "<!-- shipmill:needs-decision -->\nDecision by `@maintainer`, relayed by Claude Code\n\naccept",
    ],
)
def test_s028_18_any_other_app_comment_is_still_never_an_answer(ist: ModuleType, body: str) -> None:
    app = open_plan(20, comment(body, 10, author="shipmill-app", bot=True))
    assert state_of(ist, app, maintainers=MAINTAINERS) == ("PLAN_OPEN", "")


def test_s028_18_the_relay_pattern_is_triage_states(ist: ModuleType) -> None:
    path = SCRIPT.parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
    spec = importlib.util.spec_from_file_location("triage_state_relay", path)
    assert spec is not None and spec.loader is not None
    triage = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = triage
    spec.loader.exec_module(triage)
    assert ist.DECISION_BY.pattern == triage.DECISION_BY.pattern
    assert ist.NOTE_START == triage.retro_module().NOTE_START  # D-93: one place Note: ends a relay
    for values in (["maintainer=alice,@o/t", "dev=bob"], ["maintainer=Alice,alice"]):
        assert ist.maintainer_logins(values) == frozenset(
            u.lower() for u in triage.parse_roles(values)["maintainer"][0]
        )
    for bad in (["dev=bob"], ["maintainer="], ["maintainer=a", "maintainer=b"], ["Maintainer=a"], ["maintainer=a b"]):
        with pytest.raises(ValueError):
            triage.parse_roles(bad)
        with pytest.raises(ValueError):
            ist.maintainer_logins(bad)
    assert ist.maintainer_logins([]) == frozenset()


@pytest.mark.parametrize(
    "args",
    [["--role", "maintainer=alice"], ["--plans", "--role", "dev=bob"], ["--plans", "--role", "maintainer=a b"]],
)
def test_s028_18_a_bad_role_flag_exits_2_before_any_read(args: list[str]) -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "o/r", *args], capture_output=True, text=True, check=False)
    assert proc.returncode == 2 and "--role" in proc.stderr


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
    done = reported(open_plan(20, state="CLOSED", reason="COMPLETED"))  # S-097-3: its outcome posted
    assert plan_states(ist, Fake(plans=[done])) == {}


def test_plan_rows_needing_action_exit_1(ist: ModuleType) -> None:
    actions = {"PLAN_DUE", "PLAN_MALFORMED", "PLAN_ANSWERED", "PLAN_ACCEPTED", "PLAN_DONE", "PLAN_HOLD_MET"}
    assert actions == ist.PLAN_ACTION  # PLAN_HOLD_MET: spec 098


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


# -- a finished plan says whether the goal moved (spec 097, #1710)


def work_done(
    ist: ModuleType, states: Mapping[int, tuple[str, str | None]], milestone: str = "none", existing: str | None = None
) -> Any:
    """Plan #20 accepted with W-2 and W-3 filed as #301 and #302; W-1 is #212 and W-4 other/x#5"""
    accepted = open_plan(20, owner("accept", 10), body=full_plan(milestone=milestone))
    carriers = [carrier(301, "W-2", milestone=existing), carrier(302, "W-3", milestone=existing)]
    fake = Fake(plans=[accepted], carriers=carriers, milestones={212: existing}, states=states)
    return plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake))[20], fake


def test_s097_1_an_accepted_plan_whose_work_closed_reads_done(ist: ModuleType) -> None:
    closed = {212: ("CLOSED", "COMPLETED"), 301: ("CLOSED", "NOT_PLANNED"), 302: ("CLOSED", "COMPLETED")}
    note = "work closed: W-1 #212 completed, W-2 #301 not planned, W-3 #302 completed"
    assert work_done(ist, closed)[0] == ("PLAN_DONE", note)
    assert work_done(ist, closed, milestone="v1", existing="v1")[0] == ("PLAN_DONE", note)
    assert "PLAN_DONE" in ist.PLAN_ACTION  # exit 1
    duplicate = {**closed, 302: ("CLOSED", "DUPLICATE"), 212: ("CLOSED", None)}
    assert work_done(ist, duplicate)[0] == (
        "PLAN_DONE",
        "work closed: W-1 #212 closed, W-2 #301 not planned, W-3 #302 duplicate",
    )


@pytest.mark.parametrize("still_open", [212, 301, 302])
def test_s097_1_with_an_item_still_open_it_reads_filed(ist: ModuleType, still_open: int) -> None:
    closed = {n: ("CLOSED", "COMPLETED") for n in (212, 301, 302) if n != still_open}
    assert work_done(ist, closed)[0] == ("PLAN_FILED", "filed: #301, #302")


def test_s097_1_partial_accept_kept_items_only(ist: ModuleType) -> None:
    """S-096-6 with S-097-1: a dropped item neither holds a partly accepted plan open nor counts"""

    def read(carriers: list[dict[str, Any]], states: Mapping[int, tuple[str, str | None]]) -> Any:
        accepted = open_plan(20, owner("accept except W-3", 10))
        fake = Fake(plans=[accepted], carriers=carriers, states=states)
        return plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake))[20], fake

    closed = {212: ("CLOSED", "COMPLETED"), 301: ("CLOSED", "COMPLETED")}
    done = ("PLAN_DONE", "work closed: W-1 #212 completed, W-2 #301 completed; dropped: W-3")
    assert read([carrier(301, "W-2")], closed)[0] == done  # the dropped W-3 stays unfiled
    by_hand, fake = read([carrier(301, "W-2"), carrier(302, "W-3")], closed)  # a dropped item filed, still open
    assert by_hand == done
    assert not any("s302:" in q for q in fake.asked)  # never read
    still_open = {212: ("CLOSED", "COMPLETED")}
    assert read([carrier(301, "W-2")], still_open)[0] == ("PLAN_FILED", "filed: #301; dropped: W-3")


def test_s097_1_states_are_read_only_once_the_plan_reads_filed(ist: ModuleType) -> None:
    accepted = open_plan(20, owner("accept", 10), body=full_plan())
    fake = Fake(plans=[accepted], carriers=[carrier(301, "W-2")])
    assert plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake))[20] == ("PLAN_ACCEPTED", "not filed: W-3")
    assert not any(re.search(r"\bs\d+: issue\(", q) for q in fake.asked)


def test_s097_2_an_existing_item_of_another_repo_is_never_read(ist: ModuleType) -> None:
    closed = {212: ("CLOSED", "COMPLETED"), 301: ("CLOSED", "COMPLETED"), 302: ("CLOSED", "COMPLETED")}
    (state, note), fake = work_done(ist, closed)
    assert state == "PLAN_DONE" and "W-4" not in note  # other/x#5, open or not, holds nothing
    asked = [q for q in fake.asked if re.search(r"\bs\d+: issue\(", q)]
    assert len(asked) == 1 and "s212: issue(" in asked[0] and "s5:" not in asked[0]


def test_s097_3_the_newest_completed_plan_without_an_outcome_reads_done(ist: ModuleType) -> None:
    older = open_plan(20, state="CLOSED", reason="COMPLETED")
    newest = open_plan(30, state="CLOSED", reason="COMPLETED")
    assert plan_states(ist, Fake(plans=[older, newest])) == {30: ("PLAN_DONE", "closed without an outcome")}
    assert plan_states(ist, Fake(plans=[older, reported(open_plan(30, state="CLOSED", reason="COMPLETED"))])) == {}
    declined = open_plan(30, state="CLOSED", reason="NOT_PLANNED")
    assert plan_states(ist, Fake(plans=[older, declined])) == {
        30: ("PLAN_DECLINED", "closed as not planned with no reason")
    }
    other_goal = open_plan(40, body=full_plan(goal="G-2"), state="CLOSED", reason="COMPLETED")
    assert plan_states(ist, Fake(plans=[older, other_goal])) == {
        20: ("PLAN_DONE", "closed without an outcome"),
        40: ("PLAN_DONE", "closed without an outcome"),
    }


def outcome_by(minutes: int, **who: Any) -> dict[str, Any]:
    """An outcome comment the given minutes after the plan's close (negative: before it)"""
    body = "<!-- shipmill:plan-outcome -->\nThe work closed.\n\nStill missing:\n- nothing"
    agent = who.pop("agent", False)
    made = comment(body + (AGENT if agent else ""), **who)
    minute = 60 + minutes
    stamp = f"2026-10-02T{9 + minute // 60:02d}:{minute % 60:02d}:00Z"
    return {**made, "createdAt": stamp}


@pytest.mark.parametrize(
    ("outcome", "counts"),
    [
        (outcome_by(5, author="shipmill-app", bot=True), True),
        (outcome_by(5, author="shipmill-app", bot=True, agent=True), True),
        (outcome_by(0, author="maintainer", association="OWNER"), True),
        (outcome_by(5, author="maintainer", association="MEMBER"), True),
        (outcome_by(5, author="maintainer", association="COLLABORATOR"), True),
        (outcome_by(5, author="maintainer", association="MEMBER", agent=True), False),  # D-62: an agent's text
        (outcome_by(5, author="drive-by", association="CONTRIBUTOR"), False),
        (outcome_by(5, author="drive-by", association="NONE"), False),
        (outcome_by(-5, author="shipmill-app", bot=True), False),  # before the last close
    ],
)
def test_s097_4_only_a_trusted_outcome_after_the_close_counts(
    ist: ModuleType, outcome: dict[str, Any], counts: bool
) -> None:
    done = open_plan(30, outcome, state="CLOSED", reason="COMPLETED")
    assert plan_states(ist, Fake(plans=[done])) == ({} if counts else {30: ("PLAN_DONE", "closed without an outcome")})


def test_s097_4_the_first_line_is_the_marker(ist: ModuleType) -> None:
    quoted = {**outcome_by(5, author="shipmill-app", bot=True)}
    quoted["body"] = "As said:\n<!-- shipmill:plan-outcome -->\nStill missing:\n- nothing"
    done = open_plan(30, quoted, state="CLOSED", reason="COMPLETED")
    assert plan_states(ist, Fake(plans=[done])) == {30: ("PLAN_DONE", "closed without an outcome")}
    no_login = open_plan(30, outcome_by(5, author="shipmill-app", bot=True), state="CLOSED", reason="COMPLETED")
    assert plan_states(ist, Fake(plans=[no_login]), bot_login=None) == {30: ("PLAN_DONE", "closed without an outcome")}


def test_s097_6_no_no_work_row_while_the_newest_plan_reads_done(ist: ModuleType) -> None:
    done = plan(30, "G-1", state="CLOSED", reason="COMPLETED")
    assert set(due(ist, Fake(plans=[done]))) == {"G-2", "G-3"}
    assert set(due(ist, Fake(plans=[done]), wip=1, room=0)) == {"G-2", "G-3"}  # no PLAN_WAITS either
    request = issue(25, title="Plan G-1", labels=("goal-plan",), association="OWNER")
    assert due(ist, Fake([request], plans=[done]))["G-1"] == ("PLAN_DUE", "requested in #25")  # a request still is
    filed_open = plan(40, "G-1")  # a newer open plan: its goal reads nothing
    assert set(due(ist, Fake(plans=[done, filed_open]))) == {"G-2", "G-3"}


# -- accepting part of a plan in one reply (spec 096, #1708)

ALL = ["W-1", "W-2", "W-3", "W-4"]


def plan_rows_of(ist: ModuleType, fake: Fake, *, filing: Any = None, **kwargs: Any) -> dict[Any, Any]:
    """Each row's --json line, by plan number for a plan issue's row and by goal for a goal's"""
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
        bot_login=kwargs.get("bot_login", BOT),
        wip=None,
        room=lambda limit: 1,
        run=fake,
        filing=filing if filing is not None else (lambda issue, plan: ("PLAN_ACCEPTED", "unfiled")),
        maintainers=kwargs.get("maintainers", frozenset()),
    )
    return {(r.number if r.kind == "plan" else r.goal): ist.plan_json(r) for r in found}


def answered(ist: ModuleType, *comments: str | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """The --json line of plan #20 (full_plan's W-1 to W-4) with these comments"""
    found: dict[str, Any] = plan_rows_of(ist, Fake(plans=[open_plan(20, *comments)]), **kwargs)[20]
    return found


@pytest.mark.parametrize("first", ["accept W-1, W-3", "Accept w-1 w-3", "ACCEPT W-1,W-3.", "accept W-3 ,  W-1"])
def test_s096_1_accept_naming_ids_keeps_them_and_drops_the_rest(ist: ModuleType, first: str) -> None:
    row = answered(ist, owner(f"{first}\nW-2 can wait.", 10))
    assert (row["state"], row["note"]) == ("PLAN_ACCEPTED", "unfiled; dropped: W-2, W-4")
    assert (row["kept"], row["dropped"]) == (["W-1", "W-3"], ["W-2", "W-4"])


@pytest.mark.parametrize("first", ["accept except W-2", "Accept EXCEPT w-2.", "accept except,W-2"])
def test_s096_2_accept_except_drops_the_ids_and_keeps_the_rest(ist: ModuleType, first: str) -> None:
    row = answered(ist, owner(first, 10))
    assert (row["state"], row["note"]) == ("PLAN_ACCEPTED", "unfiled; dropped: W-2")
    assert (row["kept"], row["dropped"]) == (["W-1", "W-3", "W-4"], ["W-2"])


@pytest.mark.parametrize("first", ["accept", "Accept.", "accept W-1, W-2, W-3, W-4", "accept W-4 W-3 W-2 W-1."])
def test_s096_3_a_full_accept_keeps_every_item_and_names_no_drop(ist: ModuleType, first: str) -> None:
    row = answered(ist, owner(first, 10))
    assert (row["state"], row["note"], row["kept"], row["dropped"]) == ("PLAN_ACCEPTED", "unfiled", ALL, [])


def test_s096_3_only_an_accepted_row_has_kept_and_dropped(ist: ModuleType) -> None:
    for comments in ((), (owner("Split W-2", 10),), (owner("accept W-9", 10),)):
        row = answered(ist, *comments)
        assert "kept" not in row and "dropped" not in row, row


@pytest.mark.parametrize(
    ("first", "rule"),
    [
        ("accept W-9", "W-9 is not in the plan"),
        ("accept W-1, w-01", "W-01 is not in the plan"),
        ("accept W-1, W-3, w-1", "W-1 is named twice"),
        ("accept except", "no item named"),
        ("accept except.", "no item named"),
        ("accept ,", "no item named"),
        ("accept except W-1 W-2, W-3, W-4", "drops every item"),
        ("accept W-1 except W-2", "both a kept and a dropped list"),
        ("accept W-1, W-3 for now", "words past the ids"),
        ("accept: W-1", "words past the ids"),
        ("accept-ish", "words past the ids"),
    ],
)
def test_s096_4_an_unclear_accept_reads_answered_with_its_rule(ist: ModuleType, first: str, rule: str) -> None:
    row = answered(ist, owner(f"{first}\nThanks.", 10))
    assert (row["state"], row["note"]) == ("PLAN_ANSWERED", f"unclear accept: {rule}")
    assert row["state"] in ist.PLAN_ACTION  # exit 1


@pytest.mark.parametrize("first", ["accepted", "Accepted W-1, W-3", "acceptable", "Acceptable except W-2"])
def test_s096_4_accepted_or_acceptable_is_still_an_edit(ist: ModuleType, first: str) -> None:
    row = answered(ist, owner(first, 10))
    assert (row["state"], row["note"]) == ("PLAN_ANSWERED", "edit")


def asked(hour: int, *, bot: bool = True) -> dict[str, Any]:
    """The needs-decision question on an unclear accept, by the --bot-login or by a maintainer"""
    body = "<!-- shipmill:needs-decision -->\n@maintainer Decision needed: `accept W-9` names no item." + AGENT
    if bot:
        return comment(body, hour, author="shipmill-app", bot=True)
    return comment(body, hour, author="maintainer", association="OWNER")


def test_s096_5_the_bot_logins_question_makes_an_unclear_accept_wait(ist: ModuleType) -> None:
    row = answered(ist, owner("accept W-9", 10), asked(11))
    assert (row["state"], row["note"]) == ("PLAN_OPEN", "unclear accept asked")
    assert row["state"] not in ist.PLAN_ACTION


@pytest.mark.parametrize(
    ("answer", "state", "note"),
    [
        ("accept W-1, W-3", "PLAN_ACCEPTED", "unfiled; dropped: W-2, W-4"),
        ("decline: not now", "PLAN_ANSWERED", "decline"),
        ("Split W-2", "PLAN_ANSWERED", "edit"),
        ("accept W-8", "PLAN_ANSWERED", "unclear accept: W-8 is not in the plan"),  # newer than the question
    ],
)
def test_s096_5_an_answer_after_the_question_is_read_anew(ist: ModuleType, answer: str, state: str, note: str) -> None:
    row = answered(ist, owner("accept W-9", 10), asked(11), owner(answer, 12))
    assert (row["state"], row["note"]) == (state, note)


def test_s096_5_anyone_elses_or_an_older_question_changes_nothing(ist: ModuleType) -> None:
    unclear = ("PLAN_ANSWERED", "unclear accept: W-9 is not in the plan")
    for comments in (
        (owner("accept W-9", 10), asked(11, bot=False)),  # a maintainer's marker
        (asked(10), owner("accept W-9", 11)),  # older than the unclear accept
        (owner("accept W-9", 10), comment("<!-- shipmill:needs-decision -->\nx", 11, author="drive-by")),
    ):
        row = answered(ist, *comments)
        assert (row["state"], row["note"]) == unclear
    no_login = answered(ist, owner("accept W-9", 10), asked(11), bot_login=None)
    assert (no_login["state"], no_login["note"]) == unclear


def partly(ist: ModuleType, first: str, milestone: str, carriers: list[dict[str, Any]], existing: str | None) -> Any:
    accepted = open_plan(20, owner(first, 10), body=full_plan(milestone=milestone))
    fake = Fake(plans=[accepted], carriers=carriers, milestones={212: existing})
    row = plan_rows_of(ist, fake, filing=ist.gh_filing("o/r", BOT, fake))[20]
    return (row["state"], row["note"]), fake


def test_s096_6_the_filing_reads_the_kept_items_alone(ist: ModuleType) -> None:
    kept_w2 = [carrier(301, "W-2", milestone="v1")]
    assert partly(ist, "accept except W-3", "v1", kept_w2, "v1")[0] == ("PLAN_FILED", "filed: #301; dropped: W-3")
    by_hand = [*kept_w2, carrier(302, "W-3", milestone="v0")]  # a dropped item someone filed by hand
    assert partly(ist, "accept except W-3", "v1", by_hand, "v1")[0] == ("PLAN_FILED", "filed: #301; dropped: W-3")
    expected = ("PLAN_ACCEPTED", "not filed: W-3; dropped: W-1, W-2, W-4")
    assert partly(ist, "accept W-3", "v1", [], None)[0] == expected
    _, fake = partly(ist, "accept W-3", "v1", [], None)
    assert not any(re.search(r"\be\d+: issue\(", q) for q in fake.asked)  # the dropped W-1 is never read
    outside = ("PLAN_ACCEPTED", "not filed: W-3; not in milestone v1: #212; dropped: W-2, W-4")
    assert partly(ist, "accept W-1, W-3", "v1", [], None)[0] == outside
    stray = ("PLAN_ACCEPTED", "not in milestone v1: #301; dropped: W-1, W-3, W-4")
    assert partly(ist, "accept W-2", "v1", [carrier(301, "W-2", milestone="v0")], None)[0] == stray
    assert partly(ist, "accept W-2", "none", [carrier(301, "W-2")], None)[0] == (
        "PLAN_FILED",
        "filed: #301; dropped: W-1, W-3, W-4",
    )


@pytest.mark.parametrize(
    ("answer", "kept", "dropped"),
    [("accept W-1, W-3", ["W-1", "W-3"], ["W-2", "W-4"]), ("accept except W-2", ["W-1", "W-3", "W-4"], ["W-2"])],
)
def test_s096_7_a_relayed_partial_accept_reads_the_same(
    ist: ModuleType, answer: str, kept: list[str], dropped: list[str]
) -> None:
    row = answered(ist, relay(answer, 10), maintainers=MAINTAINERS)
    assert (row["state"], row["kept"], row["dropped"]) == ("PLAN_ACCEPTED", kept, dropped)


def test_s096_7_a_relayed_unclear_accept_is_unclear_and_anyone_elses_relay_nothing(ist: ModuleType) -> None:
    row = answered(ist, relay("accept W-1 except W-2", 10), maintainers=MAINTAINERS)
    assert (row["state"], row["note"]) == ("PLAN_ANSWERED", "unclear accept: both a kept and a dropped list")
    other = answered(ist, relay("accept W-1, W-3", 10, named="`@someone`"), maintainers=MAINTAINERS)
    assert (other["state"], other["note"]) == ("PLAN_OPEN", "")


def test_s096_8_a_partial_accept_goes_stale_as_an_accept_does(ist: ModuleType) -> None:
    edited = open_plan(20, owner("accept W-1, W-3", 10), edited="2026-10-01T10:00:01Z")
    row = plan_rows_of(ist, Fake(plans=[edited]))[20]
    assert (row["state"], row["note"]) == ("PLAN_OPEN", "edited after accept")
    assert "kept" not in row
    revision = answered(ist, owner("accept except W-2", 10), revised(2, 11))
    assert (revision["state"], revision["note"]) == ("PLAN_OPEN", "")
    by_person = answered(ist, owner("accept except W-2", 10), revised(2, 11, association="OWNER"))
    assert by_person["state"] == "PLAN_ACCEPTED"  # only the --bot-login revises


def closed_plan(number: int, first: str | None, reason: str, goal: str = "G-1") -> dict[str, Any]:
    comments = [owner(first, 10)] if first else []
    return open_plan(number, *comments, body=full_plan(goal=goal), state="CLOSED", reason=reason)


def test_s096_9_a_due_plan_lists_what_earlier_plans_dropped(ist: ModuleType) -> None:
    plans = [  # each goal's newest plan has its outcome: without one its goal reads no PLAN_DUE (S-097-6)
        reported(closed_plan(24, "accept W-1, W-3", "COMPLETED")),
        closed_plan(20, "accept except W-2", "COMPLETED"),
        closed_plan(21, "accept", "COMPLETED"),  # fully accepted: none
        closed_plan(22, "accept W-1", "NOT_PLANNED"),  # its decline holds: none
        closed_plan(23, "accept W-9", "COMPLETED"),  # unclear: none
        reported(closed_plan(25, "accept W-2", "COMPLETED", goal="G-2")),
    ]
    rows = plan_rows_of(ist, Fake(plans=plans))
    assert rows["G-1"]["state"] == "PLAN_DUE"
    assert rows["G-1"]["dropped"] == [
        {"plan": 20, "id": "W-2", "text": "A release cut"},
        {"plan": 24, "id": "W-2", "text": "A release cut"},
        {"plan": 24, "id": "W-4", "text": "other/x#5"},
    ]
    assert [d["id"] for d in rows["G-2"]["dropped"]] == ["W-1", "W-3", "W-4"]
    assert rows["G-2"]["dropped"][1] == {"plan": 25, "id": "W-3", "text": "The lane stalls"}
    assert rows["G-3"]["dropped"] == [] and "kept" not in rows["G-3"]


def test_s096_9_an_open_plans_drop_counts_and_a_closed_plans_comments_are_paged(ist: ModuleType) -> None:
    open_one = open_plan(20, owner("accept except W-2", 10))
    found = ist.dropped_items([open_one], frozenset({"G-1"}), "Triage:", BOT, frozenset())
    assert found == {"G-1": ({"plan": 20, "id": "W-2", "text": "A release cut"},)}
    done = reported(closed_plan(20, None, "COMPLETED"))  # its outcome posted (S-097-6)
    done["comments"]["pageInfo"] = {"hasPreviousPage": True, "startCursor": "c1"}
    older = {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": [owner("accept W-2", 10)]}

    class Older(Fake):
        def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            if "before: $cursor" in query:
                return {"data": {"repository": {"issue": {"comments": older}}}}
            return super().__call__(query, variables)

    rows = plan_rows_of(ist, Older(plans=[done]))
    assert [d["id"] for d in rows["G-1"]["dropped"]] == ["W-1", "W-3", "W-4"]


def goal_rows(ist: ModuleType, fake: Fake, *, wip: int | None = None, room: int = 1) -> dict[str, dict[str, Any]]:
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
        wip=wip,
        room=lambda limit: room,
        run=fake,
    )
    return {r.goal: ist.plan_json(r) for r in found if r.kind == "goal"}


def test_s097_7_the_next_plan_follows_the_finished_one(ist: ModuleType) -> None:
    missing = "- the release cut runs on its own\n- the lane reports a stall"
    done = reported(plan(30, "G-1", state="CLOSED", reason="COMPLETED"), missing)
    row = goal_rows(ist, Fake(plans=[plan(20, "G-1", state="CLOSED", reason="COMPLETED"), done]))["G-1"]
    assert (row["state"], row["note"], row["follows"]) == ("PLAN_DUE", "no-work; follows #30", 30)
    assert row["missing"] == ["the release cut runs on its own", "the lane reports a stall"]
    waits = goal_rows(ist, Fake(plans=[done]), wip=1, room=0)["G-1"]
    assert (waits["state"], waits["note"], waits["follows"]) == (
        "PLAN_WAITS",
        "no-work; waits for room; follows #30",
        30,
    )
    request = issue(25, title="Plan G-1", labels=("goal-plan",), association="OWNER")
    requested = goal_rows(ist, Fake([request], plans=[done]))["G-1"]
    assert (requested["note"], requested["missing"]) == ("requested in #25; follows #30", missing_items(missing))
    assert "follows" not in goal_rows(ist, Fake(plans=[done]))["G-2"]


def missing_items(text: str) -> list[str]:
    return [line[2:] for line in text.splitlines()]


def test_s097_7_nothing_missing_is_an_empty_list(ist: ModuleType) -> None:
    done = reported(plan(30, "G-1", state="CLOSED", reason="COMPLETED"))
    row = goal_rows(ist, Fake(plans=[done]))["G-1"]
    assert (row["follows"], row["missing"]) == (30, [])
    assert ist.still_missing("Still missing:\n\n- Nothing\n") == ()
    assert ist.still_missing("Holds:\n- a\n\nStill missing:\n- b\n- c\n\n<!-- shipmill:agent -->") == ("b", "c")
    assert ist.still_missing("No list here") == ()


def test_s097_3_a_finished_plans_comments_are_paged_back(ist: ModuleType) -> None:
    done = open_plan(30, comment("+1", 12), state="CLOSED", reason="COMPLETED")
    done["comments"]["pageInfo"] = {"hasPreviousPage": True, "startCursor": "c1"}
    outcome = outcome_by(5, author="shipmill-app", bot=True)
    older = {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": [outcome]}

    class Older(Fake):
        def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            if "before: $cursor" in query:
                assert variables["number"] == 30
                return {"data": {"repository": {"issue": {"comments": older}}}}
            return super().__call__(query, variables)

    assert plan_states(ist, Older(plans=[done])) == {}


# -- an accepted plan's existing items become its sub-issues (D-114, #1706)


def existing_plan() -> str:
    """A plan whose items are all existing: two of this repo's, one of another repo"""
    return full_plan().replace(
        "- W-1 existing: #212\n- W-2 feature: A release cut\n- W-3 fix: The lane stalls (after W-2)\n"
        "- W-4 existing: other/x#5\n",
        "- W-1 existing: #212\n- W-2 existing: #213\n- W-3 existing: other/x#5\n",
    )


def linked(
    ist: ModuleType,
    parents: Mapping[int, tuple[str, int] | None],
    *,
    answer: str = "accept",
    body: str = "",
    states: Mapping[int, tuple[str, str | None]] | None = None,
) -> Any:
    accepted = open_plan(20, owner(answer, 10), body=body or existing_plan())
    fake = Fake(plans=[accepted], parents=parents, states=states)
    return plan_states(ist, fake, filing=ist.gh_filing("o/r", BOT, fake))[20], fake


def test_1706_an_accepted_plan_reads_accepted_until_its_existing_items_are_its_sub_issues(ist: ModuleType) -> None:
    assert linked(ist, {212: None, 213: None})[0] == ("PLAN_ACCEPTED", "not linked: #212, #213")
    assert linked(ist, {213: None})[0] == ("PLAN_ACCEPTED", "not linked: #213")  # #212 is the plan's already
    done, fake = linked(ist, {})  # both are #20's sub-issues: nothing left to do, nothing new to file
    assert done == ("PLAN_FILED", "nothing to file")
    # one batched read of this repo's existing items, never another repo's
    (asked,) = [q for q in fake.asked if re.search(r"\bp\d+: issue\(", q)]
    assert "p212: issue(" in asked and "p213: issue(" in asked and "p5:" not in asked
    assert "parent" in asked
    # beside work still to file, the note names both
    mixed = linked(ist, {212: None}, body=full_plan())[0]
    assert mixed == ("PLAN_ACCEPTED", "not filed: W-2, W-3; not linked: #212")


def test_1706_a_closed_existing_item_is_linked_too_before_the_plan_reads_done(ist: ModuleType) -> None:
    closed = {212: ("CLOSED", "COMPLETED"), 213: ("CLOSED", "NOT_PLANNED")}
    assert linked(ist, {212: None}, states=closed)[0] == ("PLAN_ACCEPTED", "not linked: #212")
    note = "work closed: W-1 #212 completed, W-2 #213 not planned"
    assert linked(ist, {}, states=closed)[0] == ("PLAN_DONE", note)  # S-097-1 once they are its children


def test_1706_an_existing_item_with_another_parent_is_named_and_never_holds_the_plan(ist: ModuleType) -> None:
    other = {212: ("o/r", 99), 213: ("other/x", 20)}  # another issue of this repo, and #20 of another repo
    assert linked(ist, other)[0] == ("PLAN_FILED", "nothing to file; another parent: #212, #213")
    mixed = linked(ist, {212: ("o/r", 99), 213: None})[0]
    assert mixed == ("PLAN_ACCEPTED", "not linked: #213; another parent: #212")
    assert linked(ist, {212: ("O/R", 20), 213: None})[0] == ("PLAN_ACCEPTED", "not linked: #213")  # any case


def test_1706_a_partial_accept_links_its_kept_existing_items_alone(ist: ModuleType) -> None:
    (state, note), fake = linked(ist, {212: None, 213: None}, answer="accept except W-2")
    assert (state, note) == ("PLAN_ACCEPTED", "not linked: #212; dropped: W-2")
    assert not any("p213:" in q for q in fake.asked)  # a dropped existing item is never read
    kept = linked(ist, {213: None}, answer="accept W-1, W-3")[0]
    assert kept == ("PLAN_FILED", "nothing to file; dropped: W-2")
