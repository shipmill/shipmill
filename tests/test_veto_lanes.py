"""Spec 059's setting: [gates] veto_lanes, the hourly tick it needs, and doctor's gates line"""

import datetime as dt
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.config import CONFIG_PATH
from shipmill.doctor import CALLER, doctor
from shipmill.errors import ReleaseError
from shipmill.policy import Lane, Policy
from shipmill.ticks import HOURLY, Ticks, needed

from .conftest import POLICY, Repo

TODAY = dt.date(2026, 11, 13)
HEAD = POLICY.split("[lanes.dev]", 1)[0]
AGENTS = '\n[agents]\nprompt = "/t"\napp_id = 1\n'


def _gates(veto: str) -> str:
    return f"\n[gates]\nveto_lanes = {veto}\n"


def _parse(text: str) -> Policy:
    return Policy.parse(tomllib.loads(text), "shipmill.toml")


def test_s059_1_veto_lanes_is_empty_by_default_and_reads_the_lanes_it_names() -> None:
    assert _parse(POLICY).veto_lanes == frozenset()
    assert _parse(POLICY + "\n[gates]\nblocker_lanes = []\n").veto_lanes == frozenset()
    assert _parse(POLICY + _gates("[]")).veto_lanes == frozenset()
    assert _parse(POLICY + _gates('["rc", "stable"]')).veto_lanes == {Lane.RC, Lane.STABLE}


BAD = {
    "hotfix": '["hotfix"]',
    "hotfix among others": '["rc", "hotfix"]',
    "not a lane": '["beta"]',
    "a string": '"rc"',
    "an empty name": '[""]',
    "not strings": "[1]",
    "a table": "{ rc = true }",
}


@pytest.mark.parametrize("value", BAD.values(), ids=BAD.keys())
def test_s059_1_a_value_not_a_list_of_releasing_lanes_exits_2_naming_the_key(value: str, tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="veto_lanes"):
        _parse(POLICY + _gates(value))
    path = tmp_path / CONFIG_PATH
    path.parent.mkdir()
    path.write_text(POLICY + _gates(value), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr.startswith("shipmill: shipmill.toml [gates]: veto_lanes ")


# lanes that, without veto_lanes, need no hourly tick: quiet_minutes only, or a window
QUIET = "[lanes.dev]\nquiet_minutes = 30\n\n[lanes.hotfix]\n"
WINDOW = '[lanes.rc]\nschedule = ["Mon 07:00 UTC"]\n\n[lanes.hotfix]\n'


@pytest.mark.parametrize(("lanes", "veto"), [(QUIET, '["dev"]'), (WINDOW, '["rc"]'), (WINDOW, '["rc", "stable"]')])
def test_s059_10_veto_lanes_naming_an_enabled_lane_needs_the_hourly_tick(lanes: str, veto: str) -> None:
    assert needed(_parse(HEAD + lanes), TODAY) != Ticks(hourly=True)
    assert needed(_parse(HEAD + lanes + _gates(veto)), TODAY) == Ticks(hourly=True)


def test_s059_10_veto_lanes_naming_only_lanes_not_enabled_needs_no_tick() -> None:
    assert needed(_parse(HEAD + QUIET + _gates('["rc", "stable"]')), TODAY) == Ticks(hourly=False)
    assert needed(_parse(HEAD + WINDOW + _gates('["dev"]')), TODAY).lines() == ("0 7 * * 1",)


def _release(*crons: str) -> str:
    schedule = "".join(f'    - cron: "{c}"\n' for c in crons)
    on = "on:\n  push:\n    branches: [main]\n" + (f"  schedule:\n{schedule}" if crons else "")
    return (
        f"name: Release\n{on}  workflow_dispatch:\n\njobs:\n"
        "  prepare:\n    uses: shipmill/shipmill/.github/workflows/prepare.yml@v0\n"
        "  land:\n    uses: shipmill/shipmill/.github/workflows/land.yml@v0\n"
    )


def _named(repo: Repo, name: str) -> list[str]:
    return [f"{c.status} {c.detail}" for c in doctor(repo.root, repo.github, today=TODAY) if c.name == name]


def test_s059_10_doctor_warns_when_release_yml_lacks_the_hourly_tick_veto_lanes_needs(repo: Repo) -> None:
    repo.write(str(CONFIG_PATH), HEAD + WINDOW + _gates('["rc"]'))
    repo.write(str(CALLER), _release("0 7 * * 1"))
    [check] = _named(repo, "schedule")
    assert check.startswith("WARN ") and f'"{HOURLY}"' in check and "init --caller --force" in check
    repo.write(str(CALLER), _release(HOURLY))
    assert _named(repo, "schedule") == [f"PASS {CALLER} has the hourly tick the policy's triggers need"]
    repo.write(str(CONFIG_PATH), HEAD + WINDOW)  # without veto_lanes, the window's cron is enough
    repo.write(str(CALLER), _release("0 7 * * 1"))
    [check] = _named(repo, "schedule")
    assert check.startswith("PASS ")


def test_s059_11_doctor_passes_a_gates_line_naming_the_lanes(repo: Repo) -> None:
    repo.write(str(CONFIG_PATH), POLICY + _gates('["stable", "rc"]') + AGENTS)
    assert _named(repo, "gates") == [
        "PASS veto_lanes rc, stable: a release waits for the veto window of each notify decision it ships"
    ]


@pytest.mark.parametrize("agents", ["", '\n[agents]\nprompt = "/t"\n'], ids=["no [agents]", "no app_id"])
def test_s059_11_doctor_warns_on_the_gates_line_without_an_app_id(repo: Repo, agents: str) -> None:
    repo.write(str(CONFIG_PATH), POLICY + _gates('["rc"]') + agents)
    [check] = _named(repo, "gates")
    assert check.startswith("WARN veto_lanes rc, but no [agents] app_id: ")
    assert "app-create" in check


@pytest.mark.parametrize("gates", ["", _gates("[]"), "\n[gates]\nblocker_lanes = []\n"])
def test_s059_11_doctor_prints_no_gates_line_without_veto_lanes(repo: Repo, gates: str) -> None:
    repo.write(str(CONFIG_PATH), POLICY + gates + AGENTS)
    assert _named(repo, "gates") == []
