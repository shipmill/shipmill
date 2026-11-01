"""Spec 029's doctor checks: the `issues: write` a breaking stable candidate's proposal needs
(S-029-7), and min_soak_days, deprecated in 0.53.0 (S-029-8) and refused since, the stable lane
off while it is set (spec 052)"""

from shipmill.cli import main
from shipmill.doctor import CALLER, doctor
from shipmill.planner import Event
from shipmill.policy import Lane
from shipmill.refused import MIN_SOAK_DAYS

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


# S-029-9's exit 2 was dropped in #859: the policy loads with the stable lane off (spec 052,
# tests/test_refused.py). S-029-8's deprecation window, 0.53.0, is over; the upgrade it names
# still takes the refused key out
# proves: S-029-8
def test_s029_8_the_upgrade_takes_the_refused_key_out(repo: Repo) -> None:
    repo.write(repo.policy_file, soaked(0))
    assert repo.policy.refused == (MIN_SOAK_DAYS,)
    assert main(["--repo", str(repo.root), "upgrade", "--apply", "stable-every-batch"]) == 0
    assert "min_soak_days" not in repo.read(repo.policy_file)
    assert not repo.policy.refused
    assert repo.policy.rule(Lane.STABLE).promote  # promote_from stays, with no age (S-029-10)
    assert {c.name: c.status for c in doctor(repo.root)}["policy"] == "PASS"


def test_s029_10_a_promotion_waits_for_no_age(repo: Repo) -> None:
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))  # rc1
    promoted = plan(repo, at_day(1, hour=9), event=Event.MANUAL, lane=Lane.STABLE)
    assert (promoted.action, str(promoted.version)) == ("release", "1.1.0")
    assert "promotes v1.1.0rc1, cut 0 day(s) ago" in promoted.reason
