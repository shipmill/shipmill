"""D-90, #1189: `shipmill app-token --permission <name>=<read|write>` mints a token asking for
those permissions alone, cached apart from the session's `app-token.json`. Without the flag,
the request and the cache are the ones a session has always had"""

import datetime as dt
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app import (
    CACHE,
    OPTIONAL_PERMISSIONS,
    PERMISSIONS,
    Access,
    Answer,
    Narrowing,
    Permission,
    Token,
    app_token,
    load_token,
    product_cache,
    read_cache,
    save_token,
)
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git

from .test_app import APP_ID, GRANTED, REPO, FakeSigner, key_file
from .test_app_token import ACCESS_TOKENS, GET, HOUR, MintApi, cache_of, checkout, cli_args
from .test_gate import NOW

__all__ = ["checkout"]  # the fixture, imported for pytest

CONTENTS_WRITE = Narrowing((Permission("contents", "Contents", Access.WRITE),))


@dataclass
class GrantingApi(MintApi):
    """MintApi whose answer names the permissions GitHub granted: those asked, plus metadata
    read as GitHub adds it, unless `granted` says otherwise"""

    granted: dict[str, str] | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        answer = super().post(path, token, body)
        if answer.status != 201:
            return answer
        data = json.loads(answer.body)
        asked = body["permissions"]
        assert isinstance(asked, dict)
        data["permissions"] = self.granted if self.granted is not None else {**asked, "metadata": "read", **self.extra}
        return Answer(201, json.dumps(data))


def narrowed(git: Git, tmp_path: Path, api: MintApi, narrowing: Narrowing | None, now: dt.datetime = NOW) -> str:
    return app_token(cache_of(git), REPO, APP_ID, key_file(tmp_path), now, FakeSigner(), api, narrowing)


# The request


def test_without_the_flag_the_request_and_the_cache_are_a_sessions(checkout: Git, tmp_path: Path) -> None:
    api = GrantingApi()
    assert narrowed(checkout, tmp_path, api, None) == "token-1"
    [(_, _, body)] = api.posts
    assert body == {"repositories": ["demo"], "permissions": {p.key: str(p.access) for p in PERMISSIONS}}
    assert [p.name for p in cache_of(checkout).parent.iterdir()] == [CACHE]


def test_the_flag_asks_github_for_its_permissions_alone(checkout: Git, tmp_path: Path) -> None:
    api = GrantingApi()
    assert narrowed(checkout, tmp_path, api, CONTENTS_WRITE) == "token-1"
    [(path, _, body)] = api.posts
    assert path == ACCESS_TOKENS
    assert body == {"repositories": ["demo"], "permissions": {"contents": "write"}}


def test_the_cli_flag_reaches_the_request(checkout: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    api = GrantingApi(expires_from=dt.datetime.now(dt.UTC))
    args = cli_args(checkout, tmp_path, "--permission", "issues=read", "--permission", "contents=write")
    assert main(args, api=api, signer=FakeSigner()) == 0
    assert capsys.readouterr() == ("token-1\n", "")
    [(_, _, body)] = api.posts
    assert body["permissions"] == {"contents": "write", "issues": "read"}  # sorted by name
    assert (cache_of(checkout).parent / "app-token-contents-write-issues-read.json").is_file()


def test_the_flag_combines_with_git_credential(
    checkout: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = GrantingApi(expires_from=dt.datetime.now(dt.UTC))
    args = cli_args(checkout, tmp_path, "--permission", "contents=write", "--git-credential", "get")
    assert main(args, api=api, signer=FakeSigner(), stdin=io.StringIO(GET)) == 0
    assert capsys.readouterr() == ("username=x-access-token\npassword=token-1\n", "")
    [(_, _, body)] = api.posts
    assert body["permissions"] == {"contents": "write"}
    assert not cache_of(checkout).exists()


def test_an_optional_permission_is_asked_for_only_where_the_installation_grants_it(
    checkout: Git, tmp_path: Path
) -> None:
    """D-77's deployments read may be named: asked by name, an installation without it is
    refused before the token's request, as any named permission it lacks"""
    deployments = Narrowing.parse(("deployments=read",))
    assert deployments.permissions == (
        Permission("deployments", "Deployments", Access.READ, OPTIONAL_PERMISSIONS[0].serves),
    )
    lacking = GrantingApi()
    with pytest.raises(ReleaseError, match="lacks these permissions: Deployments: read"):
        narrowed(checkout, tmp_path, lacking, deployments)
    assert lacking.posts == []
    granting = GrantingApi(permissions=GRANTED | {"deployments": "read"})
    assert narrowed(checkout, tmp_path, granting, deployments) == "token-1"
    assert granting.posts[0][2]["permissions"] == {"deployments": "read"}


def test_a_narrowed_token_needs_only_its_permissions_on_the_installation(checkout: Git, tmp_path: Path) -> None:
    api = GrantingApi(permissions={"contents": "write", "metadata": "read"})
    assert narrowed(checkout, tmp_path, api, CONTENTS_WRITE) == "token-1"


@pytest.mark.parametrize(
    "granted",
    [
        {"contents": "write", "metadata": "read", "issues": "write"},
        {"contents": "admin", "metadata": "read"},
        {"contents": "write", "metadata": "write"},
        None,
    ],
)
def test_a_token_broader_than_asked_is_refused_and_not_cached(
    checkout: Git, tmp_path: Path, granted: dict[str, str] | None
) -> None:
    api = GrantingApi(granted=granted) if granted is not None else MintApi()
    with pytest.raises(ReleaseError, match="broader than it asked|without its permissions"):
        narrowed(checkout, tmp_path, api, CONTENTS_WRITE)
    assert not cache_of(checkout).parent.exists() or list(cache_of(checkout).parent.iterdir()) == []


# The cache


def test_the_narrowed_cache_is_apart_and_never_crosses(checkout: Git, tmp_path: Path) -> None:
    """A narrowed token never answers an unflagged call, nor a session's token a narrowed one"""
    api = GrantingApi()
    assert narrowed(checkout, tmp_path, api, None) == "token-1"
    assert narrowed(checkout, tmp_path, api, CONTENTS_WRITE) == "token-2"
    assert narrowed(checkout, tmp_path, api, None) == "token-1"
    assert narrowed(checkout, tmp_path, api, CONTENTS_WRITE) == "token-2"
    other = Narrowing.parse(("contents=read",))
    assert narrowed(checkout, tmp_path, api, other) == "token-3"
    folder = cache_of(checkout).parent
    assert sorted(p.name for p in folder.iterdir()) == [
        "app-token-contents-read.json",
        "app-token-contents-write.json",
        CACHE,
    ]
    assert load_token(folder / CACHE) == Token("token-1", NOW + HOUR, REPO, APP_ID)
    assert load_token(folder / "app-token-contents-write.json") == Token("token-2", NOW + HOUR, REPO, APP_ID)


def test_a_cached_session_token_is_never_returned_narrowed(checkout: Git, tmp_path: Path) -> None:
    save_token(cache_of(checkout), Token("session", NOW + HOUR, REPO, APP_ID))
    assert narrowed(checkout, tmp_path, GrantingApi(), CONTENTS_WRITE) == "token-1"


def test_the_cache_name_is_sorted_whatever_the_order_given() -> None:
    one = Narrowing.parse(("issues=read", "contents=write", "pull_requests=read"))
    two = Narrowing.parse(("pull_requests=read", "contents=write", "issues=read", "issues=read"))
    assert one == two
    assert one.cache == "app-token-contents-write-issues-read-pull_requests-read.json"


def test_no_narrowed_cache_name_is_another_tokens() -> None:
    """Every name starts with a table's key, never `product` or `read`, and ends with an access"""
    known = PERMISSIONS + OPTIONAL_PERMISSIONS
    names = {Narrowing.parse((f"{p.key}=read",)).cache for p in known}
    assert CACHE not in names
    assert all(not n.startswith(("app-token-product-", "app-token-read-")) for n in names)
    assert product_cache("contents") != Narrowing.parse(("contents=read",)).cache
    assert read_cache("contents") not in names
    assert all(Path(n).name == n and n.isascii() for n in names)


def test_metadata_read_may_be_named() -> None:
    assert Narrowing.parse(("metadata=read",)).cache == "app-token-metadata-read.json"


# Refusals: exit 2 before any request


@pytest.mark.parametrize(
    ("given", "message"),
    [
        (["contents"], "it is <name>=<read|write>"),
        (["=write"], "it is <name>=<read|write>"),
        (["contents=write=x"], "it is <name>=<read|write>"),
        (["secrets=read"], "the App's table has no 'secrets'"),
        (["Contents=write"], "the App's table has no 'Contents'"),
        (["contents=admin"], "the access is read or write, not 'admin'"),
        (["contents=WRITE"], "the access is read or write, not 'WRITE'"),
        (["contents="], "the access is read or write, not ''"),
        (["checks=write"], "the App's table has Checks: read, and a token asks for no more"),
        (["metadata=write"], "the App's table has Metadata: read"),
        (["deployments=write"], "the App's table has Deployments: read"),
        (["contents=write", "contents=read"], "contents is also asked as write; name it once"),
    ],
)
def test_a_bad_permission_exits_2_before_any_request(
    checkout: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str], given: list[str], message: str
) -> None:
    api = GrantingApi()
    extra = [arg for each in given for arg in ("--permission", each)]
    with pytest.raises(ReleaseError, match=message):
        main(cli_args(checkout, tmp_path, *extra), api=api, signer=FakeSigner())
    assert (api.calls, api.posts, capsys.readouterr().out) == ([], [], "")
    assert not cache_of(checkout).parent.exists()


def test_the_flag_is_refused_with_check(checkout: Git) -> None:
    with pytest.raises(ReleaseError, match="app-token --check takes no --permission"):
        main(["--repo", str(checkout.root), "app-token", "--check", "--permission", "contents=write"])


def test_the_flag_is_refused_with_product(checkout: Git, tmp_path: Path) -> None:
    api = GrantingApi()
    with pytest.raises(ReleaseError, match="never --product's"):
        main(cli_args(checkout, tmp_path, "--product", "--permission", "contents=read"), api=api, signer=FakeSigner())
    assert (api.calls, api.posts) == ([], [])


@pytest.mark.parametrize(
    "permissions",
    [
        (),
        (Permission("issues", "Issues", Access.READ), Permission("contents", "Contents", Access.READ)),
        (Permission("contents", "Contents", Access.READ), Permission("contents", "Contents", Access.READ)),
        (Permission("checks", "Checks", Access.WRITE),),
        (Permission("secrets", "Secrets", Access.READ),),
    ],
)
def test_a_narrowing_holds_only_known_sorted_unique_permissions(permissions: tuple[Permission, ...]) -> None:
    with pytest.raises(ReleaseError):
        Narrowing(permissions)
