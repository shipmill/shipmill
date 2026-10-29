"""Spec 049: with [agents] credit = "decider", `shipmill gh pr merge` names who decided the
pull request in a Co-authored-by trailer. No test reaches the network: the pull request's
classification is FakeReads, its records FakeCredit, GitHub MintApi"""

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Credit, gh_identity_of
from shipmill.app import Answer
from shipmill.app_gh import with_body
from shipmill.cli import main
from shipmill.config import CONFIG_PATH, Table
from shipmill.credit import (
    MARKER,
    Account,
    Comment,
    Commit,
    CreditReads,
    Filed,
    Message,
    Messages,
    Named,
    Person,
    Pull,
    Review,
    accepters,
    answerers,
    approvers,
    authors,
    closes_of,
    credited_body,
    deciders,
    default_body,
)
from shipmill.errors import ReleaseError
from shipmill.github import FileChange, GhCli

from .conftest import POLICY, Repo
from .test_app import APP_ID, REPO, FakeSigner
from .test_app_gh_merge import CODE, DIRECTION, FakeReads, Reader, connected
from .test_app_token import FAKE_GH, MintApi, executable

APP_LOGIN = "demo-agent[bot]"  # the App FakeApi answers GET /app for
WITH_APP = f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n'
ON = WITH_APP + 'credit = "decider"\n'
OFF = WITH_APP + 'credit = "off"\n'
OCTOCAT = Account(583231, "octocat", "The Octocat")
OCTOCAT_TRAILER = "Co-authored-by: The Octocat <583231+octocat@users.noreply.github.com>"
HUBOT = Account(7, "hubot", None)
HUBOT_TRAILER = "Co-authored-by: hubot <7+hubot@users.noreply.github.com>"
APP = Person(APP_LOGIN, True)


def approved(login: str, association: str = "OWNER", state: str = "APPROVED", bot: bool = False) -> Review:
    return Review(Person(login, bot), state, association)


def pull(body: str = "The change.\n\nFixes #9", author: Person = APP) -> Pull:
    return Pull(7, author, "Add the thing", body)


@dataclass
class FakeCredit:
    """The pull request's records, as GhCli reads them for the credit"""

    record: Pull = field(default_factory=pull)
    reviews: list[Review] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=lambda: [Commit("Add the thing\n\nIts body.", "A", "a@x", None)])
    accounts: dict[str, Account] = field(default_factory=lambda: {"octocat": OCTOCAT, "hubot": HUBOT})
    messages: Messages = Messages(Message.PR_BODY, Message.PR_TITLE)
    closes: list[Filed] = field(default_factory=list)
    comments: dict[int, list[Comment]] = field(default_factory=dict)
    labelers: dict[int, list[Person | None]] = field(default_factory=dict)
    permissions: dict[str, str] = field(default_factory=dict)
    read: list[str] = field(default_factory=list)

    def credit_pull(self, number: int) -> Pull:
        self.read.append(f"pull {number}")
        return self.record

    def credit_reviews(self, number: int) -> list[Review]:
        self.read.append(f"reviews {number}")
        return self.reviews

    def credit_commits(self, number: int) -> list[Commit]:
        self.read.append(f"commits {number}")
        return self.commits

    def credit_account(self, login: str) -> Account:
        self.read.append(f"user {login}")
        return self.accounts[login]

    def credit_messages(self) -> Messages:
        self.read.append("repo")
        return self.messages

    def credit_closes(self, number: int) -> list[Filed]:
        self.read.append(f"closes {number}")
        return self.closes

    def credit_comments(self, number: int) -> list[Comment]:
        self.read.append(f"comments {number}")
        return self.comments.get(number, [])

    def credit_labelers(self, number: int, label: str) -> list[Person | None]:
        self.read.append(f"labeled {number} {label}")
        return self.labelers.get(number, [])

    def credit_permission(self, login: str) -> str:
        self.read.append(f"permission {login}")
        return self.permissions.get(login, "read")


@dataclass
class CreditReader:
    reads: FakeCredit
    envs: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, top: Path, binary: Path, env: Mapping[str, str]) -> FakeCredit:
        self.envs.append(dict(env))
        return self.reads


def refusing(top: Path, binary: Path, env: Mapping[str, str]) -> CreditReads:
    raise AssertionError("with credit off nothing of the pull request's records is read")


@dataclass
class Runner:
    """gh; records its argv and what stderr held when it ran"""

    capsys: pytest.CaptureFixture[str]
    calls: list[list[str]] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.calls.append(list(argv))
        self.stderr.append(self.capsys.readouterr().err)
        return 0


def gh(
    repo: Repo,
    tmp_path: Path,
    key: Path,
    args: list[str],
    runner: Runner,
    credit: CreditReader | None = None,
    files: tuple[FileChange, ...] = (CODE,),
    stdin: str = "",
    api: MintApi | None = None,
) -> int:
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    executable(fakes / "gh", FAKE_GH)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return main(
        ["--repo", str(repo.root), "gh", "--app-key", str(key), *args],
        api=api if api is not None else MintApi(),
        signer=FakeSigner(),
        stdin=io.StringIO(stdin),
        environ={"PATH": f"{fakes}:/usr/bin:/bin"},
        home=home,
        gh_runner=runner,
        merge_reader=Reader(FakeReads(files)),
        credit_reader=credit if credit is not None else refusing,
    )


@dataclass
class NoSlugApi(MintApi):
    """MintApi whose GET /app names no slug after the one the token's mint makes, so the App's
    bot login can't be read"""

    def get(self, path: str, token: str | None) -> Answer:
        if path == "/app" and any(called == "/app" for called, _ in self.calls):
            return Answer(200, "{}")
        return super().get(path, token)


def body_of(argv: list[str]) -> str:
    """The one --body gh gets"""
    assert argv.count("--body") == 1
    return argv[argv.index("--body") + 1]


# -- S-049-1: the setting ----------------------------------------------------------------------


def agents(credit: str | None) -> Table:
    return Table({"prompt": "/t", **({} if credit is None else {"credit": credit})}, "shipmill.toml [agents]")


@pytest.mark.parametrize("value", ["on", "Decider", "", "approver"])
def test_s049_1_any_other_credit_fails_to_load_naming_the_key_and_both_values(value: str) -> None:
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        AgentsConfig.parse(agents(value))
    message = str(raised.value)
    assert "[agents] credit" in message and '"off"' in message and '"decider"' in message
    assert repr(value) in message


def test_s049_1_a_credit_that_isnt_a_string_fails_to_load() -> None:
    with pytest.raises(ReleaseError, match=r"\[agents\] credit must be"):
        AgentsConfig.parse(Table({"prompt": "/t", "credit": True}, "x"))


def test_s049_1_credit_reads_as_off_without_the_key_and_as_set_with_it(tmp_path: Path) -> None:
    assert AgentsConfig.parse(agents(None)).credit is Credit.OFF
    assert AgentsConfig.parse(agents("off")).credit is Credit.OFF
    assert AgentsConfig.parse(agents("decider")).credit is Credit.DECIDER
    (tmp_path / CONFIG_PATH).parent.mkdir()
    (tmp_path / CONFIG_PATH).write_text(POLICY + '\n[agents]\nprompt = "/t"\n', encoding="utf-8")
    assert gh_identity_of(tmp_path).credit is Credit.OFF
    (tmp_path / CONFIG_PATH).write_text(POLICY + ON, encoding="utf-8")
    assert gh_identity_of(tmp_path).credit is Credit.DECIDER
    (tmp_path / CONFIG_PATH).write_text(POLICY + ON.replace("decider", "yes"), encoding="utf-8")
    with pytest.raises(ReleaseError, match=r"\[agents\] credit must be \"off\" \(the default\) or \"decider\""):
        gh_identity_of(tmp_path)


# -- S-049-2: credit off -----------------------------------------------------------------------


@pytest.mark.parametrize("config", [POLICY + OFF, POLICY + WITH_APP])
@pytest.mark.parametrize(
    "args",
    [
        ["pr", "merge", "7", "--squash"],
        ["pr", "merge", "7", "-s", "--body", "x"],
        ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"],
    ],
)
def test_s049_2_with_credit_off_gh_gets_its_arguments_and_no_record_is_read(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, args: list[str]
) -> None:
    key = connected(repo, tmp_path, config)
    runner = Runner(capsys)
    assert gh(repo, tmp_path, key, args, runner) == 0  # the reader raises when called
    assert [argv[1:] for argv in runner.calls] == [args]
    assert runner.stderr == [""]


# -- S-049-3: an approver ----------------------------------------------------------------------


@pytest.mark.parametrize(("login", "trailer"), [("octocat", OCTOCAT_TRAILER), ("hubot", HUBOT_TRAILER)])
def test_s049_3_a_trusted_approver_gets_the_trailer_named_by_profile_or_login(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], login: str, trailer: str
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit = CreditReader(FakeCredit(reviews=[approved(login, "MEMBER")]))
    runner = Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash"], runner, credit) == 0
    [argv] = runner.calls
    assert argv[1:5] == ["pr", "merge", "7", "--squash"]
    assert body_of(argv) == f"The change.\n\nFixes #9\n\nCo-authored-by: A <a@x>\n{trailer}"
    [env] = credit.envs
    assert (env["GH_TOKEN"], env["GH_REPO"]) == ("token-1", REPO)  # read as the App, in the pull's repo
    assert f"user {login}" in credit.reads.read


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_s049_3_each_trusted_association_approves(association: str) -> None:
    reads = FakeCredit(reviews=[approved("octocat", association)])
    assert deciders(reads, pull(), APP_LOGIN) == [Named(Person("octocat", False), True, "approved the pull request")]


def test_s049_3_only_the_latest_review_of_each_person_counts() -> None:
    reads = FakeCredit(
        reviews=[
            approved("octocat"),
            approved("octocat", state="CHANGES_REQUESTED"),
            approved("hubot", state="CHANGES_REQUESTED"),
            approved("hubot"),
            approved("mona", state="DISMISSED"),
        ]
    )
    assert [n.person.login for n in approvers(reads, pull(), APP_LOGIN) if n.trusted] == ["hubot"]


def test_s049_3_a_comment_after_an_approval_keeps_it_as_github_reads_it() -> None:
    reads = FakeCredit(
        reviews=[
            approved("octocat"),
            approved("octocat", state="COMMENTED"),
            approved("octocat", state="PENDING"),
            approved("hubot"),
            approved("hubot", state="DISMISSED"),
            approved("hubot", state="COMMENTED"),
            approved("mona", state="COMMENTED"),
        ]
    )
    assert [n.person.login for n in approvers(reads, pull(), APP_LOGIN)] == ["octocat"]


def test_s049_3_the_account_parses_as_users_gives_it() -> None:
    assert Account.parse({"id": 583231, "login": "octocat", "name": "The Octocat"}).trailer == OCTOCAT_TRAILER
    assert Account.parse({"id": 7, "login": "hubot", "name": None}).trailer == HUBOT_TRAILER
    assert Account.parse({"id": 7, "login": "hubot", "name": "  "}).trailer == HUBOT_TRAILER


# -- S-049-7: who never gets it ------------------------------------------------------------------


def test_s049_7_bots_the_app_the_untrusted_and_the_author_never_get_the_trailer() -> None:
    author = Person("alice", False)
    reads = FakeCredit(
        record=pull(author=author),
        reviews=[
            approved("dependabot[bot]", "NONE", bot=True),
            approved(APP_LOGIN, "NONE", bot=True),
            approved("renovate", "MEMBER", bot=True),  # GitHub's type Bot, whatever its login
            approved("stranger", "CONTRIBUTOR"),
            approved("first", "FIRST_TIME_CONTRIBUTOR"),
            approved("nobody", "NONE"),
            approved("Alice", "OWNER"),  # the author, in another case
        ],
    )
    assert deciders(reads, reads.record, APP_LOGIN) == []


def test_s049_7_each_person_is_named_once_by_the_first_source_that_names_them() -> None:
    def second(reads: CreditReads, record: Pull, app: str) -> list[Named]:
        return [
            Named(Person("OctoCat", False), True, "answered the question"),
            Named(Person("mona", False), False, "answered the question"),
            Named(Person("hubot", False), True, "filed #9"),
        ]

    reads = FakeCredit(reviews=[approved("octocat"), approved("octocat")])
    found = deciders(reads, pull(), APP_LOGIN, (approvers, second))
    assert [(n.person.login, n.why) for n in found] == [("octocat", "approved the pull request"), ("hubot", "filed #9")]


def test_s049_7_a_person_is_parsed_a_bot_by_type_or_login() -> None:
    assert Person.parse({"login": "x", "type": "Bot"}).bot
    assert Person.parse({"login": "x[bot]", "type": "User"}).bot
    assert not Person.parse({"login": "x", "type": "User"}).bot


@pytest.mark.parametrize(
    "reviews", [[], [approved("stranger", "CONTRIBUTOR")], [approved("octocat", state="COMMENTED")]]
)
def test_s049_7_a_pull_request_no_record_names_merges_with_its_arguments_unchanged(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], reviews: list[Review]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=reviews)), Runner(capsys)
    args = ["pr", "merge", "7", "--squash", "--body", "x"]
    assert gh(repo, tmp_path, key, args, runner, credit) == 0
    assert [argv[1:] for argv in runner.calls] == [args]
    assert runner.stderr == [""]
    # no account is looked up
    assert credit.reads.read == ["pull 7", "reviews 7", "comments 7", "closes 7", "closes 7", "closes 7"]


# -- S-049-8: the body ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "kept"),
    [
        (["pr", "merge", "7", "--squash", "--body", "Given."], ["pr", "merge", "7", "--squash"]),
        (["pr", "merge", "7", "-s", "--body=Given."], ["pr", "merge", "7", "-s"]),
        (["pr", "merge", "7", "-b", "old", "-s", "-b", "Given."], ["pr", "merge", "7", "-s"]),
        (["pr", "merge", "7", "-sbGiven."], ["pr", "merge", "7", "-s"]),
        (["pr", "merge", "7", "-sb", "Given."], ["pr", "merge", "7", "-s"]),
        (["pr", "merge", "7", "-s", "-b=Given."], ["pr", "merge", "7", "-s"]),
        (
            ["pr", "merge", "7", "-s", "--subject", "Add -b it", "-t", "-b", "--body", "Given."],
            ["pr", "merge", "7", "-s", "--subject", "Add -b it", "-t", "-b"],
        ),
    ],
)
def test_s049_8_a_given_body_is_kept_and_replaced_by_one_body_and_the_subject_reaches_gh(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], kept: list[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    assert gh(repo, tmp_path, key, args, runner, credit) == 0
    [argv] = runner.calls
    assert argv[1:] == [*kept, "--body", f"Given.\n\n{OCTOCAT_TRAILER}"]
    assert "repo" not in credit.reads.read and "commits 7" not in credit.reads.read  # no default body is built


def test_s049_8_a_body_file_or_stdin_is_the_body(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    (tmp_path / "body.md").write_text("From a file.\n", encoding="utf-8")
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "-s", "-F", str(tmp_path / "body.md")], runner, credit) == 0
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "-s", "--body-file", "-"], runner, credit, stdin="Piped.") == 0
    assert [argv[1:] for argv in runner.calls] == [
        ["pr", "merge", "7", "-s", "--body", f"From a file.\n\n{OCTOCAT_TRAILER}"],
        ["pr", "merge", "7", "-s", "--body", f"Piped.\n\n{OCTOCAT_TRAILER}"],
    ]


def test_s049_8_a_stdin_body_already_naming_the_decider_still_reaches_gh(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """shipmill read stdin to its end, so gh can't read it again: the body goes as --body"""
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    piped = f"Piped.\n\n{OCTOCAT_TRAILER}"
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "-s", "--body-file", "-"], runner, credit, stdin=piped) == 0
    assert [argv[1:] for argv in runner.calls] == [["pr", "merge", "7", "-s", "--body", piped]]


def test_s049_8_a_missing_body_file_exits_2(repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError, match="--body-file .*missing.md can't be read"):
        gh(repo, tmp_path, key, ["pr", "merge", "7", "-s", "-F", str(tmp_path / "missing.md")], runner, credit)
    assert runner.calls == []


def test_s049_8_the_default_body_follows_the_repos_squash_setting(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    commits = [
        Commit("Add a\n\nWhy a.", "Bot", "4242+shipmill-demo[bot]@users.noreply.github.com", APP_LOGIN),
        Commit("Add b", "Bea", "Bea@Example.com", "bea"),
        Commit("Fix b", "Bea", "bea@example.com", "bea"),  # the same author, by email without case
        Commit("Add c", "Cy", "cy@example.com", None),
    ]
    reads = FakeCredit(
        reviews=[approved("octocat")], commits=commits, messages=Messages(Message.COMMIT_MESSAGES, Message.PR_TITLE)
    )
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash", "--subject", "Add it (#7)"], runner, credit) == 0
    [argv] = runner.calls
    assert argv[1:6] == ["pr", "merge", "7", "--squash", "--subject"]
    assert body_of(argv) == (
        "* Add a\n\nWhy a.\n\n* Add b\n\n* Fix b\n\n* Add c\n\n"
        "Co-authored-by: Bea <Bea@Example.com>\nCo-authored-by: Cy <cy@example.com>\n"
        f"{OCTOCAT_TRAILER}"
    )


def test_s049_8_a_merge_commit_follows_the_repos_merge_setting(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    reads = FakeCredit(reviews=[approved("octocat")], messages=Messages(Message.BLANK, Message.PR_BODY))
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--merge"], runner, credit) == 0
    [argv] = runner.calls
    assert body_of(argv) == f"The change.\n\nFixes #9\n\n{OCTOCAT_TRAILER}"  # a merge commit adds no co-authors


def commit_by(name: str, email: str, login: str | None = None, message: str = "Add it\n\nThe body.") -> Commit:
    return Commit(message, name, email, login)


@pytest.mark.parametrize(
    ("setting", "commits", "body"),
    [
        (Message.PR_BODY, [commit_by("A", "a@x", APP_LOGIN)], "The change.\n\nFixes #9"),
        (Message.COMMIT_MESSAGES, [commit_by("A", "a@x", APP_LOGIN)], "The body."),  # the one message's body
        (Message.COMMIT_MESSAGES, [commit_by("A", "a@x", APP_LOGIN, "Add it")], ""),
        (Message.BLANK, [commit_by("A", "a@x", APP_LOGIN)], ""),
        (Message.PR_TITLE, [commit_by("A", "a@x", APP_LOGIN)], ""),
        (Message.BLANK, [commit_by("A", "a@x")], "Co-authored-by: A <a@x>"),
        (
            Message.PR_BODY,
            [commit_by("A", "a@x", "ann"), commit_by("B", "b@x", "bo")],
            "The change.\n\nFixes #9\n\nCo-authored-by: A <a@x>\nCo-authored-by: B <b@x>",
        ),
    ],
)
def test_s049_8_the_default_body_is_githubs(setting: Message, commits: list[Commit], body: str) -> None:
    assert default_body(setting, pull(), commits, squash=True) == body


def test_s049_8_a_commit_author_already_named_in_the_body_gets_no_second_trailer() -> None:
    record = pull("Body.\n\nco-authored-by: Ann <A@X>")
    assert default_body(Message.PR_BODY, record, [commit_by("Ann", "a@x", "ann")], squash=True) == record.body


def test_s049_8_a_decider_already_named_by_email_gets_no_second_trailer(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    named = "Body.\n\nCo-authored-by: Octo <583231+OctoCat@users.noreply.github.com>"
    assert credited_body(named, [OCTOCAT]) is None
    assert credited_body(named, [OCTOCAT, HUBOT]) == f"{named}\n{HUBOT_TRAILER}"  # in the trailers' paragraph
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    args = ["pr", "merge", "7", "-s", "--body", named]
    assert gh(repo, tmp_path, key, args, runner, credit) == 0
    assert [argv[1:] for argv in runner.calls] == [args]  # nothing to add: gh gets its arguments


def test_s049_8_an_empty_body_holds_the_trailers_alone() -> None:
    assert credited_body("", [OCTOCAT]) == OCTOCAT_TRAILER
    assert credited_body("  \n", [OCTOCAT, HUBOT]) == f"{OCTOCAT_TRAILER}\n{HUBOT_TRAILER}"


@pytest.mark.parametrize(
    ("args", "argv"),
    [
        (["pr", "merge", "7", "-s"], ["pr", "merge", "7", "-s", "--body", "B"]),
        (["pr", "merge", "-s", "--", "7"], ["pr", "merge", "-s", "--body", "B", "--", "7"]),
        (["pr", "-R", "a/b", "merge", "-dsb", "x", "7"], ["pr", "-R", "a/b", "merge", "-ds", "7", "--body", "B"]),
        (["pr", "merge", "-bx", "7"], ["pr", "merge", "7", "--body", "B"]),
        (["pr", "merge", "--body-file", "f", "7"], ["pr", "merge", "7", "--body", "B"]),
        (["pr", "merge", "-tb", "7"], ["pr", "merge", "-tb", "7", "--body", "B"]),  # -t's value is `b`
        (["pr", "merge", "--subject", "--body", "7"], ["pr", "merge", "--subject", "--body", "7", "--body", "B"]),
    ],
)
def test_s049_8_with_body_drops_every_body_flag_and_keeps_the_rest(args: list[str], argv: list[str]) -> None:
    assert with_body(args, "B") == argv


def test_s049_8_without_a_method_or_a_body_the_default_cant_be_told(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError, match="names no method.*add --squash"):
        gh(repo, tmp_path, key, ["pr", "merge", "7"], runner, credit)
    assert runner.calls == []


@pytest.mark.parametrize("args", [["pr", "merge", "7", "--rebase"], ["pr", "merge", "7", "--disable-auto"]])
def test_s049_8_a_rebase_or_turning_auto_merge_off_is_left_alone(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    assert gh(repo, tmp_path, key, args, runner, credit) == 0
    assert ([argv[1:] for argv in runner.calls], credit.envs) == ([args], [])


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["pr", "merge", "7", "-s", "-m"], "one of --merge, --rebase, or --squash"),
        (["pr", "merge", "7", "-s", "-b", "x", "-F", "f"], "--body or --body-file, not both"),
    ],
)
def test_s049_8_flags_gh_refuses_exit_2(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError, match=message):
        gh(repo, tmp_path, key, args, runner, credit)
    assert runner.calls == []


# -- S-049-9: the stderr line --------------------------------------------------------------------


def test_s049_9_one_stderr_line_per_decider_names_the_login_in_a_code_span_before_gh_runs(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    reads = FakeCredit(reviews=[approved("octocat"), approved("hubot", "COLLABORATOR"), approved("octocat")])
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "-s", "-b", "x"], runner, credit) == 0
    assert runner.stderr == [
        "credit: `@hubot` approved the pull request\ncredit: `@octocat` approved the pull request\n"
    ]
    assert body_of(runner.calls[0]) == f"x\n\n{HUBOT_TRAILER}\n{OCTOCAT_TRAILER}"


# -- S-049-10: the API's merge -------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"],
        [
            "api",
            "--method=put",
            "https://api.github.com/repos/{owner}/{repo}/pulls/7/merge",
            "-f",
            "merge_method=squash",
        ],
    ],
)
def test_s049_10_with_credit_on_the_apis_merge_exits_2_naming_the_pr_merge(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        gh(repo, tmp_path, key, args, runner, credit)
    assert "gh pr merge 7 --squash` instead" in str(raised.value)
    assert '[agents] credit = "decider"' in str(raised.value)
    assert (runner.calls, credit.envs) == ([], [])


def test_s049_10_the_never_zone_hold_still_comes_first(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError, match="has a never zone"):
        gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash"], runner, credit, files=(DIRECTION,))
    assert (runner.calls, credit.envs) == ([], [])


# -- S-049-4, S-049-5, S-049-6: answerers, issue authors, accepters ------------------------------

OCTO = Person("octocat", False)
QUESTION = Comment(APP, "NONE", f"{MARKER}\n<!-- shipmill:zone scope -->\n@octocat Decision needed: which?")


def said(login: str, body: str = "1", association: str = "OWNER", bot: bool = False) -> Comment:
    return Comment(Person(login, bot), association, body)


def issue(
    number: int,
    author: Person | None = OCTO,
    association: str = "OWNER",
    labels: tuple[str, ...] = (),
    parent: Filed | None = None,
) -> Filed:
    return Filed(number, author, association, frozenset(labels), parent)


def named(found: list[Named]) -> list[tuple[str, bool, str]]:
    return [(n.person.login, n.trusted, n.why) for n in found]


def test_s049_4_a_trusted_reply_after_the_question_answers_it_on_the_pull_request() -> None:
    reads = FakeCredit(
        comments={
            7: [
                said("early", "I'd go with 1"),  # before the question: no answer
                QUESTION,
                said("octocat", "2, please"),
                said("stranger", "1", "CONTRIBUTOR"),
                said(APP_LOGIN, "Triage: noted", "NONE", bot=True),  # the App's own comment is no reply
                said("hubot", f"{MARKER}\n@octocat again?", "MEMBER"),  # a question, not a reply
            ]
        }
    )
    assert named(answerers(reads, reads.record, APP_LOGIN)) == [
        ("octocat", True, "answered the decision on the pull request"),
        ("stranger", False, "answered the decision on the pull request"),
    ]
    assert [n.person.login for n in deciders(reads, reads.record, APP_LOGIN)] == [
        "octocat"
    ]  # the untrusted reply gives none


def test_s049_4_a_question_needs_the_app_or_a_trusted_asker_and_the_marker_as_first_line() -> None:
    reads = FakeCredit(
        comments={
            7: [
                said("stranger", MARKER, "NONE"),  # an outsider's marker asks nothing
                said("octocat", "1"),
                said(APP_LOGIN, f"Triage: see below\n{MARKER}", "NONE", bot=True),  # a quote of it, not a question
                said("hubot", "2", "MEMBER"),
            ]
        }
    )
    assert answerers(reads, reads.record, APP_LOGIN) == []


def test_s049_4_answers_on_a_closed_issue_and_its_parent_count_each_issue_once() -> None:
    parent = issue(3, Person("lead", False))
    reads = FakeCredit(
        closes=[issue(9, parent=parent), issue(10, parent=parent)],
        comments={9: [QUESTION, said("mona")], 3: [QUESTION, said("lead", "Go", "MEMBER")], 10: []},
    )
    assert named(answerers(reads, reads.record, APP_LOGIN)) == [
        ("mona", True, "answered the decision on #9"),
        ("lead", True, "answered the decision on #3"),
    ]
    assert reads.read == ["comments 7", "closes 7", "comments 9", "comments 3", "comments 10"]


@pytest.mark.parametrize(
    "first",
    [
        "Decision by @octocat, relayed by Claude Code",
        "Decision by `@octocat`, relayed by Claude Code",
        "Decision by @octocat",
        "Decision by @octocat.",
        "Decision by @octocat; relayed by Claude Code",
    ],
)
def test_s049_4_the_app_relaying_a_decision_names_its_login_bare_or_in_a_code_span(first: str) -> None:
    reads = FakeCredit(comments={7: [said(APP_LOGIN, f"{first}\n\nAnswered in the session: 1", "NONE", bot=True)]})
    assert named(answerers(reads, reads.record, APP_LOGIN)) == [
        ("octocat", True, "answered the decision on the pull request")
    ]


@pytest.mark.parametrize(
    "comment",
    [
        said("mona", "Decision by @octocat, relayed by me", "OWNER"),  # not the App: a person's comment
        said("github-actions[bot]", "Decision by @octocat, relayed by a workflow", "NONE", bot=True),  # another bot
        said("dependabot[bot]", "Decision by `@octocat`", "NONE", bot=True),
        said(APP_LOGIN, "Triage: ok\nDecision by @octocat", "NONE", bot=True),  # not the first line
        said(APP_LOGIN, "Decision by @octocat-", "NONE", bot=True),  # no login GitHub allows
        said(APP_LOGIN, "Decision by `@octocat", "NONE", bot=True),
        # a login whose first part spells another account: a bot, a team, a dotted name
        said(APP_LOGIN, "Decision by @renovate[bot], relayed by Claude Code", "NONE", bot=True),
        said(APP_LOGIN, "Decision by @shipmill/maintainers", "NONE", bot=True),
        said(APP_LOGIN, "Decision by @octo.cat", "NONE", bot=True),
        said(APP_LOGIN, "Decision by @octocat's call", "NONE", bot=True),
    ],
)
def test_s049_4_only_the_apps_first_line_relays_a_decision(comment: Comment) -> None:
    reads = FakeCredit(comments={7: [comment]})
    assert answerers(reads, reads.record, APP_LOGIN) == []


def test_s049_4_another_bots_question_asks_nothing_and_its_relay_credits_nobody() -> None:
    other = "github-actions[bot]"
    reads = FakeCredit(
        comments={
            7: [
                said(other, f"{MARKER}\n@octocat Decision needed: which?", "NONE", bot=True),
                said("octocat", "1"),
                said(other, "Decision by @hubot, relayed by Claude Code", "NONE", bot=True),
            ]
        }
    )
    assert answerers(reads, reads.record, APP_LOGIN) == []
    assert deciders(reads, reads.record, APP_LOGIN) == []


def test_s049_4_the_apps_login_is_matched_without_case_and_never_credited() -> None:
    question = said(APP_LOGIN.upper(), MARKER, "NONE", bot=True)
    reads = FakeCredit(comments={7: [question, said("octocat")]}, reviews=[approved(APP_LOGIN, bot=False)])
    assert [n.person.login for n in deciders(reads, reads.record, APP_LOGIN)] == ["octocat"]


def test_s049_4_a_merge_exits_2_when_the_apps_login_cant_be_read(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError, match="needs the App's bot login, which can't be read: .*gave no slug"):
        gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash"], runner, credit, api=NoSlugApi())
    assert runner.calls == []


def test_s049_4_an_answerer_gets_the_trailer_on_the_merge(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    reads = FakeCredit(closes=[issue(9, author=APP, association="NONE")], comments={9: [QUESTION, said("octocat")]})
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash", "--body", "Given."], runner, credit) == 0
    assert body_of(runner.calls[0]) == f"Given.\n\n{OCTOCAT_TRAILER}"
    assert runner.stderr == ["credit: `@octocat` answered the decision on #9\n"]


def test_s049_5_the_trusted_author_of_a_closed_issue_or_its_parent_files_the_decision() -> None:
    reads = FakeCredit(
        closes=[
            issue(9, Person("mona", False), "MEMBER", parent=issue(3, Person("lead", False), "COLLABORATOR")),
            issue(10, Person("stranger", False), "CONTRIBUTOR", parent=issue(4, None, "NONE")),
            issue(11, Person("dependabot[bot]", True), "NONE"),
        ]
    )
    assert named(authors(reads, reads.record, APP_LOGIN)) == [
        ("mona", True, "filed #9"),
        ("lead", True, "filed #3"),
        ("stranger", False, "filed #10"),
        ("dependabot[bot]", False, "filed #11"),
    ]
    assert [n.person.login for n in deciders(reads, reads.record, APP_LOGIN)] == ["mona", "lead"]


def test_s049_5_an_issue_author_gets_the_trailer_on_the_merge(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    credit, runner = CreditReader(FakeCredit(closes=[issue(9, Person("hubot", False))])), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash", "--body", "Given."], runner, credit) == 0
    assert body_of(runner.calls[0]) == f"Given.\n\n{HUBOT_TRAILER}"
    assert runner.stderr == ["credit: `@hubot` filed #9\n"]


@pytest.mark.parametrize("permission", ["write", "maintain", "admin"])
def test_s049_6_who_added_planned_to_an_opportunity_with_write_accepted_it(permission: str) -> None:
    opportunity = issue(3, APP, "NONE", ("opportunity", "planned"))
    reads = FakeCredit(
        closes=[issue(9, APP, "NONE", parent=opportunity)],
        labelers={3: [Person("mona", False), None, Person("octocat", False)]},
        permissions={"octocat": permission},
    )
    assert named(accepters(reads, reads.record, APP_LOGIN)) == [
        ("octocat", True, "accepted #3 (planned)")
    ]  # the last to add it
    assert "labeled 9 planned" not in reads.read  # #9 is no opportunity


@pytest.mark.parametrize(
    ("labels", "labelers", "permission"),
    [
        (("opportunity", "planned"), [Person("octocat", False)], "read"),
        (("opportunity", "planned"), [Person("octocat", False)], "none"),
        (("opportunity", "planned"), [Person("renovate", True)], "write"),  # a bot never accepts
        (("opportunity", "planned"), [None], "write"),  # a deleted account
        (("opportunity", "planned"), [], "write"),
        (("planned",), [Person("octocat", False)], "write"),  # no opportunity
        (("opportunity",), [Person("octocat", False)], "write"),  # not accepted
    ],
)
def test_s049_6_an_accepter_without_write_or_an_issue_not_an_accepted_opportunity_gives_none(
    labels: tuple[str, ...], labelers: list[Person | None], permission: str
) -> None:
    reads = FakeCredit(
        closes=[issue(9, APP, "NONE", labels)], labelers={9: labelers}, permissions={"octocat": permission}
    )
    assert deciders(reads, reads.record, APP_LOGIN) == []


def test_s049_6_an_accepter_gets_the_trailer_on_the_merge(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON)
    reads = FakeCredit(
        closes=[issue(9, APP, "NONE", ("opportunity", "planned"))],
        labelers={9: [OCTO]},
        permissions={"octocat": "admin"},
    )
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash", "--body", "Given."], runner, credit) == 0
    assert body_of(runner.calls[0]) == f"Given.\n\n{OCTOCAT_TRAILER}"
    assert runner.stderr == ["credit: `@octocat` accepted #9 (planned)\n"]


def test_s049_7_the_sources_run_in_the_specs_order_and_the_first_names_a_person() -> None:
    """proves: S-049-4, S-049-5, S-049-6"""
    reads = FakeCredit(
        reviews=[approved("mona")],
        closes=[
            issue(9, Person("mona", False), parent=issue(3, Person("lead", False), labels=("opportunity", "planned")))
        ],
        comments={7: [QUESTION, said("hubot"), said("mona")]},
        labelers={3: [Person("octocat", False)]},
        permissions={"octocat": "write"},
    )
    assert named(deciders(reads, reads.record, APP_LOGIN)) == [
        ("mona", True, "approved the pull request"),
        ("hubot", True, "answered the decision on the pull request"),
        ("lead", True, "filed #3"),
        ("octocat", True, "accepted #3 (planned)"),
    ]


USER_NODE = {"login": "octocat", "__typename": "User"}


def filed_node(
    number: int, repo: str = REPO, author: object = USER_NODE, labels: tuple[str, ...] = (), **more: object
) -> dict[str, object]:
    return {
        "number": number,
        "repository": {"nameWithOwner": repo},
        "authorAssociation": "OWNER",
        "author": author,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        **more,
    }


def answer(nodes: list[object], more: bool = False) -> dict[str, object]:
    references = {"pageInfo": {"hasNextPage": more}, "nodes": nodes}
    pr = {"closingIssuesReferences": references}
    return {"data": {"repository": {"nameWithOwner": REPO.upper(), "pullRequest": pr}}}


def test_s049_5_closing_references_parse_with_parents_in_the_repo_only() -> None:
    nodes: list[object] = [
        filed_node(9, labels=("Opportunity",), parent=filed_node(3, author={"login": "renovate", "__typename": "Bot"})),
        filed_node(5, repo="other/repo"),  # another repo's issue: its records aren't this repo's
        filed_node(10, author=None, parent=filed_node(4, repo="other/repo")),  # a deleted author
    ]
    assert closes_of(answer(nodes), 7) == [
        Filed(
            9,
            OCTO,
            "OWNER",
            frozenset({"opportunity"}),
            Filed(3, Person("renovate[bot]", True), "OWNER", frozenset(), None),
        ),
        Filed(10, None, "OWNER", frozenset(), None),
    ]


@pytest.mark.parametrize(
    "found",
    [
        answer([], more=True),
        answer([filed_node(9, labels=())]) | {"errors": [{"message": "no"}]},
        answer([{"number": 9}]),
        answer([filed_node(9, author="octocat")]),
        {"data": {"repository": None}},
    ],
)
def test_s049_5_a_malformed_or_cut_closing_reference_answer_exits_2(found: dict[str, object]) -> None:
    with pytest.raises(ReleaseError, match="closing issues"):
        closes_of(found, 7)


# -- GhCli reads the records ---------------------------------------------------------------------


def test_s049_3_gh_reads_the_pull_request_its_reviews_commits_accounts_and_settings(tmp_path: Path) -> None:
    """GhCli's credit reads, against a gh that answers from a script; proves: S-049-3, S-049-8"""
    user = {"login": APP_LOGIN, "type": "Bot"}
    answers = {
        "pulls/7/reviews": [
            json.dumps(
                {"user": {"login": "octocat", "type": "User"}, "state": "APPROVED", "author_association": "OWNER"}
            ),
            json.dumps({"user": None, "state": "APPROVED", "author_association": "NONE"}),
            json.dumps({"user": {"login": "mona", "type": "User"}, "state": "PENDING", "author_association": "OWNER"}),
        ],
        "pulls/7/commits": [
            json.dumps({"commit": {"message": "Add it", "author": {"name": "A", "email": "a@x"}}, "author": None})
        ],
    }
    pull_json = json.dumps({"number": 7, "user": user, "title": "Add it", "body": None})
    repo_json = json.dumps({"squash_merge_commit_message": "COMMIT_MESSAGES", "merge_commit_message": "PR_TITLE"})
    script = tmp_path / "gh"
    lines = "".join(
        f"  *{path}*) printf '%s\\n' {' '.join(repr(a) for a in found)} ;;\n" for path, found in answers.items()
    )
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"{lines}"
        f"  *pulls/7) echo '{pull_json}' ;;\n"
        """  *users/octocat) echo '{"id": 583231, "login": "octocat", "name": "The Octocat"}' ;;\n"""
        f"  *repos/{{owner}}/{{repo}}) echo '{repo_json}' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    hub = GhCli(tmp_path, gh=str(script))
    assert hub.credit_pull(7) == Pull(7, APP, "Add it", "")
    assert hub.credit_reviews(7) == [approved("octocat"), Review(None, "APPROVED", "NONE")]  # a draft isn't one
    assert hub.credit_commits(7) == [Commit("Add it", "A", "a@x", None)]
    assert hub.credit_account("octocat") == OCTOCAT
    assert hub.credit_messages() == Messages(Message.COMMIT_MESSAGES, Message.PR_TITLE)


def test_s049_8_an_unknown_merge_message_setting_exits_2() -> None:
    with pytest.raises(ReleaseError, match="squash_merge_commit_message as 'NEW'"):
        Messages.parse({"squash_merge_commit_message": "NEW", "merge_commit_message": "PR_TITLE"})


def test_s049_4_gh_reads_the_comments_closing_issues_label_events_and_permission(tmp_path: Path) -> None:
    """GhCli's reads for answerers, issue authors, and accepters; proves: S-049-4, S-049-5, S-049-6"""
    comment = {"user": {"login": "octocat", "type": "User"}, "author_association": "OWNER", "body": None}
    events = [
        {"event": "labeled", "label": {"name": "Planned"}, "actor": {"login": "octocat", "type": "User"}},
        {"event": "labeled", "label": {"name": "opportunity"}, "actor": {"login": "mona", "type": "User"}},
        {"event": "unlabeled", "label": {"name": "planned"}, "actor": {"login": "mona", "type": "User"}},
        {"event": "labeled", "label": {"name": "planned"}, "actor": None},
    ]
    graphql = json.dumps(answer([filed_node(9)]))
    script = tmp_path / "gh"
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *'number=7'*closingIssuesReferences*) echo '{graphql}' ;;\n"
        f"  *issues/7/comments*) printf '%s\\n' '{json.dumps(comment)}' ;;\n"
        f"  *issues/9/events*) printf '%s\\n' {' '.join(repr(json.dumps(e)) for e in events)} ;;\n"
        """  *collaborators/octocat/permission) echo '{"permission": "write", "role_name": "maintain"}' ;;\n"""
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    hub = GhCli(tmp_path, gh=str(script))
    assert hub.credit_comments(7) == [Comment(OCTO, "OWNER", "")]
    assert hub.credit_closes(7) == [Filed(9, OCTO, "OWNER", frozenset(), None)]
    assert hub.credit_labelers(9, "planned") == [OCTO, None]
    assert hub.credit_permission("octocat") == "write"
