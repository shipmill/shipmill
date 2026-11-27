"""Spec 108: `shipmill project add`, `focus`, `unfocus`, `hold`, and `resume` write the
maintainer's move as a relay, then its label, and refuse a move the head's reader wouldn't count"""

import datetime as dt
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill import answer, moves
from shipmill.answer import Comment, Item
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.moves import Head, Projects, Request, Verb

from .test_answer import QUESTION, at, host
from .test_app import FakeSigner
from .test_app_gh import WITH_APP, Host, checkout
from .test_app_token import MintApi
from .test_intake_projects import check, head

BOT = "shipmill-demo[bot]"
MAINTAINERS = frozenset({"amy"})
URL = "https://github.com/o/r/issues/7#issuecomment-1"

__all__ = ["host"]  # the fixture, shared with spec 107's tests


def issue(
    labels: Sequence[str] = ("project",),
    comments: Sequence[Comment] = (),
    open_: bool = True,
    pull: bool = False,
    title: str = "Ship the plan page",
) -> Item:
    return Item(7, pull, open_, frozenset(labels), "", at(0), tuple(comments), title)


def heads(state: str = "PROJECT_ACTIVE", check_issue: int | None = 50, **slots: int) -> Projects:
    found = {7: Head(7, state, check_issue)}
    if not slots:
        return Projects(found)
    return Projects(found, slots["limit"], slots["active"], slots["room"])


@dataclass
class FakeHub:
    found: Item
    read: Projects = field(default_factory=heads)
    login: str = BOT
    fail_label: int | None = None
    written: list[tuple[str, str]] = field(default_factory=list)

    def viewer(self) -> str:
        return self.login

    def item(self, number: int) -> Item:
        if number == 51:  # a closed check issue
            return Item(51, False, False, frozenset(), "", at(0), ())
        if number == 50:  # an open check issue
            return Item(50, False, True, frozenset(), "", at(0), ())
        assert number == self.found.number
        return self.found

    def comment(self, found: Item, body: str) -> str:
        self.written.append(("comment", body))
        return URL

    def unlabel(self, found: Item) -> None:
        self.written.append(("unlabel", answer.DECISION_LABEL))

    def label(self, found: Item, add: str | None, remove: str | None) -> None:
        if self.fail_label is not None:
            raise moves.StepFailed("gh issue edit exited 4", self.fail_label)
        self.written.append(("add", add) if add is not None else ("remove", remove or ""))

    def projects(self, bot_login: str) -> Projects:
        assert bot_login == self.login
        return self.read

    def close(self, found: Item) -> None:
        if self.fail_label is not None:
            raise moves.StepFailed("gh issue close exited 4", self.fail_label)
        self.written.append(("close", "not planned"))


def run(hub: FakeHub, verb: Verb, by: str = "amy", **flags: Any) -> list[str]:
    said: list[str] = []
    assert moves.run(Request(verb, 7, by, **flags), hub, MAINTAINERS, said.append) == 0
    return said


def relay(line: str) -> str:
    return f"Decision by `@amy`, relayed by Claude Code\n\n{line}"


def node_after(labels: tuple[str, ...], subs: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    """The head as intake_state.py reads it once the App labelled it project (S-106: a head the
    --bot-login labelled counts)"""
    return head(labels=labels, association="NONE", author="someone", labelled_by=BOT, subs=subs)


def state(node: dict[str, Any]) -> tuple[str, str]:
    row = answer._intake().project_row(node, BOT)
    assert row is not None
    return row.state, row.note


# proves: S-108-1
def test_s108_1_add_posts_the_relay_then_labels_the_issue_project() -> None:
    hub = FakeHub(issue(labels=()))
    assert run(hub, Verb.ADD) == [URL]
    assert hub.written == [("comment", relay("project")), ("add", "project")]
    assert state(node_after(("project",))) == ("PROJECT_HELD", "no check issue")


# proves: S-108-2
@pytest.mark.parametrize(
    ("verb", "before", "line", "step", "after", "read"),
    [
        (Verb.FOCUS, ("project",), "focus", ("add", "focus"), ("project", "focus"), "PROJECT_FOCUS"),
        (Verb.UNFOCUS, ("project", "focus"), "unfocus", ("remove", "focus"), ("project",), "PROJECT_ACTIVE"),
        (Verb.HOLD, ("project",), "hold", ("add", "held"), ("project", "held"), "PROJECT_HELD"),
        (Verb.RESUME, ("project", "held"), "resume", ("remove", "held"), ("project",), "PROJECT_ACTIVE"),
    ],
)
def test_s108_2_each_move_posts_its_relay_and_moves_its_label(
    verb: Verb,
    before: tuple[str, ...],
    line: str,
    step: tuple[str, str],
    after: tuple[str, ...],
    read: str,
) -> None:
    hub = FakeHub(issue(labels=before))
    assert run(hub, verb) == [URL]
    assert hub.written == [("comment", relay(line)), step]
    found = state(node_after(after, (check(),)))
    assert found[0] == read
    if verb is Verb.HOLD:
        assert found == ("PROJECT_HELD", "labelled held")


def test_s108_2_hold_answering_the_idle_question_takes_its_label_off_too() -> None:
    idle = Comment(BOT, "NONE", f"{QUESTION}\n<!-- shipmill:agent -->", at(1))
    hub = FakeHub(issue(labels=("project", "needs-decision"), comments=(idle,)))
    run(hub, Verb.HOLD)
    assert [kind for kind, _ in hub.written] == ["comment", "unlabel", "add"]


# proves: S-108-3
@pytest.mark.parametrize(
    ("found", "read", "verb", "said"),
    [
        (issue(pull=True), heads(), Verb.FOCUS, "is a pull request"),
        (issue(open_=False), heads(), Verb.FOCUS, "is closed"),
        (
            issue(labels=("project", "needs-decision"), comments=(Comment(BOT, "NONE", QUESTION, at(1)),)),
            heads(),
            Verb.FOCUS,
            "open needs-decision question",
        ),
        (
            issue(labels=("needs-decision",), comments=(Comment(BOT, "NONE", QUESTION, at(1)),)),
            heads(),
            Verb.ADD,
            "open needs-decision question",
        ),
        (issue(labels=("goal-plan",)), heads(), Verb.ADD, "goal's plan"),
        (issue(labels=(), title="Check: the page shows the plan"), heads(), Verb.ADD, "is a check issue"),
        (issue(), heads(), Verb.ADD, "labelled `project` already"),
        (issue(), Projects({}), Verb.FOCUS, "no project head"),
        (issue(), Projects({}), Verb.UNFOCUS, "no project head"),
        (issue(), Projects({}), Verb.HOLD, "no project head"),
        (issue(), Projects({}), Verb.RESUME, "no project head"),
        (issue(), heads("PROJECT_STOP_DUE"), Verb.FOCUS, "stop pending"),
        (issue(), heads("PROJECT_STOP_DUE"), Verb.HOLD, "stop pending"),
        (issue(labels=("project", "held")), heads("PROJECT_STOP_DUE"), Verb.RESUME, "stop pending"),
    ],
)
def test_s108_3_a_move_on_the_wrong_item_is_refused(found: Item, read: Projects, verb: Verb, said: str) -> None:
    hub = FakeHub(found, read)
    with pytest.raises(ReleaseError, match=said):
        run(hub, verb)
    assert hub.written == []


# proves: S-108-4
@pytest.mark.parametrize(
    ("labels", "read", "verb", "said"),
    [
        (("project", "focus"), heads(), Verb.FOCUS, "in focus already"),
        (("project",), heads(), Verb.UNFOCUS, "no focus to take off"),
        (("project", "held"), heads("PROJECT_HELD"), Verb.HOLD, "labelled `held` already"),
        (("project",), heads(), Verb.RESUME, "no hold to lift"),
        (("project", "held"), heads("PROJECT_HELD", None), Verb.RESUME, "has no open check issue"),
        (("project", "held"), heads("PROJECT_HELD", 51), Verb.RESUME, "has no open check issue"),
        (("project", "held"), heads("PROJECT_HELD", limit=2, active=2, room=0), Verb.RESUME, r"\(2 of 2 active\)"),
    ],
)
def test_s108_4_a_move_its_head_already_made_or_cant_take_is_refused(
    labels: tuple[str, ...], read: Projects, verb: Verb, said: str
) -> None:
    hub = FakeHub(issue(labels=labels), read)
    with pytest.raises(ReleaseError, match=said):
        run(hub, verb)
    assert hub.written == []


def test_s108_4_resume_with_a_slot_free_starts_the_head() -> None:
    hub = FakeHub(issue(labels=("project", "held")), heads("PROJECT_HELD", limit=2, active=1, room=1))
    run(hub, Verb.RESUME)
    assert hub.written[-1] == ("remove", "held")


def test_the_heads_are_read_from_intake_states_json_lines() -> None:
    out = "\n".join(
        [
            json.dumps({"autonomy": "propose", "projects": {"limit": 2, "active": 2, "room": 0}}),
            json.dumps({"kind": "opportunity", "number": 3}),
            json.dumps({"kind": "project", "number": 7, "state": "PROJECT_HELD", "check": None}),
            json.dumps({"kind": "project", "number": 8, "state": "PROJECT_ACTIVE", "check": 50}),
        ]
    )
    assert moves.read_projects(out) == Projects(
        {7: Head(7, "PROJECT_HELD", None), 8: Head(8, "PROJECT_ACTIVE", 50)}, 2, 2, 0
    )
    assert moves.read_projects(json.dumps({"autonomy": "propose"})) == Projects({})
    with pytest.raises(ReleaseError, match="isn't JSON"):
        moves.read_projects("PROJECT_HELD #7")
    with pytest.raises(ReleaseError, match="without its fields"):
        moves.read_projects(json.dumps({"kind": "project", "number": 7}))


# proves: S-108-11
@pytest.mark.parametrize("verb", list(Verb))
def test_s108_11_a_by_that_isnt_the_maintainer_is_refused(verb: Verb) -> None:
    hub = FakeHub(issue(labels=("project", "focus", "held")))
    with pytest.raises(ReleaseError, match="is not the maintainer"):
        run(hub, verb, by="bob")
    assert hub.written == []


@dataclass
class FakeGh:
    """gh as `shipmill gh` runs it, its output captured: the viewer, open head #7, no comments"""

    labels: tuple[str, ...] = ("project",)
    edit: int = 0
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv[1:])
        self.calls.append(args)
        if args[:2] == ["api", "graphql"]:
            return 0, f"{BOT}\n"
        if args[:2] == ["api", "--paginate"]:
            return 0, ""
        if args[0] == "api":
            data = {
                "state": "open",
                "title": "Head",
                "labels": [{"name": n} for n in self.labels],
                "body": "",
                "created_at": at(0),
            }
            return 0, json.dumps(data)
        if args[:2] == ["issue", "create"]:
            return 0, "https://github.com/o/r/issues/51\n"
        if args[1] == "edit":
            return self.edit, "" if self.edit == 0 else "HTTP 502\n"
        return 0, URL + "\n"


def intake(state_: str = "PROJECT_ACTIVE", check_issue: int | None = 50) -> Any:
    def run_(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        assert "--projects" in cmd and cmd[cmd.index("--bot-login") + 1] == BOT
        row = {"kind": "project", "number": 7, "state": state_, "check": check_issue}
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"autonomy": "propose"}) + "\n" + json.dumps(row), "")

    return run_


STATUS = "o/r#7 (https://github.com/o/r/issues/7): active\n  why:  2 of 3 parts open\n        clears: agents\n"


@dataclass
class ItemState:
    """`status --item` as the CLI runs it after a move: the items it was asked about"""

    out: str = STATUS
    code: int = 0
    asked: list[int] = field(default_factory=list)

    def __call__(self, root: Path, number: int) -> subprocess.CompletedProcess[str]:
        self.asked.append(number)
        return subprocess.CompletedProcess([], self.code, self.out, "gh: HTTP 502\n" if self.code else "")


def cli(root: Path, host: Host, gh: FakeGh, *args: str, after: ItemState | None = None, entity: str = "project") -> int:
    return main(
        ["--repo", str(root), entity, *args, "--by", "amy"]
        if entity != "project"
        else ["--repo", str(root), entity, *args, "7", "--by", "amy"],
        api=MintApi(expires_from=dt.datetime.now(dt.UTC)),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_capture=gh,
        login=lambda: "amy",
        state=intake(),
        item_state=after or ItemState(),
    )


def test_s108_11_without_the_apps_key_it_exits_2_and_writes_nothing(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh = FakeGh()
    with pytest.raises(ReleaseError, match="no App private key at"):
        cli(root, host, gh, "focus")
    assert gh.calls == []


def test_s108_11_with_identity_none_it_exits_2_with_the_owners_choice(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "none"\n')
    gh = FakeGh()
    with pytest.raises(ReleaseError, match="owner chose that agents don.t write to GitHub here"):
        cli(root, host, gh, "focus")
    assert not any(call[0] in ("issue", "pr") for call in gh.calls)  # reads only, never a write


def test_through_the_cli_focus_posts_the_relay_then_the_label(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    gh = FakeGh()
    after = ItemState()
    assert cli(root, host, gh, "focus", after=after) == 0
    writes = [call[:2] for call in gh.calls if call[0] == "issue"]
    assert writes == [["issue", "comment"], ["issue", "edit"]]
    assert gh.calls[-1][-2:] == ["--add-label", "focus"]
    assert capsys.readouterr().out.splitlines() == [URL, "state: active; 2 of 3 parts open"]  # proves: S-108-13
    assert after.asked == [7]


# proves: S-108-12
@pytest.mark.parametrize(
    ("verb", "labels", "step"),
    [
        (Verb.ADD, (), "label: add `project`"),
        (Verb.FOCUS, ("project",), "label: add `focus`"),
        (Verb.UNFOCUS, ("project", "focus"), "label: remove `focus`"),
        (Verb.HOLD, ("project",), "label: add `held`"),
        (Verb.RESUME, ("project", "held"), "label: remove `held`"),
    ],
)
def test_s108_12_dry_run_prints_every_step_and_writes_nothing(verb: Verb, labels: tuple[str, ...], step: str) -> None:
    hub = FakeHub(issue(labels=labels))
    said = run(hub, verb, note="seen", dry_run=True)
    assert said == [relay(verb.value if verb is not Verb.ADD else "project") + "\n\nNote: seen", step]
    assert hub.written == []


def test_s108_12_hold_dry_run_says_the_idle_questions_label_comes_off() -> None:
    idle = Comment(BOT, "NONE", f"{QUESTION}\n<!-- shipmill:agent -->", at(1))
    hub = FakeHub(issue(labels=("project", "needs-decision"), comments=(idle,)))
    said = run(hub, Verb.HOLD, dry_run=True)
    assert said[1:] == ["needs-decision: comes off", "label: add `held`"]
    assert hub.written == []


def test_s108_12_a_failed_label_step_names_it_and_the_relays_url() -> None:
    hub = FakeHub(issue(), fail_label=4)
    with pytest.raises(moves.StepFailed, match=f"relay is posted at {URL}, but label: add `focus` failed") as raised:
        run(hub, Verb.FOCUS)
    assert raised.value.code == 4
    assert [kind for kind, _ in hub.written] == ["comment"]


def test_s108_12_through_the_cli_a_failed_label_exits_with_ghs_code(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    assert cli(root, host, FakeGh(edit=1), "focus") == 1
    assert f"relay is posted at {URL}" in capsys.readouterr().err


# -- project check (S-108-5, S-108-6)


@dataclass
class FakeCheckHub(FakeHub):
    open_checks: frozenset[int] = frozenset()
    fail_link: int | None = None

    def item(self, number: int) -> Item:
        if number == self.found.number:
            return self.found
        return Item(number, False, number in self.open_checks, frozenset(), "", at(0), ())

    def create(self, title: str, body: str) -> str:
        self.written.append(("create", f"{title}\n{body}"))
        return "https://github.com/o/r/issues/51"

    def link_child(self, head_: int, child: int) -> None:
        if self.fail_link is not None:
            raise moves.StepFailed("chains.py link exited 2", self.fail_link)
        self.written.append(("link", f"#{head_} --child #{child}"))


def run_check(hub: FakeCheckHub, title: str = "the page shows the plan", **flags: Any) -> list[str]:
    said: list[str] = []
    text = flags.pop("check", "Open /plans and see the new plan.")
    assert moves.run_check(moves.CheckRequest(7, title, text, **flags), hub, said.append) == 0
    return said


# proves: S-108-5
def test_s108_5_check_files_the_check_issue_and_links_it_to_the_head() -> None:
    hub = FakeCheckHub(issue(), heads("PROJECT_HELD", None))
    said = run_check(hub, cleanup="- [ ] drop the flag")
    body = "## Check\n\nOpen /plans and see the new plan.\n\n## Cleanup\n\n- [ ] drop the flag\n"
    assert hub.written == [
        ("create", f"Check: the page shows the plan\n{body}"),
        ("link", "#7 --child #51"),
    ]
    assert said == ["https://github.com/o/r/issues/51"]
    assert not any(kind == "comment" for kind, _ in hub.written)  # the session's own step: no relay
    filed = {"number": 51, "title": "Check: the page shows the plan", "body": body, "state": "OPEN"}
    filed |= {"updatedAt": "2026-11-25T10:00:00Z", "subIssues": {"totalCount": 0, "nodes": []}}
    assert state(node_after(("project",), (filed,))) == ("PROJECT_ACTIVE", "no part filed")


def test_s108_5_a_closed_check_issue_lets_a_new_one_be_filed() -> None:
    hub = FakeCheckHub(issue(), heads("PROJECT_CLOSING", 50))
    run_check(hub)
    assert [kind for kind, _ in hub.written] == ["create", "link"]


# proves: S-108-6
@pytest.mark.parametrize(
    ("read", "title", "flags", "said"),
    [
        (heads(check_issue=50), "the page shows the plan", {}, "open check issue already, #50"),
        (heads("PROJECT_HELD", None), " ", {}, "--title is empty"),
        (heads("PROJECT_HELD", None), "one\ntwo", {}, "several lines"),
        (heads("PROJECT_HELD", None), "the page shows the plan", {"check": "  \n"}, "--check-file is empty"),
        (Projects({}), "the page shows the plan", {}, "no project head"),
        (heads("PROJECT_STOP_DUE", None), "the page shows the plan", {}, "stop pending"),
    ],
)
def test_s108_6_a_check_its_head_already_has_or_a_bad_title_or_file_is_refused(
    read: Projects, title: str, flags: dict[str, str], said: str
) -> None:
    hub = FakeCheckHub(issue(), read, open_checks=frozenset({50}))
    with pytest.raises(ReleaseError, match=said):
        run_check(hub, title, **flags)
    assert hub.written == []


def test_s108_6_a_missing_check_file_exits_2_before_any_read(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    gh = FakeGh()
    with pytest.raises(ReleaseError, match="is missing"):
        main(
            ["--repo", str(root), "project", "check", "7", "--title", "T", "--check-file", str(tmp_path / "none.md")],
            environ=host.env(),
            home=host.home,
            gh_capture=gh,
            login=lambda: "amy",
            state=intake(),
        )
    assert gh.calls == []


def test_s108_12_a_failed_link_names_the_check_issues_url() -> None:
    hub = FakeCheckHub(issue(), heads("PROJECT_HELD", None), fail_link=2)
    with pytest.raises(moves.StepFailed, match="check issue is open at https://github.com/o/r/issues/51") as raised:
        run_check(hub)
    assert raised.value.code == 2


def test_s108_12_check_dry_run_prints_the_issue_and_the_link_and_writes_nothing() -> None:
    hub = FakeCheckHub(issue(), heads("PROJECT_HELD", None))
    said = run_check(hub, dry_run=True)
    assert said == [
        "issue: Check: the page shows the plan",
        "## Check\n\nOpen /plans and see the new plan.",
        "link: #7 --child the new issue",
    ]
    assert hub.written == []


def test_through_the_cli_check_files_the_issue_then_runs_chains_link(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    text = tmp_path / "check.md"
    text.write_text("Open /plans.\n", encoding="utf-8")
    linked: list[list[str]] = []

    def chains(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        linked.append(cmd[2:])
        return subprocess.CompletedProcess(cmd, 0, "linked\n", "")

    gh = FakeGh()
    code = main(
        ["--repo", str(root), "project", "check", "7", "--title", "T", "--check-file", str(text)],
        api=MintApi(expires_from=dt.datetime.now(dt.UTC)),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_capture=gh,
        login=lambda: "amy",
        state=intake("PROJECT_HELD", None),
        chains=chains,
        item_state=ItemState(),
    )
    assert code == 0
    created = next(call for call in gh.calls if call[:2] == ["issue", "create"])
    assert created[created.index("--title") + 1] == "Check: T"
    assert linked[0][0] == "link" and linked[0][2:] == ["--child", linked[0][3]]


# -- opportunity accept and decline (S-108-7 to S-108-9, D-115)

GOALS = frozenset({"G-2"})


def opportunity_issue(
    labels: Sequence[str] = ("opportunity",), comments: Sequence[Comment] = (), open_: bool = True
) -> Item:
    return Item(7, False, open_, frozenset(labels), "Serves: G-2\n", at(0), tuple(comments), "Plans page")


def run_opportunity(hub: FakeHub, verb: str, by: str = "amy", **flags: Any) -> list[str]:
    said: list[str] = []
    request = moves.OpportunityRequest(verb, 7, by, **flags)
    assert moves.run_opportunity(request, hub, MAINTAINERS, lambda: GOALS, said.append) == 0
    return said


def ist() -> Any:
    return answer._intake()


def posted_node(found: Item, body: str, closed: bool = False) -> dict[str, Any]:
    node = found.node([Comment(BOT, "NONE", f"{body}\n\n<!-- shipmill:agent -->", at(30))])
    node |= {"title": found.title, "reactions": {"totalCount": 0}}
    if closed:
        node |= {"state": "CLOSED", "stateReason": "NOT_PLANNED", "closedAt": at(31)}
    else:
        node |= {"state": "OPEN", "stateReason": None, "closedAt": None}
    names = found.labels | ({"planned"} if not closed else set())
    node["labels"] = {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in names]}
    return node


# proves: S-108-7
@pytest.mark.parametrize(("goal", "line", "named"), [("G-2", "accept G-2", "G-2"), ("new", "accept new goal", "new")])
def test_s108_7_accept_posts_the_relay_then_labels_it_planned(goal: str, line: str, named: str) -> None:
    found = opportunity_issue()
    hub = FakeHub(found)
    assert run_opportunity(hub, "accept", goal=goal) == [URL]
    assert hub.written == [("comment", relay(line)), ("add", "planned")]
    node = posted_node(found, relay(line))
    assert ist().opportunity_state(node, "planned", answer.MARKER, BOT)[0] == "ACCEPTED"
    assert ist().accept_goal(node, answer.MARKER, BOT, MAINTAINERS) == (ist().NEW_GOAL if named == "new" else named)


def test_s108_7_accept_on_an_opportunity_planned_already_is_spec_107s_relay_alone() -> None:
    hub = FakeHub(opportunity_issue(("opportunity", "planned")))
    run_opportunity(hub, "accept", goal="G-2")
    assert hub.written == [("comment", relay("accept G-2"))]


# proves: S-108-8
@pytest.mark.parametrize(
    ("found", "goal", "said"),
    [
        (opportunity_issue(labels=()), "G-2", "isn't labelled `opportunity`"),
        (opportunity_issue(open_=False), "G-2", "is closed"),
        (
            opportunity_issue(("opportunity", "needs-decision"), (Comment(BOT, "NONE", QUESTION, at(1)),)),
            "G-2",
            "open needs-decision question",
        ),
        (opportunity_issue(), "G-9", "no open goal of kind goal"),
        (opportunity_issue(), " ", "is empty"),
    ],
)
def test_s108_8_an_accept_its_reader_wouldnt_count_is_refused(found: Item, goal: str, said: str) -> None:
    hub = FakeHub(found)
    with pytest.raises(ReleaseError, match=said):
        run_opportunity(hub, "accept", goal=goal)
    assert hub.written == []


def test_s108_8_an_accept_with_no_goal_is_refused() -> None:
    hub = FakeHub(opportunity_issue())
    with pytest.raises(ReleaseError, match="needs the goal it serves"):
        run_opportunity(hub, "accept")
    assert hub.written == []


# proves: S-108-9
def test_s108_9_decline_posts_the_relay_then_closes_it_and_intake_reads_its_reason() -> None:
    found = opportunity_issue()
    hub = FakeHub(found)
    assert run_opportunity(hub, "decline", reason="another tool covers it") == [URL]
    assert hub.written == [("comment", relay("decline: another tool covers it")), ("close", "not planned")]
    node = posted_node(found, relay("decline: another tool covers it"), closed=True)
    read = ist().opportunity_state(node, "planned", answer.MARKER, BOT)
    assert read == ("DECLINED", "another tool covers it")


def test_s108_9_a_decline_written_by_hand_reads_as_before() -> None:
    found = opportunity_issue()
    node = found.node([Comment("amy", "OWNER", "Not for now: the tool covers it.", at(30))])
    node |= {"state": "CLOSED", "stateReason": "NOT_PLANNED", "closedAt": at(31)}
    read = ist().opportunity_state(node, "planned", answer.MARKER, BOT)
    assert read == ("DECLINED", "Not for now: the tool covers it.")


@pytest.mark.parametrize(
    ("labels", "reason", "said"),
    [
        (("opportunity", "planned"), "no", "is accepted"),
        (("opportunity",), None, "needs --reason"),
        (("opportunity",), "  ", "is empty"),
        (("opportunity",), "one\ntwo", "several lines"),
    ],
)
def test_s108_9_a_decline_its_reader_wouldnt_count_is_refused(
    labels: tuple[str, ...], reason: str | None, said: str
) -> None:
    hub = FakeHub(opportunity_issue(labels))
    with pytest.raises(ReleaseError, match=said):
        run_opportunity(hub, "decline", **({} if reason is None else {"reason": reason}))
    assert hub.written == []


def test_s108_11_an_opportunity_move_by_someone_else_is_refused() -> None:
    hub = FakeHub(opportunity_issue())
    with pytest.raises(ReleaseError, match="is not the maintainer"):
        run_opportunity(hub, "decline", by="bob", reason="no")
    assert hub.written == []


def test_s108_12_a_failed_close_names_it_and_the_relays_url() -> None:
    hub = FakeHub(opportunity_issue(), fail_label=1)
    with pytest.raises(moves.StepFailed, match="but close: as not planned failed") as raised:
        run_opportunity(hub, "decline", reason="no")
    assert raised.value.code == 1


def test_s108_12_decline_dry_run_prints_the_relay_and_the_close() -> None:
    hub = FakeHub(opportunity_issue())
    said = run_opportunity(hub, "decline", reason="no", dry_run=True)
    assert said == [relay("decline: no"), "close: as not planned"]
    assert hub.written == []


def test_s108_9_a_comment_in_the_hour_before_a_decline_refuses_it_naming_why() -> None:
    recent = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)  # within the hour the reader reads
    plus = Comment("bob", "NONE", "+1", recent.strftime("%Y-%m-%dT%H:%M:%SZ"))
    hub = FakeHub(opportunity_issue(comments=(plus,)))
    with pytest.raises(ReleaseError, match="oldest comment of the hour before the close"):
        run_opportunity(hub, "decline", reason="no")
    assert hub.written == []


# proves: S-108-13
@pytest.mark.parametrize(
    ("labels", "args", "line"),
    [
        (("opportunity",), ("accept", "7", "G-6"), "state: active; 2 of 3 parts open"),
        (("opportunity",), ("decline", "7", "--reason", "no"), "state: closed as not planned"),
    ],
)
def test_s108_13_an_opportunity_move_prints_the_items_state_after_its_url(
    tmp_path: Path,
    host: Host,
    capsys: pytest.CaptureFixture[str],
    labels: tuple[str, ...],
    args: tuple[str, ...],
    line: str,
) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    (root / "docs").mkdir(exist_ok=True)
    goals = (
        "# Demo\n\n## Mission\n\nShip widgets.\n\n## Users\n\n- U-1: Buyers\n\n## Goals\n\n"
        "- G-6: Buyers can track a widget. Check: `track` names its van. By: 2026-12-31\n\n"
        "## Non-goals\n\n- N-1: Vans\n\n## Quality bar\n\n- Q-1: Tests pass\n"
    )
    (root / "docs" / "product.md").write_text(goals, encoding="utf-8")
    after = ItemState()
    assert cli(root, host, FakeGh(labels=labels), *args, after=after, entity="opportunity") == 0
    assert capsys.readouterr().out.splitlines() == [URL, line]
    assert after.asked == ([] if "decline" in args else [7])  # a closed item is no item status --item explains


def test_s108_13_spec_107s_answer_prints_the_state_too(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    assert cli(root, host, FakeGh(), "continue", after=ItemState()) == 0
    assert capsys.readouterr().out.splitlines() == [URL, "state: active; 2 of 3 parts open"]


def test_s108_13_dry_run_reads_no_state_and_a_failed_read_exits_with_its_code(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\nidentity = "host"\n')
    quiet = ItemState()
    assert cli(root, host, FakeGh(), "focus", "--dry-run", after=quiet) == 0
    assert quiet.asked == []
    capsys.readouterr()
    assert cli(root, host, FakeGh(), "focus", after=ItemState(code=1)) == 1
    said = capsys.readouterr()
    assert said.out.splitlines() == [URL]
    assert "the move is written, but status --item 7 exited 1: gh: HTTP 502" in said.err


def test_s108_13_the_state_line_reads_status_items_first_line_and_reason() -> None:
    assert moves.state_line(STATUS) == "state: active; 2 of 3 parts open"
    assert moves.state_line("o/r#7 (https://github.com/o/r/issues/7): done\n") == "state: done"
    with pytest.raises(ReleaseError, match="no item line"):
        moves.state_line("")


# proves: S-108-14
@pytest.mark.parametrize(
    "doc",
    [
        "skills/product-intake/SKILL.md",
        "skills/product-intake/references/plan.md",
        "skills/github-issue-triage/references/needs-decision.md",
        "docs/flow.md",
    ],
)
def test_s108_14_the_skills_and_the_flow_name_the_moves(doc: str) -> None:
    text = (Path(__file__).resolve().parents[1] / doc).read_text(encoding="utf-8")
    assert "spec 108" in text
    assert any(name in text for name in ("project add", "project check", "opportunity decline", "project focus"))
