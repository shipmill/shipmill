"""Spec 029's doctor checks: the `issues: write` a breaking stable candidate's proposal needs
(S-029-7), and the deprecated min_soak_days, still honoured while it warns (S-029-8)"""

from shipmill.doctor import CALLER, Check, doctor
from shipmill.planner import Event
from shipmill.policy import Lane

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
SOAK_WARNING = (
    "[lanes.stable] min_soak_days is deprecated (spec 029): a time soak checks nothing;"
    " run shipmill upgrade --apply stable-every-batch, which the next minor release requires"
)


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
    # a pending upgrade under propose joins the same land warning (spec 014)
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


def soak_checks(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root) if c.name == "min_soak_days"]


def test_s029_8_a_deprecated_soak_still_holds_a_promotion_and_doctor_warns(repo: Repo) -> None:
    assert "min_soak_days = 3" in repo.read(repo.policy_file)
    [warning] = soak_checks(repo)
    assert (warning.status, warning.detail) == ("WARN", SOAK_WARNING)
    assert {c.name: c.status for c in doctor(repo.root)}["policy"] == "PASS"  # still read

    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))  # rc1
    held = plan(repo, at_day(2), event=Event.MANUAL, lane=Lane.STABLE)
    assert held.action == "skip" and "stable: no rc has soaked 3 day(s)" in held.reason
    ripe = plan(repo, at_day(4), event=Event.MANUAL, lane=Lane.STABLE)
    assert (ripe.action, str(ripe.version)) == ("release", "1.1.0")


def test_s029_8_doctor_warns_whatever_the_value_and_not_without_the_key(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY.replace("min_soak_days = 3", "min_soak_days = 0"))
    assert [c.detail for c in soak_checks(repo)] == [SOAK_WARNING]
    repo.write(repo.policy_file, POLICY.replace("min_soak_days = 3\n", ""))
    assert soak_checks(repo) == []
