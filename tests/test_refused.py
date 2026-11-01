"""Spec 052: a refused config key stops only the feature it configures. The catalogue
(S-052-1), loading a config that sets one (S-052-2 to S-052-4), the stderr line (S-052-5), the
stable lane off while min_soak_days is set (S-052-6, S-052-7), and the dropped criteria of
specs 029 and 031 (S-052-13)"""

import datetime as dt
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from shipmill import refused
from shipmill.agents import PLUGIN_UPDATE_REMOVED, AgentsConfig
from shipmill.cli import main
from shipmill.config import Table, config_path
from shipmill.errors import ReleaseError
from shipmill.planner import Event
from shipmill.policy import SOAK_REMOVED, Lane, Policy
from shipmill.refused import CATALOGUE, MIN_SOAK_DAYS, PLUGIN_UPDATE

from .conftest import POLICY, Repo, at_day
from .test_lanes import plan, release

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/shipmill:github-issue-triage {repo} triage the new issues"\nretry_hours = 12\n'
VALUES = ["3", "0", "true", '"yes"', "[1]"]  # any value, of the wrong type too
SOAK_OFF = (
    "[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade --apply"
    " stable-every-batch; the stable lane is off"
)


def soaked(text: str = POLICY, value: str = "3") -> str:
    """text with [lanes.stable] min_soak_days set"""
    assert 'promote_from = "rc"\n' in text
    return text.replace('promote_from = "rc"\n', f'promote_from = "rc"\nmin_soak_days = {value}\n')


def parsed(text: str) -> Policy:
    return Policy.parse(tomllib.loads(text), "shipmill.toml")


def shipmill(repo: Repo, *args: str) -> subprocess.CompletedProcess[str]:
    """The CLI in its own process, as a workflow or the gate runs it"""
    return subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(repo.root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# -- S-052-1: the catalogue --------------------------------------------------------------------


def test_s052_1_the_catalogue_lists_both_refused_keys_with_what_they_turn_off_and_their_fix() -> None:
    assert CATALOGUE == (MIN_SOAK_DAYS, PLUGIN_UPDATE)
    soak = (MIN_SOAK_DAYS.table, MIN_SOAK_DAYS.key, MIN_SOAK_DAYS.spec, MIN_SOAK_DAYS.off, MIN_SOAK_DAYS.lane)
    assert soak == ("[lanes.stable]", "min_soak_days", "029", "the stable lane", Lane.STABLE)
    assert MIN_SOAK_DAYS.fix == "delete it, or run shipmill upgrade --apply stable-every-batch"
    plugin = (PLUGIN_UPDATE.table, PLUGIN_UPDATE.key, PLUGIN_UPDATE.spec, PLUGIN_UPDATE.lane)
    assert plugin == ("[agents]", "plugin_update", "031", None)
    assert PLUGIN_UPDATE.off == "nothing: gate sessions load the installed plugin"
    assert PLUGIN_UPDATE.fix == "delete it"
    assert (MIN_SOAK_DAYS.turns_off, PLUGIN_UPDATE.turns_off) == (True, False)


def test_s052_1_each_message_is_todays_line_then_what_it_turns_off() -> None:
    assert MIN_SOAK_DAYS.removed == SOAK_REMOVED  # the line a load raised before spec 052
    assert PLUGIN_UPDATE.removed == PLUGIN_UPDATE_REMOVED == "[agents] plugin_update was removed (spec 031); delete it"
    assert MIN_SOAK_DAYS.message == SOAK_OFF
    assert PLUGIN_UPDATE.message == PLUGIN_UPDATE_REMOVED  # it turns nothing off
    assert PLUGIN_UPDATE.named == "[agents] plugin_update (spec 031)"


# -- S-052-2, S-052-3: the config loads without the key -----------------------------------------


@pytest.mark.parametrize("value", VALUES)
def test_s052_2_min_soak_days_loads_whatever_its_value_and_the_table_reads_as_without_it(value: str) -> None:
    for text in (POLICY, POLICY.replace('promote_from = "rc"\n', 'promote_from = "rc"\nquiet_minutes = 30\n')):
        policy, without = parsed(soaked(text, value)), parsed(text)
        assert policy.refused == (MIN_SOAK_DAYS,)
        assert policy.lanes == without.lanes  # every other key of [lanes.stable], and every other lane
        assert replace(policy, refused=()) == without
        assert policy.lane_off(Lane.STABLE) == MIN_SOAK_DAYS
        assert {policy.lane_off(ln) for ln in (Lane.DEV, Lane.RC, Lane.HOTFIX)} == {None}


def test_s052_2_policy_load_names_it(repo: Repo) -> None:
    repo.write(repo.policy_file, soaked())
    assert Policy.load(config_path(repo.root)).refused == (MIN_SOAK_DAYS,)


@pytest.mark.parametrize("value", VALUES)
def test_s052_3_plugin_update_loads_whatever_its_value_and_agents_reads_as_without_it(value: str) -> None:
    text = POLICY + AGENTS
    policy, without = parsed(text + f"plugin_update = {value}\n"), parsed(text)
    assert policy.refused == (PLUGIN_UPDATE,)
    assert policy.agents is not None and without.agents is not None
    assert replace(policy.agents, refused=()) == without.agents
    assert replace(policy, refused=(), agents=without.agents) == without
    assert policy.lane_off(Lane.STABLE) is None  # it turns nothing off


@pytest.mark.parametrize("value", VALUES)
def test_s052_3_agents_config_parse_alone_drops_it_too(value: str) -> None:
    raw = tomllib.loads(POLICY + AGENTS + f"plugin_update = {value}\n")
    agents = AgentsConfig.parse(Table(raw, "shipmill.toml").table("agents"))
    without = AgentsConfig.parse(Table(tomllib.loads(POLICY + AGENTS), "shipmill.toml").table("agents"))
    assert agents.refused == (PLUGIN_UPDATE,)
    assert replace(agents, refused=()) == without
    assert agents.retry_hours == 12


def test_s052_3_both_keys_in_one_config_are_both_named(repo: Repo) -> None:
    repo.write(repo.policy_file, soaked() + AGENTS + "plugin_update = true\n")
    assert repo.policy.refused == (MIN_SOAK_DAYS, PLUGIN_UPDATE)
    assert AgentsConfig.load(repo.root).refused == (PLUGIN_UPDATE,)


# -- S-052-4: a key no release knew still fails -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key"),
    [
        (POLICY.replace('promote_from = "rc"\n', 'promote_from = "rc"\nmin_soak_day = 3\n'), "min_soak_day"),
        (soaked().replace('promote_from = "rc"\n', 'promote_from = "rc"\nsoak = 3\n'), "soak"),
        (POLICY + AGENTS + "plugin_updates = true\n", "plugin_updates"),
        (POLICY + AGENTS + "plugin_update = true\nwhen = 1\n", "when"),
    ],
    ids=["stable typo", "stable unknown beside the refused key", "agents typo", "agents unknown beside it"],
)
def test_s052_4_a_key_no_release_knew_still_exits_2_naming_it(repo: Repo, text: str, key: str) -> None:
    repo.write(repo.policy_file, text)
    done = shipmill(repo, "plan", "--dry-run")
    assert done.returncode == 2
    assert done.stdout == ""
    assert re.search(rf"unknown keys \['{key}'\]", done.stderr), done.stderr
    assert "refused" not in done.stderr  # the load failed before any refusal was said


# -- S-052-5: the stderr line, once; stdout and the exit code as without the key ------------------


def test_s052_5_plan_says_the_plugin_update_refusal_once_and_otherwise_runs_as_without_it(repo: Repo) -> None:
    now = at_day(1).isoformat()
    repo.write(repo.policy_file, POLICY + AGENTS)
    without = shipmill(repo, "plan", "--dry-run", "--event", "schedule", "--now", now)
    repo.write(repo.policy_file, POLICY + AGENTS + "plugin_update = false\n")
    done = shipmill(repo, "plan", "--dry-run", "--event", "schedule", "--now", now)
    assert (without.returncode, without.stderr) == (0, "")
    assert done.stderr == f"shipmill: refused: {PLUGIN_UPDATE_REMOVED}\n"
    assert (done.returncode, done.stdout) == (without.returncode, without.stdout)


def test_s052_5_plan_says_the_min_soak_days_refusal_once_and_only_the_stable_line_differs(repo: Repo) -> None:
    now = at_day(1).isoformat()
    without = shipmill(repo, "plan", "--dry-run", "--event", "schedule", "--now", now)
    repo.write(repo.policy_file, soaked())
    done = shipmill(repo, "plan", "--dry-run", "--event", "schedule", "--now", now)
    assert done.stderr == f"shipmill: refused: {SOAK_OFF}\n"
    assert done.returncode == without.returncode == 0
    off, before = json.loads(done.stdout), json.loads(without.stdout)
    stable = "stable: no rc after 1.0.0 to promote"
    assert stable in before["reason"]
    assert off["reason"] == before["reason"].replace(stable, f"stable: off: {SOAK_OFF}")
    assert {k: v for k, v in off.items() if k != "reason"} == {k: v for k, v in before.items() if k != "reason"}


def test_s052_5_a_command_loading_the_config_twice_says_each_refusal_once(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.write(repo.policy_file, soaked() + AGENTS + "plugin_update = true\n")
    refused.begin()
    for _ in range(2):
        Policy.load(config_path(repo.root))
        AgentsConfig.load(repo.root)
    assert capsys.readouterr().err == f"shipmill: refused: {SOAK_OFF}\nshipmill: refused: {PLUGIN_UPDATE_REMOVED}\n"
    for _ in range(2):  # each command says it again, once
        assert main(["--repo", str(repo.root), "settle-minutes"], github=repo.github) == 0
        captured = capsys.readouterr()
        assert captured.err == f"shipmill: refused: {SOAK_OFF}\nshipmill: refused: {PLUGIN_UPDATE_REMOVED}\n"
        assert captured.out == "30\n"


def test_s052_5_a_config_without_a_refused_key_says_nothing(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    assert main(["--repo", str(repo.root), "settle-minutes"], github=repo.github) == 0
    assert capsys.readouterr().err == ""


def test_s052_5_shipmills_own_config_sets_no_refused_key() -> None:
    assert Policy.load(config_path(ROOT)).refused == ()


# -- S-052-6, S-052-7: the stable lane is off ----------------------------------------------------

LATER = at_day(1, 9) + dt.timedelta(minutes=40)  # after rc1 and Fix B: stable's Monday window and dev are due


def rc_then_fix(repo: Repo) -> None:
    """rc1 of Feature A, then Fix B on main: stable would promote rc1, dev would build Fix B"""
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))  # rc1
    repo.at(at_day(1, 9))
    repo.merge(2, "Fixed", "Fix B")


def test_s052_6_the_stable_lane_is_off_and_dev_plans_as_without_the_key(repo: Repo) -> None:
    rc_then_fix(repo)
    due = plan(repo, LATER)
    assert (due.action, due.lane, str(due.version)) == ("release", Lane.STABLE, "1.1.0")  # due without the key
    repo.write(repo.policy_file, soaked())
    off = plan(repo, LATER)
    assert off.lane is Lane.DEV and off.action == "release"
    # dev and rc plan as on the same config whose stable lane isn't due, save the stable line
    repo.write(repo.policy_file, POLICY.replace('schedule = ["Mon 07:00 UTC"]\n', ""))
    alone = plan(repo, LATER)
    assert (off.action, off.lane, off.version, off.base) == (alone.action, alone.lane, alone.version, alone.base)
    assert off.reason == f"{alone.reason}; stable: off: {SOAK_OFF}"


def test_s052_6_plan_says_stable_off_and_releases_nothing_on_it(repo: Repo) -> None:
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))  # rc1: stable's window would promote it at once
    repo.write(repo.policy_file, soaked(value="0"))
    decision = plan(repo, at_day(1, 9))
    assert (decision.action, decision.lane, decision.version) == ("skip", None, None)
    assert decision.reason.startswith(f"stable: off: {SOAK_OFF}; ")
    assert "rc: an rc of 1.1.0 already holds main's head" in decision.reason


def test_s052_7_a_stable_release_by_hand_exits_2_with_the_message(repo: Repo) -> None:
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))  # rc1, which a hand start would promote without the key
    assert plan(repo, at_day(1, 9), event=Event.MANUAL, lane=Lane.STABLE).action == "release"
    repo.write(repo.policy_file, soaked())
    with pytest.raises(ReleaseError) as caught:
        plan(repo, at_day(1, 9), event=Event.MANUAL, lane=Lane.STABLE)
    assert str(caught.value) == f"stable: off: {SOAK_OFF}"
    done = shipmill(repo, "plan", "--lane", "stable", "--event", "workflow_dispatch", "--dry-run")
    assert done.returncode == 2
    assert done.stdout == ""  # no plan, so no release
    assert done.stderr == f"shipmill: refused: {SOAK_OFF}\nshipmill: stable: off: {SOAK_OFF}\n"
    # the other lanes still plan by hand, as without the key
    assert (
        plan(repo, at_day(1, 9), event=Event.MANUAL, lane=Lane.DEV).reason == "dev: v1.1.0rc1 already holds main's head"
    )


# -- S-052-13: the criteria spec 052 replaces are dropped -----------------------------------------


@pytest.mark.parametrize(
    ("spec", "criterion", "replaced_by"),
    [
        ("029-stable-every-batch.md", "S-029-9", ("S-052-2", "S-052-5", "S-052-6", "S-052-7")),
        ("031-plugin-pinned-release.md", "S-031-22", ("S-052-3", "S-052-5")),
    ],
)
def test_s052_13_specs_029_and_031_mark_the_exit_2_dropped(
    spec: str, criterion: str, replaced_by: tuple[str, ...]
) -> None:
    text = (ROOT / "docs" / "specs" / spec).read_text(encoding="utf-8")
    criteria = text.split("## Acceptance criteria", 1)[1].split("\n## ", 1)[0]
    [line] = [ln for ln in criteria.splitlines() if ln.startswith(f"- {criterion}: ")]
    assert line.startswith(f"- {criterion}: dropped in #859, see "), line
    for replacement in replaced_by:
        assert replacement in line
