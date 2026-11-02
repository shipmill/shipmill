"""Spec 051, the assisted write: with [agents] author = "decider", `shipmill gh` runs `issue
create`, `pr create`, and `pr merge` with the decider's stored user access token, refreshed
first when it has expired, and as the App after one stderr line saying why otherwise; every
other command runs as the App. No test reaches the network: GitHub's API is UserApi, github.com
FakeWeb, the records FakeCredit"""

import datetime as dt
import io
import json
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.app import Answer
from shipmill.app_gh import decided_in, write_command
from shipmill.app_login import (
    ACCESS_TOKEN,
    CLIENT_SECRET,
    AsApp,
    SecretRefused,
    Unreachable,
    UserLogin,
    UserToken,
    client_secret,
    client_secret_file,
    decider_token,
    load_user_token,
    save_user_token,
    user_file,
)
from shipmill.cli import main
from shipmill.credit import MARKER, Comment, Filed, Person, closed_by, issue_of
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo
from .test_app import APP_ID, REPO, FakeSigner
from .test_app_gh_merge import CODE, FakeReads, Reader, connected
from .test_app_token import FAKE_GH, MintApi, executable
from .test_credit import (
    APP,
    OCTOCAT_TRAILER,
    WITH_APP,
    CreditReader,
    FakeCredit,
    approved,
    body_of,
    refusing,
)

ASSISTED = POLICY + WITH_APP + 'author = "decider"\n'
ACCESS = "ghu_octocat-access-secret"
REFRESH = "ghr_octocat-refresh-secret"
NEW_ACCESS = "ghu_octocat-new-access-secret"
NEW_REFRESH = "ghr_octocat-new-refresh-secret"
CLIENT = "cs_the-apps-client-secret"  # the App's client secret, in its file beside the App's key
SECRETS = (ACCESS, REFRESH, NEW_ACCESS, NEW_REFRESH, CLIENT)
APP_TOKEN = "token-1"  # the App's installation token MintApi mints
OCTO = Person("octocat", False)
MERGE = ["pr", "merge", "7", "--squash"]
ISSUE = ["issue", "create", "--title", "t", "--body", "x"]


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def store(tmp_path: Path, expires: dt.timedelta = dt.timedelta(hours=8), refresh: str | None = REFRESH) -> Path:
    """octocat's stored token for the App, its access token expiring after expires"""
    home = tmp_path / "home"
    token = UserToken(
        APP_ID,
        "Iv1.client",
        UserLogin("octocat"),
        ACCESS,
        now() + expires,
        refresh,
        None if refresh is None else now() + dt.timedelta(days=180),
    )
    return save_user_token(home, token)


def put_secret(tmp_path: Path, content: str = CLIENT + "\n", mode: int = 0o600) -> Path:
    """The App's client secret's file in the home gh runs with, as the maintainer puts it there"""
    path = client_secret_file(APP_ID, tmp_path / "home")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


@dataclass
class UserApi(MintApi):
    """MintApi that also answers GET /user for the user access tokens it knows"""

    users: dict[str, str] = field(default_factory=lambda: {ACCESS: "octocat", NEW_ACCESS: "octocat"})
    user_status: int = 200

    def get(self, path: str, token: str | None) -> Answer:
        if path != "/user":
            return super().get(path, token)
        self.calls.append((path, token))
        login = self.users.get(token or "")
        if login is None or self.user_status != 200:
            return Answer(self.user_status if self.user_status != 200 else 401, '{"message": "Bad credentials"}')
        return Answer(200, json.dumps({"login": login, "id": 583231}))


@dataclass
class FakeWeb:
    """github.com: answers the refresh with answer, or is out of reach; records each request"""

    answer: Answer | None = None
    sent: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)

    def send(self, method: str, url: str, headers: Mapping[str, str], data: bytes | None) -> Answer:
        fields = dict(urllib.parse.parse_qsl((data or b"").decode()))
        self.sent.append((method, url, fields))
        if self.answer is None:
            raise Unreachable(f"GitHub is unreachable for {method} {url}: timed out")
        return self.answer


def granted() -> Answer:
    return Answer(
        200,
        json.dumps(
            {
                "access_token": NEW_ACCESS,
                "expires_in": 28800,
                "refresh_token": NEW_REFRESH,
                "refresh_token_expires_in": 15897600,
                "token_type": "bearer",
            }
        ),
    )


@dataclass
class EnvRunner:
    """gh: records its argv, its env, and what stdout and stderr held when it ran"""

    capsys: pytest.CaptureFixture[str]
    calls: list[list[str]] = field(default_factory=list)
    envs: list[dict[str, str]] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    stdout: list[str] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.calls.append(list(argv))
        self.envs.append(dict(env))
        out = self.capsys.readouterr()
        self.stderr.append(out.err)
        self.stdout.append(out.out)
        return 0

    @property
    def token(self) -> str:
        [env] = self.envs
        return env["GH_TOKEN"]


def gh(
    repo: Repo,
    tmp_path: Path,
    key: Path,
    args: list[str],
    runner: EnvRunner,
    credit: CreditReader | None = None,
    api: UserApi | None = None,
    web: FakeWeb | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    executable(fakes / "gh", FAKE_GH)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return main(
        ["--repo", str(repo.root), "gh", "--app-key", str(key), *args],
        api=api if api is not None else UserApi(),
        signer=FakeSigner(),
        stdin=io.StringIO(""),
        environ={"PATH": f"{fakes}:/usr/bin:/bin", **(environ or {})},
        home=home,
        gh_runner=runner,
        merge_reader=Reader(FakeReads((CODE,))),
        credit_reader=credit if credit is not None else refusing,
        web=web if web is not None else FakeWeb(),
    )


def filed(number: int, author: Person | None = OCTO, association: str = "OWNER", agent: bool = False) -> Filed:
    return Filed(number, author, association, frozenset(), None, agent)


def as_person(runner: EnvRunner, why: str) -> None:
    assert runner.token == ACCESS
    assert runner.stderr[-1].endswith(f"author: `@octocat`, who {why}\n")


def as_app(runner: EnvRunner, why: str) -> None:
    assert runner.token == APP_TOKEN
    assert runner.stderr[-1].endswith(f"author: the App; {why}\n")
    assert runner.stderr[-1].count("author: ") == 1


# -- S-051-7: the three writes run as the decider ----------------------------------------------


def test_s051_7_pr_merge_runs_with_the_stored_token_of_the_pull_requests_decider(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    api, runner = UserApi(), EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, api) == 0
    as_person(runner, "approved the pull request")
    assert body_of(runner.calls[0]).endswith(OCTOCAT_TRAILER)  # spec 049's trailers, as before
    assert ("/user", ACCESS) in api.calls  # GitHub took the token before the write
    assert all(env["GH_TOKEN"] == APP_TOKEN for env in reader.envs)  # the records are read as the App


def test_s051_7_the_first_decider_in_spec_049s_order_is_the_one_written_as(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)  # octocat has a token, hubot doesn't: hubot approved, so hubot is the decider
    reader = CreditReader(FakeCredit(reviews=[approved("hubot", "MEMBER")], closes=[filed(9)]))
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    as_app(runner, f"`@hubot` has not run {cli_command()} app-login")


def test_s051_7_pr_create_runs_as_the_decider_of_the_issues_its_body_closes(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    credit = FakeCredit(issues={9: filed(9), 11: None})  # #11 is a pull request: it closes nothing
    runner = EnvRunner(capsys)
    args = ["pr", "create", "--title", "t", "--body", f"Fixes #9\ncloses #11\nfixes other/repo#12 ({REPO})"]
    assert gh(repo, tmp_path, key, args, runner, CreditReader(credit)) == 0
    as_person(runner, "filed #9")
    assert [r for r in credit.read if r.startswith("issue")] == ["issue 9", "issue 11"]


def test_s051_7_pr_create_takes_an_answerer_before_the_issues_author(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    question = Comment(APP, "NONE", f"{MARKER}\n@octocat Decision needed: which?", False)
    answer = Comment(OCTO, "OWNER", "1", False)
    credit = FakeCredit(issues={9: filed(9, Person("hubot", False))}, comments={9: [question, answer]})
    runner = EnvRunner(capsys)
    args = ["pr", "create", "--title", "t", "--body", "Resolves #9"]
    assert gh(repo, tmp_path, key, args, runner, CreditReader(credit)) == 0
    as_person(runner, "answered the decision on #9")


@pytest.mark.parametrize(
    "flag",
    [["--decided-in", "9"], ["--decided-in=9"], ["--decided-in", "#9"]],
)
@pytest.mark.parametrize("at", [2, 4, 6])  # right after create, between flags, last
def test_s051_7_issue_create_runs_as_the_decider_decided_in_names_and_the_flag_never_reaches_gh(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: list[str], at: int
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    credit = FakeCredit(issues={9: filed(9)})
    runner = EnvRunner(capsys)
    args = [*ISSUE[:at], *flag, *ISSUE[at:]]
    assert gh(repo, tmp_path, key, args, runner, CreditReader(credit)) == 0
    as_person(runner, "filed #9")
    [argv] = runner.calls
    assert not any(arg.startswith("--decided-in") for arg in argv)
    assert argv[1:5] == ISSUE[:4]


def test_s051_7_issue_create_decided_in_a_pull_request_takes_spec_049s_deciders(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    credit = FakeCredit(issues={7: None}, reviews=[approved("octocat", "MEMBER")])
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, [*ISSUE, "--decided-in", "7"], runner, CreditReader(credit)) == 0
    as_person(runner, "approved the pull request")
    assert credit.read[:3] == ["issue 7", "pull 7", "reviews 7"]


@pytest.mark.parametrize("author", [None, "app"])
def test_s051_7_decided_in_never_reaches_gh_in_autonomous_mode_or_without_author(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], author: str | None
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + ("" if author is None else f'author = "{author}"\n'))
    store(tmp_path)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, [*ISSUE, "--decided-in=9"], runner) == 0  # the credit reader raises when called
    [argv] = runner.calls
    assert argv[1:] == ISSUE[:4] + ["--body", argv[-1]]
    assert runner.token == APP_TOKEN
    assert runner.stderr == [""]


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "create", "--title", "t", "--body", "x", "--decided-in", "9"],
        ["pr", "merge", "7", "--squash", "--decided-in=9"],
        ["issue", "comment", "9", "--body", "x", "--decided-in", "9"],
        ["issue", "edit", "9", "--decided-in", "9"],
        ["api", "repos/o/r/issues", "--decided-in", "9"],
        ["label", "list", "--decided-in", "9"],
    ],
)
def test_s051_7_decided_in_on_any_command_but_issue_create_exits_2_before_gh(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    runner = EnvRunner(capsys)
    with pytest.raises(ReleaseError, match="only `gh issue create` takes it"):
        gh(repo, tmp_path, key, args, runner)
    assert runner.calls == []


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--decided-in", "9", "--decided-in", "10"], "given 2 times"),
        (["--decided-in", "abc"], "takes the number"),
        (["--decided-in="], "takes the number"),
        (["--decided-in"], "needs a value"),
    ],
)
def test_s051_7_a_decided_in_given_twice_or_without_a_number_exits_2(flags: list[str], message: str) -> None:
    with pytest.raises(ReleaseError, match=message):
        decided_in([*ISSUE, *flags])


def test_s051_7_decided_in_reads_the_flag_not_another_flags_value_nor_past_the_double_dash() -> None:
    assert decided_in(["issue", "create", "--title", "--decided-in", "--body", "x"]) == (
        None,
        ["issue", "create", "--title", "--decided-in", "--body", "x"],
    )
    assert decided_in(["issue", "create", "--body", "x", "--", "--decided-in", "9"])[0] is None
    assert decided_in(["issue", "new", "-t", "t", "--decided-in", "5", "-b", "x"]) == (
        5,
        ["issue", "new", "-t", "t", "-b", "x"],
    )


@pytest.mark.parametrize(
    ("args", "command"),
    [
        (["issue", "create", "--body", "x"], "issue create"),
        (["issue", "new"], "issue create"),
        (["pr", "-R", "o/r", "create"], "pr create"),
        (["pr", "merge", "7", "--squash"], "pr merge"),
        (["pr", "create", "--help"], None),
        (["pr", "merge", "7", "-h"], None),
        (["issue", "comment", "9"], None),
        (["pr", "review", "7", "--approve"], None),
        (["api", "repos/o/r/issues"], None),
        ([], None),
    ],
)
def test_s051_12_only_issue_create_pr_create_and_pr_merge_are_written_as_the_decider(
    args: list[str], command: str | None
) -> None:
    assert write_command(args) == command


def test_s051_7_closing_references_name_the_repos_issues_once_in_order() -> None:
    body = (
        f"Fixes #9 and closes #15.\n- closes {REPO}#10.\nResolved: https://github.com/{REPO}/issues/11\n"
        f"fixes other/repo#12, see #13\n  * fixes #9\nFIXES {REPO.upper()}#14"
    )
    assert closed_by(body, REPO) == [9, 10, 11, 14]
    assert closed_by("Prefixes #9; fixes#9", REPO) == []


@pytest.mark.parametrize(
    "body",
    [
        "Explains why `Fixes #12` is wrong",
        "`Fixes #12` is quoted",
        "Fixes `#12`",
        "Intro\n```\nFixes #12\n```\n",
        "Intro\n~~~md\nFixes #12\n~~~\n",
        "This doesn't fix #12 yet",
        "See the plan; it fixes #12 later",
    ],
)
def test_s051_7_a_keyword_in_code_or_mid_line_closes_nothing(body: str) -> None:
    """triage_state.py's keyword_closes rule (#416): a pull request whose body only quotes a
    keyword names no decider by it, so no one is written as by mistake"""
    assert closed_by(body, REPO) == []
    assert closed_by(body + "\nFixes #9", REPO) == [9]


def test_s051_7_one_issue_parses_with_its_parent_or_reads_as_a_pull_request() -> None:
    def node(number: int, **extra: object) -> dict[str, object]:
        return {
            "number": number,
            "repository": {"nameWithOwner": REPO},
            "authorAssociation": "OWNER",
            "body": "x",
            "author": {"login": "octocat", "__typename": "User"},
            "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": "Planned"}]},
            **extra,
        }

    def answer(found: object) -> dict[str, object]:
        return {"data": {"repository": {"nameWithOwner": REPO, "issueOrPullRequest": found}}}

    parent = Filed(3, OCTO, "OWNER", frozenset({"planned"}), None, False)
    assert issue_of(answer({"__typename": "Issue", **node(9, parent=node(3))}), 9) == Filed(
        9, OCTO, "OWNER", frozenset({"planned"}), parent, False
    )
    assert issue_of(answer({"__typename": "PullRequest"}), 7) is None
    with pytest.raises(ReleaseError, match="no issue or pull request"):
        issue_of(answer(None), 9)


# -- S-051-8: an expired token is refreshed first ----------------------------------------------


@pytest.mark.parametrize("expires", [dt.timedelta(hours=-1), dt.timedelta(minutes=2)])
def test_s051_8_an_expired_token_is_refreshed_before_the_write_and_stored_again_0600(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], expires: dt.timedelta
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path, expires)
    secret = put_secret(tmp_path)
    web, runner = FakeWeb(granted()), EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, web=web) == 0
    assert runner.token == NEW_ACCESS
    [(method, url, fields)] = web.sent
    assert (method, url) == ("POST", ACCESS_TOKEN)
    assert fields == {
        "client_id": "Iv1.client",
        "grant_type": "refresh_token",
        "refresh_token": REFRESH,
        "client_secret": CLIENT,  # from the file beside the App's key, its newline dropped
    }
    assert path.stat().st_mode & 0o777 == 0o600
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert (stored["access_token"], stored["refresh_token"]) == (NEW_ACCESS, NEW_REFRESH)
    assert dt.datetime.fromisoformat(stored["expires_at"]) > now() + dt.timedelta(hours=7)
    # written atomically: no temporary left; the secret's file is untouched
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([path.name, secret.name])
    assert secret.read_text(encoding="utf-8") == CLIENT + "\n"


def test_s051_8_a_refresh_without_the_client_secret_file_sends_none(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path, dt.timedelta(hours=-1))
    web, runner = FakeWeb(granted()), EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, web=web, environ={CLIENT_SECRET: "from-env"}) == 0
    assert "client_secret" not in web.sent[0][2]  # app-logout's environment variable is not the refresh's
    assert runner.token == NEW_ACCESS
    assert not client_secret_file(APP_ID, tmp_path / "home").exists()  # shipmill never creates it


@pytest.mark.parametrize(
    ("content", "mode", "why"),
    [
        (CLIENT, 0o644, "has mode 0644, wider than 0600; run `chmod 600 {path}`"),
        (CLIENT, 0o604, "has mode 0604, wider than 0600"),
        (CLIENT, 0o660, "has mode 0660, wider than 0600"),
        (CLIENT, 0o700, "has mode 0700, wider than 0600"),
        ("", 0o600, "is empty; write the App's client secret into it"),
        (" \n", 0o600, "is empty; write the App's client secret into it"),
        (f"{CLIENT}\n{CLIENT}\n", 0o600, "holds more than one word"),
    ],
)
def test_s051_8_a_client_secret_too_open_or_empty_writes_as_the_app_and_keeps_the_token_file(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str, mode: int, why: str
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path, dt.timedelta(hours=-1))
    secret = put_secret(tmp_path, content, mode)
    web, runner = FakeWeb(granted()), EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, web=web) == 0
    assert runner.token == APP_TOKEN
    [line] = [x for x in runner.stderr[-1].splitlines() if x.startswith("author: ")]
    assert line.startswith(
        f"author: the App; `@octocat`'s expired token isn't refreshed: the App's client secret {secret} "
        + why.format(path=secret)
    )
    assert web.sent == []  # no refresh goes without the secret the maintainer meant to give it
    assert path.exists()  # the person's token is kept: the fault is the host's, not theirs
    assert secret.stat().st_mode & 0o777 == mode  # shipmill never fixes or rewrites it
    said = "".join(runner.stdout + runner.stderr)
    assert CLIENT not in said
    assert body_of(runner.calls[0]).endswith(OCTOCAT_TRAILER)  # as autonomous mode merges it


@pytest.mark.parametrize(
    ("content", "mode"), [(CLIENT, 0o644), (CLIENT, 0o640), ("", 0o600), (f"{CLIENT} {CLIENT}", 0o600)]
)
def test_s051_8_a_refused_client_secret_never_reaches_the_exception_or_its_repr(
    tmp_path: Path, content: str, mode: int
) -> None:
    put_secret(tmp_path, content, mode)
    with pytest.raises(SecretRefused) as raised:
        client_secret(APP_ID, tmp_path / "home")
    assert CLIENT not in str(raised.value) and CLIENT not in repr(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_s051_8_the_client_secret_reads_from_its_file_or_none() -> None:
    home = Path("/nonexistent-shipmill-home")
    assert client_secret_file(APP_ID, home) == home / ".config" / "shipmill" / f"app-{APP_ID}-client-secret"
    assert client_secret(APP_ID, home) is None


def test_s051_8_a_non_utf8_client_secret_is_refused_without_quoting_it(tmp_path: Path) -> None:
    path = put_secret(tmp_path)
    path.write_bytes(b"\xff\xfe" + CLIENT.encode())
    with pytest.raises(SecretRefused, match="is not UTF-8 text") as raised:
        client_secret(APP_ID, tmp_path / "home")
    assert CLIENT not in str(raised.value)


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        (Answer(200, '{"error": "bad_refresh_token"}'), "bad_refresh_token"),
        (Answer(200, '{"error": "incorrect_client_credentials"}'), "incorrect_client_credentials"),
        (Answer(500, "oops"), "no token in its answer"),
        (Answer(200, '{"token_type": "bearer"}'), "no token in its answer"),
    ],
)
def test_s051_8_a_refused_refresh_deletes_the_stored_file_and_writes_as_the_app(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], answer: Answer, why: str
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path, dt.timedelta(hours=-1))
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, web=FakeWeb(answer)) == 0
    as_app(runner, f"GitHub refused to refresh `@octocat`'s token ({why}), so its stored file is deleted; "
           f"`@octocat` runs `{cli_command()} app-login` again to write as themselves")  # fmt: skip
    assert not path.exists()
    assert body_of(runner.calls[0]).endswith(OCTOCAT_TRAILER)  # autonomous mode's trailer


def test_s051_8_a_token_with_no_live_refresh_token_is_deleted_and_the_app_writes(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path, dt.timedelta(hours=-1), refresh=None)
    web, runner = FakeWeb(granted()), EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, web=web) == 0
    assert runner.token == APP_TOKEN
    assert "`@octocat`'s token expired and can't be refreshed" in runner.stderr[0]
    assert (web.sent, path.exists()) == ([], False)


def test_s051_8_github_out_of_reach_for_the_refresh_keeps_the_file_and_the_app_writes(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path, dt.timedelta(hours=-1))
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, web=FakeWeb(None)) == 0
    as_app(runner, "GitHub couldn't be reached to refresh `@octocat`'s expired token")
    assert path.exists()


# -- S-051-9: no decider, no token, or a refused token: the App writes, saying why -------------


def test_s051_9_a_merge_no_record_decided_goes_as_the_app_saying_so(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, MERGE, runner, CreditReader(FakeCredit())) == 0
    as_app(runner, "no trusted person decided pull request #7")
    assert runner.calls[0][1:] == MERGE  # as autonomous mode merges it: no decider, no trailer


@pytest.mark.parametrize(
    ("args", "credit", "why"),
    [
        (ISSUE, FakeCredit(), "no --decided-in names the issue or pull request that decided it"),
        ([*ISSUE, "--decided-in", "9"], FakeCredit(issues={9: filed(9, agent=True)}), "no trusted person decided #9"),
        (
            [*ISSUE, "--decided-in", "9"],
            FakeCredit(issues={9: filed(9, association="NONE")}),
            "no trusted person decided #9",
        ),
        (
            ["pr", "create", "--body", "No reference"],
            FakeCredit(),
            "the pull request's body closes no issue of the repo",
        ),
        (
            ["pr", "create", "--body", "Fixes #9"],
            FakeCredit(issues={9: filed(9, None)}),
            "no trusted person decided #9",
        ),
    ],
)
def test_s051_9_a_create_with_no_decider_goes_as_the_app_saying_why(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], credit: FakeCredit, why: str
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, args, runner, CreditReader(credit)) == 0
    as_app(runner, why)


@dataclass
class Unreadable(FakeCredit):
    def credit_issue(self, number: int) -> Filed | None:
        raise ReleaseError(f"gh api graphql printed errors or no object for #{number}: {{'errors': [...]}}")


def test_s051_9_a_decider_that_cant_be_read_goes_as_the_app_never_as_the_host(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, [*ISSUE, "--decided-in", "9"], runner, CreditReader(Unreadable())) == 0
    assert runner.token == APP_TOKEN
    assert runner.stderr[0].startswith("author: the App; its decider can't be read: gh api graphql printed errors")


def test_s051_9_a_decider_with_no_stored_token_goes_as_the_app_naming_them_in_a_code_span(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    as_app(runner, f"`@octocat` has not run {cli_command()} app-login")
    assert body_of(runner.calls[0]).endswith(OCTOCAT_TRAILER)  # autonomous mode's trailer


@pytest.mark.parametrize("status", [401, 403])
def test_s051_9_a_token_github_refuses_goes_as_the_app_and_keeps_the_file(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], status: int
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path)
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, UserApi(user_status=status)) == 0
    as_app(runner, f"GitHub refused `@octocat`'s stored token (status {status}); "
           f"`@octocat` runs `{cli_command()} app-login` again to write as themselves")  # fmt: skip
    assert path.exists()


@pytest.mark.parametrize(
    ("record", "why"),
    [
        ("not json", "is malformed (not JSON)"),
        ('{"app_id": 1}', "is malformed (client_id"),
    ],
)
def test_s051_9_a_malformed_stored_file_goes_as_the_app(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], record: str, why: str
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path)
    path.write_text(record, encoding="utf-8")
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    assert runner.token == APP_TOKEN
    assert runner.stderr[0].startswith("credit: `@octocat` approved the pull request\nauthor: the App; `@octocat`'s ")
    assert why in runner.stderr[0]


def test_s051_9_a_stored_token_of_another_login_goes_as_the_app(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    assert gh(repo, tmp_path, key, MERGE, runner, reader, UserApi(users={ACCESS: "hubot"})) == 0
    as_app(runner, f"`@octocat`'s stored token isn't theirs by GET /user; "
           f"`@octocat` runs `{cli_command()} app-login` again to write as themselves")  # fmt: skip


# -- S-051-12: every other command runs as the App ---------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "comment", "9", "--body", "x"],
        ["issue", "close", "9"],
        ["issue", "edit", "9", "--add-label", "bug"],
        ["pr", "review", "7", "--approve"],
        ["pr", "comment", "7", "--body", "x"],
        ["pr", "edit", "7", "--add-label", "bug"],
        ["pr", "create", "--help"],
        ["label", "create", "planned"],
        ["api", "repos/o/r/issues/9/comments", "-f", "body=x"],
        ["api", "repos/o/r/issues/9/labels", "-f", "labels[]=bug"],
        ["release", "view"],
    ],
)
def test_s051_12_every_other_command_runs_with_the_apps_installation_token(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    store(tmp_path)  # a token is stored, and still not used
    api, runner = UserApi(), EnvRunner(capsys)
    assert gh(repo, tmp_path, key, args, runner, api=api) == 0  # the credit reader raises when called
    assert runner.token == APP_TOKEN
    assert runner.stderr == [""]
    assert not any(path == "/user" for path, _ in api.calls)


# -- No token value ever reaches output, an error, or a repr -----------------------------------


@pytest.mark.parametrize(
    ("expires", "answer", "user_status"),
    [
        (dt.timedelta(hours=8), None, 200),  # written as the person
        (dt.timedelta(hours=8), None, 401),  # refused
        (dt.timedelta(hours=-1), granted(), 200),  # refreshed
        (dt.timedelta(hours=-1), Answer(200, json.dumps({"error": "bad_refresh_token", "x": REFRESH})), 200),
    ],
)
def test_s051_9_no_token_value_reaches_stdout_stderr_or_a_record_repr(
    repo: Repo,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    expires: dt.timedelta,
    answer: Answer | None,
    user_status: int,
) -> None:
    key = connected(repo, tmp_path, ASSISTED)
    path = store(tmp_path, expires)
    put_secret(tmp_path)  # the client secret is never said either, nor in gh's env
    runner = EnvRunner(capsys)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    api = UserApi(user_status=user_status)
    assert gh(repo, tmp_path, key, MERGE, runner, reader, api, FakeWeb(answer)) == 0
    after = capsys.readouterr()
    said = "".join(runner.stdout + runner.stderr) + after.out + after.err + " ".join(runner.calls[0])
    assert not any(secret in said for secret in SECRETS)
    assert not any(CLIENT in value for value in runner.envs[0].values())
    if path.exists():
        assert not any(secret in repr(load_user_token(path)) for secret in SECRETS)


def test_s051_9_a_malformed_file_quoting_a_token_never_reaches_the_error(tmp_path: Path) -> None:
    path = user_file(APP_ID, UserLogin("octocat"), tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"app_id": APP_ID, "client_id": "c", "login": "octocat", "access_token": 5,
                                "refresh_token": REFRESH}), encoding="utf-8")  # fmt: skip
    with pytest.raises(AsApp) as raised:
        decider_token(APP_ID, UserLogin("octocat"), tmp_path, UserApi(), FakeWeb(), now())
    assert REFRESH not in str(raised.value)
