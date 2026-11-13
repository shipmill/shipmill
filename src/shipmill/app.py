"""The GitHub App a gated session writes as (spec 004, D-14): its private key on the host,
the JWT signed with it, and the checks that the App is installed on the gate's repo with
every permission a session needs.

The key is a host secret: shipmill reads its mode, hands its path to `openssl`, and never
reads its bytes, so they can't reach output. The package keeps no dependencies: the JWT is
signed by `openssl dgst -sha256 -sign <key>`, and GitHub is asked over urllib.

A session never holds a token (spec 004, Tokens): its `gh` and git credential helpers mint
one, limited to the gate's repo, at each call, or reuse the one cached in `app-token.json`
(mode 0600) while it has at least 10 minutes left. A token reaches stdout only as
`shipmill app-token`'s answer, which the helpers read; never an error message, a process's
arguments, or a helper's file.

The product's home repo, the coordinator, has a second token (spec 038, D-47): over the repos
its `[product] repos` lists under one owner, and the home repo itself when it has that owner
(#1032), with PRODUCT_PERMISSIONS, cached apart in
`app-token-product-<owner>.json`. It never reaches the session's cache or helpers, so a push
from the coordinator's session still reaches only the home repo.

A component has a third (spec 065, D-84): over its home and the repos the home lists, of one
owner, with READ_PERMISSIONS, cached apart in `app-token-read-<owner>.json`; it too never
reaches the session's cache or helpers.
"""

import base64
import binascii
import datetime as dt
import enum
import http.client
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from shipmill import cli_command
from shipmill.errors import ReleaseError

API = "https://api.github.com"
TIMEOUT = 30.0  # seconds a GitHub API call may take
ISSUED_BEFORE = dt.timedelta(seconds=60)  # iat: allows for a host clock ahead of GitHub's
VALID_FOR = dt.timedelta(minutes=9)  # exp: GitHub refuses a JWT valid longer than 10 minutes
_BODY_LIMIT = 1 << 20

Clock = Callable[[], dt.datetime]  # read when a JWT is signed, so a long tick never signs with its start (#694)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Access(enum.StrEnum):
    READ = "read"
    WRITE = "write"

    def covers(self, need: Access) -> bool:
        """write covers read"""
        return self is Access.WRITE or need is Access.READ


@dataclass(frozen=True, slots=True)
class Permission:
    key: str  # the name GitHub's API gives it
    label: str  # the name GitHub's settings page gives it
    access: Access
    serves: str = ""  # an optional permission's use, which its warning names

    def named(self) -> str:
        return f"{self.label}: {self.access}"


# The spec's table: what a session needs on the repo, and nothing more. installation()
# requires every one, so adding one here stops every gate whose installation hasn't
# accepted it (D-63); a new permission goes in OPTIONAL_PERMISSIONS instead (D-77)
PERMISSIONS = (
    Permission("contents", "Contents", Access.WRITE),
    Permission("pull_requests", "Pull requests", Access.WRITE),
    Permission("issues", "Issues", Access.WRITE),
    Permission("actions", "Actions", Access.WRITE),
    Permission("workflows", "Workflows", Access.WRITE),
    Permission("checks", "Checks", Access.READ),
    Permission("statuses", "Commit statuses", Access.READ),
    Permission("discussions", "Discussions", Access.READ),
    Permission("metadata", "Metadata", Access.READ),
)

# D-77: what the App asks for beyond PERMISSIONS. A session's token asks for one only where
# the installation grants it, and an installation without it still launches sessions;
# doctor and the gate's GitHub preflight name it as a warning saying what to accept
OPTIONAL_PERMISSIONS = (
    Permission("deployments", "Deployments", Access.READ, "the report reads the environments' deployments with it"),
)

# Spec 038, D-47: the coordinator's second token, over the product's repos: it reads their code
# and items and files and links issues there; it never writes contents, pull requests, actions,
# or workflows
PRODUCT_PERMISSIONS = (
    Permission("contents", "Contents", Access.READ),
    Permission("issues", "Issues", Access.WRITE),
    Permission("pull_requests", "Pull requests", Access.READ),
    Permission("metadata", "Metadata", Access.READ),
)

# Spec 065, D-84: a component's read token, over its product's other repos: it reads their code,
# issues, and pull requests, and writes nothing anywhere
READ_PERMISSIONS = (
    Permission("contents", "Contents", Access.READ),
    Permission("issues", "Issues", Access.READ),
    Permission("pull_requests", "Pull requests", Access.READ),
    Permission("metadata", "Metadata", Access.READ),
)


# Spec 054: the token `shipmill land --app-key` pushes the protected branches with: the release
# and sync commits, and a hotfix's cherry-picked merges, which may touch .github/workflows/
LAND_PERMISSIONS = (
    Permission("contents", "Contents", Access.WRITE),
    Permission("workflows", "Workflows", Access.WRITE),
)


def default_key(app_id: int, home: Path) -> Path:
    """Where the key lives when `--app-key` doesn't say"""
    return home / ".config" / "shipmill" / f"app-{app_id}.pem"


# Spec 033: the key's path, which shipmill gate sets on every session it starts. A non-empty
# value makes the App available to the session; `shipmill gh` and `app-token` take the key
# from it before the default path, and a leading --app-key wins over it
APP_KEY = "SHIPMILL_APP_KEY"

NOT_AVAILABLE = (
    "the App isn't available here, so shipmill writes nothing: a skill hands you its text to post, "
    "and what you post yourself with gh is yours (spec 033)"
)


def session_key(app_id: int, environ: Mapping[str, str], home: Path) -> Path:
    """The key a session uses without --app-key: a non-empty SHIPMILL_APP_KEY, else the
    default path (spec 033)"""
    named = environ.get(APP_KEY, "")
    return Path(named).expanduser() if named else default_key(app_id, home)


def require_key(path: Path) -> Path:
    """`shipmill gh`'s key, before any token: a missing one exits 2 with check_key's line and
    spec 033's second; its mode is check_key's to judge when a token is minted"""
    if not path.is_file():
        raise ReleaseError(
            f"no App private key at {path}; download it from the App's settings to that path\n{NOT_AVAILABLE}"
        )
    return path


@dataclass(frozen=True, slots=True)
class Availability:
    """`shipmill app-token --check`'s answer (spec 033): whether the App is available to the
    session, by the delivery hook's own test; the reason names it either way"""

    available: bool
    reason: str


def availability(app_id: int, environ: Mapping[str, str], home: Path) -> Availability:
    """The hook's test and nothing more, for a repo with [agents] app_id: a non-empty
    SHIPMILL_APP_KEY, or a file at the default key path, checked with one stat and never read.
    No token, no network"""
    if environ.get(APP_KEY):
        return Availability(True, f"the App {app_id} is available here: {APP_KEY} is set")
    path = default_key(app_id, home)
    if path.is_file():
        return Availability(True, f"the App {app_id} is available here: its key is at {path}")
    return Availability(False, f"the App {app_id} isn't available here: no key at {path} and no {APP_KEY}")


class AuthFailure(ReleaseError):
    """A failure of the identity a gated session writes as, one row of spec 048's GITHUB_AUTH
    table: problem names what failed, fix what to run; the message is the one the error read
    before spec 048, so a caller that prints it is unchanged"""

    def __init__(self, problem: str, fix: str, message: str | None = None) -> None:
        super().__init__(problem if message is None else message)
        self.problem = problem
        self.fix = fix


class KeyRefused(AuthFailure):
    """The App's private key is missing, or readable by group or others"""


class JwtRefused(AuthFailure):
    """GitHub answered 401 to the App's JWT"""


class MintRefused(AuthFailure):
    """GitHub refused to mint an installation token"""


GITHUB_STATUS = "https://www.githubstatus.com"
UNAVAILABLE_FIX = f"wait for GitHub ({GITHUB_STATUS}): nothing here needs repair, the next tick tries again"


def unavailable(status: int) -> bool:
    """A 5xx: GitHub's own failure, which no repair on this side fixes (#981)"""
    return 500 <= status <= 599


class GitHubUnavailable(AuthFailure):
    """GitHub answered a call with a 5xx (#981): its problem names the call and the status,
    never the body; its fix is to wait for GitHub, since the next tick tries again. The
    message stays the one the error read before, for a caller that prints it"""

    def __init__(self, method: str, path: str, status: int, message: str | None = None) -> None:
        if not unavailable(status):
            raise ValueError(f"GitHub is unavailable only on a 5xx, not {status}")
        super().__init__(f"GitHub is unavailable ({method} {path} answered {status})", UNAVAILABLE_FIX, message)
        self.method = method
        self.path = path
        self.status = status


RATE_LIMITED_FIX = "wait for GitHub's rate limit to reset: nothing here needs repair, the next tick tries again"
_RATE_LIMIT = re.compile(r"\brate limit\b", re.IGNORECASE)  # "API rate limit exceeded", "a secondary rate limit"


def rate_limited(answer: Answer) -> bool:
    """A 403 or 429 whose body says GitHub's rate limit was exceeded, primary or secondary
    (#1034): a limit that resets, which no repair on this side fixes. A 403 saying anything
    else is a refusal, read as before"""
    return answer.status in (403, 429) and _RATE_LIMIT.search(answer.body) is not None


class RateLimited(AuthFailure):
    """GitHub rate-limited a call (#1034): its problem names the call and the status, never the
    body; its fix is to wait, since the next tick tries again. The message stays the one the
    error read before, for a caller that prints it"""

    def __init__(self, method: str, path: str, answer: Answer, message: str | None = None) -> None:
        if not rate_limited(answer):
            raise ValueError(f"GitHub rate-limited a call only on a 403 or 429 saying so, not {answer.status}")
        problem = f"GitHub rate-limited the call ({method} {path} answered {answer.status})"
        super().__init__(problem, RATE_LIMITED_FIX, message)
        self.method = method
        self.path = path
        self.status = answer.status


def check_key(path: Path) -> Path:
    """The key's path once it is a file only its owner can read; its bytes are never read here"""
    if not path.is_file():
        problem = f"no App private key at {path}"
        fix = f"download the App's private key to {path}, or create an App with `{cli_command()} app-create`"
        raise KeyRefused(problem, fix, f"{problem}; download it from the App's settings to that path")
    if path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
        problem = f"the App private key {path} is readable by group or others"
        raise KeyRefused(problem, f"chmod 600 {path}", f"{problem}; run `chmod 600 {path}`")
    return path


class Signer(Protocol):
    def sign(self, key: Path, data: bytes) -> bytes:
        """data's RSA SHA-256 signature with the key"""
        ...


class Openssl:
    def __init__(self, command: str = "openssl") -> None:
        self.command = command

    def sign(self, key: Path, data: bytes) -> bytes:
        binary = shutil.which(self.command)
        if binary is None:
            raise ReleaseError(f"{self.command} not found; the App's JWT is signed with `openssl dgst -sha256 -sign`")
        proc = subprocess.run(
            [binary, "dgst", "-sha256", "-sign", str(key)], input=data, capture_output=True, check=False
        )
        if proc.returncode != 0 or not proc.stdout:
            detail = proc.stderr.decode(errors="replace").strip()[:300]
            raise ReleaseError(f"openssl could not sign with the App private key {key}: {detail}")
        return proc.stdout


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt(app_id: int, key: Path, now: dt.datetime, signer: Signer) -> str:
    """An RS256 App JWT, issued 60 seconds before now and valid until 9 minutes after it"""
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iat": int((now - ISSUED_BEFORE).timestamp()),
        "exp": int((now + VALID_FOR).timestamp()),
        "iss": app_id,
    }
    signing = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    return f"{signing}.{_b64(signer.sign(key, signing.encode('ascii')))}"


@dataclass(frozen=True, slots=True)
class Answer:
    status: int
    body: str


class Api(Protocol):
    def get(self, path: str, token: str | None) -> Answer:
        """GET api.github.com's path with the token as a bearer, or anonymously with None; an
        error status is an Answer"""
        ...

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        """POST body as JSON to api.github.com's path with the token as a bearer; an error
        status is an Answer"""
        ...


class UrllibApi:
    def get(self, path: str, token: str | None) -> Answer:
        return self._send("GET", path, token, None)

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        return self._send("POST", path, token, json.dumps(body).encode())

    def _send(self, method: str, path: str, token: str | None, data: bytes | None) -> Answer:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "shipmill-gate",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                return Answer(int(answer.status), answer.read(_BODY_LIMIT).decode(errors="replace"))
        except urllib.error.HTTPError as exc:  # 4xx and 5xx: an answer to report
            body = exc.read(_BODY_LIMIT) if exc.fp is not None else b""
            return Answer(exc.code, body.decode(errors="replace"))
        except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts are OSErrors
            reason = getattr(exc, "reason", exc)
            raise ReleaseError(f"GitHub's API is unreachable for {method} {path}: {reason}") from None


def _json(answer: Answer, path: str, method: str = "GET") -> dict[str, Any]:
    """The answer's JSON object; the message never quotes the body, which may hold a token"""
    try:
        data = json.loads(answer.body)
    except json.JSONDecodeError:
        raise ReleaseError(f"{method} {path} answered {answer.status} without JSON") from None
    if not isinstance(data, dict):
        raise ReleaseError(f"{method} {path} answered {answer.status} with JSON that is not an object")
    return data


def _ok(answer: Answer, path: str, app_id: int, method: str = "GET", status: int = 200) -> dict[str, Any]:
    """The JSON of an answer with the expected status; an error answer's body, which is only
    ever GitHub's message, is quoted"""
    if answer.status == status:
        return _json(answer, path, method)
    message = answer.body.strip()[:300]
    said = f"{method} {path} for app_id {app_id} answered {answer.status}: {message}"
    if unavailable(answer.status):
        raise GitHubUnavailable(method, path, answer.status, said)
    if rate_limited(answer):
        raise RateLimited(method, path, answer, said)
    if answer.status == 401:
        problem = f"GitHub refused the JWT for app_id {app_id} ({method} {path}: 401 {message})"
        raise JwtRefused(
            problem,
            f"set the host's clock (`sntp -sS time.apple.com`), or use App {app_id}'s own private key",
            f"{problem}; check that the private key is App {app_id}'s and the host's clock is right",
        )
    raise ReleaseError(said)


@dataclass(frozen=True, slots=True)
class Installation:
    """The App as GitHub knows it, installed on the gate's repo"""

    slug: str
    id: int
    permissions: Mapping[str, Access]
    page: str | None = None  # the installation's settings page, GitHub's html_url

    @property
    def bot(self) -> str:
        return f"{self.slug}[bot]"

    @property
    def settings(self) -> str:
        """Where the owner accepts the App's permissions on this installation"""
        return self.page or f"https://github.com/settings/installations/{self.id}"

    def grants(self, table: tuple[Permission, ...]) -> tuple[Permission, ...]:
        """The table's permissions this installation grants"""
        lacking = missing(self.permissions, table)
        return tuple(p for p in table if p not in lacking)

    def notices(self, repo: str, optional: tuple[Permission, ...] = OPTIONAL_PERMISSIONS) -> tuple[str, ...]:
        """D-77: one warning per optional permission the installation lacks, naming it, what it
        serves, and that the owner accepts it on the installation's page"""
        return tuple(
            f"app {self.slug} on {repo} lacks the optional permission {p.named()} ({p.serves}); sessions"
            f" start without it; fix: add {p.named()} to the App's permissions if it doesn't ask for it yet,"
            f" then the owner accepts it on the App's installation page {self.settings}"
            for p in missing(self.permissions, optional)
        )


def missing(granted: Mapping[str, Access], table: tuple[Permission, ...] = PERMISSIONS) -> list[Permission]:
    """The table's permissions the installation lacks, or grants only read where write is needed"""
    return [p for p in table if (have := granted.get(p.key)) is None or not have.covers(p.access)]


_ACCESS = {"read": Access.READ, "write": Access.WRITE, "admin": Access.WRITE}  # admin covers write


def _permissions(raw: object, path: str) -> dict[str, Access]:
    if not isinstance(raw, dict):
        raise ReleaseError(f"GET {path}: permissions is not an object")
    granted = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ReleaseError(f"GET {path}: permission {key!r} has access {value!r}, not a string")
        if value not in _ACCESS:
            raise ReleaseError(f"GET {path}: permission {key} has unknown access {value!r}")
        granted[key] = _ACCESS[value]
    return granted


class NotInstalled(AuthFailure):
    """The App has no installation on the repo, or its installation is suspended; the message
    is spec 004's, S-004-5"""


class Lacks(AuthFailure):
    """The App's installation on the repo lacks a permission the table asks for"""


def install_fix(repo: str) -> str:
    return f"{cli_command()} app-install {repo}"


def app_slug(app_id: int, token: str, api: Api) -> str:
    """The App's slug, from GET /app with its JWT"""
    app = _ok(api.get("/app", token), "/app", app_id)
    slug = app.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ReleaseError(f"GET /app for app_id {app_id} gave no slug")
    return slug


def installation(
    app_id: int, repo: str, token: str, api: Api, table: tuple[Permission, ...] = PERMISSIONS
) -> Installation:
    """Spec 004, At launch step 3: the App's slug, then its installation on repo, which must
    grant every permission in the table (a session's, unless another is given)"""
    return installed(app_id, app_slug(app_id, token, api), repo, token, api, table)


def installed(
    app_id: int, slug: str, repo: str, token: str, api: Api, table: tuple[Permission, ...] = PERMISSIONS
) -> Installation:
    """`installation` once the App's slug is known: its installation on repo, granting every
    permission in the table; NotInstalled and Lacks name the repo. A suspended installation is
    none (spec 048): it can't mint a token"""
    path = f"/repos/{repo}/installation"
    answer = api.get(path, token)
    if answer.status == 404:
        raise NotInstalled(f"app {slug} is not installed on {repo}", install_fix(repo))
    found = _ok(answer, path, app_id)
    number = found.get("id")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ReleaseError(f"GET {path} gave no installation id")
    if found.get("suspended_at") is not None:
        raise NotInstalled(f"app {slug}'s installation on {repo} is suspended", install_fix(repo))
    granted = _permissions(found.get("permissions"), path)
    page = found.get("html_url")
    found_installation = Installation(slug, number, granted, page if isinstance(page, str) and page else None)
    if lacking := missing(granted, table):
        names = ", ".join(p.named() for p in lacking)
        problem = f"app {slug} on {repo} lacks these permissions: {names}"
        fix = f"grant them in the App's settings, then accept them at {found_installation.settings}"
        raise Lacks(problem, fix, f"{problem}; {fix}")
    return found_installation


NOREPLY = "users.noreply.github.com"


@dataclass(frozen=True, slots=True)
class Identity:
    """Who a gated session writes as: the App's bot account, and the key its helpers mint with"""

    app_id: int
    slug: str
    bot_id: int  # the bot account's user id, not the App's id
    key: Path

    @property
    def login(self) -> str:
        return f"{self.slug}[bot]"

    @property
    def email(self) -> str:
        """The bot's noreply address, which GitHub links its commits to"""
        return f"{self.bot_id}+{self.login}@{NOREPLY}"


def bot_id(slug: str, app_id: int, api: Api, token: str | None) -> int:
    """Spec 004, At launch step 4: the user id of the App's bot account, read with token, an
    installation token, so the read counts against the App's own rate limit (#1034). None
    reads it anonymously, under GitHub's 60 an hour per IP that every gate on the host shares;
    the App's JWT is never given, since GitHub accepts it only on the App's own endpoints"""
    login = f"{slug}[bot]"
    path = f"/users/{urllib.parse.quote(login)}"
    answer = api.get(path, token)
    if answer.status == 404:
        raise ReleaseError(f"GitHub has no bot account {login} for app_id {app_id}")
    found = _ok(answer, path, app_id)
    number = found.get("id")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ReleaseError(f"GET {path} gave no user id")
    if found.get("login") != login:
        raise ReleaseError(f"GET {path} answered for {found.get('login')!r}, not {login}")
    return number


BOT_IDS = "bot-ids.json"  # in the gate's state folder: each App's slug and bot account id, by App id (#1034)


@dataclass(frozen=True, slots=True)
class BotIds:
    """#1034: where the App check keeps the bot account's id, and whether it may write there.
    The id never changes for an App, so the check reads it from GitHub once per App and slug;
    the gate writes, while a dry run, status, and factory only read"""

    path: Path
    write: bool

    def _malformed(self, reason: str) -> ReleaseError:
        fix = "delete it, and the next App check reads the id again"
        return ReleaseError(f"the bot id cache {self.path} is malformed ({reason}); {fix}")

    def load(self) -> dict[int, tuple[str, int]]:
        """Each App id's slug and bot id; none when there is no file. Malformed content raises
        naming the file rather than be trusted or silently replaced"""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_bytes())
        except json.JSONDecodeError, UnicodeDecodeError:
            raise self._malformed("not JSON") from None
        if not isinstance(data, dict):
            raise self._malformed("not a JSON object")
        found = {}
        for key, entry in data.items():
            if not key.isdecimal():
                raise self._malformed(f"key {key!r} is not an App id")
            if not isinstance(entry, dict):
                raise self._malformed(f"entry {key} is not an object")
            slug, number = entry.get("slug"), entry.get("bot_id")
            if not isinstance(slug, str) or not slug:
                raise self._malformed(f"entry {key}'s slug is not a non-empty string")
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                raise self._malformed(f"entry {key}'s bot_id is not a positive integer")
            found[int(key)] = (slug, number)
        return found

    def bot_id(self, slug: str, app_id: int, api: Api) -> int:
        """The cached id when its slug is the App's; else the id read anonymously (no token is
        minted, S-048-5), written back when this may write"""
        known = self.load()
        if (cached := known.get(app_id)) is not None and cached[0] == slug:
            return cached[1]
        number = bot_id(slug, app_id, api, None)
        if self.write:
            known[app_id] = (slug, number)
            record = {str(k): {"slug": s, "bot_id": n} for k, (s, n) in known.items()}
            write_atomic(self.path, (json.dumps(record, indent=2) + "\n").encode(), 0o644)
        return number


AppCheck = Callable[[int], Identity]


def _no_product() -> tuple[str, ...]:
    return ()


def app_check(
    repo: str,
    key: Path | None,
    home: Path,
    signer: Signer,
    api: Api,
    product: Callable[[], tuple[str, ...]] = _no_product,
    clock: Clock = utc_now,
    bots: BotIds | None = None,
) -> AppCheck:
    """The gate's App check for repo, spec 004's At launch steps 1 to 4: the key (`--app-key`,
    else the default path for the App's id), the JWT, the installation, then the bot account.
    In the product's home repo (S-038-7) product gives the config's `[product] repos`, and the
    App must be installed on each with PRODUCT_PERMISSIONS before any session starts.
    The JWT is signed with clock's time when the check runs, never the tick's start, which a
    slow prune can put past VALID_FOR (#694).
    The bot account's id comes from bots, the state folder's cache, when it holds the App's
    slug, and is read from GitHub only on a miss (#1034); None reads it on every check.
    Any failure raises ReleaseError (exit 2). It writes only the cache, and only when bots
    may write, so a dry run runs it too and writes nothing"""

    def check(app_id: int) -> Identity:
        path = check_key(key if key is not None else default_key(app_id, home))
        bearer = jwt(app_id, path, clock(), signer)
        found = installation(app_id, repo, bearer, api)
        for listed in product():
            installed(app_id, found.slug, listed, bearer, api, PRODUCT_PERMISSIONS)
        # anonymous on a miss: the check mints no token (S-048-5), so a rate limit reads as a wait
        number = bot_id(found.slug, app_id, api, None) if bots is None else bots.bot_id(found.slug, app_id, api)
        return Identity(app_id, found.slug, number, path)

    return check


AppLogin = Callable[[int, Path], str]


def app_login(signer: Signer, api: Api, clock: Clock = utc_now) -> AppLogin:
    """The App's bot login, `<slug>[bot]`, with the key at the path: the JWT and GET /app
    alone, one GitHub call, without the full check's installation and bot account reads
    (#311). Whose needs-decision questions are the gate's (D-21), whether or not the App is
    installed and granted today; any failure raises ReleaseError. The JWT is signed with
    clock's time at the call (#694)"""

    def login(app_id: int, key: Path) -> str:
        return f"{app_slug(app_id, jwt(app_id, check_key(key), clock(), signer), api)}[bot]"

    return login


CACHE = "app-token.json"  # in the gate's state folder, `$(git rev-parse --git-common-dir)/shipmill`
REUSE_FOR = dt.timedelta(minutes=10)  # a cached token is reused while it has at least this long left


def repo_name(repo: str) -> str:
    """The name in owner/name, which the token is limited to"""
    owner, slash, name = repo.partition("/")
    if not owner or not slash or not name or "/" in name:
        raise ReleaseError(f"the repo is owner/name, such as romamo/demo; got {repo!r}")
    return name


_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")  # the characters GitHub allows in an owner or a repo name


def _plain(part: str) -> bool:
    """One plain folder name: GitHub's characters, never `.` or `..`"""
    return part not in {".", ".."} and _SEGMENT.fullmatch(part) is not None


def is_plain_repo(repo: str) -> bool:
    """repo is owner/name by `repo_name`'s rule, each part a plain name by the cache's rule"""
    owner, slash, name = repo.partition("/")
    return bool(owner and slash and name) and "/" not in name and _plain(owner) and _plain(name)


def cache_outside(repo: str, environ: Mapping[str, str], home: Path) -> Path:
    """Spec 012: the token cache with no git checkout, `$XDG_CACHE_HOME/shipmill/<owner>/<repo>/`
    (`~/.cache` when XDG_CACHE_HOME is unset or empty). Each part of the repo is one plain
    folder name, so the path never leaves the cache folder"""
    name = repo_name(repo)
    owner = repo.partition("/")[0]
    if not is_plain_repo(repo):
        raise ReleaseError(f"the repo is owner/name of letters, digits, '.', '-', or '_'; got {repo!r}")
    base = environ.get("XDG_CACHE_HOME", "")
    folder = Path(base) if base else home / ".cache"
    if not folder.is_absolute():
        raise ReleaseError(f"XDG_CACHE_HOME must be an absolute path, got {base!r}")
    return folder / "shipmill" / owner / name / CACHE


@dataclass(frozen=True, slots=True)
class Token:
    """An installation token for one repository; repr leaves the value out"""

    value: str = field(repr=False)
    expires: dt.datetime
    repo: str
    app_id: int
    notices: tuple[str, ...] = field(default=(), compare=False)  # D-77: the optional permissions it went without

    def reusable(self, repo: str, app_id: int, now: dt.datetime) -> bool:
        return self.repo.lower() == repo.lower() and self.app_id == app_id and self.expires - now >= REUSE_FOR


def _malformed(path: Path, reason: str) -> ReleaseError:
    return ReleaseError(f"the App token cache {path} is malformed ({reason}); delete it to mint a new token")


def _expiry(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def load_token(path: Path) -> Token | None:
    """The cached token, or None when there is no cache; a malformed one raises naming it.
    No message quotes the file, which holds the token"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_bytes())
    except json.JSONDecodeError, UnicodeDecodeError:
        raise _malformed(path, "not JSON") from None
    if not isinstance(data, dict):
        raise _malformed(path, "not a JSON object")
    value, repo, app_id = data.get("token"), data.get("repository"), data.get("app_id")
    if not isinstance(value, str) or not value:
        raise _malformed(path, "token is not a non-empty string")
    if not isinstance(repo, str) or not repo:
        raise _malformed(path, "repository is not a non-empty string")
    if not isinstance(app_id, int) or isinstance(app_id, bool):
        raise _malformed(path, "app_id is not an integer")
    expires = _expiry(data.get("expires_at"))
    if expires is None:
        raise _malformed(path, "expires_at is not an ISO time with an offset")
    return Token(value, expires, repo, app_id)


def write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Write path through a sibling created with mode (never wider, so no chmod follows) and
    renamed over it, so a reader sees the old file or the new one, never part of one"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    done = False
    try:
        with os.fdopen(descriptor, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        done = True
    finally:
        if not done:
            temporary.unlink(missing_ok=True)


def save_token(path: Path, token: Token) -> None:
    """Cache the token with mode 0600; two helpers minting at once each write a whole, valid
    token, and the later rename wins"""
    record = {
        "app_id": token.app_id,
        "repository": token.repo,
        "expires_at": token.expires.isoformat(),
        "token": token.value,
    }
    write_atomic(path, (json.dumps(record, indent=2) + "\n").encode(), 0o600)


def _scope(data: Mapping[str, object], repo: str, path: str) -> None:
    """D-14: the token must be limited to the gate's repo, as asked"""
    repos = data.get("repositories")
    if not isinstance(repos, list) or len(repos) != 1:
        raise ReleaseError(f"POST {path} gave a token not limited to {repo}; refusing it")
    only = repos[0]
    full = only.get("full_name") if isinstance(only, dict) else None
    if not isinstance(full, str) or full.lower() != repo.lower():
        raise ReleaseError(f"POST {path} gave a token for another repository than {repo}; refusing it")


def mint(
    app_id: int,
    repo: str,
    key: Path,
    now: dt.datetime,
    signer: Signer,
    api: Api,
    table: tuple[Permission, ...] = PERMISSIONS,
    optional: tuple[Permission, ...] = (),
) -> Token:
    """Spec 004, Tokens: an installation token limited to repo and the table's permissions (a
    session's, unless another is given), plus each optional one the installation grants (D-77):
    GitHub refuses a token asking for a permission the installation hasn't accepted, so one it
    lacks is never asked for, only named in the token's notices"""
    name = repo_name(repo)
    bearer = jwt(app_id, check_key(key), now, signer)
    found = installation(app_id, repo, bearer, api, table)
    path = f"/app/installations/{found.id}/access_tokens"
    asked = table + found.grants(optional)
    body = {"repositories": [name], "permissions": {p.key: str(p.access) for p in asked}}
    answer = api.post(path, bearer, body)
    # _ok names a 401 (the JWT's), a 5xx, and a rate limit
    if answer.status not in (201, 401) and not unavailable(answer.status) and not rate_limited(answer):
        problem = f"POST {path} for app_id {app_id} answered {answer.status}: {answer.body.strip()[:300]}"
        raise MintRefused(problem, install_fix(repo))
    data = _ok(answer, path, app_id, "POST", 201)
    value = data.get("token")
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ReleaseError(f"POST {path} gave no token")
    expires = _expiry(data.get("expires_at"))
    if expires is None:
        raise ReleaseError(f"POST {path} gave no expires_at with an offset")
    _scope(data, repo, path)
    return Token(value, expires, repo, app_id, found.notices(repo, optional))


def app_token(cache: Path, repo: str, app_id: int, key: Path, now: dt.datetime, signer: Signer, api: Api) -> str:
    """The cached token while it has at least 10 minutes left by this host's clock, else a new
    one, cached. GitHub's expiry is an hour out, so the margin also absorbs a host clock up to
    10 minutes behind GitHub's"""
    repo_name(repo)
    cached = load_token(cache)
    if cached is not None and cached.reusable(repo, app_id, now):
        return cached.value
    fresh = mint(app_id, repo, key, now, signer, api, PERMISSIONS, OPTIONAL_PERMISSIONS)
    save_token(cache, fresh)
    return fresh.value


def product_cache(owner: str) -> str:
    """Spec 038: the product token's cache for owner's repos, beside the session's `app-token.json`
    in the state folder and never the same file"""
    if not _plain(owner):
        raise ReleaseError(f"the owner is letters, digits, '.', '-', or '_'; got {owner!r}")
    return f"app-token-product-{owner.lower()}.json"


def with_home(repos: tuple[str, ...], home: str | None) -> tuple[str, ...]:
    """S-038-8, #1032: the repos one product token covers: one owner's listed repos, plus the
    home repo when it has their owner and isn't among them, so the token sees both ends of a
    home-repo report and a listed repo's issue under it. A home of another owner, or one that
    can't be told, adds nothing: one installation token never spans owners"""
    if home is None or not repos:
        return repos
    owner = repos[0].partition("/")[0].lower()
    if home.partition("/")[0].lower() != owner or any(r.lower() == home.lower() for r in repos):
        return repos
    return (*repos, home)


def _same_repos(one: tuple[str, ...], other: tuple[str, ...]) -> bool:
    return sorted(r.lower() for r in one) == sorted(r.lower() for r in other)


@dataclass(frozen=True, slots=True)
class ProductToken:
    """The coordinator's token over one owner's listed repos (spec 038); repr leaves the value out"""

    value: str = field(repr=False)
    expires: dt.datetime
    repos: tuple[str, ...]
    app_id: int

    def reusable(self, repos: tuple[str, ...], app_id: int, now: dt.datetime) -> bool:
        """S-038-8: the same App, the very repos asked (the config's, with the home of the same
        owner), and at least 10 minutes left"""
        return self.app_id == app_id and _same_repos(self.repos, repos) and self.expires - now >= REUSE_FOR


def load_product_token(path: Path) -> ProductToken | None:
    """The cached product token, or None when there is none; a malformed one raises naming it.
    No message quotes the file, which holds the token"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_bytes())
    except json.JSONDecodeError, UnicodeDecodeError:
        raise _malformed(path, "not JSON") from None
    if not isinstance(data, dict):
        raise _malformed(path, "not a JSON object")
    value, repos, app_id = data.get("token"), data.get("repositories"), data.get("app_id")
    if not isinstance(value, str) or not value:
        raise _malformed(path, "token is not a non-empty string")
    if not isinstance(repos, list) or not repos or not all(isinstance(r, str) and is_plain_repo(r) for r in repos):
        raise _malformed(path, "repositories is not a non-empty list of owner/name")
    if not isinstance(app_id, int) or isinstance(app_id, bool):
        raise _malformed(path, "app_id is not an integer")
    expires = _expiry(data.get("expires_at"))
    if expires is None:
        raise _malformed(path, "expires_at is not an ISO time with an offset")
    return ProductToken(value, expires, tuple(repos), app_id)


def save_product_token(path: Path, token: ProductToken) -> None:
    """Cache the product token with mode 0600, written whole as `save_token` writes"""
    record = {
        "app_id": token.app_id,
        "repositories": list(token.repos),
        "expires_at": token.expires.isoformat(),
        "token": token.value,
    }
    write_atomic(path, (json.dumps(record, indent=2) + "\n").encode(), 0o600)


@dataclass(frozen=True, slots=True)
class _Kind:
    """Which of the tokens over several repos is minted: its permissions, and whose it is, as a
    refusal names it"""

    table: tuple[Permission, ...]
    whose: str


_PRODUCT = _Kind(PRODUCT_PERMISSIONS, "the coordinator asks (D-47)")
_READ = _Kind(READ_PERMISSIONS, "a component's read token asks (D-84)")


def _product_scope(data: Mapping[str, object], repos: tuple[str, ...], path: str, kind: _Kind = _PRODUCT) -> None:
    """S-038-6, S-065-4, mirroring `_scope`: GitHub's answer covers exactly the asked repos and
    grants no permission broader than the kind's table (a key not asked, write where read was,
    or admin)"""
    listed = data.get("repositories")
    names: list[str] = []
    if isinstance(listed, list):
        for each in listed:
            full = each.get("full_name") if isinstance(each, dict) else None
            if not isinstance(full, str):
                raise ReleaseError(f"POST {path} gave a repository with no full_name; refusing the token")
            names.append(full)
    asked = ", ".join(repos)
    if not isinstance(listed, list) or len(names) != len(repos) or not _same_repos(tuple(names), repos):
        raise ReleaseError(f"POST {path} gave a token for other repositories than {asked}; refusing it")
    granted = data.get("permissions")
    if not isinstance(granted, dict):
        raise ReleaseError(f"POST {path} gave a token without its permissions; refusing it")
    table = {p.key: p.access for p in kind.table}
    for key, value in granted.items():
        access = _ACCESS.get(value) if isinstance(value, str) else None
        wanted = table.get(key) if isinstance(key, str) else None
        if access is None or wanted is None or not wanted.covers(access) or value == "admin":
            raise ReleaseError(f"POST {path} gave a token with {key}: {value}, broader than {kind.whose}; refusing it")


def mint_product(
    app_id: int, repos: tuple[str, ...], key: Path, now: dt.datetime, signer: Signer, api: Api, kind: _Kind = _PRODUCT
) -> ProductToken:
    """Spec 038: one installation token over repos, all of one owner, asking PRODUCT_PERMISSIONS
    (spec 065: READ_PERMISSIONS for a component's read token). Each repo's installation must
    grant them (NotInstalled and Lacks name the repo), and all must be the one installation of
    the App on that owner"""
    owners = {r.partition("/")[0].lower() for r in repos}
    if not repos or len(owners) != 1 or not all(is_plain_repo(r) for r in repos):
        raise ReleaseError(f"a product token covers owner/name repos of one owner; got {', '.join(repos) or 'none'}")
    bearer = jwt(app_id, check_key(key), now, signer)
    slug = app_slug(app_id, bearer, api)
    ids = {installed(app_id, slug, repo, bearer, api, kind.table).id for repo in repos}
    if len(ids) != 1:
        raise ReleaseError(f"app {slug} has more than one installation over {', '.join(repos)}; refusing the token")
    path = f"/app/installations/{ids.pop()}/access_tokens"
    body = {
        "repositories": [repo_name(r) for r in repos],
        "permissions": {p.key: str(p.access) for p in kind.table},
    }
    data = _ok(api.post(path, bearer, body), path, app_id, "POST", 201)
    value = data.get("token")
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ReleaseError(f"POST {path} gave no token")
    expires = _expiry(data.get("expires_at"))
    if expires is None:
        raise ReleaseError(f"POST {path} gave no expires_at with an offset")
    _product_scope(data, repos, path, kind)
    return ProductToken(value, expires, repos, app_id)


def product_token(
    cache: Path, repos: tuple[str, ...], app_id: int, key: Path, now: dt.datetime, signer: Signer, api: Api
) -> str:
    """S-038-8: the cached product token while it has 10 minutes left and covers the very repos
    asked (`with_home`'s), else a new one, cached only once its scope checks out; a token cached
    before the home joined them no longer matches, so it is minted again"""
    cached = load_product_token(cache)
    if cached is not None and cached.reusable(repos, app_id, now):
        return cached.value
    fresh = mint_product(app_id, repos, key, now, signer, api)
    save_product_token(cache, fresh)
    return fresh.value


def read_cache(owner: str) -> str:
    """Spec 065: a component's read token's cache for owner's repos, beside the session's
    `app-token.json` and the coordinator's `app-token-product-<owner>.json`, never either"""
    if not _plain(owner):
        raise ReleaseError(f"the owner is letters, digits, '.', '-', or '_'; got {owner!r}")
    return f"app-token-read-{owner.lower()}.json"


def cached_read_token(cache: Path, needed: tuple[str, ...], app_id: int, now: dt.datetime) -> ProductToken | None:
    """S-065-5: the cached read token while the same App minted it, it has at least 10 minutes
    left, and it covers every repo needed; else None. The home's list isn't read for it, so a
    repo the home drops stays readable until the token expires"""
    cached = load_product_token(cache)
    if cached is None or cached.app_id != app_id or cached.expires - now < REUSE_FOR:
        return None
    covered = {r.lower() for r in cached.repos}
    return cached if all(r.lower() in covered for r in needed) else None


def mint_read(
    app_id: int, repos: tuple[str, ...], key: Path, now: dt.datetime, signer: Signer, api: Api
) -> ProductToken:
    """Spec 065: one installation token over repos, all of one owner, asking READ_PERMISSIONS;
    refused, never returned, when GitHub's answer covers other repos or grants more (S-065-4)"""
    return mint_product(app_id, repos, key, now, signer, api, _READ)


def contents(repo: str, file: str, token: str, api: Api) -> str | None:
    """A file's text on repo's default branch, read with an installation token (spec 038's
    doctor reads a component's config with the product token); None when GitHub has no such
    file. No message quotes the token"""
    path = f"/repos/{repo}/contents/{urllib.parse.quote(file)}"
    answer = api.get(path, token)
    if answer.status == 404:
        return None
    if answer.status != 200:
        raise ReleaseError(f"GET {path} answered {answer.status}: {answer.body.strip()[:300]}")
    data = _json(answer, path)
    content = data.get("content")
    if data.get("type") != "file" or data.get("encoding") != "base64" or not isinstance(content, str):
        raise ReleaseError(f"GET {path} gave no file's base64 content")
    try:
        return base64.b64decode(content).decode("utf-8")
    except binascii.Error, UnicodeDecodeError:
        raise ReleaseError(f"GET {path} gave content that is not base64 of UTF-8 text") from None


CREDENTIAL_HOST = "github.com"


def credential(operation: str, request: str, token: Callable[[], str]) -> str:
    """git-credential(1)'s helper protocol. get answers an https request for github.com with
    the App's token as x-access-token, and anything else with nothing, so git asks its next
    helper; store, erase, and any other operation are ignored, as the protocol asks"""
    if operation != "get":
        return ""
    asked: dict[str, str] = {}
    for line in request.splitlines():
        if not line:
            break
        key, equals, value = line.partition("=")
        if not equals or not key:
            raise ReleaseError("git sent a credential request line that is not key=value")
        asked[key] = value
    if asked.get("protocol") != "https" or asked.get("host") != CREDENTIAL_HOST:
        return ""
    return f"username=x-access-token\npassword={token()}\n"


HELPERS = "bin"  # in the gate's state folder, next to the token cache
GH_HELPER = "gh"
CREDENTIAL_HELPER = "git-credential-shipmill"


@dataclass(frozen=True, slots=True)
class Helpers:
    folder: Path  # goes first on a session's PATH
    gh: Path
    git_credential: Path
    real_gh: Path  # the gh the gh helper runs


def resolve_gh(folder: Path, path: str) -> Path:
    """The gh on path, skipping the helpers' folder, so the gh helper never runs itself. It
    keeps the path as PATH names it, made absolute, not its symlink's target: Homebrew's gh
    links into a versioned folder that `brew upgrade` deletes mid-session (#1015)"""
    mine = folder.resolve()
    rest = [entry for entry in path.split(os.pathsep) if entry and Path(entry).resolve() != mine]
    found = shutil.which("gh", path=os.pathsep.join(rest))
    if found is None:
        raise ReleaseError("gh not found on PATH; the session's gh helper runs it with the App's token")
    return Path(found).absolute()


def write_helpers(folder: Path, python: Path, checkout: Path, repo: str, app_id: int, key: Path, path: str) -> Helpers:
    """Spec 004, Tokens: write the session's gh and git credential helpers, mode 0700. Each
    runs `<python> -m shipmill app-token` with the App's id, key, repo, and checkout as
    arguments; neither holds a token"""
    repo_name(repo)
    real_gh = resolve_gh(folder, path)
    command = shlex.join(
        [
            str(python),
            "-m",
            "shipmill",
            "--repo",
            str(checkout.resolve()),
            "app-token",
            repo,
            "--app-id",
            str(app_id),
            "--app-key",
            str(key.resolve()),
        ]
    )
    header = "#!/bin/sh\n# Written by shipmill gate (spec 004). It holds no token: each call mints or reuses one.\n"
    gh = (
        header
        + f"token=$({command}) || exit $?\n"
        + "GH_TOKEN=$token\nexport GH_TOKEN\nunset token\n"
        + f'exec {shlex.quote(str(real_gh))} "$@"\n'
    )
    credential_helper = header + f'exec {command} --git-credential "$1"\n'
    helpers = Helpers(folder, folder / GH_HELPER, folder / CREDENTIAL_HELPER, real_gh)
    write_atomic(helpers.gh, gh.encode(), 0o700)
    write_atomic(helpers.git_credential, credential_helper.encode(), 0o700)
    return helpers


CREDENTIAL_KEY = "credential.https://github.com.helper"
INSTEAD_OF = "url.https://github.com/.insteadOf"
SSH_REMOTES = ("git@github.com:", "ssh://git@github.com/")  # sent over https, so a push goes through the App


def _helper_value(helper: Path) -> str:
    """credential.helper's value for an absolute path: git runs it through the shell, so a
    path that needs quoting goes in as a `!` shell command"""
    quoted = shlex.quote(str(helper))
    return quoted if quoted == str(helper) else f"!{quoted}"


def session_env(identity: Identity, helpers: Helpers, path: str) -> dict[str, str]:
    """Spec 004, At launch step 5: the env a session's `--settings` carries. The helpers'
    folder goes first on PATH, the git author and committer are the App's bot, and git's
    config, through GIT_CONFIG_*, drops the host's credential helpers for github.com, adds
    the App's, and sends SSH remotes over https. SHIPMILL_APP_KEY names the key's absolute path,
    so the delivery hooks and the skills read the App as available in the session, and
    `shipmill gh` finds the key the gate used (spec 033). It holds no token"""
    config = [
        (CREDENTIAL_KEY, ""),
        (CREDENTIAL_KEY, _helper_value(helpers.git_credential)),
        *((INSTEAD_OF, remote) for remote in SSH_REMOTES),
    ]
    env = {
        "PATH": os.pathsep.join([str(helpers.folder), path]) if path else str(helpers.folder),
        "GIT_AUTHOR_NAME": identity.login,
        "GIT_AUTHOR_EMAIL": identity.email,
        "GIT_COMMITTER_NAME": identity.login,
        "GIT_COMMITTER_EMAIL": identity.email,
        "GIT_CONFIG_COUNT": str(len(config)),
    }
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    env[APP_KEY] = str(identity.key.resolve())
    return env


def prepare_session(
    identity: Identity, folder: Path, python: Path, checkout: Path, repo: str, path: str
) -> dict[str, str]:
    """Write the session's helpers to folder, then give the env that puts them to work.
    python is the gate's own interpreter, so the helpers run the same shipmill"""
    helpers = write_helpers(folder.resolve(), python, checkout, repo, identity.app_id, identity.key, path)
    return session_env(identity, helpers, path)
