"""`shipmill status --item` on a goal, a plan issue, and a project head: its state, who holds
it, and what moves it, as one spec 094 condition (spec 106, S-106-25); without gh or the network"""

import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.item_status import GoalRef, Holder, Ref, Who, explain, explain_goal, parse_item
from shipmill.status import Facts, Issue, Row

from .test_status_item import NONE, Fake
from .test_status_picture import REPO, VERSION_JSON, facts, host, repo_with_release
from .test_status_plan_waits import BOT, INTAKE_STATE, intake_lines, load
from .test_watch_goal_states import first, head, spec106_lines
from .test_watch_plans import WATCH_STATE


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(WATCH_STATE, "watch_state_status_goal_states")


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load(INTAKE_STATE, "intake_state_status_goal_states")


def status_rows(ws: ModuleType, text: str) -> list[Row]:
    """The watch's --item rows for these intake lines, as `shipmill status` parses them"""
    found = [*ws.plans_rows(text, REPO, BOT).rows, *ws.item_states(text, REPO, BOT)]
    return [Row(r.state, r.subject, r.detail, bool(r.json()["agent"]), r.fix) for r in found]


def read(ws: ModuleType, ist: ModuleType) -> Facts:
    issues = [
        Issue(60, "TRIAGED", verdict="plan"),
        Issue(61, "TRIAGED", verdict="plan"),
        Issue(62, "TRIAGED", verdict="plan"),
        Issue(53, "BLOCKED", note="project #53 held"),
        Issue(54, "BLOCKED", note="project #54 held"),
        Issue(80, "BLOCKED", note="project #53 held"),
        Issue(55, "TRIAGED"),
        Issue(51, "TRIAGED"),
        Issue(45, "TRIAGED"),
    ]
    return facts(*status_rows(ws, spec106_lines(ist)), issues=issues)


def conditions(found: Facts, number: int) -> list[tuple[str, Who, str]]:
    return [
        (c.reason, c.who, c.clears)
        for c in explain(found, Ref(str(number), number, None), lambda _: NONE, None).conditions
    ]


def goal_of(found: Facts, goal: str) -> tuple[str, list[tuple[str, Who, str]]]:
    why = explain_goal(found, GoalRef(goal, goal))
    return why.bucket, [(c.reason, c.who, c.clears) for c in why.conditions]


def test_s106_25_a_goal_names_its_state_holder_and_what_moves_it(ws: ModuleType, ist: ModuleType) -> None:
    found = read(ws, ist)
    assert goal_of(found, "G-2")[0] == "overdue"
    assert goal_of(found, "G-2")[1][0] == (
        "past its horizon 2026-11-01: waits on a session to ask you to extend, rewrite, or drop it",
        Who.AGENT,
        "a gate session opens its goal-review question, then you extend, rewrite, or drop the goal",
    )
    assert goal_of(found, "G-1") == (
        "written",
        [
            (
                "written: its plan #60 waits on your answer",
                Who.MAINTAINER,
                "answer plan #60; shipmill status --item 60 says what holds it",
            )
        ],
    )
    assert goal_of(found, "G-3") == (
        "planned",
        [("planned: its projects run (#51)", Who.AGENT, "its last project closing, when its check is read again")],
    )
    bucket, ((reason, who, _),) = goal_of(found, "G-4")
    assert (bucket, reason, who) == ("met", "met: the direction records it met", Who.EVENT)
    record = explain_goal(found, GoalRef("G-1", "G-1")).record()
    assert record["kind"] == "goal" and record["goal"] == "G-1" and record["bucket"] == "written"
    assert record["conditions"] == [
        {
            "reason": "written: its plan #60 waits on your answer",
            "who": "maintainer",
            "clears": "answer plan #60; shipmill status --item 60 says what holds it",
            "holder": "maintainer",
        }
    ]
    with pytest.raises(ReleaseError, match="G-9 is no goal of kind goal"):
        explain_goal(found, GoalRef("G-9", "G-9"))
    # a goal proposal's issue reads as the proposal
    assert conditions(found, 45)[0][:2] == ("a goal proposal: waits on your answer", Who.MAINTAINER)


def test_s106_25_a_plan_names_its_answer_date_overdue_past_it(ws: ModuleType, ist: ModuleType) -> None:
    found = read(ws, ist)
    assert conditions(found, 61)[0] == (
        "triaged as plan: answer due 2026-11-20, overdue",
        Who.MAINTAINER,
        "accept, change, decline, or hold the plan; while it is overdue no held project of the product starts",
    )
    assert conditions(found, 60)[0][:2] == (
        "triaged as plan: waits on the maintainer's answer to the plan, answer by 2026-12-01",
        Who.MAINTAINER,
    )
    assert conditions(found, 62)[0][:2] == (
        "triaged as plan: replaced by #63, waits on product intake to close it",
        Who.AGENT,
    )


def test_s106_25_a_held_project_names_what_it_waits_for(ws: ModuleType, ist: ModuleType) -> None:
    held = Issue(53, "BLOCKED", note="project #53 held")
    # a plan of the product overdue holds every start
    found = read(ws, ist)
    assert conditions(found, 53) == [
        ("held: plan #61 overdue", Who.MAINTAINER, "answer plan #61, then its turn to start")
    ]
    # no plan overdue, every slot taken
    full = intake_lines(head(ist, 53, "PROJECT_HELD", "labelled held")).replace(
        '{"autonomy": "propose"}', first(ist, active=2, limit=2)
    )
    found = facts(*status_rows(ws, full), issues=[held])
    ((reason, who, _),) = conditions(found, 53)
    assert (reason, who) == ("held: a free slot: 2 of 2 active", Who.EVENT)
    assert explain(found, Ref("53", 53, None), lambda _: NONE, None).conditions[0].holder is Holder.POSTPONED
    # room, and the maintainer's held label
    room = intake_lines(head(ist, 53, "PROJECT_HELD", "labelled held")).replace(
        '{"autonomy": "propose"}', first(ist, active=1, limit=2)
    )
    found = facts(*status_rows(ws, room), issues=[held])
    assert conditions(found, 53)[0][:2] == ("held: held by the maintainer", Who.MAINTAINER)
    # a part of a held project waits for its head
    found = read(ws, ist)
    assert conditions(found, 80)[0][:2] == ("its project #53 is held", Who.EVENT)


def test_s106_25_an_open_head_names_its_state(ws: ModuleType, ist: ModuleType) -> None:
    found = read(ws, ist)
    assert conditions(found, 55)[0] == (
        "closing: its work is done, and check #72 waits to be run",
        Who.PERSON,
        "someone other than the builder runs check #72 and closes it",
    )
    assert conditions(found, 51)[0][:2] == (
        "no change for 14 days: waits on a session to ask you to continue, hold, or stop it",
        Who.AGENT,
    )
    active = intake_lines(head(ist, 56, "PROJECT_FOCUS", "1 of 3 parts open", check=73))
    found = facts(*status_rows(ws, active), issues=[Issue(56, "TRIAGED")])
    assert conditions(found, 56)[0][:2] == ("a project in focus: your steps on it come first", Who.MAINTAINER)


def test_s106_25_an_unreadable_state_row_is_refused(ws: ModuleType, ist: ModuleType) -> None:
    for state in ("GOAL_STATE", "PLAN_STATE", "PROJECT_STATE"):
        bad = facts(Row(state, REPO, "#1 SOMETHING", False, None), issues=[Issue(1, "TRIAGED", verdict="plan")])
        with pytest.raises(ReleaseError, match=f"{state} row is unreadable"):
            conditions(bad, 1) if state != "GOAL_STATE" else explain_goal(bad, GoalRef("G-1", "G-1"))


def test_s106_25_item_takes_a_goal_id() -> None:
    assert parse_item("G-3", REPO) == GoalRef("G-3", "G-3")
    assert parse_item("12", REPO) == Ref("12", 12, None)
    with pytest.raises(ReleaseError, match="a goal id"):
        parse_item("goal 3", REPO)


class GoalFake(Fake):
    """The picture's reads, with the watch's --item G-2 rows: G-2's state and its PLANS action"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("watch_state.py") and "--item" in cmd:
            self.seen.append(cmd)
            rows: list[dict[str, object]] = [
                {"state": "GOAL_STATE", "subject": REPO, "detail": "G-2 GOAL_OVERDUE holder=agent by=2026-11-01"},
                {"state": "PLANS", "subject": REPO, "detail": "GOAL_OVERDUE G-2", "agent": True, "fix": "x"},
            ]
            lines = [{"agent": False, "fix": None, **r} for r in rows] + [VERSION_JSON]
            text = "".join(json.dumps(r) + "\n" for r in lines)
            return subprocess.CompletedProcess(cmd, 0, text, "")
        return super().__call__(cmd)


def test_s106_25_status_item_explains_a_goal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo_with_release(tmp_path / "repo")
    fake = GoalFake()
    assert main(["--repo", str(root), "status", "--item", "G-2"], state=fake, login=host) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{REPO} G-2 (https://github.com/{REPO}/blob/HEAD/docs/product.md): overdue\n")
    assert "  why:  past its horizon 2026-11-01: waits on a session to ask you to extend, rewrite, or drop it\n" in out
    (watch,) = [c for c in fake.seen if c[1].endswith("watch_state.py")]
    assert watch[watch.index("--item") + 1] == "G-2"
    assert not any(c[1].endswith("triage_state.py") for c in fake.seen)  # a goal is no issue: none read
    assert main(["--repo", str(root), "status", "--item", "G-2", "--json"], state=GoalFake(), login=host) == 0
    record = json.loads(capsys.readouterr().out)
    assert (record["kind"], record["goal"], record["bucket"]) == ("goal", "G-2", "overdue")
    assert record["conditions"][0]["who"] == "agent"
    with pytest.raises(ReleaseError, match="G-7 is no goal of kind goal"):
        main(["--repo", str(root), "status", "--item", "G-7"], state=GoalFake(), login=host)
