"""Spec 056: `shipmill gh pr merge`, as the App, labels a pull request pr_gate.py reads QUEUED
with the land window's queued_label and merges nothing, and a merge gh ran that exited 0 takes
that label off (S-056-8). No test reaches the network: the pull request is FakeReads,
pr_gate.py FakeGate, the label writes Capture, GitHub MintApi"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.errors import ReleaseError
from shipmill.merge_gate import unlabel_args

from .conftest import POLICY, Repo
from .test_app import REPO
from .test_app_gh_merge import CODE, WITH_APP, FakeGate, FakeReads, Reader, Runner, connected, gh, pinned_to, verdict
from .test_credit import CreditReader, FakeCredit, approved
from .test_decider_token import ACCESS, ASSISTED, EnvRunner, store
from .test_decider_token import gh as decider_gh

WINDOW = '\n[land.window]\ntimezone = "UTC"\nlabels = ["rollout:high"]\n'
HELD = verdict("QUEUED") + "\n  queued: held by the land window (rollout:high); opens 2026-11-14 09:00 UTC\n"
ADD = ["api", "--silent", "-X", "POST", f"repos/{REPO}/issues/7/labels", "-f", "labels[]=land-queued"]
REMOVE = ["api", "--silent", "-X", "DELETE", f"repos/{REPO}/issues/7/labels/land-queued"]
MERGES = [["pr", "merge", "7", "--squash"], ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"]]


def queued() -> FakeGate:
    """pr_gate.py reading #7 QUEUED, as it exits for it (spec 056)"""
    return FakeGate(HELD, 10)


@dataclass
class Capture:
    """The gh shipmill runs for the label writes, its stdout captured: records each call and its
    env, and exits with code"""

    code: int = 0
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env)))
        return self.code, ""


@dataclass
class FailingRunner(Runner):
    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        super().__call__(argv, env)
        return 1


def merge(
    repo: Repo,
    tmp_path: Path,
    args: list[str],
    gate: FakeGate,
    capture: Capture,
    *,
    window: str = WINDOW,
    labels: tuple[str, ...] = (),
    runner: Runner | None = None,
) -> tuple[Runner, int | str]:
    """gh as the App, the base's config ending in window: gh's runner and its exit code, or the
    refusal"""
    key = connected(repo, tmp_path, POLICY + WITH_APP + window)
    reader, ran = Reader(FakeReads((CODE,), labels=labels)), runner or Runner()
    try:
        return ran, gh(repo, tmp_path, key, args, reader, ran, gate=gate, capture=capture)
    except ReleaseError as exc:  # cli.run prints it and exits 2
        return ran, str(exc)


def sent(capture: Capture) -> list[list[str]]:
    """The label writes' args, past gh's path, each checked to go as the App"""
    assert all(env["GH_TOKEN"] == "token-1" for _, env in capture.calls)
    return [argv[1:] for argv, _ in capture.calls]


@pytest.mark.parametrize("args", MERGES)
def test_s056_8_a_queued_pr_is_labelled_as_the_app_and_never_merged(
    repo: Repo, tmp_path: Path, args: list[str]
) -> None:
    capture = Capture()
    runner, refused = merge(repo, tmp_path, args, queued(), capture)
    assert isinstance(refused, str) and "is refused: pr_gate.py reads #7 QUEUED (exit 10)" in refused
    assert "  queued: held by the land window (rollout:high)" in refused
    assert runner.calls == []  # the merge never runs
    assert sent(capture) == [ADD]


def test_s056_8_the_configs_queued_label_is_the_one_added(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    runner, refused = merge(repo, tmp_path, MERGES[0], queued(), capture, window=WINDOW + 'queued_label = "held"\n')
    assert isinstance(refused, str) and runner.calls == []
    assert sent(capture) == [[*ADD[:-1], "labels[]=held"]]


def test_s056_8_a_queued_pr_carrying_the_label_is_not_labelled_again(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    runner, refused = merge(repo, tmp_path, MERGES[0], queued(), capture, labels=("Land-Queued",))
    assert isinstance(refused, str) and "reads #7 QUEUED" in refused
    assert (runner.calls, capture.calls) == ([], [])


def test_s056_8_a_label_that_cant_be_added_is_named_beside_the_refusal(repo: Repo, tmp_path: Path) -> None:
    capture = Capture(code=1)
    runner, refused = merge(repo, tmp_path, MERGES[0], queued(), capture)
    assert isinstance(refused, str) and "is refused: pr_gate.py reads #7 QUEUED" in refused
    assert "adding land-queued to #7 failed (gh exited 1)" in refused
    assert runner.calls == []


@pytest.mark.parametrize("args", MERGES)
def test_s056_8_a_merge_that_exits_0_removes_the_queued_label_as_the_app(
    repo: Repo, tmp_path: Path, args: list[str]
) -> None:
    capture = Capture()
    runner, code = merge(repo, tmp_path, args, FakeGate(), capture, labels=("rollout:high", "land-queued"))
    assert code == 0
    assert [argv[1:] for argv in runner.calls] == [pinned_to(args)]
    assert sent(capture) == [REMOVE]


def test_s056_8_a_merge_of_a_pr_without_the_label_removes_nothing(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    runner, code = merge(repo, tmp_path, MERGES[0], FakeGate(), capture, labels=("rollout:high",))
    assert (code, len(runner.calls), capture.calls) == (0, 1, [])


def test_s056_8_a_merge_gh_fails_keeps_the_label(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    runner, code = merge(
        repo, tmp_path, MERGES[0], FakeGate(), capture, labels=("land-queued",), runner=FailingRunner()
    )
    assert (code, len(runner.calls), capture.calls) == (1, 1, [])


def test_s056_8_a_label_that_cant_be_removed_names_the_merge_as_done(repo: Repo, tmp_path: Path) -> None:
    capture = Capture(code=1)
    runner, refused = merge(repo, tmp_path, MERGES[0], FakeGate(), capture, labels=("land-queued",))
    assert isinstance(refused, str) and "the merge of #7 in romamo/demo went through" in refused
    assert len(runner.calls) == 1 and sent(capture) == [REMOVE]


def test_s056_8_without_a_land_window_a_queued_verdict_is_refused_as_before(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    runner, refused = merge(repo, tmp_path, MERGES[0], queued(), capture, window="")
    assert isinstance(refused, str) and "reads #7 QUEUED" in refused
    assert (runner.calls, capture.calls) == ([], [])


def test_s056_8_without_a_land_window_a_merge_removes_no_label(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    runner, code = merge(repo, tmp_path, MERGES[0], FakeGate(), capture, window="", labels=("land-queued",))
    assert (code, len(runner.calls), capture.calls) == (0, 1, [])


def test_s056_8_queued_with_another_exit_is_refused_without_a_label(repo: Repo, tmp_path: Path) -> None:
    capture = Capture()
    gate = FakeGate(HELD, 2)
    runner, refused = merge(repo, tmp_path, MERGES[0], gate, capture)
    assert isinstance(refused, str) and "reads #7 QUEUED (exit 2)" in refused
    assert (runner.calls, capture.calls) == ([], [])


def test_s056_8_a_merge_written_as_the_decider_removes_the_label_as_the_app(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, ASSISTED + WINDOW)
    store(tmp_path)
    runner, capture = EnvRunner(capsys), Capture()
    reader = CreditReader(FakeCredit(reviews=[approved("octocat", "MEMBER")]))
    code = decider_gh(repo, tmp_path, key, MERGES[0], runner, reader, labels=("land-queued",), capture=capture)
    assert code == 0 and runner.token == ACCESS  # the merge went out as the decider (D-65)
    assert sent(capture) == [REMOVE]  # the label as the App's token, never the decider's (D-54)


def test_s056_8_a_label_is_quoted_in_the_removals_path() -> None:
    assert unlabel_args(REPO, 7, "land queued/x")[-1] == f"repos/{REPO}/issues/7/labels/land%20queued%2Fx"
