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

Then it runs the install's Stop hook twice (spec 062, S-062-12), as a headless gate session
would (SHIPMILL_GATE=1, SHIPMILL_MAINTAINER set, TMPDIR a new empty directory), on a transcript
whose final message asks the maintainer while the session filed nothing on GitHub: it must
exit 2 with its request-on-github refusal, and exit 0 with stop_hook_active true. Either one
failing, or a hooks.json with no Stop hook, fails with the hook's stderr and the plugin update.

Only those are failures (S-026-15). What stops the test from reading what a session would load
(the plugin listing, git, sh, a settings file that isn't a JSON object) is a warning: the
verdict is unread, doctor WARNs, and the gate starts the session, as D-35 does on a failed read.
"""

import json
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from shipmill.errors import ReleaseError
from shipmill.plugin import (
    PLUGIN,
    USER_INSTALL,
    Runner,
    effective,
    listed_installs,
    session_project,
    update_command,
)

REFUSED = "gh pr merge 1 --rebase"  # what the hook is shown; rebase-merge refuses it in every repo with [agents]
REFUSAL = "shipmill hook rebase-merge: "  # the refusal's first line starts so
SESSION = "00000000-0000-4000-8000-000000000000"  # the self-test inputs' session_id
MAINTAINER = "shipmill-self-test"  # the Stop cases' SHIPMILL_MAINTAINER (spec 062)
ASKED = "Triaged the issue.\n\nFor you: @shipmill-self-test, decide whether to rotate the key."  # asks, files nothing
CASE = "a final message asking the maintainer with no request on GitHub"  # the Stop cases, as failures name them
STOP_REFUSAL = "shipmill hook request-on-github: "  # the Stop refusal's first line starts so
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
    is set when nothing here runs a session to test (no claude on PATH), and unread when the
    test couldn't read what a session would load (a warning, never a pause)"""

    problem: str | None
    fix: str | None
    detail: str = ""
    skipped: bool = False
    unread: bool = False

    @property
    def ok(self) -> bool:
        return self.problem is None and not self.skipped

    @property
    def failed(self) -> bool:
        """One of S-026-15's failures, which pause a headless gate; a skip or an unread test isn't"""
        return self.problem is not None and not self.skipped and not self.unread

    def line(self) -> str:
        """doctor's line: the pass, the skip, or the problem and its fix"""
        if self.problem is None:
            return self.detail
        return f"{self.problem}: {self.fix}"

    def reason(self) -> str:
        """A HOOKS_FAILED tick's reason: the problem, then the fix after "passes: " """
        lead = "" if self.skipped else "a session here would run without the delivery hooks: "
        return f"{lead}{self.problem}: no session starts until the self-test passes: {self.fix}"

    def record(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "problem": self.problem,
            "fix": self.fix,
            "skipped": self.skipped,
            "unread": self.unread,
        }


NO_CLAUDE = HookTest(
    "claude isn't on PATH, so no session can start here and its hooks can't be tested",
    "put claude on the PATH the gate runs with, then run shipmill doctor",
    skipped=True,
)


def failed(problem: str, fix: str) -> HookTest:
    return HookTest(problem, fix)


def unread(problem: str, fix: str) -> HookTest:
    return HookTest(problem, fix, unread=True)


def disabling(paths: list[Path]) -> tuple[HookTest | None, HookTest | None]:
    """A failure naming the first settings file that sets disableAllHooks, and a warning naming
    the first one that isn't a JSON object, since whether it sets it can't be read"""
    unreadable = None
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            data = f"not JSON ({exc})"
        if not isinstance(data, dict):
            shown = data if isinstance(data, str) else "not a JSON object"
            if unreadable is None:
                unreadable = unread(
                    f"{path} is {shown}, so whether it sets disableAllHooks can't be read",
                    "fix it, then run shipmill doctor",
                )
            continue
        if data.get("disableAllHooks") is True:
            return failed(
                f"{path} sets disableAllHooks, so a session runs no hook", f"remove disableAllHooks from {path}"
            ), unreadable
    return None, unreadable


def settings_files(checkout: Path, project: Path, home: Path) -> list[Path]:
    """The Claude Code settings a session in the checkout reads: the project's and local
    settings in the checkout (and in its main checkout, for a linked worktree), and the user's"""
    folders = [checkout] if project == checkout.resolve() else [checkout, project]
    return [folder / name for folder in folders for name in SETTINGS] + [home / ".claude" / "settings.json"]


def declared(hooks_json: Path, event: str, matcher: str | None) -> tuple[str, float]:
    """The one command hooks.json runs for event with matcher (None: an entry with no matcher),
    and its timeout"""
    named = f"{matcher} {event}" if matcher is not None else event
    try:
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        entries = data["hooks"].get(event, [])
        found = [
            (h["command"], h.get("timeout", DEFAULT_TIMEOUT))
            for e in entries
            if e.get("matcher") == matcher
            for h in e["hooks"]
            if h.get("type") == "command"
        ]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ReleaseError(f"{hooks_json} isn't a hooks file: {exc!r}") from None
    if len(found) != 1:
        raise ReleaseError(f"{hooks_json} declares {len(found)} {named} commands, not one")
    command, timeout = found[0]
    if not isinstance(command, str) or isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ReleaseError(f"{hooks_json}: the {named} command or its timeout is malformed")
    return command, float(timeout)


def pre_command(hooks_json: Path) -> tuple[str, float]:
    """The command hooks.json runs for a Bash PreToolUse, and its timeout"""
    return declared(hooks_json, "PreToolUse", "Bash")


def stop_command(hooks_json: Path) -> tuple[str, float]:
    """The command hooks.json runs on Stop, from its entry with no matcher, and its timeout"""
    return declared(hooks_json, "Stop", None)


def hook_input(cwd: Path) -> str:
    """A PreToolUse input for REFUSED, in the shape Claude Code sends"""
    return json.dumps(
        {
            "session_id": SESSION,
            "transcript_path": "",
            "cwd": str(cwd),
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": REFUSED, "description": "shipmill doctor's hook self-test"},
            "tool_use_id": "toolu_shipmill_self_test",
        }
    )


def stop_transcript(cwd: Path) -> str:
    """A headless session's JSONL transcript, in Claude Code's shape: a task, then a final
    message that asks the maintainer while the session filed nothing on GitHub"""
    session = {"isSidechain": False, "userType": "external", "cwd": str(cwd), "sessionId": SESSION}
    task_id, final_id = "10000000-0000-4000-8000-000000000001", "10000000-0000-4000-8000-000000000002"
    task = {
        **session,
        "parentUuid": None,
        "type": "user",
        "message": {"role": "user", "content": "shipmill doctor's Stop hook self-test"},
        "uuid": task_id,
    }
    final = {
        **session,
        "parentUuid": task_id,
        "type": "assistant",
        "message": {
            "id": "msg_shipmill_self_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": ASKED}],
            "stop_reason": "end_turn",
        },
        "uuid": final_id,
    }
    return "".join(json.dumps(entry) + "\n" for entry in (task, final))


def stop_input(cwd: Path, transcript: Path, active: bool) -> str:
    """A Stop input for the self-test's transcript, in the shape Claude Code sends"""
    return json.dumps(
        {
            "session_id": SESSION,
            "transcript_path": str(transcript),
            "cwd": str(cwd),
            "permission_mode": "bypassPermissions",
            "hook_event_name": "Stop",
            "stop_hook_active": active,
        }
    )


def stop_test(
    checkout: Path, command: str, timeout: float, shell: str, hook: HookRunner, env: Mapping[str, str], named: str
) -> tuple[str, str] | None:
    """S-062-12: the Stop hook, in a headless gate session's environment, refuses the stop of
    a final message asking the maintainer with no request on GitHub, and lets the same stop end
    with stop_hook_active true. Each case gets a new empty TMPDIR, so no refusal record of an
    earlier run lets it end; None when both hold, else what failed and how it exited"""
    with tempfile.TemporaryDirectory(prefix="shipmill-stop-test-") as folder:
        transcript = Path(folder) / "transcript.jsonl"
        transcript.write_text(stop_transcript(checkout), encoding="utf-8")
        for active in (False, True):
            temp = Path(folder) / ("active" if active else "refused")
            temp.mkdir()
            gate = {**env, "SHIPMILL_GATE": "1", "SHIPMILL_MAINTAINER": MAINTAINER, "TMPDIR": str(temp)}
            done = hook([shell, "-c", command], stop_input(checkout, transcript, active), checkout, gate, timeout)
            said = done.stderr.strip().splitlines()
            exited = "didn't finish" if done.code is None else f"exited {done.code}"
            shown = "; ".join(said)[:300] or "no stderr"
            if not active and not (done.code == 2 and said and said[0].startswith(STOP_REFUSAL)):
                return f"the Stop hook of {named} {exited} on {CASE}, not 2 with its refusal", shown
            if active and done.code != 0:
                return f"the Stop hook of {named} {exited} on {CASE} with stop_hook_active true, not 0", shown
    return None


def self_test(
    checkout: Path, run: Runner, hook: HookRunner, which: Which, home: Path, environ: Mapping[str, str]
) -> HookTest:
    """Run the self-test for a session in checkout. run reads git and `claude plugin list
    --json`; hook runs the hook command; which looks programs up on the session's PATH"""
    if which("claude") is None:
        return NO_CLAUDE
    try:
        common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], checkout)
    except ReleaseError as exc:
        return unread(f"can't tell the project a session in {checkout} loads: {exc}", "run it in a git checkout")
    project = session_project(checkout, common)
    disabled, unreadable = disabling(settings_files(checkout, project, home))
    if disabled is not None:
        return disabled
    if which("uv") is None:
        return failed(
            "uv isn't on PATH, and the hooks run with it",
            "install uv (https://docs.astral.sh/uv/getting-started/installation/) on the PATH a session gets",
        )
    shell = which("sh")
    if shell is None:
        return unread("sh isn't on PATH, and Claude Code runs a hook through it", "put a POSIX sh on PATH")
    try:
        installs = listed_installs(run(["claude", "plugin", "list", "--json"], checkout))
        install = effective(installs, project)
    except ReleaseError as exc:
        return unread(f"can't read the {PLUGIN} install a session loads: {exc}", "fix the read, then run doctor again")
    if install is None:
        return failed(
            f"no {PLUGIN} install applies to {project}, so a session loads no hooks",
            USER_INSTALL,  # S-039-3: one install at user scope serves every folder
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
    env = {**environ, "CLAUDE_PLUGIN_ROOT": str(root)}
    done = hook([shell, "-c", command], hook_input(checkout), checkout, env, timeout)
    said = done.stderr.strip().splitlines()
    fix = f"fix what its stderr names, or update the plugin: {update}"
    if not (done.code == 2 and said and said[0].startswith(REFUSAL)):
        shown = "; ".join(said)[:300] or "no stderr"
        exited = "didn't finish" if done.code is None else f"exited {done.code}"
        return failed(f"the PreToolUse hook of {named} {exited} on `{REFUSED}`, not 2 with its refusal: {shown}", fix)
    try:  # S-062-12: the Stop cases, against the same install
        stop, stop_timeout = stop_command(hooks_json)
    except ReleaseError as exc:
        return failed(str(exc), update)
    stopped = stop_test(checkout, stop, stop_timeout, shell, hook, env, named)
    if stopped is not None:
        problem, shown = stopped
        return failed(f"{problem}: {shown}", fix)
    if unreadable is not None:
        return unreadable
    return HookTest(
        None, None, f"self-test: {named} refused `{REFUSED}` and {CASE} (exit 2), and let it end on stop_hook_active"
    )
