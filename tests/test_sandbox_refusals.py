"""What the sandbox refused (spec 087, #1535): the tick reads a sandboxed session's log for the
refusal text the probe recorded (S-087-14), and the check of [agents] verify runs each command
through srt with the session's rules (S-087-16)"""

import dataclasses
import datetime as dt
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from shipmill.agents import Mode
from shipmill.doctor import verify_checks
from shipmill.gate import (
    RECORD,
    SANDBOX_READ,
    STATE_FILES,
    TICK,
    Action,
    Decision,
    Launch,
    Process,
    SandboxRefused,
    load_launch,
    load_tick,
    sandbox_refused,
    save_launch,
    session_log,
    state_dir,
    tick_lines,
    unread_sandboxed,
)
from shipmill.gitrepo import Git
from shipmill.sandbox import PROJECTS, Sandbox, SandboxConfig, Violation, Where, launch, violations
from shipmill.verify import (
    NO_SRT,
    SRT_INSTALL,
    Allowlist,
    Confined,
    Entry,
    Headless,
    Part,
    Ran,
    Refusal,
    Result,
    Verified,
    fingerprint,
    fix,
    judge,
    plan,
    srt_settings,
)
from shipmill.walk import HANDED, Hand, Handed, item_key

from .test_gate import FakeClaude
from .test_gate_headless import PID, STARTED
from .test_gate_walk import BOT_FAILED, INCIDENT, LATER, NOW, Source, cfg, tick

SESSION = "33333333-3333-4333-8333-333333333333"
CURL = "curl -sS --max-time 10 https://example.com/data.json"
REFUSAL_TEXT = (
    "curl: (56) CONNECT tunnel failed, response 403\n"
    "<sandbox_violations>\n"
    "deny network-outbound example.com:443 (user denied)\n"
    "</sandbox_violations>"
)
FIX = (
    'add "example.com" to [agents.sandbox] domains in .github/shipmill.toml, in a pull request the maintainer approves'
)


def bash(call: str, command: str) -> dict[str, object]:
    block = {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}}
    return {"type": "assistant", "message": {"content": [block]}}


def result(call: str, text: object) -> dict[str, object]:
    block = {"type": "tool_result", "tool_use_id": call, "content": text, "is_error": True}
    return {"type": "user", "message": {"role": "user", "content": [block]}}


OK = {"type": "result", "subtype": "success", "is_error": False, "result": "Done"}
REFUSED_LOG = (bash("t1", CURL), result("t1", REFUSAL_TEXT), OK)
PLAIN_LOG = (bash("t1", CURL), result("t1", "ok"), OK)


def logged(state: Path, *events: object, session: str = SESSION) -> Path:
    log = session_log(state, session)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    os.utime(log, (NOW.timestamp() + 600, NOW.timestamp() + 600))
    return log


def ended(git: Git, *events: object, sandboxed: bool = True) -> Path:
    """A headless launch of INCIDENT at NOW whose session is gone (the tick reads no start time),
    its log these events, and an older hand of BOT_FAILED, as test_gate_ends sets them"""
    state = state_dir(git)
    save_launch(state / RECORD, Launch(item_key(INCIDENT), SESSION, NOW, Process(PID, STARTED), sandboxed=sandboxed))
    hands = {item_key(INCIDENT): Hand(SESSION, NOW), item_key(BOT_FAILED): Hand("s0", NOW - dt.timedelta(hours=1))}
    Handed(hands).save(state / HANDED)
    return logged(state, *events)


def repo_at(folder: Path) -> Git:
    folder.mkdir()
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    git = Git(folder)
    git.run("remote", "add", "origin", "https://github.com/romamo/demo.git")
    return git


def ticked(git: Git, dry_run: bool = False) -> Decision:
    source = Source({1: [INCIDENT], 2: [BOT_FAILED]})
    return tick(git, source, LATER, cfg(Mode.HEADLESS), FakeClaude(), dry_run=dry_run)


def line(decision: Decision) -> str:
    return tick_lines(decision, None, (), (), False)[0]


# S-087-14: the refusal on the tick


def test_s087_14_a_refusal_adds_its_line_and_tick_json_and_changes_no_decision(tmp_path: Path) -> None:
    refused, plain = repo_at(tmp_path / "a"), repo_at(tmp_path / "b")
    ended(refused, *REFUSED_LOG)
    ended(plain, *PLAIN_LOG)
    with_refusal, without = ticked(refused), ticked(plain)
    expected = SandboxRefused(SESSION, 1, "curl -sS --max-time 10 …", "example.com", FIX)
    assert with_refusal.sandbox_refused == expected
    # the same decision; only the log the launch follows lives in each checkout
    assert dataclasses.replace(with_refusal, sandbox_refused=None, follow=None) == dataclasses.replace(
        without, follow=None
    )
    assert with_refusal.action is Action.LAUNCH
    shown = f"; sandbox refused 1: curl -sS --max-time 10 … (example.com); fix: {FIX}"
    assert shown in line(with_refusal)
    assert line(with_refusal).replace(shown, "") == line(without)
    record = load_tick(state_dir(refused) / TICK)
    assert record is not None and record.sandbox_refused == expected
    assert record.action == Action.LAUNCH.value and record.failing is None
    on_disk = json.loads((state_dir(refused) / TICK).read_text(encoding="utf-8"))
    assert on_disk["sandbox_refused"] == expected.record()


def test_s087_14_a_log_with_no_refusal_adds_nothing(tmp_path: Path) -> None:
    git = repo_at(tmp_path / "a")
    ended(git, *PLAIN_LOG)
    decision = ticked(git)
    assert decision.sandbox_refused is None and "sandbox refused" not in line(decision)
    assert "sandbox_refused" not in json.loads((state_dir(git) / TICK).read_text(encoding="utf-8"))


def test_s087_14_only_the_first_tick_after_the_session_ended_names_it(tmp_path: Path) -> None:
    git = repo_at(tmp_path / "a")
    ended(git, *REFUSED_LOG)
    assert ticked(git, dry_run=True).sandbox_refused is not None  # a dry run says it and records nothing
    assert not (state_dir(git) / SANDBOX_READ).exists()
    assert ticked(git).sandbox_refused is not None
    assert json.loads((state_dir(git) / SANDBOX_READ).read_text(encoding="utf-8")) == {"session": SESSION}
    ended(git, *REFUSED_LOG)  # the same session as the last launch again: its log was read
    assert ticked(git).sandbox_refused is None


def test_s087_14_an_unsandboxed_sessions_log_is_never_read(tmp_path: Path) -> None:
    git = repo_at(tmp_path / "a")
    ended(git, *REFUSED_LOG, sandboxed=False)
    assert ticked(git).sandbox_refused is None
    assert not (state_dir(git) / SANDBOX_READ).exists()


def test_s087_14_a_session_still_running_is_not_read(tmp_path: Path) -> None:
    git = repo_at(tmp_path / "a")
    ended(git, *REFUSED_LOG)
    state = state_dir(git)
    assert unread_sandboxed(state, lambda pid: STARTED) is None  # its pid with its start time
    assert unread_sandboxed(state, lambda pid: "another start") is not None  # the pid was reused


def test_s087_14_counts_each_refused_call_and_names_the_first(tmp_path: Path) -> None:
    other = "uv run python fetch.py"
    second = "<sandbox_violations>\ndeny network-outbound registry.npmjs.org:443 (user denied)\n"
    log = logged(tmp_path, bash("t1", CURL), result("t1", REFUSAL_TEXT), bash("t2", other), result("t2", second))
    found = sandbox_refused(log, SESSION)
    assert found == SandboxRefused(SESSION, 2, "curl -sS --max-time 10 …", "example.com", FIX)


@pytest.mark.parametrize(
    "events",
    [
        # a document that quotes the text, as docs/design/agent-modes.md does
        (bash("t1", "cat notes.md"), result("t1", "`<sandbox_violations>` / `deny network-outbound x.org:443`")),
        # the text in a tool the sandbox doesn't confine
        (
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r1", "name": "Read"}]}},
            result("r1", REFUSAL_TEXT),
        ),
        # the text in the assistant's own words, or a result whose call isn't in the log
        ({"type": "assistant", "message": {"content": [{"type": "text", "text": REFUSAL_TEXT}]}},),
        (result("t9", REFUSAL_TEXT),),
        # lines that aren't events, or an event cut off mid-write
        ("not an event", '{"type": "user", "message": {"content": ['),
    ],
)
def test_s087_14_only_a_bash_calls_result_with_the_refusal_text_counts(
    tmp_path: Path, events: tuple[object, ...]
) -> None:
    log = session_log(tmp_path, SESSION)
    log.parent.mkdir(parents=True)
    log.write_text("".join((e if isinstance(e, str) else json.dumps(e)) + "\n" for e in events), encoding="utf-8")
    assert sandbox_refused(log, SESSION) is None


def test_s087_14_a_result_as_text_blocks_counts_and_a_gone_log_reads_nothing(tmp_path: Path) -> None:
    log = logged(tmp_path, bash("t1", "curl x"), result("t1", [{"type": "text", "text": REFUSAL_TEXT}]))
    found = sandbox_refused(log, SESSION)
    assert found is not None and (found.command, found.target) == ("curl x", "example.com")
    assert sandbox_refused(tmp_path / "gone.log", SESSION) is None


def test_s087_14_the_read_marker_is_a_state_file_the_session_cant_write() -> None:
    assert SANDBOX_READ in STATE_FILES


def test_s087_14_a_violation_names_its_host_or_path_and_the_key_that_allows_it() -> None:
    text = (
        "<sandbox_violations>\n"
        "deny network-outbound 127.0.0.2:18765 (user denied)\n"
        "deny file-read-data /Users/x/.aws/config\n"
        "deny file-write-create /opt/out\n"
        "deny mach-lookup com.apple.x\n"
    )
    found = violations(text)
    assert [(v.key, v.named) for v in found] == [
        ("domains", "127.0.0.2"),
        ("read", "/Users/x/.aws/config"),
        ("write", "/opt/out"),
        (None, "com.apple.x"),
    ]
    assert found[1].fix().startswith('add "/Users/x/.aws/config" to [agents.sandbox] read in .github/shipmill.toml')
    assert found[3].fix().startswith("declare what it needs in [agents.sandbox]")
    assert all("--claude-arg" not in v.fix() and "allowedTools" not in v.fix() for v in found)
    assert Violation("network-outbound", "example.com:443").said == "a connection to example.com"


# S-087-16: the verify check in the sandbox


class Hook:
    def parts(self, command: str, cwd: Path) -> list[Part]:
        return [Part(command, command.split()[0], command)]

    def refusal(self, part: Part, cwd: Path, env: Mapping[str, str]) -> Refusal | None:
        return None


class Shell:
    def __init__(self, ran: Ran) -> None:
        self.ran = ran
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, argv: list[str], cwd: Path, env: Mapping[str, str], timeout: float) -> Ran:
        self.calls.append((argv, dict(env)))
        return self.ran


ALL = Allowlist(("Bash",), ())


def headless_session(home: Path) -> Headless:
    return Headless(("Bash",), (), {"PATH": "/usr/bin", "SHELL": "/bin/sh"}, home)


NONE_DECLARED = SandboxConfig()


def a_sandbox(tmp_path: Path, config: SandboxConfig = NONE_DECLARED) -> Sandbox:
    home = tmp_path / "home"
    common = tmp_path / "demo" / ".git"
    where = Where(home, tmp_path / "demo", common, tmp_path / "demo", common / "shipmill", "o/r")
    return launch(where, config, None, ())


def run(tmp_path: Path, shell: Shell, confined: Confined | None, settings: Path | None = None) -> Entry:
    session = headless_session(tmp_path)
    return judge(CURL, tmp_path, ALL, session, Hook(), shell, 60.0, confined, settings)


def test_s087_16_each_command_runs_through_srt_with_the_sessions_rules_and_env(tmp_path: Path) -> None:
    sandbox = a_sandbox(tmp_path)
    confined = Confined("/opt/bin/srt", sandbox)
    shell = Shell(Ran(0, ""))
    with srt_settings(confined) as settings:
        assert settings is not None
        written = json.loads(settings.read_text(encoding="utf-8"))
        assert run(tmp_path, shell, confined, settings) == Entry(CURL, Result.OK, "")
    assert not settings.exists()  # gone once the check ends
    [(argv, env)] = shell.calls
    assert argv == ["/opt/bin/srt", "--settings", str(settings), CURL]
    assert env["UV_CACHE_DIR"] == sandbox.env["UV_CACHE_DIR"] and env["GH_CONFIG_DIR"] == sandbox.env["GH_CONFIG_DIR"]
    filesystem = sandbox.settings["sandbox"]["filesystem"]  # type: ignore[index]
    assert written["filesystem"] == filesystem
    assert written["network"]["allowedDomains"] == sandbox.settings["sandbox"]["network"]["allowedDomains"]  # type: ignore[index]


def test_s087_16_a_command_the_sandbox_refused_reads_refused_by_sandbox_naming_the_host(tmp_path: Path) -> None:
    confined = Confined("/opt/bin/srt", a_sandbox(tmp_path))
    entry = run(tmp_path, Shell(Ran(56, REFUSAL_TEXT)), confined, tmp_path / "s.json")
    assert entry == Entry(CURL, Result.SANDBOX_REFUSED, "the sandbox refused a connection to example.com")
    assert str(entry.result) == "refused by sandbox"
    assert fix(entry) == FIX  # an [agents.sandbox] entry, never an allowlist change
    blocked = run(tmp_path, Shell(Ran(56, "Connection blocked by network allowlist")), confined, tmp_path / "s.json")
    assert blocked.result is Result.SANDBOX_REFUSED and "[agents.sandbox] domains" in fix(blocked)


def test_s087_16_doctor_names_the_refusal_and_its_sandbox_fix(tmp_path: Path) -> None:
    entry = Entry(CURL, Result.SANDBOX_REFUSED, "the sandbox refused a connection to example.com")
    path = tmp_path / "verify.json"
    Verified("f" * 64, NOW, (entry,)).save(path)
    [row] = verify_checks((CURL,), path)
    assert row.status == "FAIL"
    assert row.detail == f"{CURL}: refused by sandbox: the sandbox refused a connection to example.com; {FIX}"
    assert "allowedTools" not in row.detail and "--claude-arg" not in row.detail


def test_s087_16_without_srt_on_the_path_each_command_reads_not_checked(tmp_path: Path) -> None:
    shell = Shell(Ran(0, ""))
    entry = run(tmp_path, shell, Confined(None, a_sandbox(tmp_path)))
    assert entry == Entry(CURL, Result.NOT_CHECKED, NO_SRT)
    assert f"{entry.result}: {entry.detail}" == "not checked: srt is not on the gate's PATH"
    assert shell.calls == []  # step 3 doesn't run
    assert SRT_INSTALL in fix(entry)


def test_s087_16_srt_is_found_on_the_gates_path(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "srt"
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    program.chmod(0o755)
    sandbox = a_sandbox(tmp_path)
    assert Confined.of(sandbox, str(folder)).srt == str(program)
    assert Confined.of(sandbox, str(tmp_path / "empty")).srt is None


def test_s087_16_without_the_sandbox_a_violation_in_the_output_is_a_plain_failure(tmp_path: Path) -> None:
    shell = Shell(Ran(56, REFUSAL_TEXT))
    assert run(tmp_path, shell, None).result is Result.FAILED
    [(argv, _)] = shell.calls
    assert argv == ["/bin/sh", "-c", CURL]


def test_s087_16_the_rules_are_part_of_the_fingerprint_and_an_unsandboxed_one_is_unchanged(tmp_path: Path) -> None:
    session = headless_session(tmp_path)
    commands, texts = ("uv run pytest",), (None, None, None)
    before = {  # spec 064's inputs, so a check cached before spec 087 still holds
        "commands": list(commands),
        "allowed": list(session.allowed),
        "disallowed": list(session.disallowed),
        "settings": list(texts),
        "path": "/usr/bin",
        "plugin": "1.0",
    }
    unsandboxed = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert fingerprint(commands, session, texts, "1.0") == unsandboxed
    sandbox = a_sandbox(tmp_path)
    boxed = fingerprint(commands, session, texts, "1.0", Confined("/opt/bin/srt", sandbox))
    assert boxed != unsandboxed
    wider = a_sandbox(tmp_path, SandboxConfig.parse({"domains": ["registry.npmjs.org"]}, "t")[0])
    assert fingerprint(commands, session, texts, "1.0", Confined("/opt/bin/srt", wider)) != boxed
    assert fingerprint(commands, session, texts, "1.0", Confined(None, sandbox)) != boxed  # srt installed
    (tmp_path / "home" / PROJECTS / "-tmp-agent-worktree").mkdir(parents=True)  # a new worktree's transcripts
    grown = a_sandbox(tmp_path)
    assert any(p.endswith("-tmp-agent-worktree") for p in grown.rules["filesystem"]["denyRead"])  # type: ignore[index]
    assert fingerprint(commands, session, texts, "1.0", Confined("/opt/bin/srt", grown)) == boxed


def test_s087_16_plan_checks_in_the_sandbox_with_the_gate_sandbox_flag(tmp_path: Path) -> None:
    session = headless_session(tmp_path)
    sandbox = a_sandbox(tmp_path)

    def planned(confine: object) -> str:
        return plan(
            ("uv run pytest",),
            tmp_path,
            session,
            lambda: "main",
            lambda ref, path: None,
            lambda: (tmp_path, "1.0"),
            lambda cmd, cwd: "",
            confine,  # type: ignore[arg-type]
        ).fingerprint

    assert planned(None) == fingerprint(("uv run pytest",), session, (None, None, None), "1.0")
    assert planned(lambda: sandbox) == fingerprint(
        ("uv run pytest",), session, (None, None, None), "1.0", Confined.of(sandbox, "/usr/bin")
    )


def test_s087_16_a_sandboxed_launch_is_recorded_so_and_an_old_record_reads_unsandboxed(tmp_path: Path) -> None:
    path = tmp_path / RECORD
    save_launch(path, Launch(item_key(INCIDENT), SESSION, NOW, Process(PID, STARTED), sandboxed=True))
    assert json.loads(path.read_text(encoding="utf-8"))["sandboxed"] is True
    found = load_launch(path)
    assert found is not None and found.sandboxed
    save_launch(path, Launch(item_key(INCIDENT), SESSION, NOW, Process(PID, STARTED)))
    assert "sandboxed" not in json.loads(path.read_text(encoding="utf-8"))
    found = load_launch(path)
    assert found is not None and not found.sandboxed
    with pytest.raises(ValueError, match="interactive session is never sandboxed"):
        Launch(item_key(INCIDENT), SESSION, NOW, None, sandboxed=True)
