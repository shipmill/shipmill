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
        if args[1] == "edit":
            return self.edit, "" if self.edit == 0 else "HTTP 502\n"
        return 0, URL + "\n"


def intake(state_: str = "PROJECT_ACTIVE") -> Any:
    def run_(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        assert "--projects" in cmd and cmd[cmd.index("--bot-login") + 1] == BOT
        row = {"kind": "project", "number": 7, "state": state_, "check": 50}
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"autonomy": "propose"}) + "\n" + json.dumps(row), "")

    return run_


def cli(root: Path, host: Host, gh: FakeGh, *args: str) -> int:
    return main(
        ["--repo", str(root), "project", *args, "7", "--by", "amy"],
        api=MintApi(expires_from=dt.datetime.now(dt.UTC)),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_capture=gh,
        login=lambda: "amy",
        state=intake(),
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
    assert cli(root, host, gh, "focus") == 0
    writes = [call[:2] for call in gh.calls if call[0] == "issue"]
    assert writes == [["issue", "comment"], ["issue", "edit"]]
    assert gh.calls[-1][-2:] == ["--add-label", "focus"]
    assert capsys.readouterr().out.strip() == URL


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
