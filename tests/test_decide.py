"""Spec 030: the [decisions] section of .github/shipmill.toml and its validation"""

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.decide import CleanReleases, DecisionPolicy, Earned, Level, VetoHours, Zone, zones
from shipmill.errors import ReleaseError
from shipmill.gate import skills_dir
from shipmill.policy import Policy

from .conftest import POLICY

WHERE = "shipmill.toml [decisions]"
ZONE_IDS = (
    "direction, decision-policy, scope, accepted-spec, rule-departure, contract-change, contract-addition, security, "
    "deploy-step, protected, area-record, interpretation, triage-verdict, implementation, unknown"
)
LEVELS = "['act', 'notify', 'ask', 'never']"
DEFAULTS = {
    Zone.DIRECTION: Level.NEVER,
    Zone.DECISION_POLICY: Level.NEVER,
    Zone.SCOPE: Level.ASK,
    Zone.ACCEPTED_SPEC: Level.ASK,
    Zone.RULE_DEPARTURE: Level.ASK,
    Zone.CONTRACT_CHANGE: Level.ASK,
    Zone.CONTRACT_ADDITION: Level.NOTIFY,
    Zone.SECURITY: Level.ASK,
    Zone.DEPLOY_STEP: Level.ASK,
    Zone.PROTECTED: Level.ASK,
    Zone.AREA_RECORD: Level.ACT,
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


def test_s063_1_deploy_step_follows_security_at_ask_with_no_floor() -> None:
    order = list(Zone)
    assert order[order.index(Zone.SECURITY) + 1] is Zone.DEPLOY_STEP
    rule = zones()[Zone.DEPLOY_STEP]
    assert (rule.default, rule.floor) == (Level.ASK, None)
    for level in Level:  # no floor: [decisions] sets it to any level
        assert decisions(section(f'deploy-step = "{level.value}"')).level(Zone.DEPLOY_STEP) is level


def test_s067_2_accepted_spec_takes_notify_or_ask_and_refuses_act_naming_its_floor() -> None:
    order = list(Zone)
    assert order[order.index(Zone.SCOPE) + 1] is Zone.ACCEPTED_SPEC
    rule = zones()[Zone.ACCEPTED_SPEC]
    assert (rule.default, rule.floor) == (Level.ASK, Level.NOTIFY)
    assert decisions("").level(Zone.ACCEPTED_SPEC) is Level.ASK  # D-63: no repository changes on upgrade
    for level in (Level.NOTIFY, Level.ASK):
        policy = decisions(section(f'accepted-spec = "{level.value}"'))
        assert policy.level(Zone.ACCEPTED_SPEC) is level
        assert policy.level(Zone.SCOPE) is Level.ASK
    assert refused(section('accepted-spec = "act"')) == (
        f'{WHERE}: accepted-spec = "act" is below its floor notify:'
        " the maintainer may always veto the spec of work they accepted (D-48)"
    )
    assert refused(section('scope = "notify"')) == (
        f'{WHERE}: scope = "notify" is below its floor ask:'
        " only the maintainer accepts an opportunity, approves a spec, or plans a goal (D-10)"
    )


def test_s067_2_a_policy_below_accepted_specs_floor_exits_2(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(POLICY + section('accepted-spec = "act"'), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr.startswith(f'shipmill: {WHERE}: accepted-spec = "act" is below its floor notify: ')


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
    "accepted-spec": ('"act"', "notify", "the maintainer may always veto the spec of work they accepted (D-48)"),
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


@pytest.mark.parametrize("zone", ["release", "deploy", "rollback", "intake", "upgrade", "triage", "fix", "land"])
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


# -- spec 083: [decisions.earned], clean_releases, and the area-record zone ----------------------


def earned(*lines: str) -> str:
    return "\n[decisions.earned]\n" + "".join(f"{line}\n" for line in lines)


def test_s083_1_the_earned_table_keeps_its_bounds_and_max_lines() -> None:
    policy = decisions(earned('protected = "act"', 'security = "notify"', "max_lines = 200"))
    assert policy.earned == Earned({Zone.PROTECTED: Level.ACT, Zone.SECURITY: Level.NOTIFY}, 200)
    assert (policy.bound(Zone.PROTECTED), policy.bound(Zone.SECURITY)) == (Level.ACT, Level.NOTIFY)
    assert policy.bound(Zone.SCOPE) is None
    assert policy.levels == DEFAULTS  # a bound leaves every zone's level as it is
    assert decisions(earned('protected = "notify"')).earned == Earned({Zone.PROTECTED: Level.NOTIFY}, 200)
    assert decisions(earned("max_lines = 1")).earned == Earned({}, 1)
    assert decisions(earned("max_lines = 10000")).earned == Earned({}, 10000)


def test_s083_1_without_the_table_nothing_earns_and_the_policy_is_as_before() -> None:
    """D-63: a config without [decisions.earned] or clean_releases parses as it did"""
    policy = decisions(section('protected = "notify"'))
    assert policy.earned is None
    assert all(policy.bound(zone) is None for zone in Zone)
    assert int(policy.clean_releases) == 3
    assert decisions(section()) == DecisionPolicy()


def test_s083_1_clean_releases_takes_an_integer_from_1_to_20() -> None:
    assert int(decisions(section("clean_releases = 1")).clean_releases) == 1
    assert int(decisions(section("clean_releases = 20")).clean_releases) == 20
    assert decisions(section("clean_releases = 5")).levels == DEFAULTS


@pytest.mark.parametrize("zone", [z.value for z in Zone if z not in (Zone.PROTECTED, Zone.SECURITY)])
def test_s083_1_a_bound_on_another_zone_is_refused_naming_the_key(zone: str) -> None:
    assert refused(earned(f'{zone} = "ask"')) == (
        f"{WHERE}: [decisions.earned] {zone} takes no earned level: only protected and security do"
    )


@pytest.mark.parametrize("key", ["release", "land", "colour"])
def test_s083_1_a_key_that_is_no_earning_zone_is_refused_too(key: str) -> None:
    assert refused(earned(f'{key} = "act"')) == (
        f"{WHERE}: [decisions.earned] {key} takes no earned level: only protected and security do"
    )


@pytest.mark.parametrize("value", ['"maybe"', '"ACT"', "1", "true"])
def test_s083_1_a_bound_that_is_no_level_is_refused(value: str) -> None:
    got = repr(tomllib.loads(f"v = {value}")["v"])
    assert refused(earned(f"protected = {value}")) == (
        f"{WHERE}: [decisions.earned] protected must be one of {LEVELS}, got {got}"
    )


def test_s083_1_a_bound_below_its_zones_floor_is_refused() -> None:
    assert refused(earned('security = "act"')) == (
        f'{WHERE}: [decisions.earned] security = "act" is below its floor notify:'
        " a change to workflows, secrets, or permissions is always told (D-48)"
    )


@pytest.mark.parametrize("value", ["0", "10001", "-1", "200.0", '"200"', "true"])
def test_s083_1_a_max_lines_outside_1_to_10000_or_not_an_integer_is_refused(value: str) -> None:
    got = repr(tomllib.loads(f"v = {value}")["v"])
    assert refused(earned(f"max_lines = {value}")) == (
        f"{WHERE}: [decisions.earned] max_lines must be an integer from 1 to 10000, got {got}"
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("0", "clean_releases must be in 1..20, got 0"),
        ("21", "clean_releases must be in 1..20, got 21"),
        ("3.0", "clean_releases must be an integer, got 3.0"),
        ('"3"', "clean_releases must be an integer, got '3'"),
        ("true", "clean_releases must be an integer, got True"),
    ],
)
def test_s083_1_a_clean_releases_outside_1_to_20_or_not_an_integer_is_refused(value: str, message: str) -> None:
    assert refused(section(f"clean_releases = {value}")) == f"{WHERE}: {message}"


def test_s083_1_an_earned_key_that_is_not_a_table_is_refused() -> None:
    assert refused(section('earned = "act"')) == (f"{WHERE}: earned must be a table, [decisions.earned], got 'act'")


EARNED_EXITS = {
    "another zone": (earned('scope = "act"'), "[decisions.earned] scope takes no earned level"),
    "no level": (earned('protected = "maybe"'), "[decisions.earned] protected must be one of"),
    "below the floor": (earned('security = "act"'), '[decisions.earned] security = "act" is below its floor notify'),
    "max_lines": (earned("max_lines = 0"), "[decisions.earned] max_lines must be an integer from 1 to 10000"),
    "clean_releases": (section("clean_releases = 21"), "clean_releases must be in 1..20"),
}


# proves: S-083-1
@pytest.mark.parametrize("name", EARNED_EXITS)
def test_s083_1_a_bad_earned_table_or_clean_releases_exits_2(name: str, tmp_path: Path) -> None:
    text, part = EARNED_EXITS[name]
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


def test_s083_1_a_policy_built_in_code_holds_the_earned_rules() -> None:
    with pytest.raises(ReleaseError, match="scope takes no earned level"):
        Earned({Zone.SCOPE: Level.ACT})
    with pytest.raises(ReleaseError, match="is below its floor notify"):
        Earned({Zone.SECURITY: Level.ACT})
    with pytest.raises(ReleaseError, match="max_lines must be an integer from 1 to 10000"):
        Earned({}, 0)
    with pytest.raises(ReleaseError, match=r"clean_releases must be in 1\.\.20, got 0"):
        CleanReleases(0)


def test_s083_3_area_record_follows_protected_at_act_with_no_floor() -> None:
    order = list(Zone)
    assert order[order.index(Zone.PROTECTED) + 1] is Zone.AREA_RECORD
    rule = zones()[Zone.AREA_RECORD]
    assert (rule.default, rule.floor) == (Level.ACT, None)
    assert decisions("").level(Zone.AREA_RECORD) is Level.ACT  # D-63: no repository changes on upgrade
    assert not decisions("").is_configured(Zone.AREA_RECORD)
    policy = decisions(section('area-record = "ask"'))
    assert (policy.level(Zone.AREA_RECORD), policy.is_configured(Zone.AREA_RECORD)) == (Level.ASK, True)
    for level in Level:  # no floor: [decisions] sets it to any level
        assert decisions(section(f'area-record = "{level.value}"')).level(Zone.AREA_RECORD) is level


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
