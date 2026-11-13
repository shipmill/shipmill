"""Spec 055: `shipmill gh pr merge` and the merge API's PUT, as the App, run the wheel's
pr_gate.py and merge only the head it reads READY (S-055-1, S-055-2, S-055-3). No test reaches
the network: the pull request is FakeReads, pr_gate.py FakeGate, GitHub MintApi"""

import sys
from pathlib import Path
from typing import Any

import pytest

from shipmill.app_gh import merge_pins, pinned
from shipmill.bundle import skills_dir
from shipmill.errors import ReleaseError
from shipmill.merge_gate import gate_command
from shipmill.pr_plan import _gate

from .conftest import POLICY, Repo
from .test_agent_marker import HOST_IDENTITY
from .test_app import REPO
from .test_app_gh_merge import (
    CODE,
    DIRECTION,
    FULL,
    MERGES,
    OTHER,
    FakeGate,
    FakeReads,
    Reader,
    Runner,
    connected,
    gh,
    pinned_to,
    verdict,
)
from .test_credit import APP_LOGIN, NoSlugApi

PR_GATE = skills_dir() / "github-pr-triage" / "scripts" / "pr_gate.py"


def run(repo: Repo, tmp_path: Path, args: list[str], gate: FakeGate, **kwargs: Any) -> tuple[Runner, str | None]:
    """gh as the App with gate as pr_gate.py: gh's runner and the refusal, None when gh ran"""
    key = kwargs.pop("key") if "key" in kwargs else connected(repo, tmp_path)
    reader, runner = Reader(FakeReads(kwargs.pop("files", (CODE,)), **kwargs)), Runner()
    try:
        assert gh(repo, tmp_path, key, args, reader, runner, gate=gate) == 0
    except ReleaseError as exc:  # cli.run prints it and exits 2
        assert runner.calls == []  # gh never runs
        return runner, str(exc)
    return runner, None


# -- S-055-1: the merge runs pr_gate.py, and only READY runs gh --------------------------------


@pytest.mark.parametrize("args", MERGES)
def test_s055_1_every_spelling_of_a_merge_runs_the_wheels_pr_gate_with_the_apps_token(
    repo: Repo, tmp_path: Path, args: list[str]
) -> None:
    gate = FakeGate()
    runner, refused = run(repo, tmp_path, args, gate)
    assert refused is None and len(runner.calls) == 1
    [(cmd, env)] = gate.calls
    assert cmd[:2] == [sys.executable, str(PR_GATE)]
    assert cmd[2:6] == ["7", "-R", REPO, "--checkout"]
    assert Path(cmd[6]).resolve() == repo.root.resolve()
    assert cmd[7:] == ["--bot-login", APP_LOGIN]
    assert env["GH_TOKEN"] == "token-1"  # the App's token


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "merge", "feat/x", "--squash"],
        ["pr", "merge", "--auto", "--squash", "7"],
        ["pr", "merge", "-s", "--match-head-commit", FULL, "--", "7"],
    ],
)
def test_s055_1_a_branch_auto_and_a_pinned_merge_run_the_gate_too(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    gate = FakeGate(verdict("PENDING", FULL) + "\n  pending: test (running)\n", 3)
    _, refused = run(repo, tmp_path, args, gate)
    assert refused is not None and "is refused: pr_gate.py reads #7 PENDING" in refused
    assert [cmd[2] for cmd, _ in gate.calls] == ["7"]


@pytest.mark.parametrize(
    ("label", "code", "reasons"),
    [
        ("FAILED", 1, ["  failed: test (FAILURE)"]),
        ("PENDING", 3, ["  pending: test (queued)"]),
        ("BLOCKED", 4, []),
        ("NEEDS_DECISION", 5, ["  needs-decision: scope: adds a flag", "  needs-decision: the answer doesn't take it"]),
        ("REFUSED", 6, ["  refused: no ## Plan section"]),
        ("MAINTAINER_ONLY", 7, ["  maintainer-only: direction: edits docs/product.md"]),
        ("DRAFT", 8, ["  draft: left to its author until marked ready (D-67)"]),
    ],
)
@pytest.mark.parametrize(
    "args", [["pr", "merge", "7", "--squash"], ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"]]
)
def test_s055_1_any_verdict_but_ready_exits_2_printing_the_gates_lines(
    repo: Repo, tmp_path: Path, args: list[str], label: str, code: int, reasons: list[str]
) -> None:
    line = verdict(label)
    gate = FakeGate("\n".join([line, *reasons]) + "\n", code)
    _, refused = run(repo, tmp_path, args, gate)
    assert refused is not None
    assert f"is refused: pr_gate.py reads #7 {label}" in refused
    assert refused.splitlines()[1:] == [line, *reasons]


@pytest.mark.parametrize(
    ("files", "labels", "why"), [((DIRECTION,), (), "has a never zone"), ((CODE,), ("needs-decision",), "labelled")]
)
def test_s055_1_the_never_zone_and_label_holds_refuse_before_the_gate_runs(
    repo: Repo, tmp_path: Path, files: tuple[Any, ...], labels: tuple[str, ...], why: str
) -> None:
    gate = FakeGate()
    _, refused = run(repo, tmp_path, ["pr", "merge", "7"], gate, files=files, labels=labels)
    assert refused is not None and why in refused
    assert gate.calls == []


def test_s055_1_the_lines_pr_gate_renders_are_the_ones_read(repo: Repo, tmp_path: Path) -> None:
    gate, key = _gate(), connected(repo, tmp_path)
    ready = gate.Gate(7, "OPEN", "MERGEABLE", "main", FULL, (gate.Check("test", True, "SUCCESS"),))
    runner, refused = run(repo, tmp_path, ["pr", "merge", "7"], FakeGate(gate.render(ready) + "\n"), key=key)
    assert refused is None and runner.calls[0][1:] == pinned_to(["pr", "merge", "7"])
    held = gate.render(gate.Gate(7, "OPEN", "MERGEABLE", "main", FULL, (), asks=("scope: x",)))
    _, refused = run(repo, tmp_path, ["pr", "merge", "7"], FakeGate(held + "\n", 5), key=key)
    assert refused is not None and refused.splitlines()[1:] == held.splitlines()
    assert "is refused: pr_gate.py reads #7 NEEDS_DECISION" in refused


def test_s055_1_gate_command_names_a_script_the_wheel_ships(tmp_path: Path) -> None:
    cmd = gate_command(7, REPO, tmp_path, APP_LOGIN)
    assert Path(cmd[1]).is_file()
    assert cmd == [sys.executable, str(PR_GATE), "7", "-R", REPO, "--checkout", str(tmp_path), "--bot-login", APP_LOGIN]


def test_s055_1_a_merge_as_the_host_runs_no_gate(repo: Repo, tmp_path: Path) -> None:
    """Out of scope (spec 055): a merge shipmill gh writes as the host's login is the person's"""
    connected(repo, tmp_path, POLICY + HOST_IDENTITY)
    reader, runner, gate = Reader(FakeReads((CODE,))), Runner(), FakeGate(returncode=5)
    assert gh(repo, tmp_path, None, ["pr", "merge", "7"], reader, runner, gate=gate) == 0
    assert (gate.calls, [argv[1:] for argv in runner.calls]) == ([], [["pr", "merge", "7"]])


# -- S-055-2: the merge is pinned to the head the gate judged -----------------------------------


@pytest.mark.parametrize("args", MERGES)
def test_s055_2_an_unpinned_merge_runs_gh_pinned_to_the_ready_head(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    head = "a" * 40
    runner, refused = run(repo, tmp_path, args, FakeGate(verdict(head=head) + "\n"))
    assert refused is None
    [argv] = runner.calls
    assert argv[1:] == pinned_to(args, head)


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "merge", "7", "--squash", "--match-head-commit", FULL],
        ["pr", "merge", "7", f"--match-head-commit={FULL.upper()}"],
        ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge", "-f", f"sha={FULL}"],
        ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge", f"--raw-field=sha={FULL}", "-f", "merge_method=squash"],
    ],
)
def test_s055_2_a_merge_pinned_to_the_ready_head_runs_as_given(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    runner, refused = run(repo, tmp_path, args, FakeGate())
    assert refused is None
    [argv] = runner.calls
    assert argv[1:] == args


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "merge", "7", "--squash", "--match-head-commit", OTHER],
        ["pr", "merge", "--match-head-commit", FULL, "--match-head-commit", OTHER, "7"],
        ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge", "-f", f"sha={OTHER}"],
    ],
)
def test_s055_2_a_merge_pinned_to_another_head_exits_2_naming_both(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    gate = FakeGate()
    _, refused = run(repo, tmp_path, args, gate)
    assert refused is not None
    assert f"pins #7's head to {OTHER}, and pr_gate.py reads #7 READY at {FULL}" in refused
    assert len(gate.calls) == 1


def test_s055_2_a_merge_api_put_with_input_is_refused_before_the_gate(repo: Repo, tmp_path: Path) -> None:
    gate = FakeGate()
    args = ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge", "--input", "body.json"]
    _, refused = run(repo, tmp_path, args, gate)
    assert refused is not None and "with --input its sha can't be read" in refused
    assert gate.calls == []


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["pr", "merge", "7"], ["pr", "merge", "7", "--match-head-commit", FULL]),
        (["pr", "merge", "-s", "--", "7"], ["pr", "merge", "-s", "--match-head-commit", FULL, "--", "7"]),
        (["pr", "merge", "-b", "--", "7"], ["pr", "merge", "-b", "--", "7", "--match-head-commit", FULL]),
        (
            ["pr", "merge", "--body", "--", "--", "7"],
            ["pr", "merge", "--body", "--", "--match-head-commit", FULL, "--", "7"],
        ),
        (
            ["api", "-X", "PUT", "repos/a/b/pulls/7/merge"],
            ["api", "-X", "PUT", "repos/a/b/pulls/7/merge", "-f", f"sha={FULL}"],
        ),
        (
            ["api", "-XPUT", "--", "repos/a/b/pulls/7/merge"],
            ["api", "-XPUT", "-f", f"sha={FULL}", "--", "repos/a/b/pulls/7/merge"],
        ),
    ],
)
def test_s055_2_the_pin_goes_before_the_end_of_the_flags(args: list[str], expected: list[str]) -> None:
    assert pinned(args, FULL) == expected
    assert merge_pins(expected) == [FULL]


def test_s055_2_a_ready_line_without_a_full_head_fails_closed(repo: Repo, tmp_path: Path) -> None:
    _, refused = run(repo, tmp_path, ["pr", "merge", "7"], FakeGate(verdict(head="abc1234") + "\n"))
    assert refused is not None and "READY but names no full head SHA" in refused


# -- S-055-3: the merge fails closed ------------------------------------------------------------


@pytest.mark.parametrize(
    "args", [["pr", "merge", "7", "--squash"], ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"]]
)
def test_s055_3_a_gate_that_exits_2_refuses_the_merge(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    gate = FakeGate("", 2, "pr_gate: `uvx shipmill==0.1.0 ...` failed for #7: no such version\n")
    _, refused = run(repo, tmp_path, args, gate)
    assert refused is not None
    assert "is refused: pr_gate.py printed no verdict for #7 (exit 2), so the merge fails closed" in refused
    assert "pr_gate: `uvx shipmill==0.1.0 ...` failed for #7: no such version" in refused


def test_s055_3_exit_2_refuses_even_with_a_ready_line(repo: Repo, tmp_path: Path) -> None:
    _, refused = run(repo, tmp_path, ["pr", "merge", "7"], FakeGate(verdict() + "\n", 2))
    assert refused is not None and "is refused: pr_gate.py reads #7 READY (exit 2)" in refused


@pytest.mark.parametrize("error", [FileNotFoundError(2, "No such file or directory"), PermissionError(13, "denied")])
def test_s055_3_a_gate_that_cant_start_refuses_the_merge(repo: Repo, tmp_path: Path, error: OSError) -> None:
    _, refused = run(repo, tmp_path, ["pr", "merge", "7"], FakeGate(raises=error))
    assert refused is not None and "pr_gate.py can't be started" in refused and "fails closed" in refused


@pytest.mark.parametrize("stdout", ["", "#8 READY head=" + FULL + "\n", "all good\n"])
def test_s055_3_exit_0_without_a_verdict_line_for_the_pr_refuses_the_merge(
    repo: Repo, tmp_path: Path, stdout: str
) -> None:
    _, refused = run(repo, tmp_path, ["pr", "merge", "7"], FakeGate(stdout, 0))
    assert refused is not None and "printed no verdict for #7 (exit 0)" in refused


def test_s055_3_without_the_apps_bot_login_the_merge_is_refused(repo: Repo, tmp_path: Path) -> None:
    key = connected(repo, tmp_path)
    reader, runner, gate = Reader(FakeReads((CODE,))), Runner(), FakeGate()
    with pytest.raises(ReleaseError, match="pr_gate.py needs the App's bot login, which can't be read"):
        gh(repo, tmp_path, key, ["pr", "merge", "7"], reader, runner, api=NoSlugApi(), gate=gate)
    assert (gate.calls, runner.calls) == ([], [])
