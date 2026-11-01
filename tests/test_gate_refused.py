"""S-052-10: a gate tick on a config that sets a refused key runs as it would without the key,
its decision line ends with the refusal, and tick.json records it; the tick is never an ERROR
tick, and `shipmill status` and `shipmill factory` read its tick.json as they do any other"""

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.autonomy import Hold
from shipmill.errors import ReleaseError
from shipmill.gate import (
    ERROR,
    TICK,
    Action,
    Decision,
    InFlight,
    LastResult,
    TickRecord,
    gate,
    load_tick,
    state_dir,
    tick_lines,
    tick_record,
)
from shipmill.gitrepo import Git
from shipmill.refused import MIN_SOAK_DAYS, PLUGIN_UPDATE, in_checkout
from tests.test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg, host
from tests.test_gate_tick_report import AT, SINCE, gate_line, ticked

REPO = "romamo/demo"
AGENTS = '[agents]\nprompt = "/t"\n'
SUFFIX = "; refused: [agents] plugin_update (spec 031)"
RECORDED = {
    "key": "[agents] plugin_update",
    "spec": "031",
    "off": "nothing: gate sessions load the installed plugin",
    "fix": "delete it",
}


def checkout(root: Path, config: str) -> Git:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git = Git(root)
    git.run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    return git


NO_HOLD = Hold()


def run(git: Git, claude: FakeClaude, hold: Hold = NO_HOLD) -> tuple[Decision, str | None]:
    """A real tick on the checkout's own config, as `shipmill gate` reads it"""
    decision, launched, _, _ = gate(
        git,
        REPO,
        lambda: AgentsConfig.load(git.root, REPO),
        claude,
        lambda _: [ISSUES],
        NOW,
        lambda: hold,
        FakeNotifier(),
        NO_PRUNE,
        login=host,
        refusals=lambda: in_checkout(git.root),
    )
    return decision, launched


def tick_json(git: Git) -> dict[str, object]:
    found: dict[str, object] = json.loads((state_dir(git) / TICK).read_text(encoding="utf-8"))
    return found


def test_s052_10_a_tick_with_plugin_update_launches_as_without_it_and_names_the_refusal(tmp_path: Path) -> None:
    plain = checkout(tmp_path / "plain", AGENTS)
    refused = checkout(tmp_path / "refused", f"{AGENTS}plugin_update = true\n")
    plain_claude, refused_claude = FakeClaude(), FakeClaude()
    without, launched_without = run(plain, plain_claude)
    with_key, launched_with = run(refused, refused_claude)

    assert with_key.action is Action.LAUNCH
    assert dataclasses.replace(with_key, refused=()) == without  # the same decision, the same work
    assert launched_with == launched_without and refused_claude.launched == plain_claude.launched
    assert with_key.refused == (PLUGIN_UPDATE,) and without.refused == ()

    first = tick_lines(with_key, launched_with, (), (), dry_run=False)[0]
    assert first.endswith(SUFFIX) and first == tick_lines(without, launched_without, (), (), dry_run=False)[0] + SUFFIX

    written = tick_json(refused)
    assert written["action"] == "LAUNCH" != ERROR and written["failing"] is None
    assert written["refused"] == [RECORDED]
    assert written["reason"] == tick_json(plain)["reason"]  # the line's suffix is not the reason's
    assert "refused" not in tick_json(plain)  # a tick.json without a refusal reads as before
    assert tick_record(with_key, launched_with, (), (), dry_run=False)["refused"] == [RECORDED]
    assert tick_record(without, launched_without, (), (), dry_run=False)["refused"] == []
    loaded = load_tick(state_dir(refused) / TICK)
    assert loaded is not None and loaded.refused == (PLUGIN_UPDATE,)


@pytest.mark.parametrize(
    ("claude", "hold", "action"),
    [
        (FakeClaude([bg("a", "busy", "working")]), Hold(), Action.RUNNING),  # a tick that reads no config
        (FakeClaude(), Hold(("#5 hold the releases",)), Action.HELD),
    ],
)
def test_s052_10_every_decision_line_ends_with_the_refusal(
    tmp_path: Path, claude: FakeClaude, hold: Hold, action: Action
) -> None:
    git = checkout(tmp_path / "demo", f"{AGENTS}plugin_update = true\n")
    decision, launched = run(git, claude, hold)
    assert decision.action is action
    assert tick_lines(decision, launched, (), (), dry_run=False)[0].endswith(SUFFIX)
    assert tick_json(git)["refused"] == [RECORDED] and tick_json(git)["failing"] is None


def test_s052_10_each_refusal_ends_the_line_in_catalogue_order(tmp_path: Path) -> None:
    config = f"{AGENTS}plugin_update = false\n\n[lanes.stable]\nmin_soak_days = 3\n"
    git = checkout(tmp_path / "demo", config)
    assert in_checkout(git.root) == (MIN_SOAK_DAYS, PLUGIN_UPDATE)
    decision, launched = run(git, FakeClaude())
    first = tick_lines(decision, launched, (), (), dry_run=False)[0]
    assert first.endswith(f"; refused: [lanes.stable] min_soak_days (spec 029){SUFFIX}")
    loaded = load_tick(state_dir(git) / TICK)
    assert loaded is not None and loaded.refused == (MIN_SOAK_DAYS, PLUGIN_UPDATE)


def test_s052_10_a_config_without_the_file_or_the_key_refuses_nothing(tmp_path: Path) -> None:
    assert in_checkout(tmp_path) == ()
    assert in_checkout(checkout(tmp_path / "demo", AGENTS).root) == ()


def test_s052_10_an_error_tick_still_records_its_refusals(tmp_path: Path) -> None:
    git = checkout(tmp_path / "demo", f"{AGENTS}plugin_update = true\n")

    def broken() -> AgentsConfig:
        raise ReleaseError("the config is broken", "fix it")

    with pytest.raises(ReleaseError):
        gate(
            git, REPO, broken, FakeClaude(), lambda _: [ISSUES], NOW, Hold, FakeNotifier(), NO_PRUNE,
            refusals=lambda: in_checkout(git.root),
        )  # fmt: skip
    written = tick_json(git)
    assert written["action"] == ERROR and written["refused"] == [RECORDED]  # the error is another key's


def test_s052_10_a_tick_json_refusal_must_be_well_formed(tmp_path: Path) -> None:
    path = tmp_path / TICK
    record = TickRecord(AT, "QUIET", "no change", None, None, refused=(PLUGIN_UPDATE,)).record()
    for bad in ({**RECORDED, "key": "plugin_update"}, {"key": "[agents] plugin_update"}, "plugin_update"):
        path.write_text(json.dumps({**record, "refused": [bad]}), encoding="utf-8")
        with pytest.raises(ReleaseError, match="malformed"):
            load_tick(path)


def test_s052_10_status_and_factory_read_a_refused_tick_as_its_decision() -> None:
    """The gate log's line ends with the suffix; the record is still the tick behind it"""
    flight = InFlight((771,), (), (), None, LastResult("s5", "PRS_OPEN #770", SINCE))
    reason = f"no change since 2026-10-07T09:00; {flight.line(AT)}"
    record = TickRecord(AT, "QUIET", reason, None, None, None, flight, (PLUGIN_UPDATE,))
    check = gate_line(ticked(record, f"QUIET: {reason}{SUFFIX}", exit_code="0"))
    assert check.value.startswith("quiet: in flight: 1 waits on CI (#771)")
    assert check.ok and check.fixes == ()
