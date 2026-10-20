"""Whether Claude Code can authenticate on this host (#500): the gate's preflight before a
launch, and a line in doctor.

`claude auth status --json` prints a JSON object whose boolean `loggedIn` says whether a login
is stored. The preflight fails when it is false, when the command exits non-zero, when its
output has no boolean `loggedIn`, and when claude isn't on PATH. It never prints the command's
output: only its exit code and the first line of its stderr, cut short.
"""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

COMMAND = ["claude", "auth", "status", "--json"]
FIX = "claude auth login"
MISSING = "claude isn't on PATH"
# with claude missing, logging in can't help: the gate's PATH needs it (launchd builds that PATH)
MISSING_FIX = "install claude, then rerun shipmill launchd"

AuthRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]  # the command -> its result


@dataclass(frozen=True, slots=True)
class ClaudeAuth:
    """The preflight's verdict: problem None when Claude Code is logged in, else what is
    wrong; missing when claude isn't on PATH, which doctor warns about and the gate refuses"""

    problem: str | None
    missing: bool = False

    @property
    def ok(self) -> bool:
        return self.problem is None

    @property
    def fix(self) -> str:
        return MISSING_FIX if self.missing else FIX

    def line(self) -> str:
        """doctor's detail: the pass, or the problem and its fix"""
        if self.problem is None:
            return "Claude Code is logged in on this host (claude auth status)"
        if self.missing:
            return f"{self.problem}, so no session can start here and its login can't be read"
        return f"{self.problem}: {FIX}"

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


def run_auth(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)


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
