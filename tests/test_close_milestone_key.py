"""Spec 068's key: a lane's close_milestone (S-068-1), doctor's land-grant reason for it
(S-068-11), and init writing it beside milestone = true (S-068-12)"""

import tomllib

import pytest

from shipmill.doctor import CALLER
from shipmill.errors import ReleaseError
from shipmill.init import Detected, policy_text
from shipmill.policy import Lane, Policy, Style, VersionFiles

from .conftest import POLICY, Repo
from .test_doctor_stable import GRANTS, NO_GRANTS, permissions

STABLE = '[lanes.stable]\npromote_from = "rc"\nschedule = ["Mon 07:00 UTC"]\n'
MILESTONE = STABLE + "milestone = true\n"
CLOSES = MILESTONE + "close_milestone = true\n"
NOT_BREAKING = POLICY.replace('major = ["Breaking"]', "major = []")  # no proposal reason of its own


def parse(text: str) -> Policy:
    return Policy.parse(tomllib.loads(text), "shipmill.toml")


def test_s068_1_close_milestone_is_false_when_absent() -> None:
    policy = parse(POLICY.replace(STABLE, MILESTONE))
    assert all(not rule.close_milestone for rule in policy.lanes.values())
    assert policy.rule(Lane.STABLE).milestone


def test_s068_1_close_milestone_true_on_a_milestone_lane_loads() -> None:
    assert parse(POLICY.replace(STABLE, CLOSES)).rule(Lane.STABLE).close_milestone


@pytest.mark.parametrize("value", ['"yes"', "1", "[true]"])
def test_s068_1_a_value_that_isnt_a_boolean_names_the_key_and_the_lane(value: str) -> None:
    with pytest.raises(ReleaseError, match=r"\[lanes\] \[stable\]: close_milestone must be true or false"):
        parse(POLICY.replace(STABLE, MILESTONE + f"close_milestone = {value}\n"))


@pytest.mark.parametrize("milestone", ["", "milestone = false\n"])
def test_s068_1_true_on_a_lane_without_milestone_names_the_key_and_the_lane(milestone: str) -> None:
    with pytest.raises(ReleaseError, match=r"\[lanes\] \[stable\]: close_milestone = true needs milestone = true"):
        parse(POLICY.replace(STABLE, STABLE + milestone + "close_milestone = true\n"))
    # false stays allowed anywhere a lane can set it
    assert not parse(POLICY.replace(STABLE, STABLE + "close_milestone = false\n")).rule(Lane.STABLE).close_milestone


def test_s068_1_the_hotfix_lane_takes_no_close_milestone() -> None:
    with pytest.raises(ReleaseError, match=r"\[lanes\] \[hotfix\]: unknown keys \['close_milestone'\]"):
        parse(POLICY.replace("[lanes.hotfix]\n", "[lanes.hotfix]\nclose_milestone = false\n"))


def test_s068_11_doctor_names_close_milestone_when_the_land_job_grants_no_issues_write(repo: Repo) -> None:
    repo.write(str(CALLER), NO_GRANTS)
    [land] = permissions(repo, NOT_BREAKING.replace(STABLE, CLOSES))
    assert land == (
        "lanes.stable sets close_milestone, so a release closes its milestone and moves what's left, but the"
        f" land job in {CALLER} grants no `issues: write`: add it"
    )
    repo.write(str(CALLER), GRANTS)
    assert permissions(repo, NOT_BREAKING.replace(STABLE, CLOSES)) == []


def test_s068_11_no_close_milestone_reason_without_the_key(repo: Repo) -> None:
    repo.write(str(CALLER), NO_GRANTS)
    assert permissions(repo, NOT_BREAKING.replace(STABLE, MILESTONE)) == []
    # beside another reason, close_milestone joins the one land warning
    _, land = permissions(repo, POLICY.replace(STABLE, CLOSES))
    assert "proposal issue; lanes.stable sets close_milestone" in land
    _, land = permissions(repo, POLICY.replace(STABLE, MILESTONE))
    assert "close_milestone" not in land


def test_s068_11_two_lanes_that_set_close_milestone_are_named_together(repo: Repo) -> None:
    repo.write(str(CALLER), NO_GRANTS)
    rc = "[lanes.rc]\n"
    both = NOT_BREAKING.replace(STABLE, CLOSES).replace(rc, rc + "milestone = true\nclose_milestone = true\n")
    [land] = permissions(repo, both)
    assert land.startswith("lanes.rc, lanes.stable set close_milestone, so a release closes its milestone")


@pytest.mark.parametrize("style", list(Style))
@pytest.mark.parametrize("version_files", list(VersionFiles))
@pytest.mark.parametrize("fragments", [True, False])
def test_s068_12_init_writes_close_milestone_wherever_it_writes_milestone(
    style: Style, version_files: VersionFiles, fragments: bool
) -> None:
    text = policy_text(Detected("demo", "main", style, version_files), fragments)
    raw = tomllib.loads(text)
    for name, lane in raw["lanes"].items():
        assert lane.get("close_milestone", False) is lane.get("milestone", False), name
    policy = parse(text)  # the policy it writes loads
    assert all(rule.close_milestone is rule.milestone for rule in policy.lanes.values())
