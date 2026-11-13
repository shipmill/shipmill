"""Spec 065, The read token: a component's `shipmill gh --product OWNER/NAME` reads its
product's other repos with a read-only token over the home and the repos the home lists,
read from the home's config with a token over the home alone, scope-checked, cached apart,
and refused for every command that writes (S-065-1 to S-065-7, S-065-12). No test reaches the
network: GitHub is ReadApi"""

import base64
import datetime as dt
import io
import json
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app import (
    CACHE,
    PERMISSIONS,
    READ_PERMISSIONS,
    Answer,
    load_product_token,
    product_cache,
    read_cache,
)
from shipmill.app_gh import read_refusal
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gate import state_dir
from shipmill.gitrepo import Git

from .test_app import APP_ID, BOT, BOT_ID, BOT_PATH, GRANTED, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, GET, MintApi, executable

HOUR = dt.timedelta(hours=1)
HOME = "romamo/product"
COMPONENT = WITH_APP + f'\n[product]\nhome = "{HOME}"\n'
LISTED = (REPO, "romamo/web", "other-org/sdk")
HOME_CONFIG = WITH_APP + "\n[product]\nrepos = [" + ", ".join(f'"{r}"' for r in LISTED) + "]\n"
READ = {"contents": "read", "issues": "read", "pull_requests": "read", "metadata": "read"}
INSTALLS = {HOME: 55, REPO: 55, "romamo/web": 55, "romamo/cli": 55, "other-org/sdk": 66}
OWNERS = {55: "romamo", 66: "other-org"}
CONTENTS = f"/repos/{HOME}/contents/.github/shipmill.toml"
CHECKOUT_D84 = "D-84"


@dataclass
class ReadApi:
    """GitHub with the App installed on the product's repos: /app, each repo's installation, the
    home's config through the contents API, and access tokens, token-1, token-2, ... each valid
    for an hour from now. From post number `override_from` on, the answer's repositories and
    permissions are these when set, else they echo the request"""

    home_config: str | None = HOME_CONFIG  # None: GitHub has no such file
    repositories: list[str] | None = None
    permissions: dict[str, str] | None = None
    omit_permissions: bool = False
    override_from: int = 2  # the token over the set: the first is the home's alone
    now: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    calls: list[tuple[str, str | None]] = field(default_factory=list)
    posts: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.calls.append((path, token))
        if path == "/app":
            return Answer(200, json.dumps({"slug": "demo-agent", "id": APP_ID}))
        if path == BOT_PATH:
            return Answer(200, json.dumps({"login": BOT, "id": BOT_ID, "type": "Bot"}))
        if path == CONTENTS:
            if self.home_config is None:
                return Answer(404, '{"message": "Not Found"}')
            content = base64.b64encode(self.home_config.encode()).decode()
            return Answer(200, json.dumps({"type": "file", "encoding": "base64", "content": content}))
        for repo, number in INSTALLS.items():
            if path == f"/repos/{repo}/installation":
                granted = GRANTED if repo == REPO else READ
                return Answer(200, json.dumps({"id": number, "permissions": granted}))
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
        late = len(self.posts) >= self.override_from
        echoed = [f"{OWNERS[number]}/{n}" for n in names]
        repos = self.repositories if late and self.repositories is not None else echoed
        answer: dict[str, object] = {
            "token": f"token-{len(self.posts)}",
            "expires_at": (self.now + HOUR).isoformat().replace("+00:00", "Z"),
            "repositories": [{"full_name": r} for r in repos],
        }
        if not (late and self.omit_permissions):
            answer["permissions"] = self.permissions if late and self.permissions is not None else dict(asked)
        return Answer(201, json.dumps(answer))

    def minted(self) -> list[list[str]]:
        """Each token's asked repository names, in order"""
        out = []
        for _, body in self.posts:
            names = body["repositories"]
            assert isinstance(names, list)
            out.append([str(n) for n in names])
        return out


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes, record, home = tmp_path / "fakes", tmp_path / "record", tmp_path / "home"
    for folder in (fakes, record, home):
        folder.mkdir()
    executable(fakes / "gh", FAKE_GH)
    return Host(fakes, record, home)


def gh(root: Path, tmp_path: Path, args: list[str], host: Host, api: object, runner: Runner) -> int:
    return main(
        ["--repo", str(root), "gh", "--app-key", str(key_file(tmp_path)), *args],
        api=api,  # type: ignore[arg-type]
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
    )


def read_cache_of(root: Path, owner: str = "romamo") -> Path:
    return state_dir(Git(root)) / read_cache(owner)


def no_cache(root: Path) -> bool:
    folder = state_dir(Git(root))
    return not folder.exists() or not any(p.name.startswith("app-token") for p in folder.iterdir())


# -- S-065-1 ---------------------------------------------------------------------------------


def test_s065_1_read_permissions_are_exactly_four_reads() -> None:
    assert {p.key: str(p.access) for p in READ_PERMISSIONS} == READ


def test_s065_1_gh_product_mints_a_read_token_over_the_home_and_the_listed_repos_of_owner(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "view", "4"], host, api, runner) == 7
    # the home alone, to read its list; then the home and romamo/web, never the component itself
    # nor other-org/sdk, another owner's
    assert api.minted() == [["product"], ["product", "web"]]
    assert all(body["permissions"] == READ for _, body in api.posts)
    [(argv, env)] = runner.calls
    assert argv == [host.gh, "issue", "view", "4"]  # the args reach gh as given: no token in argv
    assert (env["GH_TOKEN"], env["GH_REPO"]) == ("token-2", "romamo/web")
    assert "token" not in capsys.readouterr().out


def test_s065_1_another_owners_listed_repo_gets_its_own_token(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    assert gh(root, tmp_path, ["--product", "other-org/sdk", "pr", "list"], host, api, runner) == 7
    assert api.minted() == [["product"], ["sdk"]]
    assert api.posts[1][0] == "/app/installations/66/access_tokens"
    assert runner.calls[0][1]["GH_REPO"] == "other-org/sdk"
    assert read_cache_of(root, "other-org").is_file()


def test_s065_1_the_home_itself_is_readable(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    assert gh(root, tmp_path, ["--product", HOME, "api", f"repos/{HOME}/contents/docs/specs"], host, api, runner) == 7
    assert runner.calls[0][1]["GH_REPO"] == HOME


# -- S-065-2 ---------------------------------------------------------------------------------


def test_s065_2_the_set_comes_from_the_homes_config_read_with_a_token_over_the_home_alone(
    tmp_path: Path, host: Host
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = (
        ReadApi(home_config=WITH_APP + f'\n[product]\nrepos = ["{REPO}", "romamo/web", "romamo/cli"]\n'),
        Runner(),
    )
    assert gh(root, tmp_path, ["--product", "romamo/cli", "issue", "list"], host, api, runner) == 7
    assert (CONTENTS, "token-1") in api.calls  # the home's own read token, minted over the home alone
    assert api.minted() == [["product"], ["product", "web", "cli"]]


@pytest.mark.parametrize("extra", ["\n[hooks]\ndefault_branch = false\n", ""])
def test_s065_2_the_components_own_config_adds_only_its_home(tmp_path: Path, host: Host, extra: str) -> None:
    root = checkout(tmp_path, COMPONENT + extra)
    api, runner = ReadApi(), Runner()
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner) == 7
    assert api.minted()[-1] == ["product", "web"]


# -- S-065-3 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("config", "why"),
    [
        (WITH_APP + '\n[product]\nrepos = ["romamo/web"]\n', f"doesn't list {REPO}"),
        (None, "GitHub has no"),
        (WITH_APP + "\nbroken = [\n", "can't be read"),
        (WITH_APP + '\n[product]\nhome = "romamo/else"\n', f"doesn't list {REPO}"),  # a component, not a home
        (WITH_APP + "\n[product]\nstandalone = true\n", f"doesn't list {REPO}"),
        ('[product]\nrepos = ["romamo/demo"]\n', "can't be read"),  # repos without app_id doesn't parse
    ],
)
def test_s065_3_a_home_that_doesnt_list_the_component_mints_no_token_over_the_set(
    tmp_path: Path, host: Host, config: str | None, why: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(home_config=config), Runner()
    with pytest.raises(ReleaseError, match=CHECKOUT_D84) as raised:
        gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner)
    assert why in str(raised.value)
    assert f'add "{REPO}" to [product] repos in {HOME}' in str(raised.value)
    assert api.minted() == [["product"]]  # the home's alone, to read its list; none over the set
    assert runner.calls == []
    assert no_cache(root)
    assert capsys.readouterr().out == ""


def test_s065_3_the_home_lists_the_component_case_ignored(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    config = WITH_APP + f'\n[product]\nrepos = ["{REPO.upper()}", "romamo/web"]\n'
    api, runner = ReadApi(home_config=config), Runner()
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner) == 7
    assert api.minted() == [["product"], ["product", "web"]]  # the component, listed in capitals, left out


# -- S-065-4 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"repositories": ["romamo/product", "romamo/web", "romamo/cli"]}, "for other repositories"),
        ({"repositories": ["romamo/web"]}, "for other repositories"),  # the home left out
        ({"repositories": ["romamo/product", REPO]}, "for other repositories"),
        ({"permissions": dict(READ, contents="write")}, "contents: write, broader"),
        ({"permissions": dict(READ, issues="write")}, "issues: write, broader"),
        ({"permissions": dict(READ, pull_requests="write")}, "pull_requests: write, broader"),
        ({"permissions": dict(READ, metadata="admin")}, "metadata: admin, broader"),
        ({"permissions": dict(READ, actions="read")}, "actions: read, broader"),
        ({"omit_permissions": True}, "without its permissions"),
    ],
)
def test_s065_4_a_read_token_other_than_asked_is_refused_unprinted_and_uncached(
    tmp_path: Path, host: Host, answer: dict[str, object], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(**answer), Runner()  # type: ignore[arg-type]
    with pytest.raises(ReleaseError, match=message) as raised:
        gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner)
    assert "token-2" not in str(raised.value)
    if "broader" in message:
        assert "a component's read token asks (D-84)" in str(raised.value)
    assert runner.calls == []
    assert no_cache(root)
    assert capsys.readouterr().out == ""


def test_s065_4_the_homes_own_token_is_scope_checked_too(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(permissions=dict(READ, contents="write"), override_from=1), Runner()
    with pytest.raises(ReleaseError, match="contents: write, broader"):
        gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner)
    assert CONTENTS not in [path for path, _ in api.calls]  # the home's config is never read with it
    assert runner.calls == [] and no_cache(root)


# -- S-065-5 ---------------------------------------------------------------------------------


def test_s065_5_the_read_token_is_cached_apart_with_mode_0600(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, ReadApi(), Runner()) == 7
    cache = read_cache_of(root)
    assert cache.name == "app-token-read-romamo.json"
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    cached = load_product_token(cache)
    assert cached is not None and (cached.value, cached.repos, cached.app_id) == (
        "token-2",
        (HOME, "romamo/web"),
        APP_ID,
    )
    assert not (state_dir(Git(root)) / CACHE).exists()
    assert not (state_dir(Git(root)) / product_cache("romamo")).exists()


def test_s065_5_reused_while_10_minutes_remain_with_the_same_app(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    now = dt.datetime.now(dt.UTC)
    nine = ReadApi(now=now - HOUR + dt.timedelta(minutes=9))  # its tokens have 9 minutes left
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, nine, Runner()) == 7
    fresh = ReadApi(now=now)
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, fresh, Runner()) == 7
    assert len(fresh.posts) == 2  # 9 minutes left: the list read again and minted again
    again, runner = ReadApi(now=now), Runner()
    assert gh(root, tmp_path, ["--product", HOME, "pr", "list"], host, again, runner) == 7  # the same owner's token
    assert (again.calls, again.posts) == ([], [])
    assert runner.calls[0][1]["GH_TOKEN"] == "token-2"


def test_s065_5_a_token_another_app_minted_is_minted_again(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    cache = read_cache_of(root)
    cache.parent.mkdir(parents=True, exist_ok=True)
    later = (dt.datetime.now(dt.UTC) + HOUR).isoformat()
    other = {"app_id": APP_ID + 1, "repositories": [HOME, "romamo/web"], "expires_at": later, "token": "theirs"}
    cache.write_text(json.dumps(other), encoding="utf-8")
    api, runner = ReadApi(), Runner()
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner) == 7
    assert runner.calls[0][1]["GH_TOKEN"] == "token-2"


def test_s065_5_a_repo_the_cached_token_misses_reads_the_list_again(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    assert gh(root, tmp_path, ["--product", HOME, "issue", "list"], host, ReadApi(), Runner()) == 7
    cache = read_cache_of(root)
    narrow = load_product_token(cache)
    assert narrow is not None
    # a cache over the home alone (as a home that listed less would leave) doesn't cover web
    record = json.loads(cache.read_text())
    record["repositories"] = [HOME]
    cache.write_text(json.dumps(record), encoding="utf-8")
    api, runner = ReadApi(), Runner()
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner) == 7
    assert api.minted() == [["product"], ["product", "web"]]


def test_s065_5_the_session_token_and_its_helpers_stay_one_repos(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    assert gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, ReadApi(), Runner()) == 7
    argv = ["--repo", str(root), "app-token", REPO, "--app-id", str(APP_ID), "--app-key", str(key_file(tmp_path))]
    api = MintApi()
    assert (
        main(
            [*argv, "--git-credential", "get"],
            api=api,
            signer=FakeSigner(),
            environ={},
            home=host.home,
            stdin=io.StringIO(GET),
        )
        == 0
    )
    assert capsys.readouterr().out == "username=x-access-token\npassword=token-1\n"
    [(_, _, body)] = api.posts
    assert body == {"repositories": ["demo"], "permissions": {p.key: str(p.access) for p in PERMISSIONS}}
    # the gh helper runs `shipmill gh` without --product: the session's token, for its own repo
    session, runner = MintApi(), Runner()
    assert gh(root, tmp_path, ["issue", "list"], host, session, runner) == 7
    assert runner.calls[0][1]["GH_TOKEN"] == "token-1" and "GH_REPO" not in runner.calls[0][1]
    assert json.loads((state_dir(Git(root)) / CACHE).read_text())["repository"] == REPO
    cached = load_product_token(read_cache_of(root))
    assert cached is not None and cached.value == "token-2"  # untouched by the session's mints


# -- S-065-6 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("product", "args", "message"),
    [
        (REPO, ["issue", "list"], "names this checkout's own repo"),
        (REPO.upper(), ["issue", "list"], "names this checkout's own repo"),
        ("romamo/web", ["issue", "list", "-R", "other-org/sdk"], "-R other-org/sdk isn't a repo of romamo"),
        ("romamo/web", ["issue", "list", "-sR", HOME], "-sR bundles -R"),
        ("romamo", ["issue", "list"], "needs owner/name"),
    ],
)
def test_s065_6_gh_product_exits_2_before_any_token(
    tmp_path: Path, host: Host, product: str, args: list[str], message: str
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    with pytest.raises(ReleaseError, match=message):
        gh(root, tmp_path, ["--product", product, *args], host, api, runner)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


@pytest.mark.parametrize(
    ("product", "args", "outside"),
    [
        ("romamo/other", ["issue", "list"], "romamo/other"),
        ("romamo/web", ["issue", "list", "-R", "romamo/other"], "romamo/other"),
        ("romamo/web", ["issue", "list", "-R", REPO], REPO),  # the component is outside the set
        ("elsewhere/x", ["issue", "list"], "elsewhere/x"),
    ],
)
def test_s065_6_gh_product_exits_2_for_a_repo_outside_the_set_before_gh_runs(
    tmp_path: Path, host: Host, product: str, args: list[str], outside: str
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    with pytest.raises(ReleaseError, match=f"names {re.escape(outside)}, which isn't {HOME}.*D-84"):
        gh(root, tmp_path, ["--product", product, *args], host, api, runner)
    assert api.minted() == [["product"]]  # the home's alone, to read the set; none over it
    assert runner.calls == [] and no_cache(root)


def test_s065_6_gh_product_exits_2_without_app_id(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, f'[product]\nhome = "{HOME}"\n')
    api, runner = ReadApi(), Runner()
    with pytest.raises(ReleaseError, match="needs \\[agents\\] app_id.*D-84"):
        gh(root, tmp_path, ["--product", "romamo/web", "issue", "list"], host, api, runner)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


# -- S-065-7 ---------------------------------------------------------------------------------


REFUSED = [
    ["issue", "create", "-t", "x", "-b", "y"],
    ["issue", "comment", "1", "-b", "x"],
    ["issue", "edit", "1", "--add-label", "x"],
    ["issue", "close", "1"],
    ["issue", "reopen", "1"],
    ["issue", "delete", "1"],
    ["issue", "transfer", "1", "x/y"],
    ["issue", "lock", "1"],
    ["issue", "pin", "1"],
    ["issue", "develop", "1"],
    ["issue"],
    ["issue", "-R", "romamo/web", "comment", "1"],  # gh reads this as `issue comment`: the subcommand comes right after
    ["pr", "merge", "1"],
    ["pr", "create", "-t", "x"],
    ["pr", "edit", "1"],
    ["pr", "comment", "1", "-b", "x"],
    ["pr", "review", "1", "--approve"],
    ["pr", "close", "1"],
    ["pr", "ready", "1"],
    ["pr", "checkout", "1"],
    ["label", "create", "x"],
    ["label", "edit", "x"],
    ["label", "delete", "x"],
    ["label", "clone", "x/y"],
    ["release", "create", "v1"],
    ["release", "upload", "v1", "x"],
    ["release", "delete", "v1"],
    ["release", "download", "v1"],
    ["repo", "edit"],
    ["repo", "create", "x"],
    ["repo", "fork"],
    ["repo", "clone", "romamo/web"],
    ["workflow", "run", "ci.yml"],
    ["workflow", "enable", "ci.yml"],
    ["run", "rerun", "1"],
    ["run", "cancel", "1"],
    ["run", "delete", "1"],
    ["secret", "set", "X"],
    ["variable", "set", "X"],
    ["gist", "create", "x"],
    ["api", "-X", "POST", "repos/romamo/web/issues"],
    ["api", "-XPOST", "repos/romamo/web/issues"],
    ["api", "-X=PATCH", "repos/romamo/web/issues/1"],
    ["api", "--method", "DELETE", "repos/romamo/web/labels/x"],
    ["api", "--method=PUT", "repos/romamo/web/pulls/1/merge"],
    ["api", "repos/romamo/web/issues", "-X", "post"],
    ["api", "-X", "GET", "repos/romamo/web", "-X", "POST"],  # any method but GET, wherever
    ["api", "-iXPOST", "repos/romamo/web/issues"],
    ["api", "-X", "HEAD", "repos/romamo/web"],
    ["-R", "romamo/web", "issue", "list"],
    ["--help"],
    [],
]


@pytest.mark.parametrize("args", REFUSED)
def test_s065_7_gh_product_refuses_every_command_that_writes_before_gh_runs(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    with pytest.raises(ReleaseError, match="under --product is refused.*D-84"):
        gh(root, tmp_path, ["--product", "romamo/web", *args], host, api, runner)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "list"],
        ["issue", "view", "1"],
        ["issue", "status"],
        ["pr", "list"],
        ["pr", "view", "1"],
        ["pr", "diff", "1"],
        ["pr", "checks", "1"],
        ["pr", "status"],
        ["label", "list"],
        ["release", "list"],
        ["release", "view", "v1"],
        ["repo", "view"],
        ["repo", "list", "romamo"],
        ["api", "repos/romamo/web/contents/docs/spec.md"],
        ["api", "-X", "GET", "repos/romamo/web/issues"],
        ["api", "--method=get", "repos/romamo/web/issues"],
        ["api", "graphql", "-f", "query={ viewer { login } }"],  # a mutation is the token's to refuse
    ],
)
def test_s065_7_the_reads_run(args: list[str]) -> None:
    assert read_refusal(args) is None


def test_s065_7_a_read_runs_with_the_read_token(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = ReadApi(), Runner()
    args = ["api", "-X", "GET", "repos/romamo/web/contents/docs/specs/001.md"]
    assert gh(root, tmp_path, ["--product", "romamo/web", *args], host, api, runner) == 7
    assert runner.calls[0][0] == [host.gh, *args]


@pytest.mark.parametrize("other", ["romamo/web", HOME])
def test_s065_7_gh_r_another_repo_without_product_still_exits_2_naming_d84(
    tmp_path: Path, host: Host, other: str
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api, runner = MintApi(), Runner()
    with pytest.raises(ReleaseError, match="D-84") as raised:
        gh(root, tmp_path, ["issue", "list", "-R", other], host, api, runner)
    assert "gh --product <their repo>" in str(raised.value)
    assert (api.calls, api.posts, runner.calls) == ([], [], [])


@pytest.mark.parametrize("product", [[], ["--product"]])
@pytest.mark.parametrize("other", ["romamo/web", HOME])
def test_s065_7_app_token_for_another_repo_still_exits_2_naming_d84(
    tmp_path: Path, host: Host, other: str, product: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, COMPONENT)
    api = MintApi()
    argv = ["--repo", str(root), "app-token", other, "--app-id", str(APP_ID), "--app-key", str(key_file(tmp_path))]
    with pytest.raises(ReleaseError, match="D-84"):
        main([*argv, *product], api=api, signer=FakeSigner(), environ={}, home=host.home)
    assert (api.calls, api.posts, capsys.readouterr().out) == ([], [], "")
    assert no_cache(root)


# -- S-065-12 --------------------------------------------------------------------------------


def test_s065_12_spec_038_marks_s038_10_dropped_naming_s065_6_and_s065_7() -> None:
    text = (Path(__file__).parents[1] / "docs" / "specs" / "038-product-coordinator.md").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith("- S-038-10: ")]
    assert len(lines) == 2  # the criterion and its Verification line
    criterion = lines[0].removeprefix("- S-038-10: ")
    assert re.match(r"dropped in (?:shipmill/shipmill)?#1085\b", criterion)
    assert "S-065-6" in criterion and "S-065-7" in criterion
    assert lines[1].removeprefix("- S-038-10: ").startswith("dropped in #1085")
