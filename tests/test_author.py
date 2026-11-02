"""Spec 051, the modes and credit folding into them: [agents] author takes "app" or "decider"
and needs app_id; with it set a `shipmill gh pr merge` names the decider as credit = "decider"
does, whatever credit says; with neither key it runs as before (D-63). The assisted write, as
the decider, is tests/test_decider_token.py's"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.agents import AgentsConfig, Author, gh_identity_of
from shipmill.app_login import UserLogin, UserToken, client_secret_file, save_user_token
from shipmill.config import CONFIG_PATH, Table
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo
from .test_app import APP_ID, REPO
from .test_app_gh_merge import connected
from .test_credit import OCTOCAT_TRAILER, WITH_APP, CreditReader, FakeCredit, Runner, approved, body_of, gh

MERGE = ["pr", "merge", "7", "--squash"]
CREDITED = f"The change.\n\nFixes #9\n\nCo-authored-by: A <a@x>\n{OCTOCAT_TRAILER}"


def agents(**keys: object) -> Table:
    return Table({"prompt": "/t", **keys}, "shipmill.toml [agents]")


@dataclass
class EnvRunner(Runner):
    """Runner that also records the env gh runs with"""

    envs: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.envs.append(dict(env))
        return super().__call__(argv, env)


# -- S-051-1: the key --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["App", "person", "", "off", True, 1])
def test_s051_1_any_other_author_fails_to_load_naming_the_key_and_both_values(value: object) -> None:
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        AgentsConfig.parse(agents(app_id=APP_ID, author=value))
    message = str(raised.value)
    assert "[agents] author" in message and '"app"' in message and '"decider"' in message
    assert repr(value) in message


@pytest.mark.parametrize("value", ["app", "decider"])
def test_s051_1_author_without_app_id_fails_to_load_naming_the_key_and_both_values(value: str) -> None:
    with pytest.raises(ReleaseError) as raised:
        AgentsConfig.parse(agents(author=value))
    message = str(raised.value)
    assert f'[agents] author = "{value}" needs [agents] app_id' in message
    assert '"app"' in message and '"decider"' in message


def test_s051_1_author_reads_as_set_and_as_none_without_the_key(tmp_path: Path) -> None:
    assert AgentsConfig.parse(agents(app_id=APP_ID)).author is None
    assert AgentsConfig.parse(agents(app_id=APP_ID, author="app")).author is Author.APP
    assert AgentsConfig.parse(agents(app_id=APP_ID, author="decider")).author is Author.DECIDER
    (tmp_path / CONFIG_PATH).parent.mkdir()
    (tmp_path / CONFIG_PATH).write_text(POLICY + WITH_APP + 'author = "decider"\n', encoding="utf-8")
    assert gh_identity_of(tmp_path).author is Author.DECIDER
    (tmp_path / CONFIG_PATH).write_text(POLICY + '\n[agents]\nprompt = "/t"\nauthor = "app"\n', encoding="utf-8")
    with pytest.raises(ReleaseError, match=r"needs \[agents\] app_id"):  # every reader refuses it, gh too
        gh_identity_of(tmp_path)


# -- S-051-2: neither key ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [MERGE, ["pr", "merge", "7", "-s", "--body", "x"], ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"]],
)
def test_s051_2_neither_author_nor_credit_merges_with_ghs_arguments_unchanged_as_the_app(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP)
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, args, runner) == 0  # the credit reader raises when called
    assert [argv[1:] for argv in runner.calls] == [args]
    assert runner.stderr == [""]
    [env] = runner.envs
    assert env["GH_TOKEN"] == "token-1"  # the App's installation token


# -- S-051-3: author set, whatever credit says -------------------------------------------------


@pytest.mark.parametrize("author", ["app", "decider"])
@pytest.mark.parametrize("credit", [None, "off", "decider"])
def test_s051_3_author_names_the_decider_in_co_authored_by_whatever_credit_says(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], author: str, credit: str | None
) -> None:
    config = POLICY + WITH_APP + f'author = "{author}"\n' + ("" if credit is None else f'credit = "{credit}"\n')
    key = connected(repo, tmp_path, config)
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    runner = EnvRunner(capsys)
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    [argv] = runner.calls
    assert argv[1:5] == MERGE
    assert body_of(argv) == CREDITED
    # S-051-9: author = "decider" writes as the App when the decider stored no token, saying so
    fallback = "" if author == "app" else f"author: the App; `@octocat` has not run {cli_command()} app-login\n"
    assert runner.stderr == ["credit: `@octocat` approved the pull request\n" + fallback]
    [env] = runner.envs
    assert env["GH_TOKEN"] == "token-1"


def test_s051_3_the_apis_merge_refusal_names_author(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + 'author = "app"\ncredit = "off"\n')
    reader, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"], runner, reader)
    assert '[agents] author = "app"' in str(raised.value)
    assert (runner.calls, reader.envs) == ([], [])


# -- S-051-4: credit alone keeps spec 049's reading --------------------------------------------


def test_s051_4_credit_decider_without_author_merges_by_spec_049(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + 'credit = "decider"\n')
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    runner = Runner(capsys)
    assert gh(repo, tmp_path, key, MERGE, runner, reader) == 0
    [argv] = runner.calls
    assert body_of(argv) == CREDITED


def test_s051_4_credit_off_without_author_merges_with_ghs_arguments(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + 'credit = "off"\n')
    runner = Runner(capsys)
    assert gh(repo, tmp_path, key, MERGE, runner) == 0  # the credit reader raises when called
    assert [argv[1:] for argv in runner.calls] == [MERGE]


# -- S-051-3, S-051-4: doctor ------------------------------------------------------------------


def configure(repo: Repo, text: str) -> None:
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + text)


def credit_rows(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github) if c.name == "credit"]


AGENTS = f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n'
DECIDER = "decider, a merge names who decided it in Co-authored-by"


@pytest.mark.parametrize("credit", ["off", "decider"])
def test_s051_3_doctor_warns_that_author_replaces_credit_when_both_are_set(repo: Repo, credit: str) -> None:
    configure(repo, AGENTS + f'author = "app"\ncredit = "{credit}"\n')
    [row] = credit_rows(repo)
    assert row == Check(
        "WARN",
        "credit",
        f'{DECIDER} ([agents] author = "app", spec 051); [agents] author replaces [agents] credit, which is '
        "ignored: delete credit",
    )


@pytest.mark.parametrize("author", ["app", "decider"])
def test_s051_3_doctor_passes_author_alone_as_naming_the_decider(repo: Repo, author: str) -> None:
    configure(repo, AGENTS + f'author = "{author}"\n')
    assert credit_rows(repo) == [Check("PASS", "credit", f'{DECIDER} ([agents] author = "{author}", spec 051)')]


@pytest.mark.parametrize(("credit", "reading"), [("decider", f"{DECIDER} (spec 049)"), ("off", "off")])
def test_s051_4_doctor_warns_that_credit_is_deprecated_naming_author_app(repo: Repo, credit: str, reading: str) -> None:
    configure(repo, AGENTS + f'credit = "{credit}"\n')
    [row] = credit_rows(repo)
    assert (row.status, row.name) == ("WARN", "credit")
    assert row.detail.startswith(f"{reading}; [agents] credit is deprecated (spec 051)")
    assert 'set [agents] author = "app" instead' in row.detail
    assert "a repo that wants no trailer, leave both unset" in row.detail


def test_s051_2_doctor_passes_off_with_neither_key(repo: Repo) -> None:
    configure(repo, AGENTS)
    assert credit_rows(repo) == [Check("PASS", "credit", "off")]


# -- S-051-15: doctor's author row -------------------------------------------------------------


def author_rows(repo: Repo, home: Path) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github, home=home) if c.name == "author"]


def store(home: Path, app_id: int, login: str) -> None:
    """A stored token's file as app-login names it, its value a secret doctor must never print"""
    save_user_token(home, UserToken(app_id, "Iv1.client", UserLogin(login), "ghu_SECRET", None, "ghr_SECRET", None))


CLIENT_SECRET_VALUE = "cs_SECRET_VALUE"


def put_secret(home: Path, mode: int = 0o600, content: str = CLIENT_SECRET_VALUE) -> Path:
    """The App's client secret's file beside its key, as the maintainer puts it there"""
    path = client_secret_file(APP_ID, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def test_s051_15_doctor_names_autonomous_mode(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "app"\n')
    assert author_rows(repo, tmp_path) == [
        Check("PASS", "author", "app, the App writes and names the decider (spec 051)")
    ]


def test_s051_15_doctor_lists_the_logins_with_a_stored_token_in_assisted_mode(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "decider"\n')
    store(tmp_path, APP_ID, "Octocat")
    store(tmp_path, APP_ID, "hubot")
    store(tmp_path, APP_ID + 1, "monalisa")  # another App's token is not this App's consent
    secret = put_secret(tmp_path)
    [row] = author_rows(repo, tmp_path)
    assert row == Check(
        "PASS",
        "author",
        f"decider, 2 people authorized (spec 051): `@hubot`, `@octocat`; the App's client secret is at {secret} "
        "(mode 0600)",
    )
    assert "SECRET" not in row.detail


def test_s051_15_doctor_names_one_person_authorized(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "decider"\n')
    store(tmp_path, APP_ID, "octocat")
    secret = put_secret(tmp_path, 0o400)
    assert author_rows(repo, tmp_path) == [
        Check(
            "PASS",
            "author",
            f"decider, 1 person authorized (spec 051): `@octocat`; the App's client secret is at {secret} (mode 0400)",
        )
    ]


def test_s051_15_doctor_says_no_one_authorized_in_assisted_mode(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "decider"\n')
    put_secret(tmp_path)
    [row] = author_rows(repo, tmp_path)
    assert (row.status, row.name) == ("PASS", "author")
    assert row.detail.startswith("decider, 0 people authorized (spec 051): every write goes as the App")
    assert "app-login" in row.detail


@pytest.mark.parametrize(
    ("mode", "content", "why"),
    [
        (None, "", "no App client secret at {path}: an expired token is refreshed without it, which GitHub may "
                   "refuse; put the App's client secret there with mode 0600"),
        (0o644, CLIENT_SECRET_VALUE, "the App's client secret {path} has mode 0644, wider than 0600; run "
                                     "`chmod 600 {path}`; until then an expired token's write goes as the App"),
        (0o640, CLIENT_SECRET_VALUE, "the App's client secret {path} has mode 0640, wider than 0600"),
        (0o700, CLIENT_SECRET_VALUE, "the App's client secret {path} has mode 0700, wider than 0600"),
        (0o600, "", "the App's client secret {path} is empty; write the App's client secret into it; until then"),
    ],
)  # fmt: skip
def test_s051_15_doctor_warns_on_a_client_secret_missing_too_open_or_empty_never_printing_it(
    repo: Repo, tmp_path: Path, mode: int | None, content: str, why: str
) -> None:
    configure(repo, AGENTS + 'author = "decider"\n')
    store(tmp_path, APP_ID, "octocat")
    path = client_secret_file(APP_ID, tmp_path) if mode is None else put_secret(tmp_path, mode, content)
    [row] = author_rows(repo, tmp_path)
    assert row.status == "WARN"
    assert row.detail.startswith("decider, 1 person authorized (spec 051): `@octocat`; ")
    assert why.format(path=path) in row.detail
    assert CLIENT_SECRET_VALUE not in row.detail and "SECRET" not in row.detail


def test_s051_15_doctor_never_reads_the_client_secret(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "decider"\n')
    path = put_secret(tmp_path, 0o200)  # write-only: reading it would fail
    [row] = author_rows(repo, tmp_path)
    assert row == Check(
        "PASS",
        "author",
        f"decider, 0 people authorized (spec 051): every write goes as the App until a person runs "
        f"`{cli_command()} app-login`; the App's client secret is at {path} (mode 0200)",
    )


def test_s051_15_doctor_names_no_client_secret_outside_assisted_mode(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "app"\n')
    put_secret(tmp_path, 0o644)
    [row] = author_rows(repo, tmp_path)
    assert row.status == "PASS" and "client secret" not in row.detail


def test_s051_15_doctor_warns_on_a_stored_file_named_without_a_login(repo: Repo, tmp_path: Path) -> None:
    configure(repo, AGENTS + 'author = "decider"\n')
    folder = tmp_path / ".config" / "shipmill"
    folder.mkdir(parents=True)
    (folder / f"user-{APP_ID}-not_a_login.json").write_text("{}")
    [row] = author_rows(repo, tmp_path)
    assert (row.status, row.name) == ("WARN", "author")
    assert row.detail.startswith("decider (spec 051); can't read the stored logins:")


@pytest.mark.parametrize(
    ("config", "detail"),
    [
        ("", "unset (spec 051)"),
        (
            'credit = "decider"\n',
            'unset (spec 051); the deprecated [agents] credit = "decider" reads as a merge names the decider in '
            "Co-authored-by (spec 049)",
        ),
        ('credit = "off"\n', 'unset (spec 051); the deprecated [agents] credit = "off" reads as no trailer (spec 049)'),
    ],
)
def test_s051_15_doctor_names_author_unset_with_the_credit_reading(
    repo: Repo, tmp_path: Path, config: str, detail: str
) -> None:
    configure(repo, AGENTS + config)
    assert author_rows(repo, tmp_path) == [Check("PASS", "author", detail)]
