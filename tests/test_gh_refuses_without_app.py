"""Spec 037: `shipmill gh` refuses a write in a repo without [agents] app_id, unless the repo
([agents] identity = "host") or the call (--as-host) allows the host's login; a read runs as
the host, untouched. No test reaches the network: GitHub is MintApi and openssl FakeSigner"""

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from shipmill import UVX, cli_command
from shipmill.agents import AgentsConfig, WriteAs
from shipmill.app_gh import is_read
from shipmill.cli import main
from shipmill.errors import ReleaseError

from .test_app import APP_ID, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout, outside
from .test_app_token import FAKE_GH, MintApi, executable
from .test_delivery_hooks import DELIVERY


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


AGENTS_NO_APP = '[agents]\nprompt = "/t"\n'
HOST_IDENTITY = '[agents]\nprompt = "/t"\nidentity = "host"\n'
PR_CREATE = ["pr", "create", "-R", "owner/name", "--title", "t", "--body-file", "f"]
COMMENT = ["issue", "comment", "1", "--body-file", "f"]
WRITES = [PR_CREATE, COMMENT]
READS = [
    ["pr", "view", "1"],
    ["issue", "list"],
    ["api", "user", "--jq", ".login"],
    ["api", "-X", "GET", "search/issues", "-f", "q=x"],
]
# no config, only [release], [agents] without app_id, and outside any checkout (S-037-1, S-037-2)
NO_APP = [None, "[release]\n", AGENTS_NO_APP, "outside"]


def one_call(args: list[str]) -> str:
    """The refusal's third line: `shipmill gh --as-host` with the same arguments, in the form
    the person can run (cli_command, #236)"""
    return f"allow this one call: {cli_command()} gh --as-host {shlex.join(args)}"


def where(tmp_path: Path, config: str | None) -> Path:
    return outside(tmp_path) if config == "outside" else checkout(tmp_path, config)


def run(
    root: Path, args: list[str], host: Host, api: MintApi | None = None, signer: FakeSigner | None = None, **env: str
) -> tuple[int, Runner]:
    runner = Runner()
    code = main(
        ["--repo", str(root), "gh", *args],
        api=api or MintApi(),
        signer=signer or FakeSigner(),
        environ=host.env(**env),
        home=host.home,
        gh_runner=runner,
    )
    return code, runner


def refusal(root: Path, args: list[str], host: Host) -> list[str]:
    """The refusal's lines; gh never ran and no token was minted"""
    api, signer, runner = MintApi(), FakeSigner(), Runner()
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it after `shipmill: ` and exits 2
        main(
            ["--repo", str(root), "gh", *args],
            api=api,
            signer=signer,
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
        )
    assert (runner.calls, api.calls, api.posts, signer.signed) == ([], [], [], [])
    return str(raised.value).split("\n")


# --- S-037-1, S-037-2: a write without app_id is refused ----------------------------------------


@pytest.mark.parametrize("args", WRITES)
def test_s037_1_no_config_refuses_a_write_naming_the_repo_and_both_fixes(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    root = checkout(tmp_path, None)
    first, second, third = refusal(root, args, host)
    repo = "owner/name" if args is PR_CREATE else REPO  # -R's, else origin's
    assert first == (
        f"refusing a write to {repo} as the host's gh login: {root} has no .github/shipmill.toml, so no [agents] app_id"
    )
    assert second == (
        f'allow it for this repo: give it an App ({cli_command()} app-create), or set [agents] identity = "host" in '
        ".github/shipmill.toml"
    )
    assert third == one_call(args)


def test_s037_1_the_refusal_exits_2_and_never_starts_gh(tmp_path: Path, host: Host) -> None:
    """Through `python -m shipmill`: exit 2, the three lines after `shipmill: `, and gh never ran"""
    root = checkout(tmp_path, None)
    env = {**host.env(), "HOME": str(host.home)}
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(root), "gh", *PR_CREATE],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 2
    assert done.stdout == ""
    lines = done.stderr.splitlines()
    assert lines[0].startswith("shipmill: refusing a write to owner/name as the host's gh login: ")
    assert "[agents] app_id" in lines[0]
    # the CLI as the person can run it (#236): here, with no shipmill on PATH, the uvx form
    assert lines[2] == f"allow this one call: {UVX} gh --as-host {shlex.join(PR_CREATE)}"
    assert not (host.record / "gh-args").exists()


@pytest.mark.parametrize("config", ["[release]\n", AGENTS_NO_APP])
@pytest.mark.parametrize("args", WRITES)
def test_s037_2_a_config_without_app_id_refuses_with_the_same_message(
    tmp_path: Path, host: Host, config: str, args: list[str]
) -> None:
    root = checkout(tmp_path, config)
    first, second, third = refusal(root, args, host)
    repo = "owner/name" if args is PR_CREATE else REPO
    assert first == f"refusing a write to {repo} as the host's gh login: .github/shipmill.toml sets no [agents] app_id"
    assert 'set [agents] identity = "host"' in second
    assert third == one_call(args)


@pytest.mark.parametrize("args", WRITES)
def test_s037_2_outside_any_checkout_the_refusal_names_the_folder(tmp_path: Path, host: Host, args: list[str]) -> None:
    folder = outside(tmp_path)
    first, _, third = refusal(folder, args, host)
    assert f"the folder {folder}" in first
    assert "[agents] app_id" in first
    if args is COMMENT:  # no -R: the folder is the repo the write names
        assert first.startswith(f"refusing a write to the folder {folder} (no git checkout) as the host's gh login")
    assert third == one_call(args)


def test_s037_2_a_checkout_without_a_github_origin_is_named_by_its_path(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, None, origin="/elsewhere/repo.git")
    first, _, _ = refusal(root, COMMENT, host)
    assert first.startswith(f"refusing a write to {root} as the host's gh login")


# --- S-037-3: a read runs as the host, untouched ------------------------------------------------


@pytest.mark.parametrize("config", NO_APP)
@pytest.mark.parametrize("args", READS)
@pytest.mark.parametrize("token", [None, ""])
def test_s037_3_a_read_runs_gh_with_exactly_its_args_and_no_token(
    tmp_path: Path,
    host: Host,
    capsys: pytest.CaptureFixture[str],
    config: str | None,
    args: list[str],
    token: str | None,
) -> None:
    root = where(tmp_path, config)
    api, signer = MintApi(), FakeSigner()
    env = {} if token is None else {"GH_TOKEN": token}
    code, runner = run(root, args, host, api, signer, **env)
    assert code == 7  # gh's
    [(argv, called)] = runner.calls
    assert argv == [host.gh, *args]  # the gh on PATH
    assert "GH_TOKEN" not in called
    assert (api.calls, api.posts, signer.signed) == ([], [], [])
    assert capsys.readouterr() == ("", "")


def test_s037_3_end_to_end_a_read_exits_with_ghs_code(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, None)
    code = main(
        ["--repo", str(root), "gh", "pr", "view", "1"],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(GH_TOKEN=""),
        home=host.home,
    )
    assert code == 7
    assert (host.record / "gh-args").read_text() == "pr\nview\n1\n"
    assert (host.record / "gh-token").read_text() == ""


# --- S-037-4, S-037-5: is_read ------------------------------------------------------------------

LISTED_READS = [
    [],
    ["--version"],
    ["version"],
    ["help"],
    ["help", "pr", "create"],
    ["status"],
    *(["issue", sub, "1"] for sub in ("list", "view", "status")),
    *(["pr", sub, "1"] for sub in ("list", "view", "status", "diff", "checks")),
    *(["release", sub] for sub in ("list", "view", "download")),
    ["label", "list"],
    *(["run", sub] for sub in ("list", "view", "watch", "download")),
    *(["workflow", sub] for sub in ("list", "view")),
    *(["repo", sub] for sub in ("view", "list", "clone")),
    *(["search", sub, "x"] for sub in ("issues", "prs", "repos", "code", "commits")),
    ["secret", "list"],
    *(["variable", sub] for sub in ("list", "get")),
    ["cache", "list"],
    *(["ruleset", sub] for sub in ("list", "view", "check")),
    *(["gist", sub] for sub in ("list", "view")),
    ["org", "list"],
    *(["project", sub] for sub in ("list", "view", "field-list", "item-list")),
    *(["auth", sub] for sub in ("status", "token")),
    *(["config", sub] for sub in ("get", "list")),
    ["alias", "list"],
    ["extension", "list"],
    ["pr", "view", "1", "-R", "o/r", "--json", "body"],
    ["pr", "view", "--help"],  # --help changes nothing: a read stays a read
    ["api", "user"],
]
HOOK_WRITES = [[group, sub] for group, subs in DELIVERY.GH_WRITES.items() for sub in sorted(subs)]
UNLISTED = [
    ["gist", "create"],
    ["project", "item-add"],
    ["codespace", "create"],
    ["pr", "create", "--help"],
    ["pr", "create", "-h"],
    ["--help"],
    ["pr"],  # no subcommand
    ["pr", "-R", "o/r", "view"],  # a flag before the subcommand: gh might read another
    ["-R", "o/r", "pr", "view"],
    ["--", "pr", "view"],
    ["co", "1"],  # an alias
]


@pytest.mark.parametrize("args", LISTED_READS)
def test_s037_4_every_listed_command_is_a_read(args: list[str]) -> None:
    assert is_read(args)


@pytest.mark.parametrize("args", HOOK_WRITES)
def test_s037_4_every_write_the_hook_lists_is_a_write(args: list[str]) -> None:
    assert not is_read(args)
    assert not is_read([*args, "--help"])


@pytest.mark.parametrize("args", UNLISTED)
def test_s037_4_an_unlisted_command_is_a_write(args: list[str]) -> None:
    assert not is_read(args)


API_READS = [
    ["api", "user"],
    ["api", "-X", "GET", "repos/o/r/issues"],
    ["api", "-XGET", "repos/o/r/issues"],
    ["api", "--method=get", "repos/o/r/issues"],
    ["api", "--method", "Get", "repos/o/r/issues"],
    ["api", "-X", "HEAD", "repos/o/r"],
    ["api", "-X", "GET", "search/issues", "-f", "q=x"],
    ["api", "-X", "GET", "search/issues", "-F", "per_page=5"],
    ["api", "-X", "HEAD", "repos/o/r", "-f", "a=b"],
    ["api", "graphql", "-f", "query={ viewer { login } }"],
    ["api", "--paginate", "repos/o/r/issues", "--jq", ".[].number"],
]
API_WRITES = [
    ["api", "-X", "POST", "repos/o/r/issues"],
    ["api", "-X", "PATCH", "repos/o/r/issues/7"],
    ["api", "-XPUT", "repos/o/r/pulls/7/merge"],
    ["api", "--method=DELETE", "repos/o/r/issues/7/labels/bug"],
    ["api", "repos/o/r/issues/7/comments", "-f", "body=hi"],
    ["api", "repos/o/r/labels", "-F", "name=bug"],
    ["api", "repos/o/r/labels", "--field", "name=bug"],
    ["api", "repos/o/r/labels", "--raw-field=name=bug"],
    ["api", "repos/o/r/labels", "-fname=bug"],
    ["api", "repos/o/r/labels", "--input", "label.json"],
    ["api", "repos/o/r/labels", "--input=label.json"],
    ["api", "graphql", "-f", "query=mutation { addStar(input: {}) { clientMutationId } }"],
    ["api", "graphql", "-F", "query=@query.graphql"],
    ["api", "graphql", "--field", "query=@query.graphql"],
    ["api", "graphql", "--input", "query.json"],
    ["api", "-X", "GET", "graphql", "-f", "query=mutation { x }"],
    ["api", "repos/o/r", "-X"],  # no method given: not GET
]


@pytest.mark.parametrize("args", API_READS)
def test_s037_5_gh_api_reads(args: list[str]) -> None:
    assert is_read(args)


@pytest.mark.parametrize("args", API_WRITES)
def test_s037_5_gh_api_writes(args: list[str]) -> None:
    assert not is_read(args)


# --- S-037-6: [agents] identity = "host" ---------------------------------------------------------


def test_s037_6_identity_host_runs_a_write_as_the_host(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    api, signer = MintApi(), FakeSigner()
    code, runner = run(root, PR_CREATE, host, api, signer, GH_TOKEN="")
    assert code == 7
    [(argv, env)] = runner.calls
    assert argv == [host.gh, *PR_CREATE]
    assert "GH_TOKEN" not in env
    assert (api.calls, api.posts, signer.signed) == ([], [], [])
    assert capsys.readouterr() == ("", "")


# --- S-037-7, S-037-8: the key's values ---------------------------------------------------------


@pytest.mark.parametrize("value", ['"App"', '"person"', '""', "1", "true", '["host"]'])
def test_s037_7_any_other_identity_exits_2_naming_the_key_and_both_values(
    tmp_path: Path, host: Host, value: str
) -> None:
    root = checkout(tmp_path, f"{AGENTS_NO_APP}identity = {value}\n")
    runner = Runner()
    for load in (
        lambda: AgentsConfig.load(root),
        lambda: main(
            ["--repo", str(root), "gh", "pr", "view", "1"],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
        ),
    ):
        with pytest.raises(ReleaseError) as raised:
            load()
        message = str(raised.value)
        assert '[agents] identity must be "app" (the default) or "host"' in message
    assert runner.calls == []


def test_s037_7_absent_identity_reads_as_app(tmp_path: Path) -> None:
    assert AgentsConfig.load(checkout(tmp_path, AGENTS_NO_APP)).identity is WriteAs.APP


def test_s037_8_identity_host_with_app_id_exits_2_naming_both(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, f'{WITH_APP}identity = "host"\n')
    key_file(tmp_path)
    runner = Runner()
    with pytest.raises(ReleaseError, match=r'\[agents\] identity = "host" and \[agents\] app_id'):
        main(
            ["--repo", str(root), "gh", "--app-key", str(tmp_path / "app.pem"), "pr", "view", "1"],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
        )
    assert runner.calls == []
    with pytest.raises(ReleaseError, match=r'\[agents\] identity = "host" and \[agents\] app_id'):
        AgentsConfig.load(root)


def test_s037_8_identity_app_with_app_id_parses(tmp_path: Path) -> None:
    found = AgentsConfig.load(checkout(tmp_path, f'{WITH_APP}identity = "app"\n'))
    assert (found.app_id, found.identity) == (APP_ID, WriteAs.APP)


# --- S-037-9: --as-host --------------------------------------------------------------------------


def test_s037_9_as_host_allows_one_write_and_the_next_is_refused(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, AGENTS_NO_APP)
    api, signer = MintApi(), FakeSigner()
    code, runner = run(root, ["--as-host", *PR_CREATE], host, api, signer, GH_TOKEN="")
    assert code == 7
    [(argv, env)] = runner.calls
    assert argv == [host.gh, *PR_CREATE]
    assert "GH_TOKEN" not in env
    assert (api.calls, signer.signed) == ([], [])
    refusal(root, PR_CREATE, host)


@pytest.mark.parametrize(
    "leading",
    [
        ["--as-host", "--app-key", "k.pem"],
        ["--app-key", "k.pem", "--as-host"],
        ["--as-host", "--app-key=k.pem"],
    ],
)
def test_s037_9_as_host_with_app_key_exits_2_in_either_order(tmp_path: Path, host: Host, leading: list[str]) -> None:
    root = checkout(tmp_path, AGENTS_NO_APP)
    runner = Runner()
    with pytest.raises(ReleaseError, match="--as-host .* --app-key"):
        main(
            ["--repo", str(root), "gh", *leading, *PR_CREATE],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
        )
    assert runner.calls == []


def test_s037_9_as_host_after_ghs_first_argument_reaches_gh(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    args = ["pr", "create", "--as-host", "--title", "t"]
    _, runner = run(root, args, host)
    assert runner.calls[0][0] == [host.gh, *args]
    # without the repo's allowance, an --as-host past gh's first argument allows nothing
    other = tmp_path / "other"
    other.mkdir()
    refusal(checkout(other, AGENTS_NO_APP), args, host)


def test_s037_9_as_host_twice_exits_2(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, AGENTS_NO_APP)
    with pytest.raises(ReleaseError, match="--as-host is given twice"):
        run(root, ["--as-host", "--as-host", *PR_CREATE], host)


# --- S-037-10: with app_id set, nothing changes ---------------------------------------------------


@pytest.mark.parametrize("args", [PR_CREATE, ["pr", "view", "1"], []])
def test_s037_10_as_host_with_app_id_exits_2_and_runs_no_gh(tmp_path: Path, host: Host, args: list[str]) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    api, signer, runner = MintApi(), FakeSigner(), Runner()
    with pytest.raises(ReleaseError, match=r"--as-host is refused: .* sets \[agents\] app_id"):
        main(
            ["--repo", str(root), "gh", "--as-host", *args],
            api=api,
            signer=signer,
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
        )
    assert (runner.calls, api.posts, signer.signed) == ([], [], [])


@pytest.mark.parametrize("args", [COMMENT, ["pr", "view", "1"]])
def test_s037_10_with_app_id_reads_and_writes_run_as_the_app(tmp_path: Path, host: Host, args: list[str]) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    code, runner = run(root, ["--app-key", str(tmp_path / "app.pem"), *args], host)
    assert code == 7
    [(argv, env)] = runner.calls
    assert (argv, env["GH_TOKEN"]) == ([host.gh, *args], "token-1")


def test_s037_10_with_app_id_a_token_failure_still_exits_2(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    runner = Runner()
    with pytest.raises(ReleaseError, match="no App private key at"):  # S-012-3, unchanged
        main(
            ["--repo", str(root), "gh", "pr", "view", "1"],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
        )
    assert runner.calls == []
