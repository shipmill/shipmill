"""Spec 038, The config and the component's guard: the [product] table, read strictly by the
policy (`shipmill plan`) and the gate's loader alike (S-038-1), `repos` needing the App
(S-038-2), and a component's `shipmill gh -R` and `shipmill app-token` limited to its origin
repo before any token is minted (S-038-10). No test reaches the network"""

import shutil
import tomllib
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, ProductConfig
from shipmill.app import is_plain_repo
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.policy import Policy

from .conftest import POLICY, Repo
from .test_app import APP_ID, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout, gh
from .test_app_token import FAKE_GH, MintApi, executable


@pytest.fixture
def host(tmp_path: Path) -> Host:
    """test_app_gh's: a fake gh on PATH, its record folder, and a home"""
    fakes, record, home = tmp_path / "fakes", tmp_path / "record", tmp_path / "home"
    for folder in (fakes, record, home):
        folder.mkdir()
    executable(fakes / "gh", FAKE_GH)
    return Host(fakes, record, home)


AGENTS = f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n'
HOME = "romamo/product"
COMPONENT = f'\n[product]\nhome = "{HOME}"\n'


def _readers(repo: Repo) -> list[ReleaseError]:
    """What `shipmill plan` and the gate's loader each raise for the repo's config"""
    errors = []
    for read in (
        lambda: main(["--repo", str(repo.root), "plan"], github=repo.github),
        lambda: AgentsConfig.load(repo.root),
        lambda: ProductConfig.load(repo.root),
    ):
        with pytest.raises(ReleaseError) as caught:
            read()
        errors.append(caught.value)
    return errors


# -- S-038-1 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (f'home = "{HOME}"', ProductConfig(home=HOME)),
        (
            'repos = ["acme/api", "acme/web", "other-org/sdk"]',
            ProductConfig(repos=("acme/api", "acme/web", "other-org/sdk")),
        ),
    ],
)
def test_s038_1_a_product_table_parses_in_plan_and_the_gates_loader(
    repo: Repo, table: str, expected: ProductConfig
) -> None:
    text = POLICY + AGENTS + f"\n[product]\n{table}\n"
    repo.write(repo.policy_file, text)
    assert Policy.parse(tomllib.loads(text), "shipmill.toml").product == expected
    assert AgentsConfig.load(repo.root).app_id == APP_ID
    assert ProductConfig.load(repo.root) == expected


def test_s038_1_without_a_product_table_nothing_is_read(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    assert Policy.parse(tomllib.loads(POLICY + AGENTS), "shipmill.toml").product is None
    assert ProductConfig.load(repo.root) is None


@pytest.mark.parametrize(
    ("table", "message"),
    [
        (f'home = "{HOME}"\nowner = "x"', "[product]: unknown keys ['owner']"),
        ('home = "acme"', "[product]: home holds 'acme'"),
        ('home = "acme/api/x"', "[product]: home holds 'acme/api/x'"),
        ('home = "../api"', "[product]: home holds '../api'"),
        ("home = 1", "[product]: home must be a string"),
        ('repos = ["acme/api", "ac me/web"]', "[product]: repos holds 'ac me/web'"),
        ("repos = []", "[product]: repos must list at least one repo"),
        ('repos = ["acme/api", "Acme/API"]', "[product]: repos lists Acme/API twice"),
        (f'home = "{HOME}"\nrepos = ["acme/api"]', "[product]: home and repos can't both be set"),
        ("", "[product]: set home (in a component) or repos"),
    ],
)
def test_s038_1_a_bad_product_table_exits_2_naming_the_key_in_plan_and_the_gate(
    repo: Repo, table: str, message: str
) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + f"\n[product]\n{table}\n")
    errors = _readers(repo)
    assert all(message in str(e) for e in errors), errors
    assert len({str(e) for e in errors}) == 1  # one message, whichever reader


def test_s038_1_the_repo_rule_is_the_token_caches() -> None:
    assert is_plain_repo("other-org/sdk.js")
    assert not any(is_plain_repo(r) for r in ("acme", "/api", "acme/", "a/b/c", "./api", "acme/..", "a b/c"))


# -- S-038-2 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("agents", ["", '\n[agents]\nprompt = "/t"\n'])
def test_s038_2_repos_without_the_app_exits_2_saying_the_coordinator_needs_it(repo: Repo, agents: str) -> None:
    text = POLICY + agents + '\n[product]\nrepos = ["acme/api"]\n'
    repo.write(repo.policy_file, text)
    with pytest.raises(ReleaseError, match=r"repos needs \[agents\] app_id; the coordinator"):
        main(["--repo", str(repo.root), "plan"], github=repo.github)
    with pytest.raises(ReleaseError, match=r"repos needs \[agents\] app_id; the coordinator"):
        ProductConfig.load(repo.root)
    if agents:
        with pytest.raises(ReleaseError, match=r"repos needs \[agents\] app_id; the coordinator"):
            AgentsConfig.load(repo.root)


def test_s038_2_a_component_needs_no_app(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + COMPONENT)
    assert ProductConfig.load(repo.root) == ProductConfig(home=HOME)


# -- S-038-10 --------------------------------------------------------------------------------

OTHER = "romamo/api"


@pytest.mark.parametrize(
    "flag",
    [
        ["-R", OTHER],
        [f"-R={OTHER}"],
        [f"-R{OTHER}"],
        ["--repo", OTHER],
        [f"--repo={OTHER}"],
        ["-R", f"github.com/{OTHER}"],
        ["-R", HOME],  # the home repo is another repo too
    ],
)
@pytest.mark.parametrize("config", [WITH_APP + COMPONENT, COMPONENT])
def test_s038_10_a_components_gh_naming_another_repo_exits_2_naming_d47_before_a_token(
    tmp_path: Path, host: Host, flag: list[str], config: str
) -> None:
    root = checkout(tmp_path, config)
    key_file(tmp_path)
    api = MintApi()
    runner = Runner()
    with pytest.raises(ReleaseError, match="D-47") as raised:
        gh(root, ["--app-key", str(tmp_path / "app.pem"), "issue", "create", *flag], host, api, runner)
    assert f"component of {HOME}" in str(raised.value)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


@pytest.mark.parametrize("flag", [["-sR", OTHER], [f"-sR{OTHER}"], ["-dsR", OTHER]])
@pytest.mark.parametrize("config", [WITH_APP + COMPONENT, COMPONENT])
def test_s038_10_a_components_gh_with_r_bundled_after_another_flag_exits_2_naming_d47(
    tmp_path: Path, host: Host, flag: list[str], config: str
) -> None:
    # gh's flag parser reads `-sR other/x` as -s and -R other/x, so the cluster names a repo too
    root = checkout(tmp_path, config)
    key_file(tmp_path)
    api = MintApi()
    runner = Runner()
    with pytest.raises(ReleaseError, match="D-47") as raised:
        gh(root, ["--app-key", str(tmp_path / "app.pem"), "pr", "merge", "1", *flag], host, api, runner)
    assert "-R owner/name on its own" in str(raised.value)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


@pytest.mark.parametrize("flag", [[], ["-R", REPO], ["--repo", f"github.com/{REPO}"]])
def test_s038_10_a_components_gh_on_its_own_repo_runs(tmp_path: Path, host: Host, flag: list[str]) -> None:
    root = checkout(tmp_path, WITH_APP + COMPONENT)
    key_file(tmp_path)
    runner = Runner()
    assert gh(root, ["--app-key", str(tmp_path / "app.pem"), "issue", "list", *flag], host, MintApi(), runner) == 7
    assert runner.calls[0][1]["GH_TOKEN"] == "token-1"


def test_s038_10_the_origin_is_compared_case_ignored() -> None:
    component = ProductConfig(home=HOME)
    component.refuse_outside("ROMAMO/Demo", REPO, "gh's -R ROMAMO/Demo")
    with pytest.raises(ReleaseError, match="D-47"):
        component.refuse_outside("romamo/demo2", REPO, "gh's -R romamo/demo2")
    ProductConfig(repos=(OTHER,)).refuse_outside(OTHER, REPO, "gh's -R")  # a home repo isn't limited here


def test_s038_10_a_home_repos_gh_is_unchanged(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP + '\n[product]\nrepos = ["romamo/api"]\n')
    key_file(tmp_path)
    runner = Runner()
    assert gh(root, ["--app-key", str(tmp_path / "app.pem"), "issue", "list", "-R", REPO], host, MintApi(), runner) == 7


def _token(root: Path, tmp_path: Path, repo: str, api: MintApi, host: Host) -> int:
    argv = ["--repo", str(root), "app-token", repo, "--app-id", str(APP_ID), "--app-key", str(key_file(tmp_path))]
    return main(argv, api=api, signer=FakeSigner(), environ={}, home=host.home)


@pytest.mark.parametrize("other", [OTHER, HOME])
def test_s038_10_a_components_app_token_for_another_repo_exits_2_naming_d47(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], other: str
) -> None:
    root = checkout(tmp_path, WITH_APP + COMPONENT)
    api = MintApi()
    with pytest.raises(ReleaseError, match="D-47") as raised:
        _token(root, tmp_path, other, api, host)
    assert f"app-token {other} names {other}" in str(raised.value)
    assert (api.calls, api.posts) == ([], [])
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("other", [OTHER, REPO])
def test_s038_10_a_component_checkout_git_cant_read_gets_no_app_token(tmp_path: Path, host: Host, other: str) -> None:
    # a worktree whose repo is gone: git can't tell the origin, but the config still says component
    root = checkout(tmp_path, WITH_APP + COMPONENT)
    shutil.rmtree(root / ".git")
    (root / ".git").write_text(f"gitdir: {tmp_path / 'gone'}\n")
    api = MintApi()
    with pytest.raises(ReleaseError, match=f"component of {HOME}.*git -C"):
        _token(root, tmp_path, other, api, host)
    assert (api.calls, api.posts) == ([], [])


def test_s038_10_a_components_app_token_for_its_own_repo_mints(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, WITH_APP + COMPONENT)
    assert _token(root, tmp_path, REPO, MintApi(), host) == 0
    assert capsys.readouterr().out == "token-1\n"


def test_s038_10_a_component_whose_origin_isnt_github_gets_no_token(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP + COMPONENT, origin="https://example.com/romamo/demo.git")
    api = MintApi()
    with pytest.raises(ReleaseError, match="only the checkout's origin \\(D-47\\)"):
        _token(root, tmp_path, REPO, api, host)
    assert api.calls == []


def test_s038_10_product_is_refused_in_a_component() -> None:
    # #585 builds --product on gh and app-token; each calls this before it mints
    with pytest.raises(ReleaseError, match="--product is the coordinator's.*D-47"):
        ProductConfig(home=HOME).refuse_product()
    ProductConfig(repos=("romamo/api",)).refuse_product()  # the home repo's coordinator may
