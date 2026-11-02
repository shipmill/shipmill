"""A person's consent to the App writing as them (spec 051, D-65): `shipmill app-login` runs
GitHub's device flow for the App named by `[agents] app_id` and stores the user access token
and its refresh token in `~/.config/shipmill/user-<app_id>-<login>.json`, mode 0600;
`shipmill app-logout <login>` deletes that file and revokes the token.

The person enters the one-time code on github.com in their own browser, signed in as
themselves: no other way stores a token. A token never reaches stdout, stderr, or an error
message: messages name GitHub's error code or status, never an answer's body, and the records
leave the values out of their repr.

Revoking a token (`DELETE /applications/<client_id>/token`) is authenticated with the App's
client id and client secret. shipmill keeps no client secret (app-create drops it unread), so
app-logout revokes only when SHIPMILL_APP_CLIENT_SECRET is set in its environment; otherwise,
or when GitHub refuses, it deletes the file and says where the person revokes the App
themselves.
"""

import base64
import datetime as dt
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from shipmill import cli_command
from shipmill.app import API, TIMEOUT, Answer, Api, Clock, Signer, check_key, jwt, write_atomic
from shipmill.errors import ReleaseError

DEVICE_CODE = "https://github.com/login/device/code"
ACCESS_TOKEN = "https://github.com/login/oauth/access_token"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SLOW_DOWN_SECONDS = 5  # RFC 8628: slow_down without an interval adds 5 seconds
CLIENT_SECRET = "SHIPMILL_APP_CLIENT_SECRET"  # read from the environment only, never stored
DEVICE_FLOW_SETTING = "Enable Device Flow"
REVOKE_PAGE = "https://github.com/settings/apps/authorizations"
_BODY_LIMIT = 1 << 20
_ERROR_CODE = re.compile(r"[a-z_]{1,64}")  # GitHub's OAuth error codes, such as access_denied
_USER_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")

Say = Callable[[str], None]
Sleep = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class UserLogin:
    """A GitHub user's login, such as octocat; never an App's bot. Logins compare
    case-insensitively, so the stored file is named by the lowercase form"""

    value: str

    def __post_init__(self) -> None:
        if not _USER_LOGIN.fullmatch(self.value):
            raise ReleaseError(f"{self.value!r} is not a GitHub user's login, such as octocat")

    @classmethod
    def given(cls, text: str) -> UserLogin:
        """A login as a person types it, `octocat` or `@octocat`"""
        return cls(text.removeprefix("@"))

    @property
    def key(self) -> str:
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


def user_file(app_id: int, login: UserLogin, home: Path) -> Path:
    """Where a person's user access token for the App lives on this host (spec 051)"""
    return home / ".config" / "shipmill" / f"user-{app_id}-{login.key}.json"


def stored_logins(app_id: int, home: Path) -> list[UserLogin]:
    """The logins with a stored user access token for the App on this host, sorted, read from
    the files' names alone, never opening one (S-051-15); a name that holds no login raises
    naming the file"""
    folder = home / ".config" / "shipmill"
    prefix = f"user-{app_id}-"
    if not folder.is_dir():
        return []
    logins = []
    for path in folder.glob(f"{prefix}*.json"):
        name = path.name.removeprefix(prefix).removesuffix(".json")
        if not _USER_LOGIN.fullmatch(name):
            raise ReleaseError(f"{path} is not named user-{app_id}-<login>.json; delete it, or run app-login again")
        logins.append(UserLogin(name))
    return sorted(logins, key=lambda login: login.key)


@dataclass(frozen=True, slots=True)
class UserToken:
    """A person's user access token for the App, with its refresh token and their expiries;
    an expiry is None when GitHub gave none (an App with expiring tokens off). repr leaves the
    values out"""

    app_id: int
    client_id: str
    login: UserLogin
    access_token: str = field(repr=False)
    expires_at: dt.datetime | None
    refresh_token: str | None = field(repr=False)
    refresh_token_expires_at: dt.datetime | None

    def record(self) -> dict[str, object]:
        return {
            "app_id": self.app_id,
            "client_id": self.client_id,
            "login": self.login.value,
            "access_token": self.access_token,
            "expires_at": None if self.expires_at is None else self.expires_at.isoformat(),
            "refresh_token": self.refresh_token,
            "refresh_token_expires_at": (
                None if self.refresh_token_expires_at is None else self.refresh_token_expires_at.isoformat()
            ),
        }


def save_user_token(home: Path, token: UserToken) -> Path:
    """Write the token's file: its folder created 0700 when missing, the file created 0600 and
    renamed into place, so it is never readable by others, even for a moment"""
    path = user_file(token.app_id, token.login, home)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_atomic(path, (json.dumps(token.record(), indent=2) + "\n").encode(), 0o600)
    return path


def _malformed(path: Path, reason: str) -> ReleaseError:
    return ReleaseError(
        f"the stored user token {path} is malformed ({reason}); delete it, and revoke the App under "
        f"your GitHub settings ({REVOKE_PAGE}, Applications, Authorized GitHub Apps)"
    )


def _moment(data: Mapping[str, object], key: str, path: Path) -> dt.datetime | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _malformed(path, f"{key} is not an ISO time")
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        raise _malformed(path, f"{key} is not an ISO time") from None
    if moment.tzinfo is None:
        raise _malformed(path, f"{key} has no offset")
    return moment


def load_user_token(path: Path) -> UserToken:
    """The stored token; a malformed file raises naming it, never quoting it"""
    try:
        data = json.loads(path.read_bytes())
    except json.JSONDecodeError, UnicodeDecodeError:
        raise _malformed(path, "not JSON") from None
    if not isinstance(data, dict):
        raise _malformed(path, "not a JSON object")
    app_id, client_id, login = data.get("app_id"), data.get("client_id"), data.get("login")
    access, refresh = data.get("access_token"), data.get("refresh_token")
    if not isinstance(app_id, int) or isinstance(app_id, bool):
        raise _malformed(path, "app_id is not an integer")
    if not isinstance(client_id, str) or not client_id:
        raise _malformed(path, "client_id is not a non-empty string")
    if not isinstance(login, str) or not _USER_LOGIN.fullmatch(login):
        raise _malformed(path, "login is not a GitHub login")
    if not isinstance(access, str) or not access:
        raise _malformed(path, "access_token is not a non-empty string")
    if refresh is not None and (not isinstance(refresh, str) or not refresh):
        raise _malformed(path, "refresh_token is not a non-empty string")
    return UserToken(
        app_id,
        client_id,
        UserLogin(login),
        access,
        _moment(data, "expires_at", path),
        refresh,
        _moment(data, "refresh_token_expires_at", path),
    )


class Web(Protocol):
    def send(self, method: str, url: str, headers: Mapping[str, str], data: bytes | None) -> Answer:
        """Send a request to a full github.com or api.github.com URL; an error status is an
        Answer, an unreachable host raises Unreachable"""
        ...


class Unreachable(ReleaseError):
    """GitHub could not be reached"""


class UrllibWeb:
    def send(self, method: str, url: str, headers: Mapping[str, str], data: bytes | None) -> Answer:
        sent = {"User-Agent": "shipmill-gate", **headers}
        request = urllib.request.Request(url, data=data, headers=sent, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                return Answer(int(answer.status), answer.read(_BODY_LIMIT).decode(errors="replace"))
        except urllib.error.HTTPError as exc:  # 4xx and 5xx: an answer to report
            body = exc.read(_BODY_LIMIT) if exc.fp is not None else b""
            return Answer(exc.code, body.decode(errors="replace"))
        except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts are OSErrors
            reason = getattr(exc, "reason", exc)
            raise Unreachable(f"GitHub is unreachable for {method} {url}: {reason}") from None


def _object(answer: Answer, what: str) -> dict[str, Any]:
    """The answer's JSON object; the message never quotes the body, which may hold a token"""
    try:
        data = json.loads(answer.body)
    except json.JSONDecodeError:
        raise ReleaseError(f"{what} answered {answer.status} without JSON") from None
    if not isinstance(data, dict):
        raise ReleaseError(f"{what} answered {answer.status} with JSON that is not an object")
    return data


@dataclass(frozen=True, slots=True)
class LoginApp:
    """What app-login reads of the App from GET /app"""

    app_id: int
    client_id: str
    slug: str
    settings: str  # the App's settings page, where Enable Device Flow is


def login_app(app_id: int, bearer: str, api: Api) -> LoginApp:
    """The App's client id, slug, and settings page, from GET /app with its JWT"""
    answer = api.get("/app", bearer)
    if answer.status != 200:
        raise ReleaseError(f"GET /app for app_id {app_id} answered {answer.status}: {answer.body.strip()[:300]}")
    data = _object(answer, "GET /app")
    client_id, slug, owner = data.get("client_id"), data.get("slug"), data.get("owner")
    if not isinstance(client_id, str) or not client_id or not isinstance(slug, str) or not slug:
        raise ReleaseError(f"GET /app for app_id {app_id} gave no client_id or slug")
    owner_login = owner.get("login") if isinstance(owner, dict) else None
    if isinstance(owner, dict) and owner.get("type") == "Organization" and isinstance(owner_login, str):
        settings = f"https://github.com/organizations/{owner_login}/settings/apps/{slug}"
    else:
        settings = f"https://github.com/settings/apps/{slug}"
    return LoginApp(app_id, client_id, slug, settings)


class DeviceFlowOff(ReleaseError):
    """The App has device flow off in its settings (S-051-5)"""


def device_flow_off(app: LoginApp) -> DeviceFlowOff:
    return DeviceFlowOff(
        f"the App {app.slug} has device flow off: turn on {DEVICE_FLOW_SETTING} in its settings, "
        f"{app.settings}, then run `{cli_command()} app-login` again"
    )


def _error(data: Mapping[str, object]) -> str | None:
    """GitHub's OAuth error code, or None; anything that is not a plain code reads as unknown"""
    error = data.get("error")
    if error is None:
        return None
    return error if isinstance(error, str) and _ERROR_CODE.fullmatch(error) else "unknown"


def _form(web: Web, url: str, fields: Mapping[str, str]) -> dict[str, Any]:
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    answer = web.send("POST", url, headers, urllib.parse.urlencode(fields).encode())
    return _object(answer, f"POST {url}")


def _seconds(data: Mapping[str, object], key: str, what: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ReleaseError(f"{what} gave no {key} as a positive number of seconds")
    return value


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """GitHub's answer to a device code request; repr leaves the device code out"""

    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


def device_code(app: LoginApp, web: Web) -> DeviceCode:
    """Ask GitHub for a device code for the App; device flow off raises DeviceFlowOff"""
    data = _form(web, DEVICE_CODE, {"client_id": app.client_id})
    error = _error(data)
    if error == "device_flow_disabled":
        raise device_flow_off(app)
    if error is not None:
        raise ReleaseError(f"GitHub refused a device code for the App {app.slug}: {error}")
    what = f"POST {DEVICE_CODE}"
    code, user, uri = data.get("device_code"), data.get("user_code"), data.get("verification_uri")
    if not isinstance(code, str) or not code or not isinstance(user, str) or not user:
        raise ReleaseError(f"{what} gave no device_code or user_code")
    if not isinstance(uri, str) or not uri.startswith("https://github.com/"):
        raise ReleaseError(f"{what} gave no verification_uri on https://github.com/")
    return DeviceCode(code, user, uri, _seconds(data, "expires_in", what), _seconds(data, "interval", what))


@dataclass(frozen=True, slots=True)
class Granted:
    """The tokens the device flow granted; repr leaves the values out"""

    access_token: str = field(repr=False)
    expires_at: dt.datetime | None
    refresh_token: str | None = field(repr=False)
    refresh_token_expires_at: dt.datetime | None


def _granted(data: Mapping[str, object], now: dt.datetime) -> Granted:
    what = f"POST {ACCESS_TOKEN}"
    access, refresh = data.get("access_token"), data.get("refresh_token")
    if not isinstance(access, str) or not access or any(c.isspace() for c in access):
        raise ReleaseError(f"{what} gave no access_token")
    expires = None if data.get("expires_in") is None else now + dt.timedelta(seconds=_seconds(data, "expires_in", what))
    if refresh is None:
        return Granted(access, expires, None, None)
    if not isinstance(refresh, str) or not refresh or any(c.isspace() for c in refresh):
        raise ReleaseError(f"{what} gave a refresh_token that is not a token")
    refresh_expires = now + dt.timedelta(seconds=_seconds(data, "refresh_token_expires_in", what))
    return Granted(access, expires, refresh, refresh_expires)


def poll(app: LoginApp, code: DeviceCode, web: Web, clock: Clock, sleep: Sleep) -> Granted:
    """Poll for the token every interval, slower on slow_down, until the code's expires_in
    runs out; access_denied, expired_token, and device flow off raise with what to do"""
    deadline = clock() + dt.timedelta(seconds=code.expires_in)
    interval = code.interval
    fields = {"client_id": app.client_id, "device_code": code.device_code, "grant_type": GRANT}
    again = f"run `{cli_command()} app-login` again"
    while clock() + dt.timedelta(seconds=interval) <= deadline:
        sleep(interval)
        data = _form(web, ACCESS_TOKEN, fields)
        error = _error(data)
        if error is None:
            return _granted(data, clock())
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            given = data.get("interval")
            if isinstance(given, int) and not isinstance(given, bool) and given > interval:
                interval = given
            else:
                interval += SLOW_DOWN_SECONDS
            continue
        if error == "access_denied":
            raise ReleaseError(f"the authorization was declined on github.com, so nothing is stored; {again}")
        if error == "expired_token":
            raise ReleaseError(f"the code expired before it was entered on github.com; {again}")
        if error == "device_flow_disabled":
            raise device_flow_off(app)
        raise ReleaseError(f"GitHub refused the device flow for the App {app.slug}: {error}")
    raise ReleaseError(f"the code expired after {code.expires_in} seconds without being entered on github.com; {again}")


def user_login(access_token: str, api: Api) -> UserLogin:
    """The login a user access token belongs to, from GET /user"""
    answer = api.get("/user", access_token)
    if answer.status != 200:
        raise ReleaseError(f"GET /user with the new user access token answered {answer.status}")
    found = _object(answer, "GET /user").get("login")
    if not isinstance(found, str):
        raise ReleaseError("GET /user gave no login")
    return UserLogin(found)


def store_login(
    app_id: int,
    key: Path,
    home: Path,
    api: Api,
    web: Web,
    signer: Signer,
    say: Say,
    clock: Clock,
    sleep: Sleep,
) -> tuple[UserLogin, Path]:
    """S-051-5: the App's client id from GET /app, GitHub's device flow, the login from GET
    /user, and the tokens stored in the person's file; the login and the file's path"""
    app = login_app(app_id, jwt(app_id, check_key(key), clock(), signer), api)
    code = device_code(app, web)
    say(
        f"open {code.verification_uri} and enter the code {code.user_code}, signed in to GitHub as yourself, "
        f"to let the App {app.slug} write as you (the code expires in {code.expires_in // 60} minutes)"
    )
    granted = poll(app, code, web, clock, sleep)
    login = user_login(granted.access_token, api)
    token = UserToken(
        app_id,
        app.client_id,
        login,
        granted.access_token,
        granted.expires_at,
        granted.refresh_token,
        granted.refresh_token_expires_at,
    )
    return login, save_user_token(home, token)


REFRESH_GRANT = "refresh_token"
REFRESH_AHEAD = dt.timedelta(minutes=5)  # a token this close to its expiry is refreshed first, so it lasts the write


class AsApp(ReleaseError):
    """Spec 051: why a write goes as the App rather than as the decider; the message names the
    login in a code span (D-61), and never a token"""


def _again(login: UserLogin) -> str:
    return f"`@{login}` runs `{cli_command()} app-login` again to write as themselves"


def refreshed(token: UserToken, home: Path, web: Web, environ: Mapping[str, str], now: dt.datetime) -> UserToken:
    """S-051-8: the token refreshed with its refresh token and stored again in home's file,
    atomically and 0600. A refresh token that is gone or expired, and a refresh GitHub refuses,
    delete the stored file and raise AsApp; GitHub out of reach raises AsApp and keeps the
    file. The App's client secret goes with the request when SHIPMILL_APP_CLIENT_SECRET is set"""
    login = token.login
    path = user_file(token.app_id, login, home)
    if token.refresh_token is None or (
        token.refresh_token_expires_at is not None and token.refresh_token_expires_at <= now
    ):
        path.unlink()
        raise AsApp(
            f"`@{login}`'s token expired and can't be refreshed, so its stored file is deleted; {_again(login)}"
        )
    fields = {"client_id": token.client_id, "grant_type": REFRESH_GRANT, "refresh_token": token.refresh_token}
    secret = environ.get(CLIENT_SECRET, "")
    if secret:
        fields["client_secret"] = secret
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    try:
        answer = web.send("POST", ACCESS_TOKEN, headers, urllib.parse.urlencode(fields).encode())
    except Unreachable:
        raise AsApp(f"GitHub couldn't be reached to refresh `@{login}`'s expired token") from None
    try:
        data = _object(answer, f"POST {ACCESS_TOKEN}")
        error = _error(data) if answer.status == 200 else f"status {answer.status}"
        granted = None if error is not None else _granted(data, now)
    except ReleaseError:  # an answer with no token in it: the refresh token may be spent, so the file is no use
        error, granted = "no token in its answer", None
    if granted is None:
        path.unlink()
        raise AsApp(
            f"GitHub refused to refresh `@{login}`'s token ({error}), so its stored file is deleted; {_again(login)}"
        )
    renewed = UserToken(
        token.app_id,
        token.client_id,
        login,
        granted.access_token,
        granted.expires_at,
        granted.refresh_token,
        granted.refresh_token_expires_at,
    )
    save_user_token(home, renewed)
    return renewed


def decider_token(
    app_id: int, login: UserLogin, home: Path, api: Api, web: Web, environ: Mapping[str, str], now: dt.datetime
) -> UserToken:
    """S-051-7 to S-051-9: the user access token login stored for the App with app-login,
    refreshed first when it has expired or is about to, and checked with GET /user to be
    login's and taken by GitHub. Raises AsApp, saying why, when there is none, its file is
    malformed or another's, it can't be refreshed, or GitHub refuses it"""
    path = user_file(app_id, login, home)
    if not path.is_file():
        raise AsApp(f"`@{login}` has not run {cli_command()} app-login")
    try:
        token = load_user_token(path)
    except ReleaseError as exc:
        raise AsApp(f"`@{login}`'s stored token can't be used: {exc}") from None
    if token.app_id != app_id or token.login.key != login.key:
        raise AsApp(f"`@{login}`'s stored token at {path} is for another App or login; {_again(login)}")
    if token.expires_at is not None and token.expires_at - REFRESH_AHEAD <= now:
        token = refreshed(token, home, web, environ, now)
    try:
        answer = api.get("/user", token.access_token)
    except ReleaseError:
        raise AsApp(f"GitHub couldn't be reached to check `@{login}`'s token") from None
    if answer.status != 200:
        raise AsApp(f"GitHub refused `@{login}`'s stored token (status {answer.status}); {_again(login)}")
    try:
        found = _object(answer, "GET /user").get("login")
    except ReleaseError:
        found = None
    if not isinstance(found, str) or found.lower() != login.key:
        raise AsApp(f"`@{login}`'s stored token isn't theirs by GET /user; {_again(login)}")
    return token


def revoke_elsewhere(login: UserLogin, why: str) -> str:
    """The line app-logout says when it couldn't revoke the token"""
    return (
        f"deleted the stored token of `@{login}`, but {why}: revoke the App under your GitHub settings, "
        f"Applications, Authorized GitHub Apps ({REVOKE_PAGE})"
    )


def remove_login(app_id: int, login: UserLogin, home: Path, web: Web, environ: Mapping[str, str], say: Say) -> bool:
    """S-051-6: delete the person's stored token, then revoke it with the App's client
    credentials; True when GitHub revoked it. Without a client secret, or when the revoke
    fails, the file is still deleted and say names where to revoke the App"""
    path = user_file(app_id, login, home)
    if not path.is_file():
        raise ReleaseError(f"no stored user token for `@{login}` at {path}; nothing to log out")
    token = load_user_token(path)
    path.unlink()
    secret = environ.get(CLIENT_SECRET, "")
    if not secret:
        say(revoke_elsewhere(login, f"shipmill has no client secret for the App to revoke it with ({CLIENT_SECRET})"))
        return False
    basic = base64.b64encode(f"{token.client_id}:{secret}".encode()).decode("ascii")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{API}/applications/{urllib.parse.quote(token.client_id, safe='')}/token"
    body = json.dumps({"access_token": token.access_token}).encode()
    try:
        answer = web.send("DELETE", url, headers, body)
    except Unreachable:
        say(revoke_elsewhere(login, "GitHub couldn't be reached to revoke it"))
        return False
    if answer.status != 204:
        say(revoke_elsewhere(login, f"GitHub answered {answer.status} to the revoke"))
        return False
    return True
