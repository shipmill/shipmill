"""Spec 064: doctor shows the gate's last check of [agents] verify, one row per command"""

import datetime as dt
import json

from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, doctor
from shipmill.gate import VERIFY, state_dir
from shipmill.gitrepo import Git
from shipmill.verify import Entry, Result, Verified

from .conftest import Repo

AT = dt.datetime(2026, 11, 13, 9, 30, tzinfo=dt.UTC)
COMMANDS = ("pnpm install --frozen-lockfile", "pnpm --dir web test", "uv run env", "psql -c 'select 1'")


def configure(repo: Repo, commands: tuple[str, ...]) -> None:
    listed = ", ".join(json.dumps(c) for c in commands)
    text = f'\n[agents]\nprompt = "/t"\nverify = [{listed}]\n' if commands else '\n[agents]\nprompt = "/t"\n'
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + text)


def rows(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github) if c.name == "verify command"]


def record(repo: Repo, *entries: Entry) -> None:
    path = state_dir(Git(repo.root)) / VERIFY
    path.parent.mkdir(parents=True, exist_ok=True)
    Verified("f" * 64, AT, entries, None).save(path)


def test_s064_9_no_list_prints_no_row(repo: Repo) -> None:
    configure(repo, ())
    record(repo, Entry("pnpm test", Result.FAILED, "exit 1: boom"))  # a result left from an older list
    assert rows(repo) == []


def test_s064_9_no_result_yet_warns_not_checked_for_each_command(repo: Repo) -> None:
    configure(repo, COMMANDS[:2])
    later = "not checked yet: the gate checks it before its next headless session"
    expected = [Check("WARN", "verify command", f"{c}: {later}") for c in COMMANDS[:2]]
    assert rows(repo) == expected
    record(repo, Entry(COMMANDS[0], Result.OK, ""))  # checked for an older list: not this one's result
    assert rows(repo) == expected


def test_s064_9_one_row_per_command_pass_for_ok_and_fail_with_its_fix(repo: Repo) -> None:
    commands = (*COMMANDS, "make db", "make web", "pnpm lint")
    configure(repo, commands)
    record(
        repo,
        Entry(commands[0], Result.OK, ""),
        Entry(commands[1], Result.DENIED, "no allow rule matches `pnpm --dir web test`"),
        Entry(commands[2], Result.REFUSED, "the hook's uv-run rule refuses `uv run env`; Instead: set [hooks] uv_run"),
        Entry(commands[3], Result.NOT_FOUND, "psql is not on the gate's PATH: /usr/bin:/bin"),
        Entry(commands[4], Result.FAILED, "exit 2: no rule to make target db"),
        Entry(commands[5], Result.TIMED_OUT, "stopped after 30 minutes"),
        Entry(commands[6], Result.DENIED, "`pnpm lint` matches the deny rule Bash(pnpm lint)"),
    )
    found = rows(repo)
    assert [c.status for c in found] == ["PASS", "FAIL", "FAIL", "FAIL", "FAIL", "FAIL", "FAIL"]
    assert found[0].detail == "pnpm install --frozen-lockfile: ok at 2026-11-13 09:30 UTC"
    assert found[1].detail == (
        "pnpm --dir web test: denied: no allow rule matches `pnpm --dir web test`; allow it on the gate:"
        ' shipmill launchd --claude-arg=--allowedTools --claude-arg "Bash(pnpm --dir web test)"'
    )
    assert found[2].detail == (
        "uv run env: refused by hook: the hook's uv-run rule refuses `uv run env`; Instead: set [hooks] uv_run;"
        " do as the hook's Instead line says; an allow rule doesn't pass the hook"
    )
    assert found[3].detail.startswith(
        "psql -c 'select 1': not found: psql is not on the gate's PATH: /usr/bin:/bin; install its program into a"
        " folder of the gate's PATH"
    )
    assert "allowedTools" not in found[3].detail and "Bash(" not in found[3].detail  # never an allowlist change
    assert found[4].detail == (
        "make db: failed: exit 2: no rule to make target db; run it in a worktree under .claude/worktrees to see why"
    )
    assert found[5].detail.startswith("make web: timed out: stopped after 30 minutes; run it in a worktree")
    assert found[6].detail.startswith("pnpm lint: denied: `pnpm lint` matches the deny rule Bash(pnpm lint); drop")


def test_s064_9_a_malformed_verify_json_fails_naming_the_file_and_its_fix(repo: Repo) -> None:
    configure(repo, COMMANDS[:1])
    path = state_dir(Git(repo.root)) / VERIFY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"fingerprint": 1}', encoding="utf-8")
    (row,) = rows(repo)
    assert row.status == "FAIL"
    assert str(path) in row.detail and "delete it to start over" in row.detail
