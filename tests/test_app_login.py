"""Spec 051, a person's consent: `shipmill app-login` stores a person's user access token from
GitHub's device flow, `shipmill app-logout` deletes and revokes it (S-051-5, S-051-6). GitHub
is faked through the code's own seams: the Api for api.github.com, the Web for github.com's
device flow and the revoke, a fake clock and sleep, and a temporary home"""

import argparse
import base64
import datetime as dt
import json
import os
import stat
import urllib.parse
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app import Answer
from shipmill.app_login import (
    ACCESS_TOKEN,
    CLIENT_SECRET,
    DEVICE_CODE,
    DeviceFlowOff,
    Unreachable,
    UserLogin,
    load_user_token,
    user_file,
)
from shipmill.cli import _parser, _user_login, main
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError

APP_ID = 5209412
CLIENT_ID = "Iv23liFakeClientId"
ACCESS = "ghu_FakeAccessTokenNeverPrinted"
REFRESH = "ghr_FakeRefreshTokenNeverPrinted"
SECRET = "fake-client-secret"
T0 = dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC)


@dataclass
class FakeApi:
    """api.github.com: GET /app with the App's JWT, GET /user with the new token"""

    login: str = "OctoCat"
    owner_type: str = "User"
    user_status: int = 200
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.calls.append((path, token))
        if path == "/app":
            owner = {"login": "acme" if self.owner_type == "Organization" else "romamo", "type": self.owner_type}
            return Answer(200, json.dumps({"client_id": CLIENT_ID, "slug": "shipmill-romamo", "owner": owner}))
        if path == "/user":
            assert token == ACCESS
            return Answer(self.user_status, json.dumps({"login": self.login, "message": f"echo {token}"}))
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        raise AssertionError(f"app-login posts nothing to api.github.com: POST {path}")


GRANTED = {
    "access_token": ACCESS,
    "expires_in": 28800,
    "refresh_token": REFRESH,
    "refresh_token_expires_in": 15897600,
    "token_type": "bearer",
    "scope": "",
}


@dataclass
class FakeWeb:
    """github.com's device flow, its polls answered in turn, and the revoke"""

    device: dict[str, object] = field(
        default_factory=lambda: {
            "device_code": "dev-code-secret",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }
    )
    device_status: int = 200
    polls: list[dict[str, object]] = field(default_factory=lambda: [GRANTED])
    revoke_status: int = 204
    unreachable: bool = False
    sent: list[tuple[str, str, dict[str, str], bytes | None]] = field(default_factory=list)

    def send(self, method: str, url: str, headers: Mapping[str, str], data: bytes | None) -> Answer:
        self.sent.append((method, url, dict(headers), data))
        if method == "POST" and url == DEVICE_CODE:
            return Answer(self.device_status, json.dumps(self.device))
        if method == "POST" and url == ACCESS_TOKEN:
            answer = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
            return Answer(200, json.dumps(answer))
        if method == "DELETE":
            if self.unreachable:
                raise Unreachable(f"GitHub is unreachable for DELETE {url}: timed out")
            return Answer(self.revoke_status, "" if self.revoke_status == 204 else '{"message": "Not Found"}')
        raise AssertionError(f"unexpected {method} {url}")


class FakeSigner:
    def sign(self, key: Path, data: bytes) -> bytes:
        return b"signature"


@dataclass
class Clock:
    now: dt.datetime = T0
    slept: list[float] = field(default_factory=list)

    def __call__(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


@pytest.fixture
def umask_0() -> Iterator[None]:
    """No umask, so a mode on disk is the mode the code created it with"""
    old = os.umask(0)
    yield
    os.umask(old)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "app.pem"
    path.write_text("not a real key\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def checkout(tmp_path: Path, config: str = f'[agents]\nprompt = "/t"\napp_id = {APP_ID}\n') -> Path:
    root = tmp_path / "repo"
    (root / CONFIG_PATH).parent.mkdir(parents=True)
    (root / CONFIG_PATH).write_text(config, encoding="utf-8")
    return root


def login(
    root: Path, home: Path, key: Path, api: FakeApi, web: FakeWeb, clock: Clock | None = None
) -> tuple[int, Clock]:
    clock = clock or Clock()
    args = argparse.Namespace(app_key=key)
    code = _user_login(root, args, api, web, FakeSigner(), {}, home, clock, clock.sleep)
    return code, clock


def form(data: bytes | None) -> dict[str, str]:
    assert data is not None
    return dict(urllib.parse.parse_qsl(data.decode()))


def test_s051_5_app_login_stores_both_tokens_0600_and_prints_the_login(
    tmp_path: Path, home: Path, key: Path, umask_0: None, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path)
    api, web = FakeApi(), FakeWeb()
    web.polls = [{"error": "authorization_pending"}, {"error": "slow_down", "interval": 10}, GRANTED]
    code, clock = login(root, home, key, api, web)
    assert code == 0
    path = home / ".config" / "shipmill" / f"user-{APP_ID}-octocat.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {
        "app_id": APP_ID,
        "client_id": CLIENT_ID,
        "login": "OctoCat",
        "access_token": ACCESS,
        "expires_at": (T0 + dt.timedelta(seconds=20 + 28800)).isoformat(),
        "refresh_token": REFRESH,
        "refresh_token_expires_at": (T0 + dt.timedelta(seconds=20 + 15897600)).isoformat(),
    }
    out, err = capsys.readouterr()
    assert out == f"stored the user access token of `@OctoCat` for the App {APP_ID} in {path}\n"
    assert "https://github.com/login/device" in err and "WDJB-MJHT" in err
    for secret in (ACCESS, REFRESH, "dev-code-secret"):
        assert secret not in out + err
    assert clock.slept == [5, 5, 10]  # the interval, then slow_down's new one
    assert [u for _, u, _, _ in web.sent] == [DEVICE_CODE, ACCESS_TOKEN, ACCESS_TOKEN, ACCESS_TOKEN]
    assert form(web.sent[0][3]) == {"client_id": CLIENT_ID}
    assert form(web.sent[1][3]) == {
        "client_id": CLIENT_ID,
        "device_code": "dev-code-secret",
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    assert web.sent[0][2]["Accept"] == "application/json"
    assert [p for p, _ in api.calls] == ["/app", "/user"]


def test_s051_5_a_slow_down_without_an_interval_adds_five_seconds(tmp_path: Path, home: Path, key: Path) -> None:
    web = FakeWeb(polls=[{"error": "slow_down"}, GRANTED])
    _, clock = login(checkout(tmp_path), home, key, FakeApi(), web)
    assert clock.slept == [5, 10]


def test_s051_5_app_login_exits_2_naming_the_setting_when_device_flow_is_off(
    tmp_path: Path, home: Path, key: Path
) -> None:
    web = FakeWeb(device={"error": "device_flow_disabled", "error_description": "Device Flow must be enabled"})
    web.device_status = 400
    with pytest.raises(DeviceFlowOff) as raised:
        login(checkout(tmp_path), home, key, FakeApi(owner_type="Organization"), web)
    message = str(raised.value)
    assert "Enable Device Flow" in message
    assert "https://github.com/organizations/acme/settings/apps/shipmill-romamo" in message
    assert not (home / ".config").exists()


def test_s051_5_device_flow_off_on_a_poll_names_the_setting_too(tmp_path: Path, home: Path, key: Path) -> None:
    web = FakeWeb(polls=[{"error": "device_flow_disabled"}])
    with pytest.raises(DeviceFlowOff, match=r"Enable Device Flow in its settings, https://github.com/settings/apps/"):
        login(checkout(tmp_path), home, key, FakeApi(), web)


@pytest.mark.parametrize(
    ("error", "said"),
    [
        ("access_denied", "the authorization was declined on github.com, so nothing is stored"),
        ("expired_token", "the code expired before it was entered on github.com"),
        ("incorrect_client_credentials", "GitHub refused the device flow for the App shipmill-romamo"),
    ],
)
def test_s051_5_a_refused_poll_exits_2_and_stores_nothing(
    tmp_path: Path, home: Path, key: Path, error: str, said: str
) -> None:
    with pytest.raises(ReleaseError, match=said):
        login(checkout(tmp_path), home, key, FakeApi(), FakeWeb(polls=[{"error": error}]))
    assert not (home / ".config").exists()


def test_s051_5_polling_stops_when_the_code_expires(tmp_path: Path, home: Path, key: Path) -> None:
    web = FakeWeb(polls=[{"error": "authorization_pending"}])
    with pytest.raises(ReleaseError, match=r"the code expired after 900 seconds"):
        login(checkout(tmp_path), home, key, FakeApi(), web)
    assert len([u for _, u, _, _ in web.sent if u == ACCESS_TOKEN]) == 900 // 5


def test_s051_5_a_config_without_app_id_exits_2(tmp_path: Path, home: Path, key: Path) -> None:
    root = checkout(tmp_path, '[agents]\nprompt = "/t"\n')
    with pytest.raises(ReleaseError, match=r"app-login needs \[agents\] app_id"):
        main(["--repo", str(root), "app-login"], api=FakeApi(), web=FakeWeb(), signer=FakeSigner(), home=home)
    with pytest.raises(ReleaseError, match=r"app-logout needs \[agents\] app_id"):
        main(["--repo", str(root), "app-logout", "octocat"], web=FakeWeb(), home=home, environ={})


def test_s051_5_no_token_reaches_an_error_message(tmp_path: Path, home: Path, key: Path) -> None:
    with pytest.raises(ReleaseError) as raised:
        login(checkout(tmp_path), home, key, FakeApi(user_status=401), FakeWeb())
    assert str(raised.value) == "GET /user with the new user access token answered 401"
    assert not (home / ".config").exists()


def test_s051_5_an_app_without_expiring_tokens_stores_no_expiry(tmp_path: Path, home: Path, key: Path) -> None:
    web = FakeWeb(polls=[{"access_token": ACCESS, "token_type": "bearer", "scope": ""}])
    login(checkout(tmp_path), home, key, FakeApi(), web)
    token = load_user_token(user_file(APP_ID, UserLogin("octocat"), home))
    assert (token.expires_at, token.refresh_token, token.refresh_token_expires_at) == (None, None, None)
    assert ACCESS not in repr(token)


def test_s051_5_an_existing_file_is_replaced_whole_and_stays_0600(
    tmp_path: Path, home: Path, key: Path, umask_0: None
) -> None:
    root = checkout(tmp_path)
    login(root, home, key, FakeApi(), FakeWeb())
    login(root, home, key, FakeApi(login="octocat"), FakeWeb())
    folder = home / ".config" / "shipmill"
    assert [p.name for p in folder.iterdir()] == [f"user-{APP_ID}-octocat.json"]
    assert stat.S_IMODE((folder / f"user-{APP_ID}-octocat.json").stat().st_mode) == 0o600


def logged_in(tmp_path: Path, home: Path, key: Path) -> tuple[Path, Path]:
    root = checkout(tmp_path)
    login(root, home, key, FakeApi(), FakeWeb())
    return root, user_file(APP_ID, UserLogin("octocat"), home)


def test_s051_6_app_logout_deletes_the_file_and_revokes_the_token(
    tmp_path: Path, home: Path, key: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, path = logged_in(tmp_path, home, key)
    capsys.readouterr()
    web = FakeWeb()
    code = main(["--repo", str(root), "app-logout", "@OctoCat"], web=web, home=home, environ={CLIENT_SECRET: SECRET})
    assert code == 0
    assert not path.exists()
    ((method, url, headers, data),) = web.sent
    assert (method, url) == ("DELETE", f"https://api.github.com/applications/{CLIENT_ID}/token")
    assert headers["Authorization"] == "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
    assert json.loads(data or b"") == {"access_token": ACCESS}
    out, err = capsys.readouterr()
    assert "`@OctoCat`" in out and err == ""
    assert ACCESS not in out and SECRET not in out


@pytest.mark.parametrize(
    ("environ", "web", "why"),
    [
        ({}, FakeWeb(), "shipmill has no client secret for the App"),
        ({CLIENT_SECRET: SECRET}, FakeWeb(revoke_status=404), "GitHub answered 404 to the revoke"),
        ({CLIENT_SECRET: SECRET}, FakeWeb(unreachable=True), "GitHub couldn't be reached to revoke it"),
    ],
)
def test_s051_6_a_failed_revoke_still_deletes_the_file_and_says_where_to_revoke(
    tmp_path: Path,
    home: Path,
    key: Path,
    capsys: pytest.CaptureFixture[str],
    environ: dict[str, str],
    web: FakeWeb,
    why: str,
) -> None:
    root, path = logged_in(tmp_path, home, key)
    capsys.readouterr()
    assert main(["--repo", str(root), "app-logout", "octocat"], web=web, home=home, environ=environ) == 1
    assert not path.exists()
    out, err = capsys.readouterr()
    assert out == ""
    assert why in err
    assert "revoke the App under your GitHub settings, Applications, Authorized GitHub Apps" in err
    assert ACCESS not in err and SECRET not in err
    if not environ:
        assert web.sent == []  # without a client secret nothing is sent


def test_s051_6_app_logout_of_a_login_with_no_file_exits_2(tmp_path: Path, home: Path) -> None:
    root = checkout(tmp_path)
    with pytest.raises(ReleaseError, match=r"no stored user token for `@octocat`"):
        main(["--repo", str(root), "app-logout", "octocat"], web=FakeWeb(), home=home, environ={})
    with pytest.raises(ReleaseError, match=r"is not a GitHub user's login"):
        main(["--repo", str(root), "app-logout", "../evil"], web=FakeWeb(), home=home, environ={})


def test_s051_6_a_malformed_file_is_named_and_never_quoted(tmp_path: Path, home: Path) -> None:
    root = checkout(tmp_path)
    path = user_file(APP_ID, UserLogin("octocat"), home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"access_token": ACCESS}), encoding="utf-8")
    with pytest.raises(ReleaseError) as raised:
        main(["--repo", str(root), "app-logout", "octocat"], web=FakeWeb(), home=home, environ={})
    assert str(path) in str(raised.value) and ACCESS not in str(raised.value)


def test_both_subcommands_are_registered() -> None:
    parser = _parser()
    assert parser.parse_args(["app-login"]).command == "app-login"
    assert parser.parse_args(["app-logout", "octocat"]).login == "octocat"
