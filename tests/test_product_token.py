"""Spec 038, The coordinator's second token: `shipmill app-token --product` and `shipmill gh
--product` in the product's home repo, the scope check on GitHub's answer, the token's own
cache, the gate's check of the App on every listed repo, and a repo never naming itself
(S-038-3, S-038-5 to S-038-10). No test reaches the network: GitHub is ProductApi"""

import datetime as dt
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agent_marker import MARKER
from shipmill.agents import AgentsConfig, ProductConfig
from shipmill.app import (
    CACHE,
    HELPERS,
    PERMISSIONS,
    PRODUCT_PERMISSIONS,
    Answer,
    Api,
    app_check,
    load_product_token,
    product_cache,
    write_helpers,
)
from shipmill.app_gh import product_refusal, run_gh
from shipmill.autonomy import Hold
from shipmill.cli import _product_repos, main
from shipmill.errors import ReleaseError
from shipmill.gate import Action, gate, state_dir
from shipmill.gitrepo import Git

from .test_agent_marker import AGENTS, Current, sent
from .test_app import APP_ID, BOT, BOT_ID, BOT_PATH, GRANTED, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, FAKE_PYTHON, MintApi, executable
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg

HOUR = dt.timedelta(hours=1)
LISTED = ("romamo/api", "romamo/web", "other-org/sdk")
HOME = WITH_APP + "\n[product]\nrepos = [" + ", ".join(f'"{r}"' for r in LISTED) + "]\n"
ASKED = {"contents": "read", "issues": "write", "pull_requests": "read", "metadata": "read"}
INSTALLS = {REPO: 77, "romamo/api": 55, "romamo/web": 55, "other-org/sdk": 66}
OWNERS = {77: "romamo", 55: "romamo", 66: "other-org"}


@dataclass
class ProductApi:
    """GitHub with the App installed on the home repo and the listed repos: /app, each repo's
    installation, the bot account, and access tokens, token-1, token-2, ... each valid for an
    hour from now. Its answer's repositories and permissions echo the request unless set"""

    installs: dict[str, int] = field(default_factory=lambda: dict(INSTALLS))
    granted: dict[str, dict[str, str]] = field(default_factory=dict)  # a repo's installation permissions
    repositories: list[str] | None = None  # the answer's, instead of the asked ones
    permissions: dict[str, str] | None = None  # the answer's, instead of the asked ones
    omit_permissions: bool = False
    now: dt.datetime = NOW
    calls: list[str] = field(default_factory=list)
    posts: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.calls.append(path)
        if path == "/app":
            return Answer(200, json.dumps({"slug": "demo-agent", "id": APP_ID}))
        if path == BOT_PATH:
            return Answer(200, json.dumps({"login": BOT, "id": BOT_ID, "type": "Bot"}))
        for repo, number in self.installs.items():
            if path == f"/repos/{repo}/installation":
                default = GRANTED if repo == REPO else ASKED
                return Answer(200, json.dumps({"id": number, "permissions": self.granted.get(repo, default)}))
        if path.startswith("/repos/") and path.endswith("/installation"):
            return Answer(404, '{"message": "Not Found"}')
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        self.posts.append((path, body))
        number = int(path.split("/")[3])
        names = body["repositories"]
        assert isinstance(names, list)
        asked = body["permissions"]
        assert isinstance(asked, dict)
        repos = self.repositories if self.repositories is not None else [f"{OWNERS[number]}/{n}" for n in names]
        answer: dict[str, object] = {
            "token": f"token-{len(self.posts)}",
            "expires_at": (self.now + HOUR).isoformat().replace("+00:00", "Z"),
            "repositories": [{"full_name": r} for r in repos],
        }
        if not self.omit_permissions:
            answer["permissions"] = self.permissions if self.permissions is not None else dict(asked)
        return Answer(201, json.dumps(answer))


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes, record, home = tmp_path / "fakes", tmp_path / "record", tmp_path / "home"
    for folder in (fakes, record, home):
        folder.mkdir()
    executable(fakes / "gh", FAKE_GH)
    return Host(fakes, record, home)


def token(root: Path, tmp_path: Path, repo: str, api: Api, host: Host, *extra: str) -> int:
    argv = ["--repo", str(root), "app-token", repo, "--app-id", str(APP_ID), "--app-key", str(key_file(tmp_path))]
    return main([*argv, "--product", *extra], api=api, signer=FakeSigner(), environ={}, home=host.home)


def gh(root: Path, tmp_path: Path, args: list[str], host: Host, api: Api, runner: Runner) -> int:
    lead = ["--app-key", str(key_file(tmp_path))]
    return main(
        ["--repo", str(root), "gh", *lead, *args],
        api=api,
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
    )


def product_cache_of(root: Path, owner: str = "romamo") -> Path:
    return state_dir(Git(root)) / product_cache(owner)


# -- S-038-3 ---------------------------------------------------------------------------------


SELF = [f'\n[product]\nrepos = ["romamo/api", "{REPO}"]\n', f'\n[product]\nrepos = ["{REPO.upper()}"]\n']
SELF_HOME = f'\n[product]\nhome = "{REPO}"\n'


@pytest.mark.parametrize("table", [*SELF, SELF_HOME])
def test_s038_3_gh_and_app_token_product_exit_2_when_the_config_names_the_checkouts_repo(
    tmp_path: Path, host: Host, table: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, WITH_APP + table)
    api, runner = ProductApi(), Runner()
    with pytest.raises(ReleaseError, match="this checkout's own repo; a repo never names itself"):
        gh(root, tmp_path, ["issue", "list"], host, api, runner)
    if "repos" in table:
        with pytest.raises(ReleaseError, match="this checkout's own repo; a repo never names itself"):
            token(root, tmp_path, "romamo/api", api, host)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("table", [*SELF, SELF_HOME])
def test_s038_3_the_gate_exits_2_when_the_config_names_its_repo(tmp_path: Path, table: str) -> None:
    root = checkout(tmp_path, WITH_APP + table)
    assert AgentsConfig.load(root).app_id == APP_ID  # no repo to compare: the parse alone passes
    api = ProductApi()
    claude = FakeClaude([bg("old", "idle", "done")])
    check = app_check(REPO, key_file(tmp_path), tmp_path, FakeSigner(), api)
    with pytest.raises(ReleaseError, match="a repo never names itself"):
        gate(
            Git(root),
            REPO,
            lambda: AgentsConfig.load(root, REPO),
            claude,
            lambda _: [ISSUES],
            NOW,
            Hold,
            FakeNotifier(),
            NO_PRUNE,
            app=check,
        )
    assert (api.calls, claude.launched, claude.stopped) == ([], [], [])


# -- S-038-5 ---------------------------------------------------------------------------------


def test_s038_5_app_token_product_mints_one_token_over_the_owners_listed_repos(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    api = ProductApi()
    assert token(root, tmp_path, "romamo/web", api, host) == 0
    assert capsys.readouterr().out == "token-1\n"
    assert api.posts == [
        ("/app/installations/55/access_tokens", {"repositories": ["api", "web"], "permissions": ASKED})
    ]
    assert {p.key: str(p.access) for p in PRODUCT_PERMISSIONS} == ASKED
    assert f"/repos/{REPO}/installation" not in api.calls  # the home repo is no part of it


def test_s038_5_another_owners_repos_get_their_own_token(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    api = ProductApi()
    assert token(root, tmp_path, "Other-Org/SDK", api, host) == 0
    assert capsys.readouterr().out == "token-1\n"
    assert api.posts == [("/app/installations/66/access_tokens", {"repositories": ["sdk"], "permissions": ASKED})]
    assert product_cache_of(root, "other-org").is_file()


@pytest.mark.parametrize(
    ("config", "repo", "message"),
    [
        (WITH_APP, "romamo/api", "needs \\[product\\] repos .* has no \\[product\\] table"),
        (HOME, "romamo/other", "names romamo/other, which \\[product\\] repos doesn't list"),
        (HOME, "elsewhere/api", "names elsewhere/api, which \\[product\\] repos doesn't list"),
        (HOME, "romamo", "needs owner/name"),
    ],
)
def test_s038_5_app_token_product_exits_2_without_repos_or_for_a_repo_not_listed(
    tmp_path: Path, host: Host, config: str, repo: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, config)
    api = ProductApi()
    with pytest.raises(ReleaseError, match=message):
        token(root, tmp_path, repo, api, host)
    assert (api.calls, api.posts, capsys.readouterr().out) == ([], [], "")


def test_s038_5_the_product_token_never_answers_git(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOME)
    api = ProductApi()
    with pytest.raises(ReleaseError, match="never goes to git"):
        token(root, tmp_path, "romamo/api", api, host, "--git-credential", "get")
    assert api.calls == []


def test_s038_5_another_app_id_than_the_configs_is_refused(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOME)
    api = ProductApi()
    argv = ["--repo", str(root), "app-token", "romamo/api", "--app-id", "99", "--app-key", str(key_file(tmp_path))]
    with pytest.raises(ReleaseError, match=f"--app-id 99 isn't .* app_id {APP_ID}"):
        main([*argv, "--product"], api=api, signer=FakeSigner(), environ={}, home=host.home)
    assert api.calls == []


# -- S-038-6 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"repositories": ["romamo/api", "romamo/web", "romamo/demo"]}, "for other repositories"),
        ({"repositories": ["romamo/api"]}, "for other repositories"),
        ({"repositories": ["romamo/api", "romamo/elsewhere"]}, "for other repositories"),
        ({"repositories": []}, "for other repositories"),
        ({"permissions": dict(ASKED, contents="write")}, "contents: write, broader"),
        ({"permissions": dict(ASKED, pull_requests="write")}, "pull_requests: write, broader"),
        ({"permissions": dict(ASKED, actions="read")}, "actions: read, broader"),
        ({"permissions": dict(ASKED, issues="admin")}, "issues: admin, broader"),
        ({"omit_permissions": True}, "without its permissions"),
    ],
)
def test_s038_6_a_token_broader_than_asked_is_refused_unprinted_and_uncached(
    tmp_path: Path, host: Host, answer: dict[str, object], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    api = ProductApi(**answer)  # type: ignore[arg-type]
    with pytest.raises(ReleaseError, match=message) as raised:
        token(root, tmp_path, "romamo/api", api, host)
    assert "token-1" not in str(raised.value)
    assert capsys.readouterr().out == ""
    assert not product_cache_of(root).exists()
    assert not (state_dir(Git(root)) / CACHE).exists()


def test_s038_6_gh_product_runs_no_gh_with_a_token_broader_than_asked(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOME)
    api, runner = ProductApi(permissions=dict(ASKED, contents="write")), Runner()
    with pytest.raises(ReleaseError, match="broader than the coordinator asks"):
        gh(root, tmp_path, ["--product", "romamo/api", "issue", "list"], host, api, runner)
    assert runner.calls == []
    assert not product_cache_of(root).exists()


def test_s038_6_a_narrower_answer_passes(tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]) -> None:
    root = checkout(tmp_path, HOME)
    assert token(root, tmp_path, "romamo/api", ProductApi(permissions={"issues": "write"}), host) == 0
    assert capsys.readouterr().out == "token-1\n"


# -- S-038-7 ---------------------------------------------------------------------------------


def _not_installed() -> ProductApi:
    api = ProductApi()
    del api.installs["romamo/web"]
    return api


def _lacking() -> ProductApi:
    return ProductApi(granted={"romamo/web": dict(ASKED, issues="read")})


LACKS = "app demo-agent on romamo/web lacks these permissions: Issues: write"
NOT_INSTALLED = "app demo-agent is not installed on romamo/web"


@pytest.mark.parametrize(("api", "message"), [(_not_installed, NOT_INSTALLED), (_lacking, LACKS)])
def test_s038_7_app_token_product_names_the_repo_the_app_misses(
    tmp_path: Path, host: Host, api: type[ProductApi], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    github = api()
    with pytest.raises(ReleaseError, match=message):
        token(root, tmp_path, "romamo/api", github, host)
    assert (github.posts, capsys.readouterr().out) == ([], "")
    assert not product_cache_of(root).exists()


@pytest.mark.parametrize(("api", "message"), [(_not_installed, NOT_INSTALLED), (_lacking, LACKS)])
def test_s038_7_the_home_repos_gate_starts_no_session_without_the_coordinators_access(
    tmp_path: Path, api: type[ProductApi], message: str
) -> None:
    root = checkout(tmp_path, HOME)
    github = api()
    claude = FakeClaude([bg("old", "idle", "done")])
    product = ProductConfig.load(root)
    assert product is not None
    check = app_check(REPO, key_file(tmp_path), tmp_path, FakeSigner(), github, lambda: product.repos)
    decision, *_ = gate(
        Git(root),
        REPO,
        lambda: AgentsConfig.load(root, REPO),
        claude,
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        app=check,
    )
    # spec 048: the failed App check reads GITHUB_AUTH, naming the listed repo
    assert decision.action is Action.GITHUB_AUTH and decision.reason.startswith(f"{message}: no session starts")
    assert (claude.launched, claude.stopped, github.posts) == ([], [], [])


def test_s038_7_the_gate_checks_every_listed_repo_with_one_jwt(tmp_path: Path) -> None:
    # the CLI's gate reads the config's repos with _product_repos
    root = checkout(tmp_path, HOME)
    api = ProductApi()
    found = app_check(REPO, key_file(tmp_path), tmp_path, FakeSigner(), api, lambda: _product_repos(root))(APP_ID)
    assert found.login == BOT
    assert api.calls == ["/app", f"/repos/{REPO}/installation", *(f"/repos/{r}/installation" for r in LISTED), BOT_PATH]
    assert api.posts == []


def test_s038_7_without_product_the_gate_checks_only_its_repo(tmp_path: Path) -> None:
    api = ProductApi()
    app_check(REPO, key_file(tmp_path), tmp_path, FakeSigner(), api)(APP_ID)
    assert api.calls == ["/app", f"/repos/{REPO}/installation", BOT_PATH]


# -- S-038-8 ---------------------------------------------------------------------------------


def test_s038_8_the_product_token_is_cached_apart_with_mode_0600(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    assert token(root, tmp_path, "romamo/api", ProductApi(), host) == 0
    cache = product_cache_of(root)
    assert cache.name == "app-token-product-romamo.json"
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    cached = load_product_token(cache)
    assert cached is not None and cached.repos == ("romamo/api", "romamo/web") and cached.value == "token-1"
    assert "token-1" not in repr(cached)
    assert not (state_dir(Git(root)) / CACHE).exists()  # never the session's
    capsys.readouterr()


def test_s038_8_reused_while_10_minutes_remain_and_the_repos_match(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    now = dt.datetime.now(dt.UTC)
    nine = ProductApi(now=now - HOUR + dt.timedelta(minutes=9))  # its token has 9 minutes left
    assert token(root, tmp_path, "romamo/api", nine, host) == 0
    fresh = ProductApi(now=now)
    assert token(root, tmp_path, "romamo/api", fresh, host) == 0
    assert len(fresh.posts) == 1  # 9 minutes left: minted again
    again = ProductApi(now=now)
    assert token(root, tmp_path, "romamo/web", again, host) == 0  # the same owner's token
    assert (again.calls, again.posts) == ([], [])
    assert capsys.readouterr().out == "token-1\ntoken-1\ntoken-1\n"


def test_s038_8_a_repo_added_to_the_config_mints_again(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    now = dt.datetime.now(dt.UTC)
    assert token(root, tmp_path, "romamo/api", ProductApi(now=now), host) == 0
    (root / ".github" / "shipmill.toml").write_text(
        WITH_APP + '\n[product]\nrepos = ["romamo/api", "romamo/web", "romamo/cli"]\n', encoding="utf-8"
    )
    api = ProductApi(now=now)
    api.installs["romamo/cli"] = 55
    assert token(root, tmp_path, "romamo/api", api, host) == 0
    assert api.posts[0][1]["repositories"] == ["api", "web", "cli"]
    cached = load_product_token(product_cache_of(root))
    assert cached is not None and cached.repos == ("romamo/api", "romamo/web", "romamo/cli")
    capsys.readouterr()


def test_s038_8_a_session_token_still_mints_for_its_one_repo(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, HOME)
    assert token(root, tmp_path, "romamo/api", ProductApi(), host) == 0
    api = MintApi()
    argv = ["--repo", str(root), "app-token", REPO, "--app-id", str(APP_ID), "--app-key", str(key_file(tmp_path))]
    assert main(argv, api=api, signer=FakeSigner(), environ={}, home=host.home) == 0
    assert capsys.readouterr().out == "token-1\ntoken-1\n"
    [(_, _, body)] = api.posts
    assert body == {"repositories": ["demo"], "permissions": {p.key: str(p.access) for p in PERMISSIONS}}
    assert json.loads((state_dir(Git(root)) / CACHE).read_text())["repository"] == REPO


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"token": "t", "repositories": "romamo/api", "app_id": 1, "expires_at": "2026-01-01T00:00:00+00:00"}',
        '{"token": "t", "repositories": ["romamo/api"], "app_id": 1, "expires_at": "soon"}',
    ],
)
def test_s038_8_a_malformed_product_cache_exits_2_naming_it(tmp_path: Path, host: Host, text: str) -> None:
    root = checkout(tmp_path, HOME)
    cache = product_cache_of(root)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    with pytest.raises(ReleaseError, match=re.escape(f"the App token cache {cache} is malformed")):
        token(root, tmp_path, "romamo/api", ProductApi(), host)


# -- S-038-9 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "target"),
    [
        (["issue", "create", "-t", "x", "--body", "y"], "romamo/api"),
        (["issue", "list", "-R", "romamo/web"], "romamo/web"),
        (["pr", "view", "3", "--repo=github.com/romamo/web"], "romamo/web"),
        (["api", "repos/romamo/api/contents/README.md"], "romamo/api"),
    ],
)
def test_s038_9_gh_product_runs_gh_with_the_product_token(
    tmp_path: Path, host: Host, args: list[str], target: str
) -> None:
    root = checkout(tmp_path, HOME)
    api, runner = ProductApi(), Runner()
    assert gh(root, tmp_path, ["--product", "romamo/api", *args], host, api, runner) == 7
    [(argv, env)] = runner.calls
    assert argv == [host.gh, *(sent(args) if "--body" in args else args)]  # spec 050 marks a body
    assert (env["GH_TOKEN"], env["GH_REPO"]) == ("token-1", target)
    assert [path for path, _ in api.posts] == ["/app/installations/55/access_tokens"]
    assert product_cache_of(root).is_file() and not (state_dir(Git(root)) / CACHE).exists()


def test_s050_3_under_product_the_edit_reads_with_the_product_token(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOME)
    current, runner = Current(body=AGENTS), Runner()
    args = ["--app-key", str(key_file(tmp_path)), "--product", "romamo/api", "issue", "edit", "2", "-b", "x"]
    code = main(
        ["--repo", str(root), "gh", *args],
        api=ProductApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
        gh_capture=current,
    )
    assert code == 7
    [(read, read_env)] = current.calls
    [(argv, env)] = runner.calls
    assert read == [host.gh, "api", "repos/romamo/api/issues/2"]
    assert argv == [host.gh, "issue", "edit", "2", "--body", f"x\n\n{MARKER}"]
    assert read_env == env and (env["GH_TOKEN"], env["GH_REPO"]) == ("token-1", "romamo/api")


def test_s038_9_gh_product_in_the_coordinators_session_skips_the_sessions_gh_helper(tmp_path: Path, host: Host) -> None:
    # the session's PATH starts with its gh helper, which would put the session's token on gh
    root = checkout(tmp_path, HOME)
    python = executable(host.fakes / "python", FAKE_PYTHON)
    helpers = write_helpers(
        state_dir(Git(root)) / HELPERS, python, root, REPO, APP_ID, key_file(tmp_path), host.env()["PATH"]
    )
    environ = host.env(PATH=os.pathsep.join([str(helpers.folder), host.env()["PATH"]]))
    argv = ["--repo", str(root), "gh", "--app-key", str(key_file(tmp_path)), "--product", "romamo/api", "issue", "list"]
    assert main(argv, api=ProductApi(), signer=FakeSigner(), environ=environ, home=host.home, gh_runner=run_gh) == 7
    assert (host.record / "gh-token").read_text() == "token-1"
    assert not (host.record / "python-args").exists()  # the session's helper never ran


def test_s038_9_product_may_follow_app_key_or_come_first(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOME)
    runner = Runner()
    argv = ["--repo", str(root), "gh", "--product=romamo/api", "--app-key", str(key_file(tmp_path)), "issue", "list"]
    code = main(argv, api=ProductApi(), signer=FakeSigner(), environ=host.env(), home=host.home, gh_runner=runner)
    assert code == 7
    assert runner.calls[0][0] == [host.gh, "issue", "list"]


@pytest.mark.parametrize(
    ("product", "args", "message"),
    [
        ("romamo/other", ["issue", "list"], "names romamo/other, which \\[product\\] repos doesn't list"),
        ("romamo/api", ["issue", "list", "-R", "romamo/other"], "-R romamo/other isn't a listed repo of romamo"),
        ("romamo/api", ["issue", "list", "-R", "other-org/sdk"], "-R other-org/sdk isn't a listed repo of romamo"),
        ("romamo/api", ["issue", "list", "-R", REPO], f"-R {REPO} isn't a listed repo"),
        ("romamo/api", ["issue", "list", "-sR", "romamo/web"], "-sR bundles -R"),
    ],
)
def test_s038_9_gh_product_exits_2_for_a_repo_not_listed_or_of_another_owner(
    tmp_path: Path, host: Host, product: str, args: list[str], message: str
) -> None:
    root = checkout(tmp_path, HOME)
    api, runner = ProductApi(), Runner()
    with pytest.raises(ReleaseError, match=message):
        gh(root, tmp_path, ["--product", product, *args], host, api, runner)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


def test_s038_9_gh_product_exits_2_without_product_repos(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    api, runner = ProductApi(), Runner()
    with pytest.raises(ReleaseError, match="needs \\[product\\] repos"):
        gh(root, tmp_path, ["--product", "romamo/api", "issue", "list"], host, api, runner)
    assert (api.calls, runner.calls) == ([], [])


REFUSED = [
    ["pr", "merge", "1"],
    ["pr", "create", "-t", "x"],
    ["pr", "new"],
    ["pr", "edit", "1"],
    ["pr", "comment", "1", "-b", "x"],
    ["pr", "review", "1", "--approve"],
    ["pr", "close", "1"],
    ["pr", "reopen", "1"],
    ["pr", "ready", "1"],
    ["pr", "checkout", "1"],
    ["pr", "-R", "list", "merge", "1"],  # gh reads this as `pr merge`
    ["pr", "--repo=romamo/api", "merge", "1"],
    ["pr"],
    ["release", "create", "v1"],
    ["release", "upload", "v1", "x"],
    ["release", "delete", "v1"],
    ["release", "edit", "v1"],
    ["repo", "edit"],
    ["repo", "create", "x"],
    ["repo", "delete"],
    ["repo", "sync"],
    ["repo", "fork"],
    ["repo", "clone", "romamo/api"],
    ["workflow", "run", "ci.yml"],
    ["workflow", "-R", "romamo/api", "run", "ci.yml"],
    ["run", "rerun", "1"],
    ["run", "cancel", "1"],
    ["-R", "romamo/api", "pr", "merge", "1"],
    ["--help"],
]


@pytest.mark.parametrize("args", REFUSED)
def test_s038_9_gh_product_refuses_the_commands_that_write_code_or_pull_requests(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    root = checkout(tmp_path, HOME)
    api, runner = ProductApi(), Runner()
    with pytest.raises(ReleaseError, match="under --product is refused.*D-47"):
        gh(root, tmp_path, ["--product", "romamo/api", *args], host, api, runner)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "list"],
        ["pr", "view", "1"],
        ["pr", "diff", "1"],
        ["pr", "checks", "1"],
        ["pr", "status"],
        ["release", "list"],
        ["release", "view", "v1"],
        ["repo", "view"],
        ["repo", "list", "romamo"],
        ["workflow", "list"],
        ["run", "list"],
        ["run", "view", "1"],
        ["issue", "create", "-t", "x"],
        ["issue", "comment", "1", "-b", "x"],
        ["api", "graphql", "-f", "query=x"],
        [],
    ],
)
def test_s038_9_the_read_commands_and_issue_writes_run(args: list[str]) -> None:
    assert product_refusal(args) is None


def test_s038_9_gh_without_product_is_unchanged_in_the_home_repo(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOME)
    api, runner = MintApi(), Runner()
    # a write --product refuses; a merge is classified first (S-030-13, tests/test_app_gh_merge.py)
    assert gh(root, tmp_path, ["pr", "edit", "1", "--title", "x"], host, api, runner) == 7
    assert runner.calls[0][1]["GH_TOKEN"] == "token-1"
    assert "GH_REPO" not in runner.calls[0][1]
    assert not product_cache_of(root).exists()


# -- S-038-10 --------------------------------------------------------------------------------

COMPONENT = WITH_APP + '\n[product]\nhome = "romamo/product"\n'


def test_s038_10_gh_product_in_a_component_exits_2_naming_d47_before_a_token(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ProductApi(), Runner()
    with pytest.raises(ReleaseError, match="--product is the coordinator's.*D-47"):
        gh(root, tmp_path, ["--product", REPO, "issue", "list"], host, api, runner)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


def test_s038_10_app_token_product_in_a_component_exits_2_naming_d47_before_a_token(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api = ProductApi()
    with pytest.raises(ReleaseError, match="--product is the coordinator's.*D-47"):
        token(root, tmp_path, "romamo/product", api, host)
    assert (api.calls, api.posts, capsys.readouterr().out) == ([], [], "")
