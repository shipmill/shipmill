"""The delivery hooks' self-test (spec 026, S-026-15, S-026-16): run the PreToolUse hook of the
shipmill@shipmill install a session in a checkout would load (D-35, plugin.effective) on a
refused input, and expect its refusal.

The test reads that install's hooks/hooks.json, runs the command it declares for Bash through
a shell, as Claude Code does, with CLAUDE_PLUGIN_ROOT set to the install's folder and a
PreToolUse input for `gh pr merge 1 --rebase` on stdin, and passes only when the hook exits 2
with its rebase-merge refusal. The command is only shown to the hook, never run. Before that
it fails, each with its fix, when a Claude Code settings file sets disableAllHooks, when uv
isn't on PATH, when no install applies to the checkout, or when the install has no
hooks/hooks.json (one older than spec 026). Any other exit, including the 1 of a hook that
can't start its script (D-40), fails with the hook's stderr.
"""

import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.plugin import PLUGIN, Runner, effective, listed_installs, session_project, update_command

REFUSED = "gh pr merge 1 --rebase"  # what the hook is shown; rebase-merge refuses it in every repo with [agents]
REFUSAL = "shipmill hook rebase-merge: "  # the refusal's first line starts so
SETTINGS = (Path(".claude") / "settings.json", Path(".claude") / "settings.local.json")  # project, then local
DEFAULT_TIMEOUT = 60  # Claude Code's, for a hook that sets none

Which = Callable[[str], str | None]  # a program's path on the PATH a session gets; None when it isn't there


@dataclass(frozen=True, slots=True)
class HookRun:
    """A hook command's exit code (None when it didn't finish) and its stderr"""

    code: int | None
    stderr: str


HookRunner = Callable[[list[str], str, Path, Mapping[str, str], float], HookRun]  # (argv, stdin, cwd, env, timeout)


def run_hook(argv: list[str], stdin: str, cwd: Path, env: Mapping[str, str], timeout: float) -> HookRun:
    """argv with stdin, as Claude Code runs a hook; a hook past its timeout didn't finish"""
    try:
        proc = subprocess.run(
            argv, input=stdin, cwd=cwd, env=dict(env), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return HookRun(None, f"timed out after {timeout:g} s")
    except OSError as exc:
        return HookRun(None, f"could not start: {exc}")
    return HookRun(proc.returncode, proc.stderr)


@dataclass(frozen=True, slots=True)
class HookTest:
    """The self-test's verdict: what failed and its fix, or for a pass what refused; skipped
    is set when nothing here runs a session to test (no claude on PATH)"""

    problem: str | None
    fix: str | None
    detail: str = ""
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return self.problem is None and not self.skipped

    def line(self) -> str:
        """doctor's line: the pass, the skip, or the problem and its fix"""
        if self.problem is None:
            return self.detail
        return f"{self.problem}: {self.fix}"

    def reason(self) -> str:
        """A HOOKS_FAILED tick's reason: the problem, then the fix after "passes: " """
        return (
            f"a session here would run without the delivery hooks: {self.problem}:"
            f" no session starts until the self-test passes: {self.fix}"
        )

    def record(self) -> dict[str, object]:
        return {"ok": self.ok, "problem": self.problem, "fix": self.fix, "skipped": self.skipped}


def failed(problem: str, fix: str) -> HookTest:
    return HookTest(problem, fix)


def disabling(paths: list[Path]) -> HookTest | None:
    """A failure naming the first settings file that sets disableAllHooks; one that isn't a
    JSON object fails too, since nothing tells what Claude Code reads from it"""
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return failed(f"{path} is not JSON ({exc})", "fix it, so whether it sets disableAllHooks can be read")
        if not isinstance(data, dict):
            return failed(f"{path} is not a JSON object", "fix it, so whether it sets disableAllHooks can be read")
        if data.get("disableAllHooks") is True:
            return failed(
                f"{path} sets disableAllHooks, so a session runs no hook", f"remove disableAllHooks from {path}"
            )
    return None


def settings_files(checkout: Path, project: Path, home: Path) -> list[Path]:
    """The Claude Code settings a session in the checkout reads: the project's and local
    settings in the checkout (and in its main checkout, for a linked worktree), and the user's"""
    folders = [checkout] if project == checkout.resolve() else [checkout, project]
    return [folder / name for folder in folders for name in SETTINGS] + [home / ".claude" / "settings.json"]


def pre_command(hooks_json: Path) -> tuple[str, float]:
    """The command hooks.json runs for a Bash PreToolUse, and its timeout"""
    try:
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        entries = data["hooks"]["PreToolUse"]
        found = [
            (h["command"], h.get("timeout", DEFAULT_TIMEOUT))
            for e in entries
            if e.get("matcher") == "Bash"
            for h in e["hooks"]
            if h.get("type") == "command"
        ]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ReleaseError(f"{hooks_json} isn't a hooks file: {exc!r}") from None
    if len(found) != 1:
        raise ReleaseError(f"{hooks_json} declares {len(found)} Bash PreToolUse commands, not one")
    command, timeout = found[0]
    if not isinstance(command, str) or isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ReleaseError(f"{hooks_json}: the Bash PreToolUse command or its timeout is malformed")
    return command, float(timeout)


def hook_input(cwd: Path) -> str:
    """A PreToolUse input for REFUSED, in the shape Claude Code sends"""
    return json.dumps(
        {
            "session_id": "00000000-0000-4000-8000-000000000000",
            "transcript_path": "",
            "cwd": str(cwd),
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": REFUSED, "description": "shipmill doctor's hook self-test"},
            "tool_use_id": "toolu_shipmill_self_test",
        }
    )


def self_test(
    checkout: Path, run: Runner, hook: HookRunner, which: Which, home: Path, environ: Mapping[str, str]
) -> HookTest:
    """Run the self-test for a session in checkout. run reads git and `claude plugin list
    --json`; hook runs the hook command; which looks programs up on the session's PATH"""
    if which("claude") is None:
        return HookTest("claude isn't on PATH", "nothing here starts a session to test", skipped=True)
    try:
        common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], checkout)
    except ReleaseError as exc:
        return failed(f"can't tell the project a session in {checkout} loads: {exc}", "run it in a git checkout")
    project = session_project(checkout, common)
    disabled = disabling(settings_files(checkout, project, home))
    if disabled is not None:
        return disabled
    if which("uv") is None:
        return failed(
            "uv isn't on PATH, and the hooks run with it",
            "install uv (https://docs.astral.sh/uv/getting-started/installation/) on the PATH a session gets",
        )
    shell = which("sh")
    if shell is None:
        return failed("sh isn't on PATH, and Claude Code runs a hook through it", "put a POSIX sh on PATH")
    try:
        installs = listed_installs(run(["claude", "plugin", "list", "--json"], checkout))
        install = effective(installs, project)
    except ReleaseError as exc:
        return failed(f"can't read the {PLUGIN} install a session loads: {exc}", "fix the read, then run doctor again")
    if install is None:
        return failed(
            f"no {PLUGIN} install applies to {project}, so a session loads no hooks",
            f"in {project}: claude plugin install {PLUGIN} --scope project",
        )
    root = install.files(home)
    hooks_json = root / "hooks" / "hooks.json"
    named = f"{PLUGIN} {install.version} ({install.where()})"
    update = update_command(install, installs)
    if not hooks_json.is_file():
        return failed(f"{named} has no hooks/hooks.json in {root}, an install older than the hooks", update)
    try:
        command, timeout = pre_command(hooks_json)
    except ReleaseError as exc:
        return failed(str(exc), update)
    done = hook(
        [shell, "-c", command], hook_input(checkout), checkout, {**environ, "CLAUDE_PLUGIN_ROOT": str(root)}, timeout
    )
    said = done.stderr.strip().splitlines()
    if done.code == 2 and said and said[0].startswith(REFUSAL):
        return HookTest(None, None, f"self-test: {named} refused `{REFUSED}` (exit 2)")
    shown = "; ".join(said)[:300] or "no stderr"
    exited = "didn't finish" if done.code is None else f"exited {done.code}"
    return failed(
        f"the PreToolUse hook of {named} {exited} on `{REFUSED}`, not 2 with its refusal: {shown}",
        f"fix what its stderr names, or update the plugin: {update}",
    )
