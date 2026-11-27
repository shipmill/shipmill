"""Spec 107: `shipmill decision answer`, `goal-plan answer`, `project`, and `opportunity accept`
write the maintainer's relayed answer in the form its reader counts"""

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import answer
from shipmill.agent_marker import marked
from shipmill.answer import Comment, Item, Kind, Request
from shipmill.app_gh import LabelEdit
from shipmill.cli import main
from shipmill.decision_label import _triage, removing_refusal
from shipmill.errors import ReleaseError

from .conftest import guarded_home
from .test_app import FakeSigner
from .test_app_gh import WITH_APP, Host, checkout
from .test_app_token import FAKE_GH, MintApi, executable
from .test_plans import PLAN
from .test_pr_gate import load as load_pr_gate

BOT = "shipmill-demo[bot]"
MAINTAINERS = frozenset({"amy"})
QUESTION = (
    "<!-- shipmill:needs-decision -->\n@amy Decision needed: which way?\n\n"
    "1. Take every recommendation (recommended): it lands\n2. Keep it open: nothing lands\n"
)


def at(minute: int) -> str:
    return f"2026-11-20T10:{minute:02d}:00Z"


def item(
    labels: Sequence[str] = (), comments: Sequence[Comment] = (), body: str = "", open_: bool = True, number: int = 7
) -> Item:
    return Item(number, False, open_, frozenset(labels), body, at(0), tuple(comments))


def asked(body: str = QUESTION) -> Comment:
    return Comment(BOT, "NONE", marked(body), at(1))


def request(kind: Kind, answer_: str | None, **flags: str) -> Request:
    return Request(kind, 7, answer_, "amy", **flags)  # type: ignore[arg-type]


def decision(option: str | None, **flags: str) -> Request:
    return request(Kind.QUESTION, option, **flags)


def goal_plan(verb: str, **flags: str) -> Request:
    return request(Kind.PLAN, verb, **flags)


def project(verb: str, **flags: str) -> Request:
    return request(Kind.PROJECT, verb, **flags)


def opportunity(goal: str | None) -> Request:
    return request(Kind.OPPORTUNITY, "accept", **({} if goal is None else {"goal": goal}))


def compose(found: Item, req: Request, goals: frozenset[str] = frozenset({"G-1"})) -> answer.Composed:
    return answer.compose(found, req, BOT, MAINTAINERS, lambda: goals)


def posted(found: Item, body: str) -> Item:
    return Item(
        found.number,
        found.pull,
        found.open,
        found.labels,
        found.body,
        found.created_at,
        (*found.comments, Comment(BOT, "NONE", marked(body), at(30))),
    )


@dataclass
class FakeHub:
    found: Item
    login: str = BOT
    written: list[tuple[str, str]] = field(default_factory=list)

    def viewer(self) -> str:
        return self.login

    def item(self, number: int) -> Item:
        assert number == self.found.number
        return self.found

    def comment(self, found: Item, body: str) -> str:
        self.written.append(("comment", body))
        return f"https://github.com/o/r/issues/{found.number}#issuecomment-1"

    def unlabel(self, found: Item) -> None:
        self.written.append(("unlabel", answer.DECISION_LABEL))


def run(hub: FakeHub, req: Request) -> list[str]:
    said: list[str] = []
    assert answer.run(req, hub, MAINTAINERS, lambda: frozenset({"G-1"}), said.append) == 0
    return said


# proves: S-107-1
def test_s107_1_an_option_posts_the_relay_takes_the_label_off_and_prints_the_url() -> None:
    hub = FakeHub(item(["needs-decision"], [asked()]))
    said = run(hub, decision("2"))
    [(_, body), unlabel] = hub.written
    assert body.splitlines() == ["Decision by `@amy`, relayed by Claude Code", "", "2. Keep it open"]
    assert unlabel == ("unlabel", "needs-decision")
    assert said == ["https://github.com/o/r/issues/7#issuecomment-1"]


@pytest.mark.parametrize(
    ("given", "line"),
    [(decision("1"), "1. Take every recommendation"), (decision(None, own="only h2"), "own: only h2")],
)
@pytest.mark.parametrize("note", [None, "checked in the session"])
def test_s107_2_the_relay_is_counted_by_every_reader(given: Request, line: str, note: str | None) -> None:
    found = item(["needs-decision"], [asked()])
    req = Request(Kind.QUESTION, 7, given.answer, "amy", own=given.own, note=note)
    body = compose(found, req).body
    assert body.splitlines()[2] == line
    ts = _triage()
    rt = ts.retro_module()
    relay = rt.parse_relay(marked(body))
    assert relay.refused is None and rt.relay_refusal(QUESTION, relay) is None
    comments = posted(found, body).triage_comments()
    index, who = ts.relayed(comments, BOT)
    assert (index, who) == (1, "amy") and ts.relay_refused(comments, BOT, index) is None
    pg = load_pr_gate()
    reply = pg.whole_reply({"author": {"login": BOT}, "body": marked(body)}, frozenset({BOT}))
    assert reply == (None if given.own else line)  # pr_gate.py reads an option, and `own:` takes none
    # shipmill gh's label rule lets needs-decision come off after it (#1312)
    assert removing_refusal(comments, BOT, LabelEdit("gh issue edit", None, 7, False, True), "o/r") is None


@pytest.mark.parametrize(
    ("found", "req", "said"),
    [
        (item(["needs-decision"], [asked()]), decision("3"), "lists no option 3"),
        (item(["needs-decision"]), decision("1"), "no open needs-decision question"),
        (item(["needs-decision"], [asked(), Comment("amy", "OWNER", "2", at(2))]), decision("1"), "no open"),
        (item(["needs-decision"], [asked()]), decision(None, own="  "), "--own is empty"),
        (item(["needs-decision"], [asked()]), decision(None, own="a\nb"), "several lines"),
        (item(["goal-plan"], body=PLAN), goal_plan("decline", reason="a\nb"), "several lines"),
        (item(["needs-decision"], [asked()]), Request(Kind.QUESTION, 7, "1", "amy", note="x\ny"), "several lines"),
    ],
)
def test_s107_3_an_answer_no_question_counts_is_refused(found: Item, req: Request, said: str) -> None:
    hub = FakeHub(found)
    with pytest.raises(ReleaseError, match=said):
        answer.run(req, hub, MAINTAINERS, lambda: frozenset(), print)
    assert hub.written == []


def plan_read(body: str) -> tuple[object, ...]:
    """How intake_state.py reads the plan after the comment: its answer's kind and what it holds"""
    intake = answer._intake()
    node = posted(item(["goal-plan"], body=PLAN), body).node()
    found = intake.plan_answer(node, BOT, answer.MARKER, MAINTAINERS)
    first = intake.PLANS.first_line(found.body)
    if found.kind == "accept":
        return ("accept", intake.read_accept(first, ("W-1", "W-2", "W-3", "W-4")).kept)
    if found.kind == "hold":
        return ("hold", intake.read_hold(found).until)
    if found.kind == "decline":
        return ("decline", intake.decline_text(found))
    return (found.kind, first)


@pytest.mark.parametrize(
    ("req", "line", "read"),
    [
        (goal_plan("accept"), "accept", ("accept", ("W-1", "W-2", "W-3", "W-4"))),
        (goal_plan("accept", only="W-1,W-3"), "accept W-1, W-3", ("accept", ("W-1", "W-3"))),
        (goal_plan("accept", excepted="W-2"), "accept except W-2", ("accept", ("W-1", "W-3", "W-4"))),
        (goal_plan("decline", reason="not this quarter"), "decline: not this quarter", ("decline", "not this quarter")),
        (goal_plan("hold", until="2026-12-15"), "hold until 2026-12-15", ("hold", "2026-12-15")),
        (goal_plan("hold", until="#12"), "hold until #12", ("hold", "#12")),
        (goal_plan("hold", until="release"), "hold until release", ("hold", "release")),
        (goal_plan("send-back", reason="split W-1 in two"), "split W-1 in two", ("edit", "split W-1 in two")),
    ],
)
def test_s107_4_a_plans_answers_read_as_intake_reads_them(req: Request, line: str, read: tuple[object, ...]) -> None:
    body = compose(item(["goal-plan"], body=PLAN), req).body
    assert body.splitlines()[2] == line
    assert plan_read(body) == read


def test_s107_4_a_held_plan_reads_held_with_its_wake_condition_in_status_item() -> None:
    body = compose(item(["goal-plan"], body=PLAN), goal_plan("hold", until="2026-12-15")).body
    intake = answer._intake()
    node = posted(item(["goal-plan"], body=PLAN), body).node()
    found = intake.plan_answer(node, BOT, answer.MARKER, MAINTAINERS)
    hold = intake.read_hold(found)
    assert hold is not None and hold.date == dt.date(2026, 12, 15)
    # intake's PLAN_HELD row, the one `shipmill status --item` names (spec 098): held, until its condition
    state, note, held = intake.held_row(node, found, BOT, lambda _: intake.HoldMet(None))
    assert (state, note, held) == ("PLAN_HELD", "until 2026-12-15", ("2026-12-15", None))


@pytest.mark.parametrize(
    ("found", "req", "said"),
    [
        (item(["goal-plan"], body=PLAN), goal_plan("accept", only="W-9"), "W-9 is not in the plan"),
        (item(["goal-plan"], body=PLAN), goal_plan("accept", only="W-1,W-1"), "named twice"),
        (item(["goal-plan"], body=PLAN), goal_plan("accept", excepted="W-1,W-2,W-3,W-4"), "drops every item"),
        (item(["goal-plan"], body=PLAN), goal_plan("hold"), "needs --until"),
        (item(["goal-plan"], body=PLAN), goal_plan("hold", until="next week"), "not one wake condition"),
        (item(["goal-plan"], body=PLAN), goal_plan("decline"), "needs --reason"),
        (item(["goal-plan"], body=PLAN), goal_plan("send-back"), "needs --reason"),
        (item(["goal-plan"], body=PLAN), goal_plan("send-back", reason="accept it all"), "may not start with"),
        (item(["goal-plan"], body=PLAN), goal_plan("send-back", reason="Hold until May"), "may not start with"),
        (item(["goal-plan"], body=PLAN), goal_plan("send-back", reason="hold  until 2027-01-01"), "may not start with"),
        (item(["goal-plan"], body=PLAN), goal_plan("send-back", reason="hold\tuntil #5"), "may not start with"),
        (item(["goal-plan"], body=PLAN), goal_plan("send-back", reason="ACCEPT."), "may not start with"),
        (item(["goal-plan"], body=PLAN, open_=False), goal_plan("accept"), "is closed"),
    ],
)
def test_s107_5_a_plan_answer_its_reader_wouldnt_count_is_refused(found: Item, req: Request, said: str) -> None:
    hub = FakeHub(found)
    with pytest.raises(ReleaseError, match=said):
        answer.run(req, hub, MAINTAINERS, lambda: frozenset(), print)
    assert hub.written == []


@pytest.mark.parametrize(
    ("req", "line"),
    [
        (project("continue"), "continue"),
        (project("hold"), "hold"),
        (project("stop", reason="merged elsewhere"), "stop: merged elsewhere"),
    ],
)
def test_s107_6_a_projects_answers_and_its_stop(req: Request, line: str) -> None:
    head = item(["project"])
    body = compose(head, req).body
    assert body.splitlines()[2] == line
    intake = answer._intake()
    reason = intake.stop_reason(posted(head, body).node(), BOT, answer.MARKER, MAINTAINERS)
    assert reason == ("merged elsewhere" if line.startswith("stop:") else None)


def test_s107_6_a_project_answer_on_its_idle_question_takes_the_label_off() -> None:
    idle = "<!-- shipmill:needs-decision -->\n@amy Decision needed: idle\n\n1. continue\n2. hold\n3. stop\n"
    head = item(["project", "needs-decision"], [asked(idle)])
    composed = compose(head, project("stop", reason="done"))
    assert composed.unlabel and composed.body.splitlines()[2] == "stop: done"


@pytest.mark.parametrize(
    ("found", "req", "said"),
    [
        (item(["project"]), project("stop"), "needs --reason"),
        (item(["project"], open_=False), project("continue"), "is closed"),
    ],
)
def test_s107_6_a_stop_without_a_reason_and_a_closed_head_are_refused(found: Item, req: Request, said: str) -> None:
    with pytest.raises(ReleaseError, match=said):
        compose(found, req)


@pytest.mark.parametrize(
    ("goal", "line", "read"),
    [("G-1", "accept G-1", "G-1"), ("g-1", "accept G-1", "G-1"), ("new", "accept new goal", "new goal")],
)
def test_s107_7_an_accepted_opportunitys_goal(goal: str, line: str, read: str) -> None:
    found = item(["opportunity", "planned"])
    body = compose(found, opportunity(goal)).body
    assert body.splitlines()[2] == line
    intake = answer._intake()
    assert intake.accept_goal(posted(found, body).node(), answer.MARKER, BOT, MAINTAINERS) == read


@pytest.mark.parametrize(
    ("found", "req", "said"),
    [
        (item(["opportunity"]), opportunity("G-1"), "the `planned` label is the maintainer's accept"),
        (item(["opportunity", "planned"]), opportunity("G-2"), "G-2 is no open goal"),
        (item(["opportunity", "planned"]), opportunity(None), "needs the goal it serves"),
    ],
)
def test_s107_7_an_opportunity_its_reader_wouldnt_count_is_refused(found: Item, req: Request, said: str) -> None:
    with pytest.raises(ReleaseError, match=said):
        compose(found, req)  # only G-1 is an open goal of kind goal


@pytest.mark.parametrize(
    ("found", "req", "said"),
    [
        (item(["goal-plan"], body=PLAN), Request(Kind.PLAN, 7, "accept", "bob"), "--by bob is not the maintainer"),
        (item(["goal-plan"], body=PLAN), goal_plan("stop", reason="x"), "`stop` doesn't answer a goal-plan"),
        (item(["project"]), goal_plan("accept"), "isn't labelled `goal-plan`"),
        (item(), project("stop", reason="x"), "isn't labelled `project`"),
        (item(["opportunity", "planned"]), decision(None, own="x"), "no open needs-decision question"),
        (item(["project"]), request(Kind.PROJECT, "continue", own="x"), "--own answers a needs-decision question"),
        (item(["goal-plan"], body=PLAN), goal_plan("accept", until="release"), "takes no --until"),
        (item(["needs-decision"], [asked()]), decision("1", reason="x"), "takes no --reason"),
    ],
)
def test_s107_8_a_wrong_maintainer_kind_or_flag_is_refused(found: Item, req: Request, said: str) -> None:
    hub = FakeHub(found)
    with pytest.raises(ReleaseError, match=said):
        answer.run(req, hub, MAINTAINERS, lambda: frozenset(), print)
    assert hub.written == []


@dataclass
class FakeGh:
    """gh as `shipmill gh` runs it, its output captured: the viewer, an open plan #7, its
    comments, then the comment's URL"""

    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv[1:])
        self.calls.append(args)
        if args[:2] == ["api", "graphql"]:
            return 0, f"{BOT}\n"
        if args[:2] == ["api", "--paginate"]:
            return 0, ""
        if args[0] == "api":
            issue = {"state": "open", "labels": [{"name": "goal-plan"}], "body": PLAN, "created_at": at(0)}
            return 0, json.dumps(issue)
        return 0, "https://github.com/o/r/issues/7#issuecomment-1\n"


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record = tmp_path / "record"
    record.mkdir()
    return Host(fakes, record, guarded_home(tmp_path / "home"))


def cli(root: Path, host: Host, gh: FakeGh, *args: str) -> int:
    return main(
        ["--repo", str(root), "goal-plan", "answer", "7", "accept", "--by", "amy", *args],
        api=MintApi(expires_from=dt.datetime.now(dt.UTC)),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_capture=gh,
        login=lambda: "amy",
    )


def test_s107_9_without_the_apps_key_it_exits_2_and_writes_nothing(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh = FakeGh()
    with pytest.raises(ReleaseError, match="no App private key at"):
        cli(root, host, gh)
    assert gh.calls == []


def test_s107_9_with_identity_none_it_exits_2_with_the_owners_choice(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "none"\n')
    gh = FakeGh()
    with pytest.raises(ReleaseError, match="owner chose that agents don.t write to GitHub here"):
        cli(root, host, gh)
    assert not any(call[0] in ("issue", "pr") for call in gh.calls)  # reads only, never a write


# proves: S-107-10
def test_s107_10_dry_run_prints_the_comment_and_the_label_step_and_writes_nothing() -> None:
    hub = FakeHub(item(["needs-decision"], [asked()]))
    said = run(hub, Request(Kind.QUESTION, 7, "1", "amy", note="seen", dry_run=True))
    assert said == [
        "Decision by `@amy`, relayed by Claude Code\n\n1. Take every recommendation\n\nNote: seen",
        "needs-decision: comes off",
    ]
    assert hub.written == []


# proves: S-107-11
@pytest.mark.parametrize(
    "doc",
    [
        "skills/github-issue-triage/references/needs-decision.md",
        "skills/product-intake/references/plan.md",
        "skills/product-intake/SKILL.md",
        "docs/flow.md",
    ],
)
def test_s107_11_the_protocols_name_the_command(doc: str) -> None:
    root = Path(__file__).resolve().parents[1]
    assert re.search(r"shipmill(?:==[0-9.]+)? (?:decision|goal-plan) answer", (root / doc).read_text(encoding="utf-8"))


def test_s107_6_a_stale_needs_decision_label_with_no_open_question_doesnt_block_the_answer() -> None:
    head = item(["project", "needs-decision"])
    hub = FakeHub(head)
    run(hub, project("hold"))
    assert [kind for kind, _ in hub.written] == ["comment"]  # the label stays: no question to answer
