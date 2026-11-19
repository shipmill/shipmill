"""Spec 081: `shipmill gh` refuses a write whose text holds a private term (to a public repo), a
secret's exact value, or a known token format, before gh runs. No test reaches the network:
gh is a Runner, its reads a Visibility capture. Names are invented: `Acme`, `example` hosts"""

import io
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agent_marker import MARKER
from shipmill.app_gh import feed_gh, sent_texts, write_repo
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.leaks import (
    FIX,
    PRIVATE_FILE,
    Destination,
    Detector,
    LeakRefused,
    Secret,
    Term,
    Text,
    Visibility,
    dotenv_secrets,
    refusal,
    scan,
)

from .test_agent_marker import AGENTS_NO_APP, HOST_IDENTITY
from .test_app import REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, MintApi, executable

ROOT = Path(__file__).resolve().parent.parent
TERM = "Acme Rocket"
LEAKED = "notes on acme  rocket's launch"  # a run of whitespace matches the term's space
CLEAN = "notes on AcmeRocketry's launch"  # no word boundary: no match
PUBLIC = "acme/widgets"

# Tokens are put together at run time, so no file of the repo holds one whole
GITHUB_TOKEN = "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
ANTHROPIC_KEY = "sk-" + "ant-" + "api03-Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2"
AWS_KEY_ID = "AKIA" + "Z7Q2EXAMPLE4ACME"
SLACK_TOKEN = "xox" + "b-1234567890-acmeexample"
PEM_BLOCK = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    + "MIIEowIBAAKCAQEAexampleAcmeKeyMaterial0123\n"
    + "-----END RSA PRIVATE KEY-----"
)
URL_PASSWORD = "https://deploy:" + "Hunter2Acme9" + "@git.example.com/acme/widgets.git"
FORMATS = [
    (GITHUB_TOKEN, "a GitHub token (ghp_…)"),
    (ANTHROPIC_KEY, "an Anthropic key (sk-a…)"),
    (AWS_KEY_ID, "an AWS access key id (AKIA…)"),
    (SLACK_TOKEN, "a Slack token (xoxb…)"),
    (PEM_BLOCK, "a PEM private key (----…)"),
    (URL_PASSWORD, "a URL with a password (http…)"),
]
SHOWN_AFTER = 4  # a format's characters a finding may name


@dataclass
class Reads:
    """Stands in for the gh that reads: a repo's visibility (`gh api repos/<r> --jq .visibility`)
    answers visibility, or exits code; an edit's current body answers an agent's body"""

    visibility: str = "public"
    code: int = 0
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        if "--jq" in argv:
            return self.code, f"{self.visibility}\n"
        return 0, f'{{"body": "was\\n\\n{MARKER}"}}'

    @property
    def reads(self) -> list[str]:
        """The repos whose visibility was read"""
        return [argv[2].removeprefix("repos/") for argv in self.calls if "--jq" in argv]


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


def private(host: Host, text: str) -> Path:
    path = host.home / PRIVATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def with_term(host: Host) -> None:
    private(host, f'terms = ["{TERM}"]\n')


def gh(
    root: Path,
    args: list[str],
    host: Host,
    capture: Reads | None = None,
    stdin: str = "",
    environ: Mapping[str, str] | None = None,
) -> Runner:
    """`shipmill gh args` run to its end: gh ran once (the Runner answers 7)"""
    runner = Runner()
    code = main(
        ["--repo", str(root), "gh", *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(**(environ or {})),
        home=host.home,
        gh_runner=runner,
        stdin=io.StringIO(stdin),
        gh_capture=capture or Reads(),
    )
    assert code == 7
    assert len(runner.calls) == 1
    return runner


def refused(
    root: Path,
    args: list[str],
    host: Host,
    capture: Reads | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """`shipmill gh args` refused by the leak check, gh never run; its refusal"""
    runner = Runner()
    with pytest.raises(LeakRefused) as caught:
        main(
            ["--repo", str(root), "gh", *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(**(environ or {})),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(""),
            gh_capture=capture or Reads(),
        )
    assert runner.calls == []
    return str(caught.value)


def failed(root: Path, args: list[str], host: Host, match: str) -> None:
    """exit 2 for another reason than a finding, gh never run"""
    runner = Runner()
    with pytest.raises(ReleaseError, match=match) as caught:
        main(
            ["--repo", str(root), "gh", *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(""),
            gh_capture=Reads(),
        )
    assert not isinstance(caught.value, LeakRefused)
    assert runner.calls == []


def body_file(tmp_path: Path, text: str, name: str = "body.md") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# -- S-081-1 -------------------------------------------------------------------------------------

WRITES = [
    ["issue", "create", "--title", "{text}", "--body", "b"],
    ["issue", "create", "--title", "t", "--body", "{text}"],
    ["issue", "create", "-t", "t", "--body-file", "{file}"],
    ["issue", "comment", "250", "--body", "{text}"],
    ["issue", "comment", "250", "-F", "{file}"],
    ["issue", "edit", "250", "--title", "{text}"],
    ["issue", "edit", "250", "--body", "{text}"],
    ["issue", "edit", "250", "--body-file", "{file}"],
    ["pr", "create", "--title", "{text}", "--body", "b"],
    ["pr", "create", "--title", "t", "--body-file", "{file}"],
    ["pr", "edit", "7", "--title", "{text}"],
    ["pr", "edit", "7", "-b", "{text}"],
    ["pr", "comment", "7", "--body", "{text}"],
    ["pr", "comment", "7", "--body-file", "{file}"],
]


def fill(args: list[str], tmp_path: Path, text: str) -> list[str]:
    path = body_file(tmp_path, f"First line.\n\nSecond, {text}.\n")
    return [arg.format(text=text, file=path) for arg in args]


@pytest.mark.parametrize("args", WRITES)
def test_s081_1_a_term_in_a_title_or_body_to_a_public_repo_is_refused(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    said = refused(root, fill(args, tmp_path, LEAKED), host)
    where = "the title" if "--title" in args and args[args.index("--title") + 1] == "{text}" else "the body"
    assert said.startswith(f"shipmill gh: refused, nothing was sent ({REPO} is public)\n")
    assert f"term: {where}" in said
    assert f'names the private term "{TERM}"' in said
    assert said.endswith(FIX)


@pytest.mark.parametrize("args", WRITES)
def test_s081_1_the_same_write_passes_without_the_term(tmp_path: Path, host: Host, args: list[str]) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    gh(root, fill(args, tmp_path, CLEAN), host)


def test_s081_1_a_body_files_line_is_named(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    path = body_file(tmp_path, f"one\ntwo\nthree\n{LEAKED}\n")
    said = refused(root, ["issue", "comment", "250", "--body-file", path], host)
    assert f'  term: the body, line 4, names the private term "{TERM}"' in said.splitlines()


def test_s081_1_as_the_app_too(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    with_term(host)
    key = str(key_file(tmp_path))
    said = refused(root, ["--app-key", key, "issue", "comment", "250", "--body", LEAKED], host)
    assert f'"{TERM}"' in said
    gh(root, ["--app-key", key, "issue", "comment", "250", "--body", CLEAN], host)


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("ACME ROCKET", True),
        ("acme\n\trocket", True),
        ("(Acme Rocket)", True),
        ("Acme Rocket_", True),  # `_` is no letter or digit
        ("AcmeRocket", False),
        ("Acme Rockets", False),
        ("xAcme Rocket", False),
        ("Acme Rocket2", False),
    ],
)
def test_s081_1_a_term_matches_at_word_boundaries_in_any_case(text: str, found: bool) -> None:
    assert bool(scan([Text("the body", text)], [Term.of(TERM)], ())) is found


# -- S-081-2 -------------------------------------------------------------------------------------

LABELS = f"repos/{PUBLIC}/labels"


@pytest.mark.parametrize(
    ("args", "where"),
    [
        ([LABELS, "-f", f"description={LEAKED}"], "the field description"),
        ([LABELS, "-F", f"description={LEAKED}"], "the field description"),
        ([LABELS, "--raw-field", f"description={LEAKED}"], "the field description"),
        ([LABELS, "-F", "description=@{file}"], "the field description"),
        ([LABELS, "--field", "description=@{file}"], "the field description"),
        (["-X", "POST", LABELS, "--input", "{file}"], "the --input file {file}"),
        ([f"repos/{PUBLIC}/issues/1/comments", "-f", f"body={LEAKED}"], "the field body"),
        (["-X", "PATCH", f"repos/{PUBLIC}/issues/comments/9", "-F", "body=@{file}"], "the field body"),
    ],
)
def test_s081_2_gh_api_writes_are_checked_field_by_field(
    tmp_path: Path, host: Host, args: list[str], where: str
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    path = body_file(tmp_path, f'{{"description": "{LEAKED}"}}')
    capture = Reads()
    said = refused(root, ["api", *(a.format(file=path) for a in args)], host, capture)
    assert f"({PUBLIC} is public)" in said
    assert f"term: {where.format(file=path)}" in said
    assert capture.reads == [PUBLIC]  # the endpoint's repo, not the checkout's


def test_s081_2_the_endpoints_placeholders_take_the_checkouts_repo() -> None:
    assert write_repo(["api", "-X", "POST", "repos/{owner}/{repo}/labels"], REPO) == REPO
    assert write_repo(["api", "/repos/acme/widgets/issues?x=1", "-f", "a=b"], REPO) == PUBLIC
    assert write_repo(["api", "https://api.github.com/repos/acme/widgets/labels"], REPO) == PUBLIC


def test_s081_2_a_read_through_gh_api_is_not_checked(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    capture = Reads()
    gh(root, ["api", f"repos/{PUBLIC}/issues", "-X", "GET", "-f", f"q={LEAKED}"], host, capture)
    assert capture.reads == []


# -- S-081-3 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("visibility", ["private", "internal"])
def test_s081_3_a_private_or_internal_repo_is_not_checked_for_terms(
    tmp_path: Path, host: Host, visibility: str
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    capture = Reads(visibility)
    gh(root, ["issue", "comment", "250", "--body", LEAKED], host, capture)
    assert capture.reads == [REPO]


def test_s081_3_a_failed_visibility_read_is_public(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    said = refused(root, ["issue", "comment", "250", "--body", LEAKED], host, Reads(code=1))
    assert f"({REPO}, checked as public)" in said
    said = refused(root, ["issue", "comment", "250", "--body", LEAKED], host, Reads("secret"))
    assert f"({REPO}, checked as public)" in said


def test_s081_3_a_remote_off_github_is_public(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY, origin="https://git.example.com/acme/widgets.git")
    with_term(host)
    capture = Reads("private")
    said = refused(root, ["issue", "comment", "250", "--body", LEAKED], host, capture)
    assert "(it goes to no repo on github.com, so it is checked as public)" in said
    assert capture.reads == []
    said = refused(root, ["issue", "comment", "250", "-R", "git.example.com/acme/x", "--body", LEAKED], host, capture)
    assert "checked as public" in said


def test_s081_3_a_write_to_no_repo_is_public(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    capture = Reads("private")
    path = body_file(tmp_path, LEAKED, "notes.txt")
    said = refused(root, ["gist", "create", path], host, capture)
    assert f"term: the file {path} names" in said
    said = refused(root, ["api", "graphql", "-f", f'query=mutation {{ x(note: "{LEAKED}") }}'], host, capture)
    assert "no repo on github.com" in said
    assert capture.reads == []


# -- S-081-4 -------------------------------------------------------------------------------------


def test_s081_4_without_the_private_file_no_term_is_checked_and_no_visibility_read(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    capture = Reads()
    gh(root, ["issue", "comment", "250", "--body", LEAKED], host, capture)
    assert capture.reads == []


def test_s081_4_a_file_without_terms_reads_no_visibility(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    private(host, "terms = []\n")
    capture = Reads()
    gh(root, ["issue", "comment", "250", "--body", LEAKED], host, capture)
    assert capture.reads == []


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('terms = ["Acme Rocket"]\nallow = true\n', "unknown key 'allow'"),
        ('terms = "Acme Rocket"\n', "terms must be a list of strings"),
        ("terms = [1]\n", "terms must be a list of strings"),
        ('secret_files = "~/.env"\n', "secret_files must be a list of strings"),
        ('terms = ["ab"]\n', "terms holds a term under 3 characters"),
        ('terms = ["  a  "]\n', "terms holds a term under 3 characters"),
        ("terms = [\n", "isn't valid TOML"),
        ('secret_files = ["/nowhere/acme/.env"]\n', "secret_files' /nowhere/acme/.env can't be read"),
    ],
)
def test_s081_4_a_malformed_private_file_fails_every_write(tmp_path: Path, host: Host, text: str, match: str) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    path = private(host, text)
    with pytest.raises(ReleaseError, match=match) as caught:
        main(
            ["--repo", str(root), "gh", "issue", "comment", "250", "--body", "clean"],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=Runner(),
            gh_capture=Reads("private"),
        )
    assert str(path) in str(caught.value)


def test_s081_4_a_malformed_private_file_fails_no_read(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    private(host, "allow = true\n")
    gh(root, ["issue", "view", "250"], host)


# -- S-081-5 -------------------------------------------------------------------------------------

TOKEN_VALUE = "acme-example-0123456789"


def private_repo(host: Host) -> Reads:
    with_term(host)
    return Reads("private")


def test_s081_5_an_untracked_env_value_is_refused_by_name_never_by_value(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    (root / ".env").write_text(f"export API_TOKEN='{TOKEN_VALUE}'\nDEBUG=true\n", encoding="utf-8")
    capture = private_repo(host)
    said = refused(root, ["issue", "comment", "250", "--body", f"it fails with {TOKEN_VALUE}"], host, capture)
    assert f"({REPO} is private)" in said
    assert "secret-value: the body, line 1, holds the value of API_TOKEN from .env" in said
    assert TOKEN_VALUE not in said
    assert TOKEN_VALUE[:4] not in said


def test_s081_5_a_secret_files_value_is_refused(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    secrets = tmp_path / "acme.env"
    secrets.write_text(f'STRIPE_SECRET="{TOKEN_VALUE}"\nDATABASE_URL=postgres://app:Pa55wordAcme@db.example\n', "utf-8")
    private(host, f'terms = ["{TERM}"]\nsecret_files = ["{secrets}"]\n')
    capture = Reads("private")
    said = refused(root, ["pr", "edit", "7", "--title", f"see {TOKEN_VALUE}"], host, capture)
    assert f"secret-value: the title holds the value of STRIPE_SECRET from {secrets}" in said
    said = refused(root, ["issue", "comment", "250", "--body", "the password Pa55wordAcme"], host, capture)
    assert f"the value of DATABASE_URL from {secrets}" in said  # a URL's password, whatever the name
    assert "Pa55" not in said


def test_s081_5_short_values_other_names_and_tracked_files_are_no_secrets(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    (root / ".env").write_text("API_TOKEN=short12\nGREETING=hello-acme-example\n", encoding="utf-8")
    (root / ".env.example").write_text(f"API_TOKEN={TOKEN_VALUE}\n", encoding="utf-8")
    Git(root).run("add", "--", ".env.example")
    capture = private_repo(host)
    gh(root, ["issue", "comment", "250", "--body", f"short12 hello-acme-example {TOKEN_VALUE}"], host, capture)


def test_s081_5_an_untracked_env_dot_file_counts_too(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    (root / ".env.local").write_text(f"SESSION_COOKIE={TOKEN_VALUE}\n", encoding="utf-8")
    said = refused(root, ["issue", "comment", "250", "--body", TOKEN_VALUE], host, private_repo(host))
    assert "SESSION_COOKIE from .env.local" in said


@pytest.mark.parametrize(
    ("line", "names"),
    [
        (f"API_KEY={TOKEN_VALUE}", ["API_KEY"]),
        (f"export db_password = {TOKEN_VALUE}", ["db_password"]),
        (f'GH_AUTH="{TOKEN_VALUE}"', ["GH_AUTH"]),
        (f"SENTRY_DSN={TOKEN_VALUE} # the project's", ["SENTRY_DSN"]),
        ("API_KEY=1234567", []),  # under 8 characters
        (f"HOSTNAME={TOKEN_VALUE}", []),  # no secret word
        (f"# API_KEY={TOKEN_VALUE}", []),
        ("REMOTE=https://deploy:Pa55wordAcme@git.example.com", ["REMOTE"]),
        ("REMOTE=https://deploy:short@git.example.com", []),
    ],
)
def test_s081_5_a_dotenv_line_gives_a_secret(line: str, names: list[str]) -> None:
    assert [s.name for s in dotenv_secrets(line, ".env")] == names


# -- S-081-6 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("token", "said"), FORMATS)
@pytest.mark.parametrize("visibility", ["public", "private"])
def test_s081_6_a_known_format_is_refused_in_any_repo(
    tmp_path: Path, host: Host, token: str, said: str, visibility: str
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    path = body_file(tmp_path, f"Steps:\n\nrun with {token}\n")
    refusal_text = refused(root, ["issue", "create", "-t", "t", "--body-file", path], host, Reads(visibility))
    assert f"  secret-format: the body, line 3, holds {said}" in refusal_text.splitlines()
    assert token[SHOWN_AFTER : SHOWN_AFTER + 4] not in refusal_text
    assert "Hunter2Acme9" not in refusal_text


def test_s081_6_a_format_is_refused_with_no_private_file(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    said = refused(root, ["issue", "comment", "250", "--body", GITHUB_TOKEN], host)
    assert f"({REPO})" not in said  # the visibility isn't read without a term
    assert f"({REPO}, checked as public)" in said


@pytest.mark.parametrize(
    "text",
    [
        "https://x-access-token:${TOKEN}@github.com/acme/widgets.git",
        "https://user:<password>@git.example.com",
        "https://user:****************@git.example.com",
        "https://deploy:short@git.example.com",
        "the ghp_ prefix and github_pat_ ones",
        "-----BEGIN RSA PRIVATE KEY----- is the header a key file starts with",
        "AKIA plus 16 more characters",
        "a SHA 3220d9c1e0b8f1c2a7e6d5c4b3a2f1e0d9c8b7a6 and S-081-6",
    ],
)
def test_s081_6_placeholders_and_mentions_pass(tmp_path: Path, host: Host, text: str) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    gh(root, ["issue", "comment", "250", "--body", text], host)


def test_s081_6_the_repos_own_text_holds_no_format() -> None:
    """The changelog, its fragments, and the specs are the text this repo's PRs quote"""
    paths = [ROOT / "CHANGELOG.md", *sorted((ROOT / "changelog.d").glob("*.md"))]
    paths.extend(sorted((ROOT / "docs").rglob("*.md")))
    texts = [Text(str(p), p.read_text(encoding="utf-8")) for p in paths]
    assert scan(texts, (), ()) == []


# -- S-081-14 ------------------------------------------------------------------------------------


def test_s081_14_no_line_holds_a_secret_beyond_four_characters() -> None:
    known = (Secret("API_TOKEN", ".env", TOKEN_VALUE),)
    texts = [Text("the body", f"{token}\n{TOKEN_VALUE}") for token, _ in FORMATS]
    said = str(refusal("shipmill gh", Destination(REPO, Visibility.PRIVATE), scan(texts, (), known)))
    for token, _ in FORMATS:
        assert token[SHOWN_AFTER:] not in said
    assert TOKEN_VALUE[:SHOWN_AFTER] not in said
    assert TOKEN_VALUE not in repr(known)


def test_s081_14_a_refusal_lists_ten_and_counts_the_rest() -> None:
    findings = scan([Text("the body", "\n".join([GITHUB_TOKEN] * 13))], (), ())
    lines = str(refusal("shipmill gh", Destination(None, None), findings)).splitlines()
    assert len([line for line in lines if line.startswith("  secret-format:")]) == 10
    assert "  and 3 more" in lines
    assert (
        lines[0]
        == "shipmill gh: refused, nothing was sent (it goes to no repo on github.com, so it is checked as public)"
    )


def test_s081_14_the_cli_prints_the_refusal_as_it_is(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(root), "gh", "issue", "comment", "1", "--body", GITHUB_TOKEN],
        capture_output=True,
        text=True,
        check=False,
        env={**host.env(), "HOME": str(host.home)},
    )
    assert done.returncode == 2
    assert done.stderr.startswith("shipmill gh: refused, nothing was sent")
    assert GITHUB_TOKEN[SHOWN_AFTER:] not in done.stderr
    # the account's own private file may list terms, and then the visibility is read: no comment ran
    ran = host.record / "gh-args"
    assert not ran.exists() or "comment" not in ran.read_text(encoding="utf-8")


# -- S-081-16 ------------------------------------------------------------------------------------


def test_s081_16_no_variable_flag_config_key_or_marker_turns_a_detector_off(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    other = tmp_path / "other.toml"
    other.write_text("terms = []\n", encoding="utf-8")
    environ = {
        "SHIPMILL_LEAKS": "off",
        "SHIPMILL_LEAK_CHECK": "0",
        "SHIPMILL_PRIVATE": str(other),
        "SHIPMILL_PRIVATE_FILE": str(other),
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path),
    }
    body = f"{LEAKED} {GITHUB_TOKEN} gitleaks:allow <!-- shipmill:leaks-allow --> <!-- shipmill:agent -->"
    said = refused(root, ["issue", "comment", "250", "--no-leak-check", "--body", body], host, environ=environ)
    assert "term:" in said
    assert "secret-format:" in said


def test_s081_16_as_host_turns_no_detector_off(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, AGENTS_NO_APP)
    with_term(host)
    assert "term:" in refused(root, ["--as-host", "issue", "comment", "250", "--body", LEAKED], host)


@pytest.mark.parametrize(
    ("config", "match"),
    [
        (f'{HOST_IDENTITY}leaks = false\nprivate = "/tmp/other.toml"\n', "unknown keys"),  # the load fails
        (f"{HOST_IDENTITY}\n[leaks]\nenabled = false\nterms = []\n", "term: the body"),  # read by nothing
    ],
)
def test_s081_16_no_config_key_turns_the_check_off(tmp_path: Path, host: Host, config: str, match: str) -> None:
    """.github/shipmill.toml holds no key of the leak check: one in [agents] fails the load, and
    a table of its own is read by nothing; gh never runs"""
    root = checkout(tmp_path, config)
    with_term(host)
    runner = Runner()
    with pytest.raises(ReleaseError, match=match):
        main(
            ["--repo", str(root), "gh", "issue", "comment", "250", "--body", LEAKED],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            gh_capture=Reads(),
        )
    assert runner.calls == []


# -- the text a write sends ----------------------------------------------------------------------


def no_read(flag: str, path: str) -> str:
    raise AssertionError(f"read {flag} {path}")


def test_every_argument_and_flag_value_is_sent_text() -> None:
    texts = sent_texts(["label", "create", "acme-x", "-dAcme Rocket", "--color=fff"], no_read)
    assert [t.text for t in texts] == ["create", "acme-x", "ocket", "-dAcme Rocket", "fff"]  # -R read in the cluster
    texts = sent_texts(["release", "create", "v1", "--notes", "n", "-t", "t"], no_read)
    assert [(t.where, t.text) for t in texts] == [
        ("an argument", "create"),
        ("an argument", "v1"),
        ("the notes", "n"),
        ("the title", "t"),
    ]


@dataclass
class Feed:
    """Stands in for the gh run with the stdin the leak check read: records argv and that text"""

    calls: list[tuple[list[str], str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str], stdin: str) -> int:
        self.calls.append((list(argv), stdin))
        return 7


# writes whose args make gh read stdin, which shipmill gh hands gh as given (S-050-6)
STDIN_WRITES = [
    ["pr", "merge", "7", "--squash", "--body-file", "-"],
    ["release", "create", "v1", "--notes-file", "-"],
    ["api", f"repos/{PUBLIC}/labels", "-F", "description=@-"],
    ["api", "-X", "POST", f"repos/{PUBLIC}/labels", "--input", "-"],
    ["workflow", "run", "w.yml", "--field", "note=@-"],
    ["gist", "create", "-"],
]


def fed(root: Path, args: list[str], host: Host, stdin: str) -> tuple[Runner, Feed]:
    """`shipmill gh args` with stdin; the runner (terminal stdin) and the feed (stdin read)"""
    runner, feed = Runner(), Feed()
    main(
        ["--repo", str(root), "gh", *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
        stdin=io.StringIO(stdin),
        gh_capture=Reads(),
        gh_feed=feed,
    )
    return runner, feed


@pytest.mark.parametrize("args", STDIN_WRITES)
def test_s081_6_a_token_on_stdin_is_refused_before_gh_runs(tmp_path: Path, host: Host, args: list[str]) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    runner, feed = Runner(), Feed()
    with pytest.raises(LeakRefused, match="secret-format: .* holds a GitHub token") as caught:
        main(
            ["--repo", str(root), "gh", *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(f"text\n{GITHUB_TOKEN}\n"),
            gh_capture=Reads(),
            gh_feed=feed,
        )
    assert GITHUB_TOKEN[SHOWN_AFTER:] not in str(caught.value)
    assert runner.calls == []
    assert feed.calls == []


@pytest.mark.parametrize("args", STDIN_WRITES)
def test_s081_5_an_env_secret_on_stdin_to_a_private_repo_is_refused(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    (root / ".env").write_text(f"API_TOKEN={TOKEN_VALUE}\n", encoding="utf-8")
    runner, feed = Runner(), Feed()
    with pytest.raises(LeakRefused, match="the value of API_TOKEN from .env") as caught:
        main(
            ["--repo", str(root), "gh", *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(f"uses {TOKEN_VALUE}"),
            gh_capture=private_repo(host),
            gh_feed=feed,
        )
    assert TOKEN_VALUE not in str(caught.value)
    assert runner.calls == []
    assert feed.calls == []


@pytest.mark.parametrize("args", STDIN_WRITES)
def test_s081_1_a_clean_stdin_body_reaches_ghs_stdin_with_its_args_as_given(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    runner, feed = fed(root, args, host, CLEAN)
    assert runner.calls == []
    assert feed.calls == [([host.gh, *args], CLEAN)]


@pytest.mark.parametrize("args", STDIN_WRITES)
def test_s081_1_a_term_on_stdin_to_a_public_repo_is_refused(tmp_path: Path, host: Host, args: list[str]) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    with pytest.raises(LeakRefused, match=f'names the private term "{TERM}"'):
        fed(root, args, host, LEAKED)


def test_s081_2_stdin_named_twice_is_read_once_and_fed_whole(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    args = ["api", f"repos/{PUBLIC}/labels", "-F", "name=@-", "-F", "description=@-"]
    runner, feed = fed(root, args, host, CLEAN)
    assert feed.calls == [([host.gh, *args], CLEAN)]


def test_s081_1_a_write_reading_no_stdin_runs_on_the_terminals(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    runner, feed = fed(root, ["pr", "merge", "7", "--squash", "--body", CLEAN], host, "")
    assert feed.calls == []
    assert runner.calls[0][0] == [host.gh, "pr", "merge", "7", "--squash", "--body", CLEAN]


def test_s081_1_a_created_body_on_stdin_is_checked(tmp_path: Path, host: Host) -> None:
    """A create's `--body-file -` is read and marked by spec 050, and checked as the body"""
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    with pytest.raises(LeakRefused, match="term: the body"):
        fed(root, ["issue", "comment", "250", "--body-file", "-"], host, LEAKED)


def test_s081_1_the_real_feed_hands_gh_the_text_on_its_stdin_and_the_args_as_given(tmp_path: Path) -> None:
    gh_path = tmp_path / "gh"
    executable(gh_path, '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$RECORD/args"\ncat > "$RECORD/stdin"\nexit 7\n')
    args = ["pr", "merge", "7", "--squash", "--body-file", "-"]
    assert feed_gh([str(gh_path), *args], {"RECORD": str(tmp_path), "PATH": "/usr/bin:/bin"}, CLEAN) == 7
    assert (tmp_path / "args").read_text(encoding="utf-8").splitlines() == args
    assert (tmp_path / "stdin").read_text(encoding="utf-8") == CLEAN


@pytest.mark.parametrize("args", [["gist", "create"], ["gist", "new", "--filename", "notes.md", "-d", "d"]])
def test_s081_1_a_gist_created_from_piped_stdin_is_checked(tmp_path: Path, host: Host, args: list[str]) -> None:
    """`cat notes | gh gist create` uploads stdin with no `-` named: read, checked, and fed"""
    root = checkout(tmp_path, HOST_IDENTITY)
    with pytest.raises(LeakRefused, match="secret-format: the file on stdin"):
        fed(root, args, host, f"x {GITHUB_TOKEN}")
    runner, feed = fed(root, args, host, CLEAN)
    assert runner.calls == []
    assert feed.calls == [([host.gh, *args], CLEAN)]


@pytest.mark.parametrize(
    "args",
    [
        ["gist", "edit", "abc123", "--filename", "notes.md", "{file}"],
        ["gist", "edit", "abc123", "--add", "{file}"],
        ["gist", "edit", "abc123", "-a{file}"],
    ],
)
def test_s081_1_a_local_file_a_gist_edit_uploads_is_checked(tmp_path: Path, host: Host, args: list[str]) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    path = body_file(tmp_path, f"x {GITHUB_TOKEN}\n", "notes.md")
    said = refused(root, [a.format(file=path) for a in args], host)
    assert f"secret-format: the file {path} holds a GitHub token" in said


def test_s081_1_a_gist_edit_reading_no_local_file_runs(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    gh(root, ["gist", "edit", "abc123", "--remove", "notes.md"], host)
    gh(root, ["gist", "edit", "abc123", "--desc", "d"], host)
    runner, feed = fed(root, ["gist", "edit", "abc123", "-f", "notes.md", "-"], host, CLEAN)
    assert feed.calls == [([host.gh, "gist", "edit", "abc123", "-f", "notes.md", "-"], CLEAN)]


def test_s081_16_secret_files_home_is_the_accounts_not_home_variable(tmp_path: Path, host: Host) -> None:
    """`~` in secret_files is the account's home, as the private file's is: $HOME names no other file"""
    root = checkout(tmp_path, HOST_IDENTITY)
    (host.home / "acme.env").write_text(f"API_TOKEN={TOKEN_VALUE}\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "acme.env").write_text("API_TOKEN=nothing-secret-here\n", encoding="utf-8")
    private(host, 'secret_files = ["~/acme.env"]\n')
    said = refused(root, ["issue", "comment", "250", "--body", TOKEN_VALUE], host, environ={"HOME": str(elsewhere)})
    assert "the value of API_TOKEN from ~/acme.env" in said


@dataclass
class ByRepo(Reads):
    """Reads whose visibility is the checkout's private repo's, and public for any other"""

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        code, out = super().__call__(argv, env)
        if "--jq" in argv:
            return code, "private\n" if argv[2] == f"repos/{REPO}" else "public\n"
        return code, out


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "comment", f"https://github.com/{PUBLIC}/issues/3", "--body", LEAKED],
        ["pr", "comment", f"https://github.com/{PUBLIC}/pull/4", "--body", LEAKED],
        ["issue", "edit", f"https://github.com/{PUBLIC}/issues/3", "--title", LEAKED],
        ["pr", "review", f"https://www.github.com/{PUBLIC}/pull/4/files", "--comment", "-b", LEAKED],
        ["repo", "edit", PUBLIC, "--description", LEAKED],
    ],
)
def test_s081_3_a_url_naming_another_repo_is_that_repos_write(tmp_path: Path, host: Host, args: list[str]) -> None:
    """gh writes to the repo an issue's or a pull request's URL, or `gh repo`'s argument, names,
    whatever the checkout's"""
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    capture = ByRepo()
    said = refused(root, args, host, capture)
    assert f"({PUBLIC} is public)" in said
    assert capture.reads == [PUBLIC]
    gh(root, ["issue", "comment", f"https://github.com/{REPO}/issues/3", "--body", LEAKED], host, ByRepo())


@pytest.mark.parametrize(
    "args",
    [
        ["project", "item-create", "1", "--owner", "acme", "--title", LEAKED],
        ["issue", "comment", "https://git.example.com/acme/widgets/issues/3", "--body", LEAKED],
        ["repo", "create", "widgets-next", "--description", LEAKED],
    ],
)
def test_s081_3_a_write_off_the_checkouts_repo_is_public(tmp_path: Path, host: Host, args: list[str]) -> None:
    """A project, an item URL off github.com, and a repo named without its owner are no
    repo whose visibility can be read: public, though the checkout's repo is private"""
    root = checkout(tmp_path, HOST_IDENTITY)
    with_term(host)
    capture = ByRepo()
    said = refused(root, args, host, capture)
    assert "(it goes to no repo on github.com, so it is checked as public)" in said
    assert capture.reads == []


def test_stdin_is_named_where_it_is_read() -> None:
    texts = sent_texts(["api", "-X", "POST", "repos/o/r/labels", "--input", "-"], lambda flag, path: "x")
    assert texts[-1] == Text("the --input on stdin", "x")
    assert sent_texts(["gist", "create", "-"], lambda flag, path: "x")[-1] == Text("the file on stdin", "x")


def test_a_finding_names_its_detector() -> None:
    [found] = scan([Text("the title", GITHUB_TOKEN)], (), ())
    assert found.detector is Detector.SECRET_FORMAT
    assert found.said() == "secret-format: the title holds a GitHub token (ghp_…)"
