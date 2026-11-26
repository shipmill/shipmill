"""Spec 093, The tick's read token: asked with TICK_READ_PERMISSIONS over the gate's repo and the
product's repos of its owner, refused when GitHub answers broader, cached apart in
`app-token-tick.json` with mode 0600, and written by no dry run (S-093-4 to S-093-7). No test
reaches the network: GitHub is TickApi"""

import base64
import datetime as dt
import json
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import ProductConfig
from shipmill.app import (
    CACHE,
    PERMISSIONS,
    TICK_CACHE,
    TICK_READ_PERMISSIONS,
    Answer,
    OtherOwner,
    ProductToken,
    load_product_token,
    save_product_token,
)
from shipmill.errors import ReleaseError
from shipmill.tick_read import tick_repos, tick_token

from .test_app import APP_ID, GRANTED, REPO, FakeSigner, key_file

NOW = dt.datetime(2026, 11, 25, 12, tzinfo=dt.UTC)
HOUR = dt.timedelta(hours=1)
HOME = "romamo/product"
TICK = {p.key: "read" for p in TICK_READ_PERMISSIONS}
WITH_APP = '[agents]\nprompt = "/t"\napp_id = 123456\n'
HOME_CONFIG = WITH_APP + f'\n[product]\nrepos = ["{REPO}", "romamo/web"]\n'
CONTENTS = f"/repos/{HOME}/contents/.github/shipmill.toml"
COMPONENT = ProductConfig(home=HOME)


@dataclass
class TickApi:
    """GitHub with the App installed once on every romamo repo: /app, each repo's installation
    (granting the session's table, and deployments read when `deployments`), the home's config,
    and access tokens token-1, token-2, ... valid for an hour from `now`. Each answer echoes the
    request, save the fields `answer` sets"""

    deployments: bool = False
    granted: dict[str, str] | None = None  # the installation's permissions; None: the session's table
    home_config: str | None = HOME_CONFIG  # None: GitHub has no such file
    answer: dict[str, object] = field(default_factory=dict)
    now: dt.datetime = NOW
    calls: list[tuple[str, str | None]] = field(default_factory=list)
    posts: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.calls.append((path, token))
        if path == "/app":
            return Answer(200, json.dumps({"slug": "demo-agent", "id": APP_ID}))
        if path == CONTENTS:
            if self.home_config is None:
                return Answer(404, '{"message": "Not Found"}')
            content = base64.b64encode(self.home_config.encode()).decode()
            return Answer(200, json.dumps({"type": "file", "encoding": "base64", "content": content}))
        if path.startswith("/repos/romamo/") and path.endswith("/installation"):
            granted = dict(self.granted or GRANTED)
            if self.deployments:
                granted["deployments"] = "read"
            return Answer(200, json.dumps({"id": 55, "permissions": granted}))
        if path.startswith("/repos/") and path.endswith("/installation"):
            return Answer(404, '{"message": "Not Found"}')
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        self.posts.append((path, body))
        names = body["repositories"]
        assert isinstance(names, list)
        reply: dict[str, object] = {
            "token": f"token-{len(self.posts)}",
            "expires_at": (self.now + HOUR).isoformat().replace("+00:00", "Z"),
            "repositories": [{"full_name": f"romamo/{n}"} for n in names],
            "repository_selection": "selected",
            "permissions": dict(body["permissions"]),  # type: ignore[call-overload]
        }
        reply.update(self.answer)
        return Answer(201, json.dumps({k: v for k, v in reply.items() if v is not None}))

    def minted(self) -> list[list[str]]:
        return [[str(n) for n in body["repositories"]] for _, body in self.posts]  # type: ignore[attr-defined]


def token(
    tmp_path: Path, api: TickApi, product: ProductConfig | None = None, write: bool = True, now: dt.datetime = NOW
) -> ProductToken:
    return tick_token(tmp_path / "state", REPO, product, APP_ID, key_file(tmp_path), now, FakeSigner(), api, write)


def cache_of(tmp_path: Path) -> Path:
    return tmp_path / "state" / TICK_CACHE


def no_token_files(tmp_path: Path) -> bool:
    state = tmp_path / "state"
    return not state.exists() or not any(p.name.startswith(("app-token", ".app-token")) for p in state.iterdir())


# -- S-093-4 ---------------------------------------------------------------------------------


def test_s093_4_the_table_is_eight_reads_each_within_the_sessions_table() -> None:
    assert TICK == {
        "actions": "read",
        "checks": "read",
        "contents": "read",
        "discussions": "read",
        "issues": "read",
        "pull_requests": "read",
        "statuses": "read",
        "metadata": "read",
    }
    session = {p.key: p.access for p in PERMISSIONS}
    assert all(p.key in session and session[p.key].covers(p.access) for p in TICK_READ_PERMISSIONS)


def test_s093_4_asked_with_exactly_the_table_without_deployments_where_not_granted(tmp_path: Path) -> None:
    api = TickApi()
    minted = token(tmp_path, api)
    [(path, body)] = api.posts
    assert path == "/app/installations/55/access_tokens"
    assert body["permissions"] == TICK
    assert (minted.value, minted.repos, minted.app_id) == ("token-1", (REPO,), APP_ID)


def test_s093_4_asks_deployments_read_where_the_installation_grants_it(tmp_path: Path) -> None:
    api = TickApi(deployments=True)
    token(tmp_path, api)
    assert api.posts[0][1]["permissions"] == dict(TICK, deployments="read")


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"permissions": dict(TICK, contents="write")}, "contents: write, broader"),
        ({"permissions": dict(TICK, issues="write")}, "issues: write, broader"),
        ({"permissions": dict(TICK, metadata="admin")}, "metadata: admin, broader"),
        ({"permissions": dict(TICK, workflows="read")}, "workflows: read, broader"),
        ({"permissions": dict(TICK, deployments="read")}, "deployments: read, broader"),  # not asked here
        ({"permissions": None}, "without its permissions"),
        ({"repositories": [{"full_name": REPO}, {"full_name": "romamo/web"}]}, "other repositories"),
        ({"repositories": [{"full_name": "romamo/web"}]}, "other repositories"),
        ({"repositories": None, "repository_selection": "all"}, "repository_selection 'all'"),
        ({"repositories": None}, "other repositories"),
        ({"repository_selection": "all"}, "repository_selection 'all'"),
    ],
)
def test_s093_4_an_answer_broader_than_asked_refuses_the_token_unreturned_and_uncached(
    tmp_path: Path, answer: dict[str, object], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    api = TickApi(answer=answer)
    with pytest.raises(ReleaseError, match=message) as raised:
        token(tmp_path, api)
    assert "token-1" not in str(raised.value)
    assert no_token_files(tmp_path)
    assert capsys.readouterr() == ("", "")


def test_s093_4_an_installation_lacking_a_read_refuses_before_any_mint(tmp_path: Path) -> None:
    api = TickApi(granted={"contents": "write", "metadata": "read"})
    with pytest.raises(ReleaseError, match="lacks these permissions"):
        token(tmp_path, api)
    assert api.posts == []


# -- S-093-5 ---------------------------------------------------------------------------------


def test_s093_5_without_product_the_gates_repo_alone(tmp_path: Path) -> None:
    api = TickApi()
    token(tmp_path, api)
    assert api.minted() == [["demo"]]
    assert CONTENTS not in [path for path, _ in api.calls]


def test_s093_5_in_a_home_repo_the_repo_and_its_listed_repos(tmp_path: Path) -> None:
    api = TickApi()
    minted = token(tmp_path, api, ProductConfig(repos=("romamo/web", "romamo/cli")))
    assert api.minted() == [["demo", "web", "cli"]]
    assert minted.repos == (REPO, "romamo/web", "romamo/cli")


def test_s093_5_in_a_component_the_repo_its_home_and_the_homes_listed_repos(tmp_path: Path) -> None:
    api = TickApi()
    minted = token(tmp_path, api, COMPONENT)
    # the repo and its home, to read the home's list with; then the set, the component once
    assert api.minted() == [["demo", "product"], ["demo", "product", "web"]]
    assert (CONTENTS, "token-1") in api.calls
    assert (minted.value, minted.repos) == ("token-2", (REPO, HOME, "romamo/web"))


@pytest.mark.parametrize(
    "config",
    [
        None,  # GitHub has no config in the home
        WITH_APP + '\n[product]\nrepos = ["romamo/web"]\n',  # the home doesn't list the component
        WITH_APP + "\n[product]\nstandalone = true\n",
    ],
)
def test_s093_5_a_home_that_doesnt_list_the_component_widens_nothing(tmp_path: Path, config: str | None) -> None:
    api = TickApi(home_config=config)
    minted = token(tmp_path, api, COMPONENT)
    assert api.minted() == [["demo", "product"]]  # the token that read the list is the one asked
    assert (minted.value, minted.repos) == ("token-1", (REPO, HOME))


@pytest.mark.parametrize(
    ("product", "config", "named"),
    [
        (ProductConfig(home="other-org/product"), HOME_CONFIG, "other-org/product"),
        (ProductConfig(repos=("romamo/web", "other-org/sdk")), HOME_CONFIG, "other-org/sdk"),
    ],
)
def test_s093_5_a_product_naming_another_owner_mints_no_token(
    tmp_path: Path, product: ProductConfig, config: str, named: str
) -> None:
    api = TickApi(home_config=config)
    with pytest.raises(OtherOwner) as raised:
        token(tmp_path, api, product)
    assert str(raised.value) == f"the product lists {named} of another owner"
    assert (api.calls, api.posts) == ([], [])
    assert no_token_files(tmp_path)


def test_s093_5_a_home_listing_another_owner_returns_and_caches_no_token(tmp_path: Path) -> None:
    api = TickApi(home_config=WITH_APP + f'\n[product]\nrepos = ["{REPO}", "other-org/sdk"]\n')
    with pytest.raises(OtherOwner, match="the product lists other-org/sdk of another owner"):
        token(tmp_path, api, COMPONENT)
    assert api.minted() == [["demo", "product"]]  # only the one that read the list, never over the set
    assert no_token_files(tmp_path)


def test_s093_5_tick_repos_keeps_each_repo_once_case_ignored() -> None:
    assert tick_repos(REPO, COMPONENT, (REPO.upper(), "romamo/web", "ROMAMO/WEB")) == (REPO, HOME, "romamo/web")


# -- S-093-6 ---------------------------------------------------------------------------------


def test_s093_6_cached_apart_in_app_token_tick_json_with_mode_0600(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    signer = FakeSigner()
    api = TickApi()
    tick_token(tmp_path / "state", REPO, None, APP_ID, key_file(tmp_path), NOW, signer, api, True)
    cache = cache_of(tmp_path)
    assert cache.name == "app-token-tick.json"
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    cached = load_product_token(cache)
    assert cached is not None and (cached.value, cached.repos, cached.app_id) == ("token-1", (REPO,), APP_ID)
    assert not (tmp_path / "state" / CACHE).exists()  # never the session's app-token.json
    assert [p.name for p in (tmp_path / "state").iterdir()] == [TICK_CACHE]
    assert capsys.readouterr() == ("", "")  # never on stdout or stderr
    assert all(b"token-1" not in data for _, data in signer.signed)  # the only process's input: no token


def test_s093_6_the_token_never_shows_in_its_repr() -> None:
    assert "secret" not in repr(ProductToken("secret", NOW + HOUR, (REPO,), APP_ID))


def test_s093_6_reused_while_the_same_app_minted_it_for_the_same_repos_with_10_minutes_left(tmp_path: Path) -> None:
    token(tmp_path, TickApi())
    again = TickApi()
    assert token(tmp_path, again, now=NOW + dt.timedelta(minutes=50)).value == "token-1"  # 10 minutes left
    assert (again.calls, again.posts) == ([], [])


def test_s093_6_minted_again_with_less_than_10_minutes_left(tmp_path: Path) -> None:
    token(tmp_path, TickApi())
    later = NOW + dt.timedelta(minutes=51)
    again = TickApi(now=later)
    assert token(tmp_path, again, now=later).value == "token-1"  # a new token-1 from the new api
    assert len(again.posts) == 1
    cached = load_product_token(cache_of(tmp_path))
    assert cached is not None and cached.expires == later + HOUR


def test_s093_6_minted_again_when_another_app_minted_it(tmp_path: Path) -> None:
    save_product_token(cache_of(tmp_path), ProductToken("theirs", NOW + HOUR, (REPO,), APP_ID + 1))
    api = TickApi()
    assert token(tmp_path, api).value == "token-1"
    assert len(api.posts) == 1


@pytest.mark.parametrize("cached", [(REPO, "romamo/web"), ("romamo/other",)])
def test_s093_6_minted_again_when_it_covers_other_repos(tmp_path: Path, cached: tuple[str, ...]) -> None:
    save_product_token(cache_of(tmp_path), ProductToken("old", NOW + HOUR, cached, APP_ID))
    api = TickApi()
    assert token(tmp_path, api).value == "token-1"
    assert api.minted() == [["demo"]]


def test_s093_6_a_component_reads_the_homes_list_with_its_cached_token_and_reuses_it(tmp_path: Path) -> None:
    token(tmp_path, TickApi(), COMPONENT)
    again = TickApi()
    assert token(tmp_path, again, COMPONENT).value == "token-2"
    assert again.posts == []
    assert again.calls == [(CONTENTS, "token-2")]  # the list, read with the cached token


def test_s093_6_a_home_that_lists_more_mints_again(tmp_path: Path) -> None:
    token(tmp_path, TickApi(), COMPONENT)
    wider = TickApi(home_config=WITH_APP + f'\n[product]\nrepos = ["{REPO}", "romamo/web", "romamo/cli"]\n')
    assert token(tmp_path, wider, COMPONENT).repos == (REPO, HOME, "romamo/web", "romamo/cli")
    assert wider.minted() == [["demo", "product", "web", "cli"]]


# -- S-093-7 ---------------------------------------------------------------------------------


def test_s093_7_a_dry_run_mints_and_writes_no_cache(tmp_path: Path) -> None:
    api = TickApi()
    assert token(tmp_path, api, COMPONENT, write=False).value == "token-2"
    assert len(api.posts) == 2
    assert no_token_files(tmp_path)


def test_s093_7_a_dry_run_reuses_a_cached_token(tmp_path: Path) -> None:
    token(tmp_path, TickApi())
    before = cache_of(tmp_path).read_bytes()
    api = TickApi()
    assert token(tmp_path, api, write=False).value == "token-1"
    assert api.posts == []
    assert cache_of(tmp_path).read_bytes() == before
