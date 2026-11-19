"""#1312: `shipmill gh issue|pr edit` as the App adds the needs-decision label only to an item
whose newest question nothing answers, relays, or withdraws yet (#1331), and removes it only once a
person's reply, a counted relay (D-93), or a withdrawn marker follows the newest question. No test
reaches the network: gh is a Runner, the comments read a Comments fake, GitHub MintApi, and
openssl FakeSigner"""

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app_gh import LabelEdit, label_edit
from shipmill.cli import main
from shipmill.decision_label import QUESTION_MARKER, WITHDRAWN_MARKER
from shipmill.decision_label import _triage as triage
from shipmill.errors import ReleaseError

from .test_agent_marker import HOST_IDENTITY
from .test_app import BOT, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, MintApi, executable


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record = tmp_path / "record"
    record.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return Host(fakes, record, home)


AGENT = "\n\n<!-- shipmill:agent -->"
QUESTION = (
    f"{QUESTION_MARKER}\n<!-- shipmill:zone contract-change -->\n@romamo Decision needed: rename the flag?\n\n"
    f"1. Rename it (recommended): clearer\n2. Keep it: no churn{AGENT}"
)
MAINTAINER = "romamo"


def relay_of(*lines: str) -> str:
    """The App's relay of the header and lines, one per paragraph"""
    return "\n\n".join(("Decision by `@romamo`, relayed by Claude Code", *lines)) + AGENT


COUNTED = relay_of("Answered in the session: 1")
REFUSED = relay_of("1", "Thanks, and rename the flag later.")  # a paragraph before Note:, out of the grammar
WITHDRAWN = f"{WITHDRAWN_MARKER}\nNo longer needed: the flag went with #12.{AGENT}"


@dataclass
class Comments:
    """Stands in for the gh that reads an item's comments: records each argv and env, and
    prints each (login, association, body) as the jq filter would, one JSON line each"""

    thread: list[tuple[str, str, str]] = field(default_factory=list)
    code: int = 0
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env)))
        return self.code, "".join(json.dumps(list(row)) + "\n" for row in self.thread)


def gh(root: Path, args: list[str], host: Host, comments: Comments, key: Path | None) -> Runner:
    runner = Runner()
    leading = [] if key is None else ["--app-key", str(key)]
    code = main(
        ["--repo", str(root), "gh", *leading, *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
        stdin=io.StringIO(""),
        gh_capture=comments,
    )
    assert code == 7
    return runner


def as_app(tmp_path: Path, args: list[str], host: Host, thread: list[tuple[str, str, str]]) -> Runner:
    """args through shipmill gh as the App; gh ran them as given, after one read of the comments"""
    comments = Comments(thread)
    runner = gh(checkout(tmp_path, WITH_APP), args, host, comments, key_file(tmp_path))
    [(read, read_env)] = comments.calls
    [(argv, env)] = runner.calls
    assert read[1:4] == ["api", "--paginate", f"repos/{REPO}/issues/{args[2]}/comments"]
    assert argv[1:] == args
    assert read_env == env and env["GH_TOKEN"].startswith("token-")  # the App's token reads and writes
    return runner


def refused_as_app(
    tmp_path: Path, args: list[str], host: Host, thread: list[tuple[str, str, str]], match: str, code: int = 0
) -> None:
    """exit 2 (cli.run prints a ReleaseError and exits 2), gh never ran"""
    comments = Comments(thread, code)
    runner = Runner()
    with pytest.raises(ReleaseError, match=match):
        main(
            ["--repo", str(checkout(tmp_path, WITH_APP)), "gh", "--app-key", str(key_file(tmp_path)), *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(""),
            gh_capture=comments,
        )
    assert runner.calls == []


ADD = ["issue", "edit", "41", "--add-label", "needs-decision"]
REMOVE = ["issue", "edit", "41", "--remove-label", "needs-decision"]


# -- adding the label --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "thread",
    [
        [(BOT, "NONE", QUESTION)],
        [(MAINTAINER, "OWNER", QUESTION)],  # a trusted person's question
    ],
    ids=["app", "trusted"],
)
def test_1312_adding_the_label_to_an_item_with_a_question_runs(
    tmp_path: Path, host: Host, thread: list[tuple[str, str, str]]
) -> None:
    as_app(tmp_path, ADD, host, thread)


REASK = QUESTION.replace(
    "<!-- shipmill:zone contract-change -->\n",
    "<!-- shipmill:zone contract-change -->\n<!-- shipmill:relay-refused format -->\nRelay not counted: format\n",
)


@pytest.mark.parametrize(
    "thread",
    [
        [(BOT, "NONE", QUESTION), (MAINTAINER, "OWNER", "1"), (BOT, "NONE", QUESTION)],  # asked again after an answer
        [(BOT, "NONE", QUESTION), (BOT, "NONE", REFUSED), (BOT, "NONE", REASK)],  # the re-ask after an uncounted relay
        [(BOT, "NONE", QUESTION), (BOT, "NONE", "Still looking into it")],  # the App's own note answers nothing
        [(BOT, "NONE", QUESTION), ("mallory", "NONE", "1")],  # an outsider's reply answers nothing
    ],
    ids=["asked-again", "re-ask", "own-note", "outsider"],
)
def test_1331_adding_the_label_while_the_newest_question_waits_runs(
    tmp_path: Path, host: Host, thread: list[tuple[str, str, str]]
) -> None:
    as_app(tmp_path, ADD, host, thread)


@pytest.mark.parametrize(
    ("thread", "found"),
    [
        ([(BOT, "NONE", QUESTION), (MAINTAINER, "OWNER", "1")], "a person's reply"),
        ([(MAINTAINER, "OWNER", QUESTION), (MAINTAINER, "MEMBER", "Keep it")], "a person's reply"),
        ([(BOT, "NONE", QUESTION), (BOT, "NONE", COUNTED)], "a relay"),
        ([(BOT, "NONE", QUESTION), (BOT, "NONE", REFUSED)], "a relay"),  # D-93: the re-ask comes first
        ([(BOT, "NONE", QUESTION), (BOT, "NONE", WITHDRAWN)], "a withdrawn marker"),
        ([(MAINTAINER, "OWNER", QUESTION), (MAINTAINER, "MEMBER", WITHDRAWN)], "a withdrawn marker"),
    ],
    ids=["answered", "answered-trusted", "relayed", "relay-not-counted", "withdrawn-app", "withdrawn-trusted"],
)
def test_1331_adding_the_label_after_its_question_was_answered_exits_2(
    tmp_path: Path, host: Host, thread: list[tuple[str, str, str]], found: str
) -> None:
    refused_as_app(
        tmp_path,
        ADD,
        host,
        thread,
        f"after .*newest needs-decision question, {found} came.*`{QUESTION_MARKER}`.* comment 41.*then add the label",
    )


def test_1331_adding_and_removing_after_an_uncounted_relay_names_both(tmp_path: Path, host: Host) -> None:
    thread = [(BOT, "NONE", QUESTION), (BOT, "NONE", REFUSED)]
    both = ["issue", "edit", "41", "--add-label", "needs-decision", "--remove-label", "needs-decision"]
    refused_as_app(tmp_path, both, host, thread, r"(?s)--add-label .*a relay came.*\n.*--remove-label .*isn't counted")


@pytest.mark.parametrize(
    "args",
    [
        ADD,
        ["issue", "edit", "41", "--add-label", "bug,needs-decision"],
        ["pr", "edit", "41", "--add-label=Needs-Decision"],
    ],
    ids=["alone", "comma-list", "pr-any-case"],
)
@pytest.mark.parametrize(
    "thread",
    [
        [],
        [(MAINTAINER, "OWNER", "Please look at this")],
        [("mallory", "NONE", QUESTION)],  # an outsider's marker is no question
        [(BOT, "NONE", f"Triage: clarify\n\n{QUESTION}")],  # the marker not on the first line
    ],
    ids=["none", "no-marker", "outsider", "quoted"],
)
def test_1312_adding_the_label_without_a_question_exits_2(
    tmp_path: Path, host: Host, args: list[str], thread: list[tuple[str, str, str]]
) -> None:
    refused_as_app(
        tmp_path, args, host, thread, f"carries no needs-decision question.*`{QUESTION_MARKER}`.* comment 41"
    )


# -- removing the label ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "thread",
    [
        [(BOT, "NONE", QUESTION), (MAINTAINER, "OWNER", "1")],  # a trusted answer
        [(BOT, "NONE", QUESTION), (MAINTAINER, "COLLABORATOR", "Keep it, but document it")],
        [(BOT, "NONE", QUESTION), (BOT, "NONE", COUNTED)],  # a relay in the grammar
        [(BOT, "NONE", QUESTION), (BOT, "NONE", WITHDRAWN)],  # the App takes it back
        [(MAINTAINER, "OWNER", QUESTION), (MAINTAINER, "MEMBER", WITHDRAWN)],  # a trusted author takes it back
    ],
    ids=["answer", "own-words", "relay", "withdrawn-app", "withdrawn-trusted"],
)
def test_1312_removing_the_label_after_a_settled_question_runs(
    tmp_path: Path, host: Host, thread: list[tuple[str, str, str]]
) -> None:
    as_app(tmp_path, REMOVE, host, thread)


def test_1312_the_gates_take_up_of_an_answer_on_a_pull_request_runs(tmp_path: Path, host: Host) -> None:
    """DECIDED: the session that takes up the answer removes the label before it acts"""
    as_app(
        tmp_path,
        ["pr", "edit", "41", "--remove-label", "needs-decision"],
        host,
        [(BOT, "NONE", QUESTION), (MAINTAINER, "OWNER", "2")],
    )


@pytest.mark.parametrize(
    "thread",
    [
        [(BOT, "NONE", QUESTION)],  # nothing after it
        [(BOT, "NONE", QUESTION), ("mallory", "NONE", "1")],  # an outsider's reply
        [(BOT, "NONE", QUESTION), (MAINTAINER, "OWNER", f"1{AGENT}")],  # a trusted login's agent text
        [(BOT, "NONE", QUESTION), ("mallory", "NONE", WITHDRAWN)],  # an outsider's withdrawn marker
        [(BOT, "NONE", QUESTION), (BOT, "NONE", f"Triage: done\n{WITHDRAWN}")],  # not the first line
        [(MAINTAINER, "OWNER", "1"), (BOT, "NONE", QUESTION)],  # answered before it was asked again
        [(BOT, "NONE", QUESTION), (BOT, "NONE", COUNTED), (BOT, "NONE", QUESTION)],
    ],
    ids=["none", "outsider", "agent-marked", "outsider-withdrawn", "quoted-withdrawn", "old-answer", "old-relay"],
)
def test_1312_removing_the_label_with_nothing_settling_the_question_exits_2(
    tmp_path: Path, host: Host, thread: list[tuple[str, str, str]]
) -> None:
    refused_as_app(tmp_path, REMOVE, host, thread, f"nothing answers it.*relay grammar.*`{WITHDRAWN_MARKER}`")


def test_1312_removing_the_label_after_a_relay_out_of_its_grammar_exits_2(tmp_path: Path, host: Host) -> None:
    thread = [(BOT, "NONE", QUESTION), (BOT, "NONE", REFUSED)]
    refused_as_app(tmp_path, REMOVE, host, thread, r"its relay isn't counted \(relay not counted: format, D-93\)")


def test_1312_removing_the_label_from_an_item_a_person_parked_exits_2(tmp_path: Path, host: Host) -> None:
    thread = [(MAINTAINER, "OWNER", "Parking this until the release")]
    refused_as_app(tmp_path, REMOVE, host, thread, "a person labelled it by hand to park it")


def test_1312_comments_that_cant_be_read_refuse_the_edit(tmp_path: Path, host: Host) -> None:
    refused_as_app(tmp_path, ADD, host, [], "its comments can't be read.*exited 1.*the edit didn't run", code=1)


# -- every other edit, and other identities ------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "edit", "41", "--add-label", "ready"],
        ["issue", "edit", "41", "--remove-label", "needs-decision-later"],
        ["issue", "comment", "41", "--body", "needs-decision"],
        ["issue", "edit", "41", "--add-label", "needs-decision", "--help"],
    ],
)
def test_1312_other_edits_read_nothing(args: list[str]) -> None:
    assert label_edit(args) is None


def test_1312_as_the_host_the_label_moves_unread(tmp_path: Path, host: Host) -> None:
    """Without the App no bot login tells its questions and relays, so nothing is checked"""
    comments = Comments()
    runner = gh(checkout(tmp_path, HOST_IDENTITY), REMOVE, host, comments, None)
    assert comments.calls == [] and runner.calls[0][0][1:] == REMOVE


@pytest.mark.parametrize(
    ("args", "edit"),
    [
        (ADD, LabelEdit("gh issue edit", None, 41, True, False)),
        (
            ["pr", "edit", "-R", "o/r", "#7", "--remove-label", "x, needs-decision"],
            LabelEdit("gh pr edit", "o/r", 7, False, True),
        ),
        (
            [
                "issue",
                "edit",
                "https://github.com/o/r/issues/9",
                "--add-label",
                "needs-decision",
                "--remove-label",
                "needs-decision",
            ],
            LabelEdit("gh issue edit", "o/r", 9, True, True),
        ),
    ],
)
def test_1312_the_edit_names_its_item_and_the_way_the_label_goes(args: list[str], edit: LabelEdit) -> None:
    assert label_edit(args) == edit


@pytest.mark.parametrize("targets", [[], ["41", "42"], ["main"]])
def test_1312_an_edit_naming_no_one_item_exits_2(targets: list[str]) -> None:
    with pytest.raises(ReleaseError, match="needs one issue by its number or URL"):
        label_edit(["issue", "edit", *targets, "--add-label", "needs-decision"])


def test_1312_the_marker_it_names_is_triage_states_own() -> None:
    """The guard reads by triage_state.py's readers, and names the question marker they read"""
    assert triage().DECISION_MARKER == QUESTION_MARKER
