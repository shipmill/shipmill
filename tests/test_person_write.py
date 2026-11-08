"""Spec 051, what a write as a person carries: an issue or pull request keeps the agent marker
and names whose decision it was (S-051-10); a merge names the decider as its author and the
App's bot as a co-author (S-051-11); and the readers never take such a record for that
person's decision, filing, or answer (S-051-13). No test reaches the network"""

from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill import cli_command
from shipmill.agent_marker import MARKER, carries, closed_with, decided_by, marked, unmarked
from shipmill.app import Answer
from shipmill.app_gh import person_args, without_author_email
from shipmill.credit import Comment, Person, answers, issue_deciders, issue_of
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo
from .test_agent_marker_readers import BOT as REPO_BOT
from .test_agent_marker_readers import QUESTION, SKILLS, issue, load
from .test_agent_marker_readers import bot as gql_bot
from .test_agent_marker_readers import comment as gql_comment
from .test_app import APP_ID, BOT, BOT_ID
from .test_app_gh_merge import connected
from .test_credit import APP, HUBOT_TRAILER, OCTOCAT_TRAILER, WITH_APP, CreditReader, FakeCredit, approved, body_of
from .test_decider_token import ASSISTED, ISSUE, MERGE, EnvRunner, UserApi, as_app, as_person, filed, gh, store

LINE = "Opened by an agent through shipmill, on `@octocat`'s decision."
BOT_TRAILER = f"Co-authored-by: {BOT} <{BOT_ID}+{BOT}@users.noreply.github.com>"


def written(repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]) -> str:
    """The body `shipmill gh` hands gh for a create written as octocat, who filed #9"""
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, args, runner, CreditReader(FakeCredit(issues={9: filed(9)}))) == 0
    as_person(runner, "filed #9")
    return body_of(runner.calls[0])


# -- S-051-10: an issue or pull request written as a person ------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        [*ISSUE, "--decided-in", "9"],
        ["issue", "create", "-t", "t", "-b", "x", "--decided-in=9"],
        ["issue", "new", "--title", "t", "--body", "x", "--decided-in", "#9"],
        ["pr", "create", "--title", "t", "--body", "x\n\nFixes #9"],
        ["pr", "new", "-t", "t", "-b", "x\n\nFixes #9", "-B", "main"],
    ],
)
def test_s051_10_a_create_written_as_a_person_keeps_the_marker_and_ends_with_the_line(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    body = written(repo, tmp_path, capsys, args)
    assert carries(body)
    assert body.endswith(f"\n\n{LINE}\n\n{MARKER}")  # the marker stays last (spec 050), unrendered
    assert unmarked(body).endswith(LINE)  # so the last line GitHub shows is the closing line
    assert body.count(LINE) == 1 and body.count(MARKER) == 1
    assert "`@octocat`" in body and " @octocat" not in body  # a code span, no mention (D-61)


@pytest.mark.parametrize("flag", ["--body-file", "-F"])
def test_s051_10_a_body_file_gets_the_line_too(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    path = tmp_path / "body.md"
    path.write_text("From a file\n\nFixes #9\n", encoding="utf-8")
    body = written(repo, tmp_path, capsys, ["pr", "create", "--title", "t", flag, str(path)])
    assert body == f"From a file\n\nFixes #9\n\n{LINE}\n\n{MARKER}"


@pytest.mark.parametrize(
    "given",
    [
        f"x\n\n{MARKER}",  # marked already
        f"x\n\n{LINE}\n\n{MARKER}",  # marked and closed already, as by a retry
        f"x\n\n{LINE}",  # closed already, not yet marked
    ],
)
def test_s051_10_a_body_that_has_the_marker_or_the_line_gets_neither_twice(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], given: str
) -> None:
    body = written(repo, tmp_path, capsys, ["issue", "create", "--title", "t", "--body", given, "--decided-in", "9"])
    assert body == f"x\n\n{LINE}\n\n{MARKER}"


def test_s051_10_the_line_goes_before_a_last_marker_and_after_any_other_text() -> None:
    assert closed_with("", LINE) == f"{LINE}\n\n{MARKER}"
    assert closed_with("x\n\n<!-- shipmill:agent via=gh -->", LINE) == f"x\n\n{LINE}\n\n<!-- shipmill:agent via=gh -->"
    # a marker on an earlier line is kept where it is, once, and the line ends the body
    assert closed_with(f"{MARKER}\nx", LINE) == f"{MARKER}\nx\n\n{LINE}"
    assert closed_with(closed_with("x", LINE), LINE) == closed_with("x", LINE)
    assert decided_by("octocat") == LINE


def test_s051_10_a_body_the_line_would_push_past_githubs_limit_exits_2() -> None:
    body = marked("x" * 65_450)
    with pytest.raises(ReleaseError, match="over GitHub's limit of 65,536, which would cut the marker off"):
        person_args(["issue", "create", "--title", "t", "--body", body], "octocat")


@pytest.mark.parametrize(
    ("args", "credit", "why"),
    [
        (ISSUE, FakeCredit(), "no --decided-in names the issue or pull request that decided it"),
        (["pr", "create", "--body", "Fixes #9"], FakeCredit(issues={9: filed(9, Person("hubot", False))}), None),
    ],
)
def test_s051_10_a_create_that_falls_back_to_the_app_is_marked_and_names_no_decision(
    repo: Repo,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    credit: FakeCredit,
    why: str | None,
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)  # octocat's token, but hubot decided #9 and has none
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, args, runner, CreditReader(credit)) == 0
    as_app(runner, why or f"`@hubot` has not run {cli_command()} app-login")
    body = body_of(runner.calls[0])
    assert carries(body) and "Opened by an agent through shipmill" not in body


@pytest.mark.parametrize("author", [None, "app"])
def test_s051_10_autonomous_mode_and_no_author_add_no_line(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], author: str | None
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + ("" if author is None else f'author = "{author}"\n'))
    store(tmp_path)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "create", "--title", "t", "--body", "Fixes #9"], runner) == 0
    assert body_of(runner.calls[0]) == f"Fixes #9\n\n{MARKER}"


# -- S-051-11: a merge written as a person -----------------------------------------------------


def test_s051_11_a_merge_as_a_person_passes_no_author_email_and_names_the_apps_bot_last(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    reviews = [approved("octocat", "MEMBER"), approved("hubot", "MEMBER")]  # octocat first: the decider
    api = UserApi()
    assert gh(repo, tmp_path, key, MERGE, runner, CreditReader(FakeCredit(reviews=reviews)), api) == 0
    as_person(runner, "approved the pull request")
    [argv] = runner.calls
    assert "--author-email" not in argv  # GitHub refuses it with a user access token, and the token names the author
    body = body_of(argv)
    assert body.endswith(f"{HUBOT_TRAILER}\n{BOT_TRAILER}")  # spec 049's other decider, then the App
    assert OCTOCAT_TRAILER not in body and body.count("Co-authored-by: ") == 3  # with the commit's own
    assert "credit: `@hubot` approved the pull request" in runner.stderr[0]
    assert "credit: `@octocat`" not in runner.stderr[0]
    assert sum(path == "/user" for path, _ in api.calls) == 1


def test_s051_11_an_author_email_given_is_dropped() -> None:
    assert without_author_email(["pr", "merge", "7", "-sA", "me@x", "--", "x"]) == ["pr", "merge", "7", "-s", "--", "x"]
    assert without_author_email(["pr", "merge", "7", "--author-email=me@x"]) == ["pr", "merge", "7"]


def test_s051_11_a_merge_that_falls_back_to_the_app_keeps_spec_049s_trailers_and_no_author(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)  # no stored token: the App merges
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    [argv] = runner.calls
    assert "--author-email" not in argv
    assert body_of(argv).endswith(OCTOCAT_TRAILER) and BOT_TRAILER not in body_of(argv)


def test_s051_11_autonomous_mode_merges_with_spec_049s_trailers_only(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + 'author = "app"\n')
    store(tmp_path)
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    [argv] = runner.calls
    assert "--author-email" not in argv and body_of(argv).endswith(OCTOCAT_TRAILER)


def test_s051_11_a_bot_id_that_cant_be_read_merges_as_the_app_with_autonomous_modes_trailer(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    api = UserApi(bot=Answer(404, '{"message": "Not Found"}'))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, api) == 0  # no exit 2: S-051-9's fallback
    as_app(runner, f"a merge as `@octocat` names the App's bot {BOT} in Co-authored-by, whose user id can't be "
           f"read: GitHub has no bot account {BOT} for app_id {APP_ID}")  # fmt: skip
    [argv] = runner.calls
    assert "--author-email" not in argv
    assert body_of(argv).endswith(OCTOCAT_TRAILER) and BOT_TRAILER not in body_of(argv)
    assert "credit: `@octocat` approved the pull request" in runner.stderr[0]


# -- S-051-13: the readers never take a person-written record for that person's decision --------


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("person_write_triage_state", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("person_write_watch_state", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


@pytest.fixture
def person_body(repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """The body of an issue `shipmill gh` wrote as octocat, an OWNER, through their own token"""
    return written(
        repo, tmp_path, capsys, ["issue", "create", "--title", "t", "--body", "go with 1", "--decided-in", "9"]
    )


@pytest.mark.parametrize("bot_login", [None, REPO_BOT])
def test_s051_13_triage_state_reads_a_person_written_record_as_an_agents(
    ts: ModuleType, person_body: str, bot_login: str | None
) -> None:
    assert ts.by_agent(person_body)
    assert not ts.by_person("octocat", "OWNER", person_body, bot_login)
    assert not ts.replies(("octocat", "OWNER", person_body), bot_login)
    assert not ts.vetoes(("octocat", "OWNER", "Veto: no\n\n" + person_body), bot_login)
    asked = gql_bot(QUESTION) if bot_login else gql_comment(QUESTION)
    triaged = gql_bot(marked("Triage: implement"))  # as the App's triage line comes before its question
    item: dict[str, Any] = issue(triaged, asked, gql_comment(person_body, by="octocat", association="OWNER"))
    assert ts.gated(item, bot_login, False) == ("NEEDS_DECISION", "waits on a reply")


def test_s051_13_watch_state_leaves_the_question_waiting(ws: ModuleType, person_body: str) -> None:
    pr = {"number": 4, "isDraft": False, "isCrossRepository": False, "labels": [{"name": "needs-decision"}]}
    pr["headRefOid"] = f"{4:040x}"
    comments = [("amy", "OWNER", QUESTION), ("octocat", "OWNER", person_body)]
    rows = {r.state: r.detail for r in ws.intake("o/r", 0, "", [pr], lambda n: comments)}
    assert rows["NEEDS_DECISION"] == "#4" and "PRS_OPEN" not in rows


def test_s051_13_credit_names_no_one_for_a_person_written_issue_or_answer(person_body: str) -> None:
    node = {
        "__typename": "Issue",
        "number": 9,
        "repository": {"nameWithOwner": "o/r"},
        "authorAssociation": "OWNER",
        "body": person_body,
        "author": {"login": "octocat", "__typename": "User"},
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": []},
    }
    found = issue_of({"data": {"repository": {"nameWithOwner": "o/r", "issueOrPullRequest": node}}}, 9)
    assert found is not None and found.agent and found.author == Person("octocat", False)
    assert issue_deciders(FakeCredit(), [found], APP.login) == []  # no filing, whoever its author
    reply = Comment.parse(
        {"user": {"login": "octocat", "type": "User"}, "author_association": "OWNER", "body": person_body}
    )
    question = Comment(APP, "NONE", QUESTION, False)
    assert reply.agent and answers([question, reply], "#9", APP.login) == []
