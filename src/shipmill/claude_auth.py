"""Whether Claude Code can authenticate on this host (#500): the gate's preflight before a
launch, and a line in doctor.

`claude auth status --json` prints a JSON object whose boolean `loggedIn` says whether a login
is stored. The preflight fails when it is false, when the command exits non-zero, when its
output has no boolean `loggedIn`, and when claude isn't on PATH. It never prints the command's
output: only its exit code and the first line of its stderr, cut short.

With a token file (spec 035) the command runs in the env a session gets, the token in it, and
must also name the environment token as its `authMethod` when it names one; every fix then
names the file and `claude setup-token`.
"""

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from shipmill.claude_token import Token, rejected_fix, session_env

COMMAND = ["claude", "auth", "status", "--json"]
FIX = "claude auth login"
MISSING = "claude isn't on PATH"
# with claude missing, logging in can't help: the gate's PATH needs it (launchd builds that PATH)
MISSING_FIX = "install claude, then rerun shipmill launchd"
TOKEN_METHOD = "oauth_token"  # the authMethod `claude auth status --json` names for CLAUDE_CODE_OAUTH_TOKEN

AuthRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]  # the command -> its result
EnvAuthRunner = Callable[[list[str], Mapping[str, str]], subprocess.CompletedProcess[str]]  # with its env


@dataclass(frozen=True, slots=True)
class ClaudeAuth:
    """The preflight's verdict: problem None when Claude Code is logged in, else what is
    wrong; missing when claude isn't on PATH, which doctor warns about and the gate refuses;
    token, the token file the verdict is about (spec 035), None for the login; remedy, a fix
    that replaces the computed one, as a refused token file's"""

    problem: str | None
    missing: bool = False
    token: Path | None = None
    remedy: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None

    @property
    def fix(self) -> str:
        if self.remedy is not None:
            return self.remedy
        if self.missing:
            return MISSING_FIX
        return FIX if self.token is None else rejected_fix(self.token)

    def line(self) -> str:
        """doctor's detail: the pass, or the problem and its fix"""
        if self.problem is None:
            if self.token is not None:
                return f"Claude Code accepts the token in {self.token} (claude auth status)"
            return "Claude Code is logged in on this host (claude auth status)"
        if self.missing:
            return f"{self.problem}, so no session can start here and its login can't be read"
        return f"{self.problem}: {self.fix}"

    def reason(self) -> str:
        """A CLAUDE_AUTH tick's reason, ending with the fix after "fix: " """
        return f"Claude Code can't authenticate on this host ({self.problem}): no session starts; fix: {self.fix}"

    def record(self) -> dict[str, object]:
        return {"ok": self.ok, "problem": self.problem, "fix": None if self.ok else self.fix}


def parse_auth(proc: subprocess.CompletedProcess[str]) -> ClaudeAuth:
    """The verdict from `claude auth status --json`'s exit code and output"""
    try:
        found = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        found = None
    logged_in = found.get("loggedIn") if isinstance(found, dict) else None
    if logged_in is False:
        return ClaudeAuth("claude auth status says not logged in")
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()
        said = f": {lines[0][:200]}" if lines else ""
        return ClaudeAuth(f"claude auth status exited {proc.returncode}{said}")
    if logged_in is not True:
        return ClaudeAuth("claude auth status --json printed no loggedIn true or false")
    return ClaudeAuth(None)


def parse_token_auth(proc: subprocess.CompletedProcess[str], token: Path) -> ClaudeAuth:
    """parse_auth's verdict for a run with the token in its env: a pass must also name the
    environment token when its JSON names an auth method, not the stored login"""
    found = parse_auth(proc)
    if not found.ok:
        return ClaudeAuth(found.problem, token=token)
    reply = json.loads(proc.stdout)
    method = reply.get("authMethod")
    if method is not None and method != TOKEN_METHOD:
        shown = method[:40] if isinstance(method, str) else type(method).__name__
        return ClaudeAuth(f"claude auth status names auth method {shown!r}, not the token", token=token)
    return ClaudeAuth(None, token=token)


def run_auth(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)


def run_auth_in(cmd: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60, env=dict(env))


def claude_auth(run: AuthRunner = run_auth, program: str | None = "claude") -> ClaudeAuth:
    """The preflight: `claude auth status --json`, read by parse_auth; program is claude's path
    on the PATH a session gets, None when it isn't there"""
    if program is None:
        return ClaudeAuth(MISSING, missing=True)
    try:
        proc = run([program, *COMMAND[1:]])
    except FileNotFoundError:
        return ClaudeAuth(MISSING, missing=True)
    except subprocess.TimeoutExpired:
        return ClaudeAuth("claude auth status didn't answer in 60 s")
    return parse_auth(proc)


def token_auth(
    token: Token,
    run: EnvAuthRunner = run_auth_in,
    program: str | None = "claude",
    environ: Mapping[str, str] = os.environ,
) -> ClaudeAuth:
    """Spec 035's preflight with a token file: `claude auth status --json` in the env a session
    gets (the token in, ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN out), read by parse_token_auth"""
    if program is None:
        return ClaudeAuth(MISSING, missing=True, token=token.path)
    try:
        proc = run([program, *COMMAND[1:]], session_env(environ, token))
    except FileNotFoundError:
        return ClaudeAuth(MISSING, missing=True, token=token.path)
    except subprocess.TimeoutExpired:
        return ClaudeAuth("claude auth status didn't answer in 60 s", token=token.path)
    return parse_token_auth(proc, token.path)


def preflight_auth(
    environ: Mapping[str, str],
    program: str | None,
    run: AuthRunner = run_auth,
    run_in: EnvAuthRunner = run_auth_in,
) -> Callable[[Token | None], ClaudeAuth]:
    """The preflight the gate and doctor ask with the credential they read: #500's without a
    token, spec 035's with one"""

    def ask(token: Token | None) -> ClaudeAuth:
        return claude_auth(run, program) if token is None else token_auth(token, run_in, program, environ)

    return ask
