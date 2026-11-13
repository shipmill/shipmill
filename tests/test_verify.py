"""Spec 064: [agents] verify and the check of its commands (S-064-1 to S-064-5). The check runs
in a real worktree of the repo fixture, through this repo's own delivery hook (hooks/hooks.json
run through a shell, as Claude Code runs it) and, unless a case records the run, a real shell"""

import os
import shutil
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.config import CONFIG_PATH, Table
from shipmill.errors import ReleaseError
from shipmill.gate import GATE_SESSION, HEADLESS_TOOLS, run_command
from shipmill.verify import (
    PREFIX,
    TIMEOUT,
    WORKTREES,
    DeliveryHook,
    Entry,
    Headless,
    Ran,
    Result,
    Shell,
    check,
    flag_rules,
    matches,
    rules,
    run_shell,
)

from .conftest import Repo

ROOT = Path(__file__).resolve().parents[1]  # this repo is a plugin install's folder: hooks/ and .claude-plugin/


def agents(text: str) -> AgentsConfig:
    return AgentsConfig.parse(Table(tomllib.loads('[agents]\nprompt = "/t"\n' + text), "shipmill.toml").table("agents"))


# --- S-064-1: [agents] verify -------------------------------------------------------------------


def test_s064_1_verify_is_a_list_of_commands_and_absent_is_empty() -> None:
    assert agents("").verify == ()
    given = agents('verify = ["pnpm install --frozen-lockfile", "uv run pytest -q tests/db"]\n')
    assert given.verify == ("pnpm install --frozen-lockfile", "uv run pytest -q tests/db")
    assert agents("verify = []\n").verify == ()


@pytest.mark.parametrize(
    ("value", "said"),
    [
        ('"pnpm test"', "must be a list of command strings"),
        ('["pnpm test", 3]', "must be a list of command strings"),
        ('[["pnpm test"]]', "must be a list of command strings"),
        ('[""]', "holds an empty command"),
        ('["  "]', "holds an empty command"),
        ('["pnpm install\\npnpm test"]', "spans lines"),
        ('["pnpm test", "pnpm test"]', "lists 'pnpm test' twice"),
    ],
    ids=["string", "not-strings", "nested", "empty", "blank", "newline", "duplicate"],
)
def test_s064_1_a_malformed_verify_exits_2_naming_the_key(value: str, said: str) -> None:
    with pytest.raises(ReleaseError) as caught:
        agents(f"verify = {value}\n")
    assert f"{CONFIG_PATH}: [agents] verify" in str(caught.value)
    assert said in str(caught.value)


# --- S-064-2: the allowlist's rules -------------------------------------------------------------


def test_s064_2_a_bash_rule_matches_as_claude_code_documents() -> None:
    assert matches("Bash", "anything at all") and matches("Bash(*)", "rm -rf build")
    assert matches("Bash(pnpm api:*)", "pnpm api") and matches("Bash(pnpm api:*)", "pnpm api test")
    assert not matches("Bash(pnpm api:*)", "pnpm --dir web api")
    assert not matches("Bash(pnpm api:*)", "pnpm apis")
    assert matches("Bash(gh *)", "gh pr view 7") and not matches("Bash(gh *)", "ghx pr")
    assert matches("Bash(pnpm --dir * test)", "pnpm --dir web test")
    assert matches("Bash(make test)", "make test") and not matches("Bash(make test)", "make test-all")
    assert not matches("Read", "cat x") and not matches("Bash(git *)", "gitk")


def test_s064_2_tool_lists_and_flags_give_their_rules() -> None:
    assert "Bash(gh *)" in rules(HEADLESS_TOOLS) and "Read" in rules(HEADLESS_TOOLS)
    assert rules("Bash(pnpm test),Read Bash(pnpm --dir web:*)") == ("Bash(pnpm test)", "Read", "Bash(pnpm --dir web:*)")
    args = [
        "--allowedTools",
        "Bash(pnpm:*)",
        "Bash(make *)",
        "--model",
        "opus",
        "--allowed-tools=Bash(npx:*)",
        "--disallowedTools",
        "Bash(pnpm publish:*)",
        "--disallowed-tools=Bash(rm *)",
    ]
    assert flag_rules(args) == (("Bash(pnpm:*)", "Bash(make *)", "Bash(npx:*)"), ("Bash(pnpm publish:*)", "Bash(rm *)"))


# --- The check, in a worktree of the repo fixture ------------------------------------------------


@dataclass
class Recorded:
    """The run step, recorded: each argv, its cwd and env, and the HEAD of the cwd when it ran"""

    code: int = 0
    calls: list[tuple[list[str], Path, dict[str, str]]] = field(default_factory=list)
    heads: list[str] = field(default_factory=list)
    fail: bool = False

    def __call__(self, argv: list[str], cwd: Path, env: Mapping[str, str], timeout: float) -> Ran:
        self.calls.append((argv, cwd, dict(env)))
        self.heads.append(run_command(["git", "rev-parse", "HEAD"], cwd).strip())
        if self.fail:
            raise ReleaseError("the run broke")
        return Ran(self.code, "")

    @property
    def commands(self) -> list[str]:
        return [argv[-1] for argv, _, _ in self.calls]


@pytest.fixture
def checkout(repo: Repo) -> Repo:
    """The repo fixture with an [agents] section, so the hook's rules apply, and a project
    settings file allowing pnpm, both pushed to origin/main"""
    if shutil.which("uv") is None:
        pytest.fail("uv runs the hooks")
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + '\n[agents]\nprompt = "/t"\nmode = "headless"\n')
    settings = '{"permissions": {"allow": ["Bash(pnpm api:*)", "Bash(sh:*)", "Bash(sleep:*)"],'
    settings += ' "deny": ["Bash(git push:*)"]}}\n'
    repo.write(".claude/settings.json", settings)
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "-m", "Connect the gate")
    repo.git.run("push", "-q", "origin", "main")
    return repo


def session(home: Path, claude_args: tuple[str, ...] = ()) -> Headless:
    environ = {**os.environ, "SHELL": "/bin/sh"}
    return Headless.of(claude_args, environ, home)


def verify(
    repo: Repo,
    commands: list[str],
    home: Path,
    claude_args: tuple[str, ...] = (),
    shell: Shell = run_shell,
    timeout: float = TIMEOUT,
) -> list[Entry]:
    hook = DeliveryHook(ROOT)
    return check(commands, repo.root, "main", session(home, claude_args), hook, run_command, shell, timeout)


def worktrees(repo: Repo) -> list[str]:
    folder = repo.root / WORKTREES
    listed = run_command(["git", "worktree", "list", "--porcelain"], repo.root)
    found = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
    return found + [line for line in listed.splitlines() if PREFIX in line]


def test_s064_2_a_part_no_rule_allows_is_denied_naming_it(checkout: Repo, tmp_path: Path) -> None:
    ran = Recorded()
    found = verify(checkout, ["pnpm --dir web api", "pnpm api test"], tmp_path / "home", shell=ran)
    assert found[0] == Entry("pnpm --dir web api", Result.DENIED, "no allow rule matches `pnpm --dir web api`")
    assert found[1] == Entry("pnpm api test", Result.OK, "")
    assert ran.commands == ["pnpm api test"]


def test_s064_2_every_part_is_judged_and_a_deny_rule_wins(checkout: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"permissions": {"deny": ["Bash(git clean:*)"]}}', "utf-8")
    ran = Recorded()
    commands = ["git status && make build", "git push origin HEAD", "git clean -fdx", "git status | pnpm api x"]
    found = verify(checkout, commands, home, ("--disallowedTools", "Bash(git status)"), shell=ran)
    assert [(e.result, e.detail) for e in found] == [
        (Result.DENIED, "`git status` matches the deny rule Bash(git status)"),
        (Result.DENIED, "`git push origin HEAD` matches the deny rule Bash(git push:*)"),
        (Result.DENIED, "`git clean -fdx` matches the deny rule Bash(git clean:*)"),
        (Result.DENIED, "`git status` matches the deny rule Bash(git status)"),
    ]
    widened = verify(checkout, ["git log -1 && make build"], home, ("--allowedTools", "Bash(make:*)"), shell=ran)
    assert widened == [Entry("git log -1 && make build", Result.OK, "")]
    assert ran.commands == ["git log -1 && make build"]


# --- S-064-3: the delivery hook -----------------------------------------------------------------


def test_s064_3_a_part_the_hook_refuses_is_refused_by_hook_and_not_run(checkout: Repo, tmp_path: Path) -> None:
    ran = Recorded()
    found = verify(checkout, ["git status && uv run env", "uv run pytest -q"], tmp_path / "home", shell=ran)
    assert found[0].result is Result.REFUSED
    assert found[0].detail.startswith("the hook's uv-run rule refuses `uv run env`; Instead: ")
    assert found[1] == Entry("uv run pytest -q", Result.OK, "")
    assert ran.commands == ["uv run pytest -q"]
    assert ran.calls[0][2][GATE_SESSION] == "1"


# --- S-064-4: the run ---------------------------------------------------------------------------


def test_s064_4_the_run_is_in_a_worktree_at_origin_default_through_shell_with_the_gates_path(
    checkout: Repo, tmp_path: Path
) -> None:
    checkout.write("local.txt", "a commit origin doesn't have\n")
    checkout.git.run("add", "-A")
    checkout.git.run("commit", "-q", "-m", "Local only")
    origin = run_command(["git", "rev-parse", "origin/main"], checkout.root).strip()
    ran = Recorded()
    environ = {**os.environ, "SHELL": "/bin/zsh", "PATH": "/opt/gate/bin:/usr/bin:/bin"}
    headless = Headless.of((), environ, tmp_path / "home")
    found = check(["git status"], checkout.root, "main", headless, DeliveryHook(ROOT), run_command, shell=ran)
    assert found == [Entry("git status", Result.OK, "")]
    (argv, cwd, env) = ran.calls[0]
    assert argv == ["/bin/zsh", "-c", "git status"]
    assert cwd.parent == checkout.root / WORKTREES and cwd.name.startswith(PREFIX) and len(cwd.name) == len(PREFIX) + 8
    assert ran.heads == [origin] and origin != checkout.git.sha()
    assert env["PATH"] == "/opt/gate/bin:/usr/bin:/bin" and env[GATE_SESSION] == "1"


def test_s064_4_exit_0_127_another_and_past_the_limit(checkout: Repo, tmp_path: Path) -> None:
    allow = ("--allowedTools", "Bash(no-such-tool-064:*)")
    commands = [
        "sh -c 'exit 0'",
        "git status && no-such-tool-064 --version",
        "sh -c 'echo first >&2; echo boom >&2; exit 3'",
    ]
    found = verify(checkout, commands, tmp_path / "home", allow)
    path = os.environ["PATH"]
    assert found == [
        Entry(commands[0], Result.OK, ""),
        Entry(commands[1], Result.NOT_FOUND, f"no-such-tool-064 is not on the gate's PATH: {path}"),
        Entry(commands[2], Result.FAILED, "exit 3: boom"),
    ]
    stopped = verify(checkout, ["sleep 30"], tmp_path / "home", timeout=0.5)
    assert stopped == [Entry("sleep 30", Result.TIMED_OUT, f"stopped after {0.5 / 60:g} minutes")]


def test_s064_4_the_check_waits_30_minutes_by_default(checkout: Repo, tmp_path: Path) -> None:
    timeouts: list[float] = []

    def shell(argv: list[str], cwd: Path, env: Mapping[str, str], timeout: float) -> Ran:
        timeouts.append(timeout)
        return Ran(None, "")

    found = verify(checkout, ["git status"], tmp_path / "home", shell=shell)
    assert timeouts == [30 * 60] and found == [Entry("git status", Result.TIMED_OUT, "stopped after 30 minutes")]


# --- S-064-5: order, one worktree, and its removal ----------------------------------------------


def test_s064_5_commands_run_in_order_in_one_worktree_which_is_removed(checkout: Repo, tmp_path: Path) -> None:
    ran = Recorded()
    commands = ["git status", "pnpm --dir web api", "pnpm api one", "uv run env", "git log -1"]
    found = verify(checkout, commands, tmp_path / "home", shell=ran)
    assert [e.result for e in found] == [Result.OK, Result.DENIED, Result.OK, Result.REFUSED, Result.OK]
    assert ran.commands == ["git status", "pnpm api one", "git log -1"]
    assert len({cwd for _, cwd, _ in ran.calls}) == 1
    assert worktrees(checkout) == []


def test_s064_5_a_setup_command_leaves_its_files_for_the_next(checkout: Repo, tmp_path: Path) -> None:
    allow = ("--allowedTools", "Bash(touch:*)", "Bash(test:*)")
    found = verify(checkout, ["touch made.txt", "test -f made.txt"], tmp_path / "home", allow)
    assert [e.result for e in found] == [Result.OK, Result.OK]
    assert worktrees(checkout) == []


def test_s064_5_an_erroring_check_removes_its_worktree(checkout: Repo, tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="the run broke"):
        verify(checkout, ["git status"], tmp_path / "home", shell=Recorded(fail=True))
    assert worktrees(checkout) == []
