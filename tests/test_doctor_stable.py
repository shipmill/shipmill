"""Spec 029's doctor checks: the `issues: write` a breaking stable candidate's proposal needs
(S-029-7), and min_soak_days, deprecated in 0.53.0 (S-029-8) and refused since (S-029-9)"""

import subprocess
import sys

import pytest

from shipmill.cli import main
from shipmill.config import config_path
from shipmill.doctor import CALLER, doctor
from shipmill.errors import ReleaseError
from shipmill.planner import Event
from shipmill.policy import SOAK_REMOVED, Lane, Policy

from .conftest import POLICY, Repo, at_day
from .test_lanes import plan, release

NO_GRANTS = """\
jobs:
  prepare:
    uses: shipmill/shipmill/.github/workflows/prepare.yml@v0
    permissions:
      contents: write
      issues: read
  land:
    uses: shipmill/shipmill/.github/workflows/land.yml@v0
    permissions:
      contents: write
      actions: write
"""
GRANTS = NO_GRANTS.replace("issues: read", "issues: write") + "      issues: write\n"
OBSERVE_UPGRADES = '\n[autonomy]\nupgrade = "observe"\n'  # spec 014's pending upgrade stays out of these tests
RELEASE_PROPOSES = '\n[autonomy]\nrelease = "propose"\nupgrade = "observe"\n'
BREAKING = "the stable lane can hold a breaking change ([bump] major), which waits for the maintainer"


def permissions(repo: Repo, config: str, autonomy: str = OBSERVE_UPGRADES) -> list[str]:
    repo.write(repo.policy_file, config + autonomy)
    return [c.detail for c in doctor(repo.root, repo.github) if c.name == "permissions" and c.status == "WARN"]


def test_s029_7_doctor_warns_about_issues_write_for_a_config_that_can_break(repo: Repo) -> None:
    repo.write(str(CALLER), NO_GRANTS)
    prepare, land = permissions(repo, POLICY)
    assert prepare == (
        f"{BREAKING}, so a run opens a proposal issue, but the prepare job in {CALLER} grants no"
        " `issues: write`: change its `issues: read` to `issues: write`"
    )
    assert land == (
        f"{BREAKING}, so a release closes its lane's proposal issue, but the land job in {CALLER}"
        " grants no `issues: write`: add it"
    )
    repo.write(str(CALLER), GRANTS)
    assert permissions(repo, POLICY) == []


def test_s029_7_one_warning_per_job_when_a_stage_proposes_too(repo: Repo) -> None:
    repo.write(str(CALLER), NO_GRANTS)
    prepare, land = permissions(repo, POLICY, RELEASE_PROPOSES)
    assert prepare.startswith("the config sets a stage to propose, so a run opens a proposal issue")
    assert land.startswith("release autonomy is propose, so a release closes its lane's proposal issue, but")
    # a pending upgrade under propose joins the same land warning (spec 014); changelog-fragments
    # is the one pending upgrade
    [_, land] = permissions(repo, POLICY, "")
    assert land == (
        f"{BREAKING}, so a release closes its lane's proposal issue; upgrade autonomy is propose and 1"
        f" upgrade(s) pending, but the land job in {CALLER}, whose grant proposes them, grants no"
        " `issues: write`: add it"
    )


def test_s029_7_doctor_stays_silent_when_major_is_empty_or_the_bump_reads_paths(repo: Repo) -> None:
    repo.write(str(CALLER), NO_GRANTS)
    assert permissions(repo, POLICY.replace('major = ["Breaking"]', "major = []")) == []
    paths = POLICY.replace(
        'major = ["Breaking"]\nminor = ["Added", "Changed"]\npatch = ["Fixed"]', 'minor_paths = ["src/**"]'
    ).replace('from = "headings"', 'from = "paths"')
    assert 'from = "paths"' in paths and "major" not in paths
    assert permissions(repo, paths) == []


def soaked(days: int = 3, promote: bool = True) -> str:
    """conftest's policy with [lanes.stable] min_soak_days, on promote_from or without it"""
    text = POLICY.replace('promote_from = "rc"\n', f'promote_from = "rc"\nmin_soak_days = {days}\n')
    return text if promote else text.replace('promote_from = "rc"\n', "")


def test_s029_9_the_policy_refuses_min_soak_days_whatever_its_value(repo: Repo) -> None:
    for text in (soaked(3), soaked(0), soaked(3, promote=False)):
        repo.write(repo.policy_file, text)
        with pytest.raises(ReleaseError) as refused:
            Policy.load(config_path(repo.root))
        assert str(refused.value) == SOAK_REMOVED
    repo.write(repo.policy_file, POLICY)
    assert repo.policy.rule(Lane.STABLE).promote  # promote_from stays, with no age (S-029-10)


def test_s029_9_a_command_on_the_refused_key_exits_2_naming_the_key_the_spec_and_the_upgrade(repo: Repo) -> None:
    repo.write(repo.policy_file, soaked())
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(repo.root), "plan", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr == f"shipmill: {SOAK_REMOVED}\n"
    for named in ("min_soak_days", "spec 029", "shipmill upgrade --apply stable-every-batch"):
        assert named in done.stderr


# S-029-8's deprecation window, 0.53.0, is over: doctor's WARN is now the policy check's FAIL
# proves: S-029-8
def test_s029_9_doctor_fails_the_policy_with_the_refusal_and_the_upgrade_fixes_it(repo: Repo) -> None:
    repo.write(repo.policy_file, soaked(0))
    checks = doctor(repo.root)
    assert [(c.status, c.name, c.detail) for c in checks] == [("FAIL", "policy", SOAK_REMOVED)]
    # shipmill upgrade reads the raw TOML, not the policy, so it fixes the config the policy refuses
    assert main(["--repo", str(repo.root), "upgrade", "--apply", "stable-every-batch"]) == 0
    assert "min_soak_days" not in repo.read(repo.policy_file)
    assert {c.name: c.status for c in doctor(repo.root)}["policy"] == "PASS"


def test_s029_10_a_promotion_waits_for_no_age(repo: Repo) -> None:
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))  # rc1
    promoted = plan(repo, at_day(1, hour=9), event=Event.MANUAL, lane=Lane.STABLE)
    assert (promoted.action, str(promoted.version)) == ("release", "1.1.0")
    assert "promotes v1.1.0rc1, cut 0 day(s) ago" in promoted.reason
