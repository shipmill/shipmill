"""Spec 030: the [decisions] section of .github/shipmill.toml and its validation"""

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.decide import DecisionPolicy, Level, VetoHours, Zone, zones
from shipmill.errors import ReleaseError
from shipmill.gate import skills_dir
from shipmill.policy import Policy

from .conftest import POLICY

WHERE = "shipmill.toml [decisions]"
ZONE_IDS = (
    "direction, decision-policy, scope, rule-departure, contract-change, contract-addition, security, "
    "protected, interpretation, triage-verdict, implementation, unknown"
)
LEVELS = "['act', 'notify', 'ask', 'never']"
DEFAULTS = {
    Zone.DIRECTION: Level.NEVER,
    Zone.DECISION_POLICY: Level.NEVER,
    Zone.SCOPE: Level.ASK,
    Zone.RULE_DEPARTURE: Level.ASK,
    Zone.CONTRACT_CHANGE: Level.ASK,
    Zone.CONTRACT_ADDITION: Level.NOTIFY,
    Zone.SECURITY: Level.ASK,
    Zone.PROTECTED: Level.ASK,
    Zone.INTERPRETATION: Level.NOTIFY,
    Zone.TRIAGE_VERDICT: Level.NOTIFY,
    Zone.IMPLEMENTATION: Level.ACT,
    Zone.UNKNOWN: Level.ASK,
}


def decisions(text: str) -> DecisionPolicy:
    return Policy.parse(tomllib.loads(POLICY + text), "shipmill.toml").decisions


def refused(text: str) -> str:
    with pytest.raises(ReleaseError) as caught:
        decisions(text)
    return str(caught.value)


def section(*lines: str) -> str:
    return "\n[decisions]\n" + "".join(f"{line}\n" for line in lines)


def test_s030_1_without_the_section_every_zone_has_its_default_and_the_window_is_24_hours() -> None:
    policy = decisions("")
    assert policy.levels == DEFAULTS
    assert list(policy.levels) == list(DEFAULTS)  # the zone table's order
    assert int(policy.veto_hours) == 24
    assert not any(policy.is_configured(zone) for zone in Zone)


def test_s030_1_an_empty_section_is_the_defaults_too() -> None:
    assert decisions(section()) == DecisionPolicy()


def test_s030_1_a_set_zone_overrides_its_default_and_the_rest_keep_theirs() -> None:
    policy = decisions(section('contract-addition = "act"', 'triage-verdict = "ask"', "veto_hours = 48"))
    assert policy.level(Zone.CONTRACT_ADDITION) is Level.ACT
    assert policy.level(Zone.TRIAGE_VERDICT) is Level.ASK
    assert policy.level(Zone.INTERPRETATION) is Level.NOTIFY
    assert policy.is_configured(Zone.CONTRACT_ADDITION)
    assert not policy.is_configured(Zone.INTERPRETATION)
    assert int(policy.veto_hours) == 48


def test_s030_1_the_window_bounds_are_inclusive() -> None:
    assert int(decisions(section("veto_hours = 1")).veto_hours) == 1
    assert int(decisions(section("veto_hours = 168")).veto_hours) == 168


def test_s030_2_an_unknown_key_is_refused_listing_the_zone_ids() -> None:
    assert refused(section('colour = "act"')) == (
        f"{WHERE}: unknown key 'colour'; a key is veto_hours or a zone id: {ZONE_IDS}"
    )


@pytest.mark.parametrize("value", ['"maybe"', '"ACT"', "1", "true", '["act"]'])
def test_s030_2_a_value_that_is_no_level_is_refused_naming_the_four_levels(value: str) -> None:
    got = repr(tomllib.loads(f"v = {value}")["v"])
    assert refused(section(f"implementation = {value}")) == (
        f"{WHERE}: implementation must be one of {LEVELS}, got {got}"
    )


FLOORS = {
    "direction": ('"act"', "ask", "only the maintainer changes the direction (D-34)"),
    "scope": (
        '"notify"',
        "ask",
        "only the maintainer accepts an opportunity, approves a spec, or plans a goal (D-10)",
    ),
    "rule-departure": (
        '"notify"',
        "ask",
        "a departure from a D-n or a spec's criterion needs the maintainer's approval (Q-5)",
    ),
    "security": ('"act"', "notify", "a change to workflows, secrets, or permissions is always told (D-48)"),
    "unknown": ('"notify"', "ask", "a decision no zone covers waits for the maintainer (D-48)"),
}


@pytest.mark.parametrize("zone", FLOORS)
def test_s030_3_a_level_below_its_zones_floor_is_refused_naming_the_floor(zone: str) -> None:
    value, floor, why = FLOORS[zone]
    assert refused(section(f"{zone} = {value}")) == f"{WHERE}: {zone} = {value} is below its floor {floor}: {why}"


def test_s030_3_the_spec_gives_the_direction_message_word_for_word() -> None:
    assert refused(section('direction = "act"')) == (
        f'{WHERE}: direction = "act" is below its floor ask: only the maintainer changes the direction (D-34)'
    )


def test_s030_3_a_level_at_or_above_the_floor_is_accepted() -> None:
    policy = decisions(section('direction = "ask"', 'security = "notify"', 'scope = "never"', 'unknown = "ask"'))
    assert policy.level(Zone.DIRECTION) is Level.ASK
    assert policy.level(Zone.SECURITY) is Level.NOTIFY
    assert policy.level(Zone.SCOPE) is Level.NEVER
    assert policy.level(Zone.UNKNOWN) is Level.ASK


def test_s030_3_a_zone_without_a_floor_takes_any_level() -> None:
    for level in Level:
        assert decisions(section(f'contract-change = "{level}"')).level(Zone.CONTRACT_CHANGE) is level


@pytest.mark.parametrize("value", ['"never"', '"act"', '"ask"', "1"])
def test_s030_4_a_decision_policy_key_is_refused_whatever_its_value(value: str) -> None:
    assert refused(section(f"decision-policy = {value}")) == (
        f"{WHERE}: decision-policy is fixed at never: only the maintainer changes [decisions] (D-48); remove the key"
    )


@pytest.mark.parametrize("zone", ["release", "deploy", "rollback", "intake", "upgrade"])
def test_s030_4_a_release_side_zone_is_refused_naming_autonomy(zone: str) -> None:
    assert refused(section(f'{zone} = "ask"')) == f"{WHERE}: {zone} is set in [autonomy] {zone}; move it there"


def test_s030_4_breaking_release_is_refused_naming_d39() -> None:
    assert refused(section('breaking-release = "act"')) == (
        f"{WHERE}: breaking-release is fixed: a breaking stable release waits for a person's hand start (D-39);"
        " remove the key"
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("0", "veto_hours must be in 1..168, got 0"),
        ("169", "veto_hours must be in 1..168, got 169"),
        ("-1", "veto_hours must be in 1..168, got -1"),
        ("24.0", "veto_hours must be an integer, got 24.0"),
        ('"24"', "veto_hours must be an integer, got '24'"),
        ("true", "veto_hours must be an integer, got True"),
    ],
)
def test_s030_4_a_veto_window_outside_1_to_168_or_not_an_integer_is_refused(value: str, message: str) -> None:
    assert refused(section(f"veto_hours = {value}")) == f"{WHERE}: {message}"


def test_s030_4_a_decisions_key_that_is_not_a_table_is_refused() -> None:
    with pytest.raises(ReleaseError) as caught:
        Policy.parse(tomllib.loads("decisions = 1\n" + POLICY), "shipmill.toml")
    assert str(caught.value) == "shipmill.toml: decisions must be a table, got 1"


EXITS = {
    "S-030-2 unknown key": (section('colour = "act"'), "unknown key 'colour'"),
    "S-030-2 no level": (section('implementation = "maybe"'), f"must be one of {LEVELS}"),
    "S-030-3 below the floor": (section('direction = "act"'), "is below its floor ask"),
    "S-030-4 decision-policy": (section('decision-policy = "never"'), "decision-policy is fixed at never"),
    "S-030-4 release side": (section('release = "act"'), "release is set in [autonomy] release"),
    "S-030-4 breaking-release": (section('breaking-release = "ask"'), "(D-39)"),
    "S-030-4 veto window": (section("veto_hours = 169"), "veto_hours must be in 1..168"),
}


# proves: S-030-2, S-030-3
@pytest.mark.parametrize("name", EXITS)
def test_s030_4_a_bad_decisions_section_exits_2(name: str, tmp_path: Path) -> None:
    text, part = EXITS[name]
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(POLICY + text, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr.startswith(f"shipmill: {WHERE}: ")
    assert part in done.stderr


def test_every_zone_has_a_rule_and_its_default_meets_its_floor() -> None:
    assert list(zones()) == list(Zone)
    for rule in zones().values():
        assert rule.floor is None or not rule.default.below(rule.floor)


def test_the_zone_table_is_the_skill_scripts_one() -> None:
    script = skills_dir() / "github-issue-triage" / "scripts" / "decisions.py"
    spec = importlib.util.spec_from_file_location("decisions_for_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert {zone.value: (rule.default.value, rule.floor and rule.floor.value) for zone, rule in zones().items()} == (
        module.ZONES
    )


def test_the_strictest_level_has_the_most_human_involvement() -> None:
    assert Level.strictest([Level.NOTIFY, Level.ACT, Level.ASK]) is Level.ASK
    assert Level.strictest([Level.ACT]) is Level.ACT
    with pytest.raises(ReleaseError):
        Level.strictest([])


def test_a_policy_built_in_code_holds_the_floors_and_the_window_bounds() -> None:
    with pytest.raises(ReleaseError, match="below its floor ask"):
        DecisionPolicy({Zone.DIRECTION: Level.ACT})
    with pytest.raises(ReleaseError, match="decision-policy is fixed at never"):
        DecisionPolicy({Zone.DECISION_POLICY: Level.NEVER})
    with pytest.raises(ReleaseError, match=r"veto_hours must be in 1\.\.168, got 0"):
        VetoHours(0)
