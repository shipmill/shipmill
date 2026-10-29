"""The gate's GitHub preflight (spec 048): before a launch, whether the identity a session
writes as can reach the repo.

With `[agents] app_id` set the preflight mints an installation token for the repo, with the
session's permission table, and reads `GET /repos/<repo>` with it; the token is never printed
or cached (`mint`, not `app_token`), so a dry run writes nothing. Without an App it reads
`gh api repos/<repo>` as the host's gh login. Any failure is the verdict's (spec 048: "Any
failure is GITHUB_AUTH"): one the GITHUB_AUTH table names reads its problem and fix; any other
shipmill error, such as GitHub being unreachable or an answer shipmill refuses, reads its first
line, naming the identity and the repo, with the table's last fix.
"""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shipmill.app import Api, AuthFailure, Clock, Identity, Signer, install_fix, mint, utc_now
from shipmill.errors import ReleaseError

HOST_FIX = "gh auth login"
# with gh missing, logging in can't help: the gate's PATH needs it (launchd builds that PATH)
GH_MISSING_FIX = "install the GitHub CLI (https://cli.github.com), then rerun shipmill launchd"
TIMEOUT = 60  # seconds `gh api repos/<repo>` may take

HostRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]  # (command, cwd) -> its result


def first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


@dataclass(frozen=True, slots=True)
class GitHubAuth:
    """The preflight's verdict: problem None when the identity reaches the repo, else what
    failed, with its fix"""

    problem: str | None
    fix: str | None = None

    def __post_init__(self) -> None:
        if (self.problem is None) != (self.fix is None):
            raise ValueError("a GitHub preflight verdict has a problem and a fix, or neither")

    @classmethod
    def of(cls, failure: AuthFailure) -> GitHubAuth:
        """A failure the GITHUB_AUTH table names: its problem and fix"""
        return cls(failure.problem, failure.fix)

    @classmethod
    def unnamed(cls, error: ReleaseError, who: str, repo: str, fix: str) -> GitHubAuth:
        """Any other failure: its first line, naming who couldn't reach repo, with the fix given"""
        return cls(f"{who} can't reach {repo}: {first_line(error)}", fix)

    @classmethod
    def app_failed(cls, error: ReleaseError, app_id: int, repo: str) -> GitHubAuth:
        """The App's failure, the table's row when it names one, else its last row's fix"""
        if isinstance(error, AuthFailure):
            return cls.of(error)
        return cls.unnamed(error, f"the App {app_id}", repo, install_fix(repo))

    @property
    def ok(self) -> bool:
        return self.problem is None

    def reason(self) -> str:
        """A GITHUB_AUTH tick's reason, ending with the fix after "fix: " """
        return f"{self.problem}: no session starts; fix: {self.fix}"


GitHubPreflight = Callable[[Identity | None], GitHubAuth]  # the App's identity, or None for the host's login


def app_reach(identity: Identity, repo: str, signer: Signer, api: Api, clock: Clock = utc_now) -> GitHubAuth:
    """Mint the session's token for repo, then read the repo with it; the token goes nowhere else.
    The API's own failures (unreachable, an answer that isn't JSON) are ReleaseErrors"""
    path = f"/repos/{repo}"
    try:
        token = mint(identity.app_id, repo, identity.key, clock(), signer, api)
        answer = api.get(path, token.value)
    except ReleaseError as exc:
        return GitHubAuth.app_failed(exc, identity.app_id, repo)
    if answer.status == 200:
        return GitHubAuth(None)
    said = f"GET {path} answered {answer.status}: {answer.body.strip()[:300]}"
    return GitHubAuth(f"the token of {identity.login} can't read {repo} ({said})", install_fix(repo))


def run_host(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=TIMEOUT)


def host_reach(repo: str, cwd: Path, run: HostRunner = run_host) -> GitHubAuth:
    """`gh api repos/<repo>` as the host's gh login; only its exit code and the first line of
    its stderr are ever shown"""
    cmd = ["gh", "api", f"repos/{repo}"]
    who = "the host's gh login"
    try:
        proc = run(cmd, cwd)
    except FileNotFoundError:
        return GitHubAuth(f"gh isn't on PATH, so {who} can't read {repo}", GH_MISSING_FIX)
    except OSError as exc:  # gh found but not runnable
        return GitHubAuth.unnamed(ReleaseError(f"gh can't run: {exc}"), who, repo, HOST_FIX)
    except subprocess.TimeoutExpired:
        return GitHubAuth.unnamed(
            ReleaseError(f"gh api repos/{repo} didn't answer in {TIMEOUT} s"), who, repo, HOST_FIX
        )
    if proc.returncode == 0:
        return GitHubAuth(None)
    lines = proc.stderr.strip().splitlines()
    said = f": {lines[0][:200]}" if lines else ""
    problem = f"{who} can't read {repo} (gh api repos/{repo} exited {proc.returncode}{said})"
    return GitHubAuth(problem, HOST_FIX)


def github_auth(
    repo: str, cwd: Path, signer: Signer, api: Api, run: HostRunner = run_host, clock: Clock = utc_now
) -> GitHubPreflight:
    """The preflight the gate asks on a LAUNCH: as the App when it has one (D-14: never as the
    host's login then), else as the host's gh login"""

    def ask(identity: Identity | None) -> GitHubAuth:
        return host_reach(repo, cwd, run) if identity is None else app_reach(identity, repo, signer, api, clock)

    return ask
