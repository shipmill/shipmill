"""Spec 064: the gate checks [agents] verify on a real headless LAUNCH (S-064-6 to S-064-8). The
check itself is tests/test_verify.py's; here a planner stands in for it, so no worktree, hook,
or session starts, and a notifier records each notification"""

import datetime as dt
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Hold
from shipmill.claude_auth import ClaudeAuth
from shipmill.claude_token import Token
from shipmill.errors import ReleaseError
from shipmill.gate import VERIFY, Action, Decision, gate, state_dir, tick_lines
from shipmill.gitrepo import Git
from shipmill.hooks import HookTest
from shipmill.verify import Entry, Headless, Planned, Result, Verified, fingerprint, plan, plugin_root

from .test_gate import NO_PRUNE, NOW, FakeClaude, FakeNotifier
from .test_gate_headless import SESSION, Reads, login, same

COMMANDS = ("pnpm install --frozen-lockfile", "pnpm test")
PASS = [Entry(c, Result.OK, "") for c in COMMANDS]
FAIL = [PASS[0], Entry("pnpm test", Result.NOT_FOUND, "pnpm is not on the gate's PATH: /usr/bin")]
Tick = tuple[Decision, str | None]


@pytest.fixture
def checkout(tmp_path: Path) -> Git:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    repo = Git(root)
    repo.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return repo


def config(verify: Sequence[str] = COMMANDS, mode: Mode = Mode.HEADLESS, notify: bool = True) -> AgentsConfig:
    return AgentsConfig(prompt="/t", prs=False, retry_hours=24, mode=mode, notify=notify, verify=tuple(verify))


@dataclass
class Planner:
    """The gate's check: each plan's fingerprint is `fp`, and each run answers `entries`, noting
    in `order` when it ran, so a test sees it ran before the session started"""

    claude: FakeClaude
    fp: str = "a" * 64
    entries: list[Entry] = field(default_factory=lambda: list(PASS))
    order: list[str] = field(default_factory=list)
    planned: list[tuple[str, ...]] = field(default_factory=list)
    ran: int = 0
    error: str | None = None

    def __call__(self, commands: tuple[str, ...]) -> Planned:
        self.planned.append(commands)
        before = len(self.claude.started)
        return Planned(self.fp, lambda: self.run(before))

    def run(self, before: int) -> list[Entry]:
        assert len(self.claude.started) == before, "the check runs before the session starts"
        self.order.append("check")
        self.ran += 1
        if self.error is not None:
            raise ReleaseError(self.error)
        return list(self.entries)


def tick(
    git: Git,
    agents: AgentsConfig,
    planner: Planner,
    notifier: FakeNotifier | None = None,
    now: dt.datetime = NOW,
    dry_run: bool = False,
) -> Tick:
    """A headless tick whose last session ended (started reads no process), with a hook
    self-test and a preflight that pass and note when they ran"""

    def hooks() -> HookTest:
        planner.order.append("hooks")
        return HookTest(None, None, "self-test: refused")

    def auth(token: Token | None) -> ClaudeAuth:
        planner.order.append("preflight")
        return ClaudeAuth(None)

    decision, launched, *_ = gate(
        git,
        "romamo/demo",
        lambda: agents,
        planner.claude,
        Reads(),
        now,
        Hold,
        notifier or FakeNotifier(),
        NO_PRUNE,
        dry_run=dry_run,
        login=login,
        started=same(None),
        new_session=lambda: SESSION,
        hooks=hooks,
        auth=auth,
        verify=planner,
    )
    return decision, launched


def verify_json(git: Git) -> Path:
    return state_dir(git) / VERIFY


def later(hours: int) -> dt.datetime:
    """Past retry_hours of the last launch, so the same finding launches again"""
    return NOW + dt.timedelta(hours=hours)


# --- S-064-6 ------------------------------------------------------------------------------------


def test_s064_6_a_headless_launch_checks_before_the_session_and_records_it(checkout: Git) -> None:
    planner = Planner(FakeClaude(), entries=list(FAIL))
    decision, launched = tick(checkout, config(), planner)
    assert planner.order == ["preflight", "hooks", "check"] and planner.planned == [COMMANDS]
    assert decision.action is Action.LAUNCH and launched == str(SESSION)  # a failing check starts it anyway
    assert len(planner.claude.started) == 1
    line = tick_lines(decision, launched, (), (), dry_run=False)[0]
    assert line.endswith("; verify: 1 of 2 commands fail: pnpm test (not found)")
    written = json.loads(verify_json(checkout).read_text(encoding="utf-8"))
    assert written == {
        "fingerprint": planner.fp,
        "at": NOW.isoformat(),
        "entries": [
            {"command": "pnpm install --frozen-lockfile", "result": "ok", "detail": ""},
            {"command": "pnpm test", "result": "not found", "detail": "pnpm is not on the gate's PATH: /usr/bin"},
        ],
        "notified": planner.fp,  # notify defaults to true: S-064-8
    }


def test_s064_6_a_passing_check_says_so_last_on_the_line(checkout: Git) -> None:
    planner = Planner(FakeClaude())
    decision, launched = tick(checkout, config(), planner)
    assert tick_lines(decision, launched, (), (), dry_run=False)[0].endswith("; verify: 2 commands pass")
    assert launched == str(SESSION)


def test_s064_6_a_check_that_errors_still_starts_the_session_and_writes_nothing(checkout: Git) -> None:
    planner = Planner(FakeClaude(), error="git worktree add failed: no origin/main")
    decision, launched = tick(checkout, config(), planner)
    assert launched == str(SESSION) and decision.action is Action.LAUNCH
    line = tick_lines(decision, launched, (), (), dry_run=False)[0]
    assert line.endswith("; verify: couldn't check: git worktree add failed: no origin/main")
    assert not verify_json(checkout).exists()  # so the next launch checks again


@pytest.mark.parametrize("which", ["user", "project", "local"])
def test_s064_6_a_settings_file_that_isnt_utf8_is_a_check_error(tmp_path: Path, which: str) -> None:
    """The plan reads the settings files the check reads; one that isn't UTF-8 is a shipmill
    error, as the check's permissions read makes it, so the tick reads `couldn't check` and
    still starts the session instead of failing with a traceback"""
    home, checkout = tmp_path / "home", tmp_path / "demo"
    (home / ".claude").mkdir(parents=True)
    (checkout / ".claude").mkdir(parents=True)
    bad = b'{"permissions": {"allow": ["Bash(caf\xe9:*)"]}}'
    if which == "user":
        (home / ".claude" / "settings.json").write_bytes(bad)
    if which == "local":
        (checkout / ".claude" / "settings.local.json").write_bytes(bad)

    def show(rev: str, path: str) -> str | None:
        return bad.decode() if which == "project" else None

    session = Headless.of([], {"PATH": "/usr/bin"}, home)
    with pytest.raises(ReleaseError, match="UTF-8"):
        plan(COMMANDS, checkout, session, lambda: "main", show, lambda: (tmp_path, "0.128.4"), no_git)


def test_s064_6_a_malformed_verify_json_fails_the_tick_before_any_session(checkout: Git) -> None:
    verify_json(checkout).parent.mkdir(parents=True, exist_ok=True)
    verify_json(checkout).write_text('{"fingerprint": "x"}\n', encoding="utf-8")
    planner = Planner(FakeClaude())
    with pytest.raises(ReleaseError, match="verify.json is malformed"):
        tick(checkout, config(), planner)
    assert planner.claude.started == [] and planner.ran == 0


# --- S-064-7 ------------------------------------------------------------------------------------


def test_s064_7_a_passing_result_is_not_checked_again_until_the_fingerprint_changes(checkout: Git) -> None:
    planner = Planner(FakeClaude())
    tick(checkout, config(), planner)
    decision, launched = tick(checkout, config(), planner, now=later(25))
    assert planner.ran == 1 and launched == str(SESSION)
    assert "; verify:" not in tick_lines(decision, launched, (), (), dry_run=False)[0]
    planner.fp = "b" * 64  # the list, a flag, a settings file, the PATH, or the plugin changed
    tick(checkout, config(), planner, now=later(50))
    assert planner.ran == 2


@pytest.mark.parametrize(("hours", "ran"), [(23, 0), (24, 1)])
def test_s064_7_a_failing_result_is_checked_again_when_retry_hours_old(checkout: Git, hours: int, ran: int) -> None:
    planner = Planner(FakeClaude(), entries=list(FAIL))
    Verified(planner.fp, NOW - dt.timedelta(hours=hours), tuple(FAIL), planner.fp).save(verify_json(checkout))
    decision, launched = tick(checkout, config(), planner)
    assert planner.ran == ran and launched == str(SESSION)
    assert (decision.verify is not None) == bool(ran)


@pytest.mark.parametrize(
    "agents",
    [config(mode=Mode.INTERACTIVE), config(verify=())],
    ids=["interactive", "empty-list"],
)
def test_s064_7_an_interactive_tick_and_an_empty_list_check_nothing(checkout: Git, agents: AgentsConfig) -> None:
    planner = Planner(FakeClaude())
    decision, _ = tick(checkout, agents, planner)
    assert decision.action is Action.LAUNCH and planner.planned == [] and decision.verify is None
    assert not verify_json(checkout).exists()


def test_s064_7_a_dry_run_checks_nothing(checkout: Git) -> None:
    planner = Planner(FakeClaude())
    decision, _ = tick(checkout, config(), planner, dry_run=True)
    assert decision.action is Action.LAUNCH and planner.planned == [] and not verify_json(checkout).exists()


def test_s064_7_the_fingerprint_covers_each_input(tmp_path: Path) -> None:
    session = Headless.of([], {"PATH": "/usr/bin"}, tmp_path)
    base = fingerprint(COMMANDS, session, (None, None, None), "0.128.4")
    widened = Headless.of(["--allowedTools", "Bash(pnpm:*)"], {"PATH": "/usr/bin"}, tmp_path)
    denied = Headless.of(["--disallowedTools", "Bash(pnpm:*)"], {"PATH": "/usr/bin"}, tmp_path)
    moved = Headless.of([], {"PATH": "/opt/homebrew/bin:/usr/bin"}, tmp_path)
    changed = [
        fingerprint(COMMANDS[:1], session, (None, None, None), "0.128.4"),
        fingerprint(COMMANDS, widened, (None, None, None), "0.128.4"),
        fingerprint(COMMANDS, denied, (None, None, None), "0.128.4"),
        fingerprint(COMMANDS, session, ("{}", None, None), "0.128.4"),
        fingerprint(COMMANDS, session, (None, "{}", None), "0.128.4"),
        fingerprint(COMMANDS, session, (None, None, "{}"), "0.128.4"),
        fingerprint(COMMANDS, moved, (None, None, None), "0.128.4"),
        fingerprint(COMMANDS, session, (None, None, None), "0.129.0"),
    ]
    assert base == fingerprint(COMMANDS, session, (None, None, None), "0.128.4")
    assert len({base, *changed}) == len(changed) + 1


def test_s064_7_the_plan_reads_the_settings_files_a_session_reads(tmp_path: Path) -> None:
    home, checkout, plugin = tmp_path / "home", tmp_path / "demo", tmp_path / "plugin"
    (home / ".claude").mkdir(parents=True)
    (checkout / ".claude").mkdir(parents=True)
    session = Headless.of([], {"PATH": "/usr/bin"}, home)
    project: dict[str, str | None] = {"text": None}
    shown: list[tuple[str, str]] = []

    def show(rev: str, path: str) -> str | None:
        shown.append((rev, path))
        return project["text"]

    def fp() -> str:
        found = plan(COMMANDS, checkout, session, lambda: "main", show, lambda: (plugin, "0.128.4"), no_git)
        return found.fingerprint

    first = fp()
    assert shown == [("origin/main", ".claude/settings.json")]  # the project's, as the worktree holds it
    (home / ".claude" / "settings.json").write_text('{"permissions": {}}', encoding="utf-8")
    user = fp()
    (checkout / ".claude" / "settings.local.json").write_text('{"permissions": {}}', encoding="utf-8")
    local = fp()
    project["text"] = '{"permissions": {"allow": ["Bash(pnpm:*)"]}}'
    assert len({first, user, local, fp()}) == 4


def no_git(cmd: list[str], cwd: Path) -> str:
    raise AssertionError("a plan runs no git until its check runs")


def test_s064_7_the_plugin_version_is_the_install_a_session_loads(checkout: Git, tmp_path: Path) -> None:
    listing = [{"id": "shipmill@shipmill", "scope": "user", "version": "0.128.4", "installPath": str(tmp_path)}]

    def run(cmd: list[str], cwd: Path) -> str:
        if cmd[:3] == ["claude", "plugin", "list"]:
            return json.dumps(listing)
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout

    assert plugin_root(checkout.root, run, tmp_path) == (tmp_path, "0.128.4")
    listing.clear()
    with pytest.raises(ReleaseError, match="no shipmill@shipmill install applies"):
        plugin_root(checkout.root, run, tmp_path)


# --- S-064-8 ------------------------------------------------------------------------------------


def test_s064_8_a_failing_result_notifies_once_per_fingerprint(checkout: Git) -> None:
    notifier = FakeNotifier()
    planner = Planner(FakeClaude(), entries=list(FAIL))
    decision, launched = tick(checkout, config(), planner, notifier)
    assert notifier.sent == [
        (
            "shipmill romamo/demo",
            "1 of 2 [agents] verify commands fail from a headless session: pnpm test (not found);"
            " shipmill doctor names the fix",
        )
    ]
    assert "  verify: notified" in tick_lines(decision, launched, (), (), dry_run=False)
    tick(checkout, config(), planner, notifier, now=later(25))  # retry_hours: checked again, still failing
    assert planner.ran == 2 and len(notifier.sent) == 1  # the same failing fingerprint sends none
    planner.fp = "c" * 64
    tick(checkout, config(), planner, notifier, now=later(50))
    assert len(notifier.sent) == 2


def test_s064_8_without_notify_or_with_a_pass_nothing_is_sent(checkout: Git) -> None:
    notifier = FakeNotifier()
    tick(checkout, config(notify=False), Planner(FakeClaude(), entries=list(FAIL)), notifier)
    tick(checkout, config(), Planner(FakeClaude(), fp="d" * 64), notifier, now=later(25))
    assert notifier.sent == []


def test_s064_8_a_failed_send_leaves_the_notification_owed(checkout: Git) -> None:
    notifier = FakeNotifier(fail="osascript exited 1")
    planner = Planner(FakeClaude(), entries=list(FAIL))
    decision, launched = tick(checkout, config(), planner, notifier)
    assert "  verify: notify failed: osascript exited 1" in tick_lines(decision, launched, (), (), dry_run=False)
    written = Verified.load(verify_json(checkout))
    assert written is not None and written.notified is None and launched == str(SESSION)


def test_s064_8_an_owed_notification_is_sent_without_checking_again(checkout: Git) -> None:
    notifier = FakeNotifier()
    planner = Planner(FakeClaude(), entries=list(FAIL))
    # the failing result isn't retry_hours old, but a failed send left its notification owed
    Verified(planner.fp, NOW - dt.timedelta(hours=1), tuple(FAIL), None).save(verify_json(checkout))
    decision, _ = tick(checkout, config(), planner, notifier)
    assert planner.ran == 0 and len(notifier.sent) == 1 and decision.verify is None
    written = Verified.load(verify_json(checkout))
    assert written is not None and written.notified == planner.fp


def test_s064_8_verify_json_round_trips(tmp_path: Path) -> None:
    path = tmp_path / VERIFY
    result = Verified("e" * 64, NOW, tuple(FAIL), None)
    result.save(path)
    assert Verified.load(path) == result
    path.write_text(json.dumps(result.record() | {"at": "2026-10-04T12:00:00"}), encoding="utf-8")
    with pytest.raises(ReleaseError, match="at has no time zone"):
        Verified.load(path)
    entry = {"command": "x", "result": "maybe", "detail": ""}
    path.write_text(json.dumps(result.record() | {"entries": [entry]}), encoding="utf-8")
    with pytest.raises(ReleaseError, match="malformed"):
        Verified.load(path)
