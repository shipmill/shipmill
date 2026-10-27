"""Spec 026: doctor's hooks block and the gate's hook self-test (S-026-15, S-026-16). The
self-test runs the real hooks/hooks.json command of a fake install (a copy of this repo's
hooks/) through a shell, with `claude plugin list --json` and its PATH lookups faked"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError
from shipmill.gate import Action, Decision, Waiting, gate, tick_lines, tick_record
from shipmill.gitrepo import Git
from shipmill.hooks import NO_CLAUDE, REFUSED, HookRun, HookTest, Which, run_hook, self_test
from shipmill.plugin import CACHE, Listed, Scope, listed_installs
from shipmill.version import Version
from shipmill.worktrees import Judged

from .conftest import Repo
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg, host

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/t"\n'
APP = '\n[agents]\nprompt = "/t"\napp_id = 5209412\n'


def install_copy(folder: Path, hooks_json: str | None = None) -> Path:
    """A plugin install's folder holding this repo's hooks/ and .claude-plugin/ (whose
    plugin.json names the CLI the hooks run, spec 031), or a hooks.json of its own"""
    shutil.copytree(ROOT / "hooks", folder / "hooks")
    shutil.copytree(ROOT / ".claude-plugin", folder / ".claude-plugin")
    if hooks_json is not None:
        (folder / "hooks" / "hooks.json").write_text(hooks_json, encoding="utf-8")
    return folder


def stub_hooks(command: str) -> str:
    """A hooks.json whose Bash PreToolUse runs command"""
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "timeout": 10, "command": command}]}
    return json.dumps({"hooks": {"PreToolUse": [entry]}})


@dataclass
class Host:
    """claude plugin list --json and git on a fake host: one user-scope install at version,
    its files at path (None: the listing names no installPath)"""

    path: Path | None
    version: str = "0.52.0"
    installed: bool = True
    calls: list[list[str]] = field(default_factory=list)
    unreadable: bool = False  # the listing fails

    def __call__(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append(cmd)
        if cmd[:3] == ["claude", "plugin", "list"]:
            if self.unreadable:
                raise ReleaseError("claude plugin list --json exited 1")
            if not self.installed:
                return "[]"
            entry: dict[str, str] = {"id": "shipmill@shipmill", "scope": "user", "version": self.version}
            if self.path is not None:
                entry["installPath"] = str(self.path)
            return json.dumps([entry])
        if cmd[0] == "git":
            return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout
        raise AssertionError(f"unexpected command {cmd}")


def which(missing: tuple[str, ...] = ()) -> Which:
    """PATH lookups with claude present and the missing programs absent"""

    def find(name: str) -> str | None:
        if name in missing:
            return None
        return "/usr/local/bin/claude" if name == "claude" else shutil.which(name)

    return find


def run_test(root: Path, host_: Host, home: Path, missing: tuple[str, ...] = ()) -> HookTest:
    return self_test(root, host_, run_hook, which(missing), home, os.environ)


@pytest.fixture
def agents_repo(repo: Repo) -> Repo:
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + AGENTS)
    repo.git.run("remote", "set-head", "origin", "main")
    return repo


def hooks_block(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.name == "hooks"]


# --- S-026-15: doctor's hooks block ---------------------------------------------------------


def test_s026_15_one_line_per_rule_on_or_off_and_why(agents_repo: Repo) -> None:
    home = agents_repo.root.parent / "home-with-key"
    key = home / ".config" / "shipmill" / "app-5209412.pem"
    key.parent.mkdir(parents=True)
    key.write_text("not a key\n", encoding="utf-8")
    found = hooks_block(doctor(agents_repo.root, home=home))
    assert [c.status for c in found] == ["PASS"] * 5
    assert found[0].detail.startswith("app-writes: off (no [agents] app_id)")
    assert found[1].detail.startswith("default-branch-push on: [hooks] default_branch is not false")
    assert found[2].detail.startswith("rebase-merge on: always") and "(D-33)" in found[2].detail
    assert found[3].detail.startswith("force-push on: always")
    assert found[4].detail == "private-paths off: no [hooks] private globs"
    hooks = '\n[hooks]\ndefault_branch = false\nprivate = ["owner/**"]\n'
    text = agents_repo.read(str(CONFIG_PATH)).replace(AGENTS, APP + hooks)
    agents_repo.write(str(CONFIG_PATH), text)
    found = hooks_block(doctor(agents_repo.root, home=home))
    assert found[0].detail.startswith(f"app-writes: on (the App's key is at {key})") and "(D-14" in found[0].detail
    assert found[1].detail.startswith("default-branch-push off: [hooks] default_branch = false")
    assert found[4].detail.startswith("private-paths on: [hooks] private holds owner/**")


def test_s026_15_a_repo_without_agents_gets_no_hooks_block(repo: Repo) -> None:
    def never() -> HookTest:
        raise AssertionError("no self-test without [agents]")

    assert hooks_block(doctor(repo.root, hooks=never)) == []


def test_s026_15_the_self_test_passes_on_the_installs_own_refusal(agents_repo: Repo, tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.fail("uv runs the hooks")
    files = install_copy(tmp_path / "install")
    found = run_test(agents_repo.root, Host(files), tmp_path / "home")
    assert found.ok, found.line()
    assert found.line() == f"self-test: shipmill@shipmill 0.52.0 (user scope) refused `{REFUSED}` (exit 2)"
    checks = hooks_block(doctor(agents_repo.root, hooks=lambda: found))
    assert checks[-1] == Check("PASS", "hooks", found.line())


@pytest.mark.parametrize(
    ("command", "exited"),
    [
        ("cat >/dev/null; exit 0", "exited 0"),
        (
            "cat >/dev/null; echo \"shipmill hook: can't start hooks/delivery.py (uv is not on PATH);"
            ' this command runs unchecked, see shipmill doctor" >&2; exit 1',
            "exited 1",
        ),
        ("cat >/dev/null; echo 'error: No interpreter found for Python >=3.11' >&2; exit 2", "exited 2"),
    ],
    ids=["allows", "cant-start", "uv-exit-2"],
)
def test_s026_15_a_hook_that_doesnt_refuse_fails_with_its_stderr(
    agents_repo: Repo, tmp_path: Path, command: str, exited: str
) -> None:
    """Any exit but 2 with the refusal fails: the 1 of a hook that can't start its script
    (D-40), and uv's own exit 2 under the hook command older than #458"""
    files = install_copy(tmp_path / "install", stub_hooks(command))
    found = run_test(agents_repo.root, Host(files), tmp_path / "home")
    assert not found.ok and not found.skipped
    assert found.problem is not None and f"{exited} on `{REFUSED}`, not 2 with its refusal" in found.problem
    if exited == "exited 1":
        assert "can't start hooks/delivery.py (uv is not on PATH)" in found.problem
    assert found.fix is not None and "claude plugin update shipmill@shipmill --scope user" in found.fix
    (last,) = [c for c in hooks_block(doctor(agents_repo.root, hooks=lambda: found)) if c.status == "FAIL"]
    assert last.detail == found.line()


def test_s026_15_an_install_without_hooks_json_fails_naming_the_update(agents_repo: Repo, tmp_path: Path) -> None:
    files = tmp_path / "install"
    (files / "skills").mkdir(parents=True)
    found = run_test(agents_repo.root, Host(files, version="0.51.0"), tmp_path / "home")
    assert found.problem == (
        f"shipmill@shipmill 0.51.0 (user scope) has no hooks/hooks.json in {files}, an install older than the hooks"
    )
    refresh = "claude plugin marketplace update shipmill"  # #477: before the update
    assert found.fix == f"{refresh} && claude plugin update shipmill@shipmill --scope user"


def test_s026_15_without_install_path_the_cache_folder_is_read(agents_repo: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    install_copy(home / CACHE / "0.52.0", stub_hooks("cat >/dev/null; exit 0"))
    found = run_test(agents_repo.root, Host(None), home)
    assert found.problem is not None and "exited 0" in found.problem


def test_s026_15_no_uv_on_path_fails(agents_repo: Repo, tmp_path: Path) -> None:
    files = install_copy(tmp_path / "install")
    found = run_test(agents_repo.root, Host(files), tmp_path / "home", missing=("uv",))
    assert found.problem == "uv isn't on PATH, and the hooks run with it"
    assert found.fix is not None and "install uv" in found.fix


@pytest.mark.parametrize("where", ["project", "local", "user"])
def test_s026_15_disable_all_hooks_in_a_settings_file_fails(agents_repo: Repo, tmp_path: Path, where: str) -> None:
    files = install_copy(tmp_path / "install")
    home = tmp_path / "home"
    path = {
        "project": agents_repo.root / ".claude" / "settings.json",
        "local": agents_repo.root / ".claude" / "settings.local.json",
        "user": home / ".claude" / "settings.json",
    }[where]
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
    found = run_test(agents_repo.root, Host(files), home)
    assert found.problem == f"{path} sets disableAllHooks, so a session runs no hook"
    assert found.fix == f"remove disableAllHooks from {path}"
    path.write_text(json.dumps({"disableAllHooks": False}), encoding="utf-8")
    assert run_test(agents_repo.root, Host(files), home).problem != found.problem


def test_s026_15_s039_3_no_install_applies_fails_with_the_user_scope_install(agents_repo: Repo, tmp_path: Path) -> None:
    # proves: S-039-3
    found = run_test(agents_repo.root, Host(None, installed=False), tmp_path / "home")
    assert found.failed and found.problem is not None
    assert found.problem.startswith("no shipmill@shipmill install applies to")
    assert found.fix == "claude plugin install shipmill@shipmill --scope user"


def test_s026_15_no_claude_on_path_warns(agents_repo: Repo, tmp_path: Path) -> None:
    host_ = Host(None)
    found = run_test(agents_repo.root, host_, tmp_path / "home", missing=("claude",))
    assert found.skipped and not found.ok and host_.calls == []
    (last,) = [c for c in hooks_block(doctor(agents_repo.root, hooks=lambda: found)) if c.detail == found.line()]
    assert last.status == "WARN"


def warned(root: Path, found: HookTest) -> str:
    """doctor's status for the self-test's line"""
    (last,) = [c for c in hooks_block(doctor(root, hooks=lambda: found)) if c.detail == found.line()]
    return last.status


def test_s026_15_an_unreadable_listing_warns_and_is_no_failure(agents_repo: Repo, tmp_path: Path) -> None:
    """Outside S-026-15's failures: what the test can't read is a WARN, as D-35 starts on a failed read"""
    found = run_test(agents_repo.root, Host(None, unreadable=True), tmp_path / "home")
    assert found.unread and not found.failed and not found.ok
    assert found.problem is not None and found.problem.startswith("can't read the shipmill@shipmill install")
    assert warned(agents_repo.root, found) == "WARN"


def test_s026_15_no_sh_on_path_warns(agents_repo: Repo, tmp_path: Path) -> None:
    files = install_copy(tmp_path / "install")
    found = run_test(agents_repo.root, Host(files), tmp_path / "home", missing=("sh",))
    assert found.unread and not found.failed
    assert warned(agents_repo.root, found) == "WARN"


def test_s026_15_a_checkout_git_cant_read_warns(agents_repo: Repo, tmp_path: Path) -> None:
    def no_git(cmd: list[str], cwd: Path) -> str:
        raise ReleaseError("git rev-parse exited 128")

    found = self_test(agents_repo.root, no_git, run_hook, which(), tmp_path / "home", os.environ)
    assert found.unread and not found.failed
    assert found.problem is not None and found.problem.startswith("can't tell the project a session in")


def test_s026_15_a_settings_file_not_json_warns_after_the_hook_refuses(agents_repo: Repo, tmp_path: Path) -> None:
    """A settings file that can't be read still runs the hook: a refusing hook WARNs, and a
    later file setting disableAllHooks, or a hook that allows, still FAILs"""
    files = install_copy(tmp_path / "install")
    home = tmp_path / "home"
    broken = agents_repo.root / ".claude" / "settings.json"
    broken.parent.mkdir()
    broken.write_text("{not json", encoding="utf-8")
    found = run_test(agents_repo.root, Host(files), home)
    assert found.unread and not found.failed, found.line()
    assert found.problem is not None and found.problem.startswith(f"{broken} is not JSON")
    assert warned(agents_repo.root, found) == "WARN"
    user = home / ".claude" / "settings.json"
    user.parent.mkdir(parents=True)
    user.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
    assert run_test(agents_repo.root, Host(files), home).failed
    user.unlink()
    allows = install_copy(tmp_path / "allows", stub_hooks("cat >/dev/null; exit 0"))
    assert run_test(agents_repo.root, Host(allows), home).failed


def test_s026_15_doctor_prints_the_block_and_warns_without_claude(
    agents_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through the CLI: no claude on PATH skips the test (WARN), and the rule lines print"""
    main(["--repo", str(agents_repo.root), "doctor"], environ={"PATH": ""})
    out = capsys.readouterr().out
    assert "PASS hooks: rebase-merge on: always" in out
    assert "WARN hooks: claude isn't on PATH, so no session can start here and its hooks can't be tested" in out


def test_s026_15_origin_head_unset_warns(agents_repo: Repo) -> None:
    warned = "origin/HEAD is unset, so a hook can't tell the default branch: git remote set-head origin --auto"
    assert Check("WARN", "hooks", warned) not in hooks_block(doctor(agents_repo.root))
    agents_repo.git.run("remote", "set-head", "origin", "--delete")
    assert Check("WARN", "hooks", warned) in hooks_block(doctor(agents_repo.root))


def test_s026_15_the_listing_reads_install_path() -> None:
    text = '[{"id": "shipmill@shipmill", "scope": "user", "version": "0.52.0", "installPath": "/c/0.52.0"}]'
    assert listed_installs(text) == [Listed(Scope.USER, None, Version.parse("0.52.0"), Path("/c/0.52.0"))]
    with pytest.raises(ReleaseError, match="installPath is 3"):
        listed_installs('[{"id": "shipmill@shipmill", "scope": "user", "version": "0.52.0", "installPath": 3}]')


def test_run_hook_reports_a_timeout(tmp_path: Path) -> None:
    done = run_hook(["/bin/sh", "-c", "sleep 5"], "", tmp_path, {"PATH": "/usr/bin:/bin"}, 0.2)
    assert done == HookRun(None, "timed out after 0.2 s")


# --- S-026-16: the gate's self-test ---------------------------------------------------------

BROKEN = HookTest("the PreToolUse hook of shipmill@shipmill 0.52.0 (user scope) exited 1", "update the plugin")
PASSED = HookTest(None, None, "self-test: refused")


@pytest.fixture
def checkout(tmp_path: Path) -> Git:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return git


@dataclass
class FakeSelfTest:
    """The self-test's result, counting its runs"""

    result: HookTest
    runs: int = 0

    def __call__(self) -> HookTest:
        self.runs += 1
        return self.result


Tick = tuple[Decision, str | None, tuple[Waiting, ...], tuple[Judged, ...]]


def tick(git: Git, mode: Mode, tests: FakeSelfTest, claude: FakeClaude, dry: bool = False) -> Tick:
    agents = AgentsConfig(prompt="/t", retry_hours=24, mode=mode)
    return gate(
        git,
        "romamo/demo",
        lambda: agents,
        claude,
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        dry_run=dry,
        login=host,
        hooks=tests,
    )


def test_s026_16_a_headless_gate_whose_self_test_fails_starts_no_session(checkout: Git) -> None:
    claude = FakeClaude([bg("old", "idle", "done")])
    tests = FakeSelfTest(BROKEN)
    decision, launched, waiting, pruned = tick(checkout, Mode.HEADLESS, tests, claude)
    assert (decision.action, launched, claude.started, claude.stopped) == (Action.HOOKS_FAILED, None, [], [])
    assert tests.runs == 1  # at most once per tick
    assert decision.reason == (
        "a session here would run without the delivery hooks: the PreToolUse hook of shipmill@shipmill 0.52.0"
        " (user scope) exited 1: no session starts until the self-test passes: update the plugin"
    )
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert lines[0] == f"HOOKS_FAILED: {decision.reason}"
    record = tick_record(decision, launched, waiting, pruned, dry_run=False)
    assert record["action"] == "HOOKS_FAILED" and record["launched"] is None and record["stopped"] == []
    assert record["hooks"] == {
        "ok": False,
        "problem": BROKEN.problem,
        "fix": BROKEN.fix,
        "skipped": False,
        "unread": False,
    }


def test_s026_16_a_headless_dry_run_reports_the_failure_too(checkout: Git) -> None:
    decision, launched, _, _ = tick(checkout, Mode.HEADLESS, FakeSelfTest(BROKEN), FakeClaude(), dry=True)
    assert (decision.action, launched) == (Action.HOOKS_FAILED, None)


def test_s026_16_an_interactive_gate_reports_the_failure_and_starts_the_session(checkout: Git) -> None:
    claude = FakeClaude()
    tests = FakeSelfTest(BROKEN)
    decision, launched, waiting, pruned = tick(checkout, Mode.INTERACTIVE, tests, claude)
    assert (decision.action, launched, tests.runs) == (Action.LAUNCH, "s1", 1)
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert f"  hooks self-test failed, the session starts anyway: {BROKEN.problem}: {BROKEN.fix}" in lines


def test_s026_16_a_headless_gate_whose_test_couldnt_read_starts_the_session(checkout: Git) -> None:
    """Only S-026-15's failures pause: an unread test is reported, and the session starts (D-35)"""
    claude = FakeClaude()
    unread = HookTest("can't read the shipmill@shipmill install a session loads: boom", "fix the read", unread=True)
    decision, launched, waiting, pruned = tick(checkout, Mode.HEADLESS, FakeSelfTest(unread), claude)
    assert (decision.action, len(claude.started)) == (Action.LAUNCH, 1) and launched is not None
    lines = tick_lines(decision, launched, waiting, pruned, dry_run=False)
    assert f"  hooks self-test couldn't run, the session starts anyway: {unread.line()}" in lines


def test_s026_16_a_headless_gate_without_claude_says_so(checkout: Git) -> None:
    claude = FakeClaude()
    decision, launched, _, _ = tick(checkout, Mode.HEADLESS, FakeSelfTest(NO_CLAUDE), claude)
    assert (decision.action, launched, claude.started) == (Action.HOOKS_FAILED, None, [])
    assert decision.reason == (
        "claude isn't on PATH, so no session can start here and its hooks can't be tested:"
        " no session starts until the self-test passes: put claude on the PATH the gate runs with,"
        " then run shipmill doctor"
    )


def test_s026_16_a_passing_self_test_launches_and_says_nothing(checkout: Git) -> None:
    claude = FakeClaude()
    decision, launched, waiting, pruned = tick(checkout, Mode.HEADLESS, FakeSelfTest(PASSED), claude)
    assert decision.action is Action.LAUNCH and len(claude.started) == 1
    assert not any("hooks" in line for line in tick_lines(decision, launched, waiting, pruned, dry_run=False))


def test_s026_16_a_tick_that_launches_nothing_runs_no_self_test(checkout: Git) -> None:
    tests = FakeSelfTest(BROKEN)
    claude = FakeClaude([bg("live", "busy", "working")])
    decision, _, _, _ = tick(checkout, Mode.HEADLESS, tests, claude)
    assert decision.action is Action.RUNNING and tests.runs == 0
