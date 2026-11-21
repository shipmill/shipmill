"""shipmill operate (#30): health checks recorded as deployment statuses, promotion after an
unbroken bake, a missed lane deploy, autonomy and the hold, --approve, and the operate caller;
rollback and incidents (#31)"""

import datetime as dt
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.autonomy import HOLD_LABEL
from shipmill.cli import main
from shipmill.doctor import OPERATE_CALLER, doctor
from shipmill.errors import ReleaseError
from shipmill.github import PROPOSAL_LABEL, Deployment, DeploymentState, DeploymentStatus, GhCli, Issue, address
from shipmill.gitrepo import pull_numbers
from shipmill.init import BOT_REF, BOT_REPO, init_operate, operate_caller_text
from shipmill.operate import (
    BODY_LIMIT,
    COMPARE_PREFIX,
    PROBE_BODY_LIMIT,
    STATUS_PREFIX,
    Cause,
    HttpResponse,
    Incident,
    IncidentState,
    Report,
    Unreachable,
    approve,
    approve_rollback,
    changes_answers,
    deploy_marker,
    excerpt,
    named_version,
    operate,
    probe,
    shown_url,
    tag_of,
)
from shipmill.planner import Decision, Event, Planner
from shipmill.policy import Lane
from shipmill.version import Version

from .conftest import POLICY, T0, FakeGitHub, Repo

S = DeploymentState
STAGING = "https://staging.example.com/health"
PRODUCTION = "https://example.com/health"
ENVIRONMENTS = f"""
[environments.staging]
lane = "rc"
workflow = "deploy.yml"
health = "{STAGING}"

[environments.production]
from = "staging"
workflow = "deploy.yml"
health = "{PRODUCTION}"
bake_minutes = 60
"""
TO_PRODUCTION = ("deploy.yml", "v1.1.0rc1", "v1.1.0rc1", {"environment": "production"})


@dataclass
class FakeHttp:
    """Health answers by URL: a response, or Unreachable"""

    answers: dict[str, HttpResponse | Unreachable] = field(default_factory=dict)
    asked: list[tuple[str, float]] = field(default_factory=list)
    limits: dict[str, int] = field(default_factory=dict)  # the bytes each URL's last read was capped at
    # answers given in turn before the one in `answers`, by URL: a release that answers differently each time
    turns: dict[str, list[HttpResponse | Unreachable]] = field(default_factory=dict)

    def get(self, url: str, timeout: float, limit: int = BODY_LIMIT) -> HttpResponse:
        self.asked.append((url, timeout))
        self.limits[url] = limit
        queued = self.turns.get(url)
        answer = queued.pop(0) if queued else self.answers[url]
        if isinstance(answer, Unreachable):
            raise answer
        return answer

    def answer(self, url: str, body: str = "ok", status: int = 200, seconds: float = 0.2) -> None:
        self.answers[url] = HttpResponse(status, body, seconds)


def minutes(n: float) -> dt.datetime:
    return T0 + dt.timedelta(minutes=n)


def configure(repo: Repo, autonomy: str = "") -> None:
    repo.write(repo.policy_file, POLICY + ENVIRONMENTS + (f"\n[autonomy]\n{autonomy}" if autonomy else ""))


def tag(repo: Repo, name: str, at: dt.datetime) -> None:
    repo.at(at)
    repo.git.run("tag", "-a", name, "-m", name)


@pytest.fixture
def setup(repo: Repo) -> tuple[Repo, FakeHttp]:
    """production runs v1.0.0, staging got v1.1.0rc1 at T0; both answer healthy"""
    configure(repo)
    tag(repo, "v1.1.0rc1", minutes(-5))
    repo.github.deploy("production", "v1.0.0", T0 - dt.timedelta(days=20), S.IN_PROGRESS, S.SUCCESS)
    repo.github.deploy("staging", "v1.1.0rc1", minutes(-1), S.IN_PROGRESS, S.SUCCESS)  # success at T0
    http = FakeHttp()
    http.answer(STAGING, '{"status": "ok", "version": "1.1.0rc1"}')
    http.answer(PRODUCTION, '{"version": "v1.0.0"}')
    return repo, http


def run(repo: Repo, http: FakeHttp, at: dt.datetime, dry_run: bool = False) -> dict[str, Report]:
    repo.github.now = at
    reports = operate(repo.policy, repo.git, repo.github, http, at, dry_run)
    return {r.environment: r for r in reports}


def staging_writes(repo: Repo) -> list[DeploymentState]:
    [staging] = repo.github.envs["staging"]
    return [state for deployment, state, _ in repo.github.status_writes if deployment == staging.id]


# -- health ----------------------------------------------------------------------------------


def test_the_version_rule_reads_a_json_version_only() -> None:
    assert named_version('{"version": "1.2.0", "python": "3.14.0"}') == "1.2.0"
    assert named_version("ok 1.2.0") is None  # plain text names no version
    assert named_version('{"version": 3}') is None
    assert named_version('["1.2.0"]') is None


def test_a_version_mismatch_is_unhealthy_and_holds_the_promotion(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    http.answer(STAGING, '{"version": "1.0.0"}')  # a stale instance answering 200
    found = run(repo, http, minutes(90))
    assert found["staging"].health.startswith("unhealthy: answers version 1.0.0, but v1.1.0rc1 is deployed")
    assert staging_writes(repo) == [S.FAILURE]
    assert repo.github.dispatched == []
    assert "staging is unhealthy on v1.1.0rc1" in found["production"].action


@pytest.mark.parametrize(
    ("answer", "detail"),
    [
        (HttpResponse(503, "", 0.1), "HTTP 503"),
        (HttpResponse(200, "ok", 12.0), "answered in 12.0 s, over 10 s"),
        (Unreachable("connection refused"), "unreachable: connection refused"),
    ],
)
def test_a_failed_check_is_unhealthy(setup: tuple[Repo, FakeHttp], answer: HttpResponse, detail: str) -> None:
    repo, http = setup
    http.answers[STAGING] = answer
    assert run(repo, http, minutes(5))["staging"].health.startswith(f"unhealthy: {detail}")
    assert (STAGING, 10.0) in http.asked


def test_no_health_url_is_reported_and_bakes_on_time_alone(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    repo.write(repo.policy_file, repo.read(repo.policy_file).replace(f'health = "{STAGING}"\n', ""))
    assert run(repo, http, minutes(30))["staging"].health == "no health URL"
    assert repo.github.dispatched == []
    run(repo, http, minutes(61))
    assert repo.github.dispatched == [TO_PRODUCTION]
    assert staging_writes(repo) == []  # nothing checked, nothing recorded


# -- promotion -------------------------------------------------------------------------------


def test_promotion_only_after_an_unbroken_bake(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    found = run(repo, http, minutes(10))
    assert found["staging"].health == "healthy (HTTP 200, version 1.1.0rc1), baking 10 of 60 min"
    assert "v1.1.0rc1 baking on staging: 10 of 60 min" in found["production"].action
    run(repo, http, minutes(59))
    assert repo.github.dispatched == []
    found = run(repo, http, minutes(61))
    # dispatched on the tag, so the deployment GitHub records names it
    assert repo.github.dispatched == [TO_PRODUCTION]
    assert "dispatch deploy.yml with v1.1.0rc1 (healthy on staging for the 60 min bake)" in found["production"].action
    assert staging_writes(repo) == [S.IN_PROGRESS, S.SUCCESS]
    # production's own latest status was success already, and nothing is promoted from it
    assert len(repo.github.status_writes) == 2


def test_a_failed_check_restarts_the_bake(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    run(repo, http, minutes(10))
    http.answer(STAGING, "", status=500)
    assert "failing for 0 min" in run(repo, http, minutes(30))["staging"].health
    assert "failing for 5 min" in run(repo, http, minutes(35))["staging"].health
    http.answer(STAGING, '{"version": "1.1.0rc1"}')
    run(repo, http, minutes(40))
    run(repo, http, minutes(61))  # 61 min since the success, but only 21 since the recovery
    assert repo.github.dispatched == []
    run(repo, http, minutes(101))
    assert repo.github.dispatched == [TO_PRODUCTION]
    # a failure per failed check, up to rollback_after (3): they count the checks failed in a row
    assert staging_writes(repo) == [S.IN_PROGRESS, S.FAILURE, S.FAILURE, S.IN_PROGRESS, S.SUCCESS]


def test_a_promotion_is_dispatched_once(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    run(repo, http, minutes(61))
    repo.github.deploy("production", "v1.1.0rc1", minutes(62), S.IN_PROGRESS)
    found = run(repo, http, minutes(71))
    assert repo.github.dispatched == [TO_PRODUCTION]
    assert "v1.1.0rc1 was deployed here already (in_progress)" in found["production"].action


def test_a_promotion_still_queued_is_not_dispatched_again(setup: tuple[Repo, FakeHttp]) -> None:
    # a deploy job creates its deployment only when it starts: behind a build job or a wait
    # for a runner, the next operate run finds no deployment of the tag yet, but the run
    repo, http = setup
    run(repo, http, minutes(61))
    found = run(repo, http, minutes(71))
    assert repo.github.dispatched == [TO_PRODUCTION]
    assert "deploy.yml already ran with v1.1.0rc1 (queued, run 1)" in found["production"].action


def test_a_deploy_run_that_failed_before_its_deployment_is_not_retried(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    run(repo, http, minutes(61))
    workflow, ref, queued = repo.github.runs[0]
    repo.github.runs[0] = (workflow, ref, replace(queued, status="completed"))  # its build job failed
    found = run(repo, http, minutes(81))
    assert repo.github.dispatched == [TO_PRODUCTION]
    assert "deploy.yml already ran with v1.1.0rc1 (completed, run 1)" in found["production"].action


def test_the_source_run_of_a_shared_workflow_does_not_block_the_promotion(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    repo.github.now = minutes(-3)  # staging's own deploy.yml run on the tag, before its deployment
    repo.github.dispatch("deploy.yml", "v1.1.0rc1", "v1.1.0rc1", {"environment": "staging"})
    repo.github.dispatched.clear()
    run(repo, http, minutes(61))
    assert repo.github.dispatched == [TO_PRODUCTION]


def test_approve_refuses_while_a_run_of_the_tag_is_queued(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    run(repo, http, minutes(61))
    repo.github.dispatch(*TO_PRODUCTION)  # approved by hand already; its run is still queued
    with pytest.raises(ReleaseError, match=r"deploy.yml is running with v1.1.0rc1 already \(run 1, queued\)"):
        approve(repo.policy, repo.github, "production", dry_run=False)


def test_repeated_runs_write_no_duplicate_statuses(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    for at in (5, 10, 20):
        run(repo, http, minutes(at))
    assert staging_writes(repo) == [S.IN_PROGRESS]
    for at in (70, 80, 90):
        run(repo, http, minutes(at))
    assert staging_writes(repo) == [S.IN_PROGRESS, S.SUCCESS]
    assert all(d.startswith(STATUS_PREFIX) for _, _, d in repo.github.status_writes)


def test_a_dry_run_acts_on_nothing(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    assert run(repo, http, minutes(30), dry_run=True)["staging"].action.startswith("would mark in_progress")
    found = run(repo, http, minutes(90), dry_run=True)
    assert found["production"].action.startswith("would dispatch deploy.yml with v1.1.0rc1")
    configure(repo, 'deploy.production = "propose"\n')
    assert run(repo, http, minutes(90), dry_run=True)["production"].action.startswith("would propose v1.1.0rc1")
    assert repo.github.status_writes == [] and repo.github.dispatched == [] and repo.github.issues == {}


# -- autonomy and the hold -------------------------------------------------------------------


def test_propose_opens_one_issue_and_keeps_it(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    found = run(repo, http, minutes(61))
    assert repo.github.dispatched == []
    [issue] = repo.github.issues.values()
    assert issue.title == "Ready to promote v1.1.0rc1 to production"
    assert deploy_marker("production") in issue.body
    assert "gh workflow run operate.yml -f approve=production -f dry-run=false" in issue.body
    opened = f"proposal #{issue.number} opened: v1.1.0rc1 (deploy.production autonomy is propose)"
    assert found["production"].action == opened
    run(repo, http, minutes(71))
    assert len(repo.github.issues) == 1 and repo.github.edits == 0


def test_observe_only_reports(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "observe"\n')
    found = run(repo, http, minutes(61))
    assert repo.github.dispatched == [] and repo.github.issues == {}
    assert "would deploy v1.1.0rc1" in found["production"].action
    assert found["production"].action.endswith("but deploy.production autonomy is observe")


def test_the_hold_turns_a_promotion_into_a_proposal(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    repo.github.holds = ["#7 Investigating"]
    run(repo, http, minutes(61))
    assert repo.github.dispatched == []
    [issue] = repo.github.issues.values()
    assert f"but held by {HOLD_LABEL} #7." in issue.body
    assert f"Close the open `{HOLD_LABEL}` issues first" in issue.body


def test_approve_deploys_the_proposed_tag_once(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    run(repo, http, minutes(61))
    [number] = repo.github.issues
    repo.github.holds = ["#7 Investigating"]
    with pytest.raises(ReleaseError, match=f"held by {HOLD_LABEL} #7; close it to approve a deploy"):
        approve(repo.policy, repo.github, "production", dry_run=False)
    repo.github.holds = []
    assert approve(repo.policy, repo.github, "production", dry_run=True).startswith("would dispatch")
    assert repo.github.dispatched == []
    done = approve(repo.policy, repo.github, "production", dry_run=False)
    assert done == f"dispatched deploy.yml with v1.1.0rc1 to production; closed #{number}"
    assert repo.github.dispatched == [TO_PRODUCTION]
    assert "Approved" in repo.github.closed[number]
    with pytest.raises(ReleaseError, match="no open proposal to deploy to production"):
        approve(repo.policy, repo.github, "production", dry_run=False)
    with pytest.raises(ReleaseError, match="no environment 'qa'"):
        approve(repo.policy, repo.github, "qa", dry_run=False)


def test_a_proposal_closes_once_its_tag_is_deployed(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    run(repo, http, minutes(61))
    [number] = repo.github.issues
    deployment = repo.github.deploy("production", "v1.1.0rc1", minutes(62), S.IN_PROGRESS)  # a person deploys it
    run(repo, http, minutes(64))
    assert number in repo.github.issues  # not running there yet
    repo.github.deploy("production", "v1.1.0rc1", minutes(65), S.IN_PROGRESS, S.SUCCESS)
    deployment += 1
    http.answer(PRODUCTION, '{"version": "v1.1.0rc1"}')
    assert run(repo, http, minutes(67), dry_run=True)["production"].action.endswith(
        f"would close proposal #{number}: v1.1.0rc1 deployed"
    )
    found = run(repo, http, minutes(67))
    assert found["production"].action.endswith(f"closed proposal #{number}: v1.1.0rc1 deployed")
    assert repo.github.closed == {number: f"production runs v1.1.0rc1 now (deployment {deployment})."}
    assert repo.github.dispatched == []


def test_a_proposal_for_an_older_tag_closes_naming_it(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    run(repo, http, minutes(61))
    [number] = repo.github.issues
    tag(repo, "v1.1.0rc2", minutes(62))
    repo.github.deploy("production", "v1.1.0rc2", minutes(62), S.IN_PROGRESS, S.SUCCESS)
    http.answer(PRODUCTION, '{"version": "v1.1.0rc2"}')
    run(repo, http, minutes(70))
    assert repo.github.closed[number].endswith("This issue proposed v1.1.0rc1, so it is closed too.")


# -- a missed lane deploy --------------------------------------------------------------------


def test_a_missed_lane_deploy_is_dispatched_once(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    tag(repo, "v1.1.0rc2", minutes(100))  # land's dispatch to staging failed
    assert "v1.1.0rc2 just landed" in run(repo, http, minutes(110))["staging"].action
    rc2 = ("deploy.yml", "v1.1.0rc2", "v1.1.0rc2", {"environment": "staging"})
    assert rc2 not in repo.github.dispatched
    found = run(repo, http, minutes(131))
    assert rc2 in repo.github.dispatched
    assert "the newest rc release, which its deploy missed" in found["staging"].action
    repo.github.deploy("staging", "v1.1.0rc2", minutes(132), S.IN_PROGRESS, S.FAILURE)
    found = run(repo, http, minutes(141))
    assert repo.github.dispatched.count(rc2) == 1
    assert "v1.1.0rc2 was deployed here already (failure)" in found["staging"].action


# -- reading deployments ---------------------------------------------------------------------


def test_a_deployment_names_its_tag_by_ref_or_sha(repo: Repo) -> None:
    tags = repo.git.tags()
    sha = tags[0].commit

    def of(ref: str) -> Version | None:
        return tag_of(Deployment(1, ref, sha, T0), tags)

    assert of("v1.2.0") == Version(1, 2, 0)
    assert of("refs/tags/v1.2.0rc1") == Version(1, 2, 0, "rc", 1)
    assert of(sha) == Version(1, 0, 0)
    assert of("main") is None


def test_a_deployment_that_never_succeeded_is_not_current(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    repo.github.deploy("production", "v1.1.0rc1", minutes(1), S.IN_PROGRESS, S.FAILURE)
    assert run(repo, http, minutes(5))["production"].tag == "v1.0.0"


# -- the CLI, init, doctor, and the workflow -------------------------------------------------


def test_cli_operate_writes_the_summary(setup: tuple[Repo, FakeHttp], tmp_path: Path) -> None:
    repo, http = setup
    summary = tmp_path / "summary.md"
    argv = ["--repo", str(repo.root), "operate", "--now", minutes(61).isoformat(), "--step-summary", str(summary)]
    assert main(argv, repo.github, http) == 0
    text = summary.read_text()
    assert "| Environment | Tag | Health | Action |" in text
    assert "| production | v1.0.0 |" in text
    assert repo.github.dispatched == [TO_PRODUCTION]


def test_init_operate_writes_the_caller_and_doctor_wants_it_only_when_used(repo: Repo) -> None:
    def operate_check() -> tuple[str, str] | None:
        found = {c.name: (c.status, c.detail) for c in doctor(repo.root, repo.github)}
        return found.get("operate")

    repo.write(repo.policy_file, POLICY + '\n[environments.staging]\nlane = "rc"\nworkflow = "deploy.yml"\n')
    assert operate_check() is None  # D-9: no from, no health, no warning
    configure(repo)
    status, detail = operate_check() or ("", "")
    assert status == "WARN" and f"`{cli_command()} init --operate` writes it" in detail
    init_operate(repo.root, force=False)
    assert operate_check() == (
        "PASS",
        f"{OPERATE_CALLER} runs shipmill operate with deployments, actions, issues: write; rolls back after 3"
        " failed checks in a row and opens an incident labelled 'incident', which holds rc, stable",
    )
    with pytest.raises(ReleaseError, match="exists; pass --force"):
        init_operate(repo.root, force=False)
    caller = operate_caller_text()
    repo.write(str(OPERATE_CALLER), caller.replace("      deployments: write", "      deployments: read"))
    assert operate_check() == ("WARN", f"the job in {OPERATE_CALLER} that calls operate.yml lacks deployments: write")
    repo.write(str(OPERATE_CALLER), caller.replace("      issues: write", "      issues: read"))
    lacks_issues = ("WARN", f"the job in {OPERATE_CALLER} that calls operate.yml lacks issues: write")
    assert operate_check() == lacks_issues  # a health URL: a failing environment opens an incident
    unchecked = re.sub(r'health = ".*"\n', "", POLICY + ENVIRONMENTS)
    repo.write(repo.policy_file, unchecked)  # promoted, but no health URL: no incident can open
    assert operate_check() == ("PASS", f"{OPERATE_CALLER} runs shipmill operate with deployments, actions: write")
    repo.write(repo.policy_file, unchecked + '\n[autonomy]\ndeploy.production = "propose"\n')  # a deploy opens one
    assert operate_check() == lacks_issues


SHIPMILL = Path(__file__).parent.parent  # this repository, which hosts shipmill's workflows
LOCAL_CALLER = ".github/workflows/operate-self.yml"


def test_doctor_accepts_the_bot_repo_calling_its_own_operate_yml_locally(repo: Repo) -> None:
    """In the repository hosting shipmill, operate.yml is the reusable workflow, so its caller
    has another name and calls it as ./.github/workflows/operate.yml (#53)"""

    def operate_check() -> tuple[str, str] | None:
        found = {c.name: (c.status, c.detail) for c in doctor(repo.root, repo.github)}
        return found.get("operate")

    configure(repo)
    repo.write(str(OPERATE_CALLER), (SHIPMILL / OPERATE_CALLER).read_text(encoding="utf-8"))
    uncalled = f"staging, production use from or health, but no job in {OPERATE_CALLER} calls shipmill's operate.yml"
    assert operate_check() == ("WARN", uncalled)
    local = operate_caller_text().replace(f"{BOT_REPO}/.github/workflows/operate.yml@{BOT_REF}", f"./{OPERATE_CALLER}")
    assert f"uses: ./{OPERATE_CALLER}\n" in local
    repo.write(LOCAL_CALLER, local)
    rolls_back = (
        "runs shipmill operate with deployments, actions, issues: write; rolls back after 3 failed checks in a row"
        " and opens an incident labelled 'incident', which holds rc, stable"
    )
    assert operate_check() == ("PASS", f"{LOCAL_CALLER} {rolls_back}")
    repo.write(LOCAL_CALLER, local.replace("      issues: write", "      issues: read"))
    assert operate_check() == ("WARN", f"the job in {LOCAL_CALLER} that calls operate.yml lacks issues: write")
    # a repository not hosting shipmill: its own operate.yml is the caller, whatever else calls it
    repo.write(str(OPERATE_CALLER), operate_caller_text())
    assert operate_check() == ("PASS", f"{OPERATE_CALLER} {rolls_back}")


def test_shipmills_own_pages_environment_and_operate_caller_pass_doctor(repo: Repo) -> None:
    """This repository's config and workflows, checked in a scratch repository so doctor asks
    no real remote"""
    for path in (SHIPMILL / ".github").rglob("*"):
        if path.is_file():
            repo.write(str(path.relative_to(SHIPMILL)), path.read_text(encoding="utf-8"))
    repo.write("changelog.d/README.md", (SHIPMILL / "changelog.d" / "README.md").read_text(encoding="utf-8"))
    checks = {c.name: (c.status, c.detail) for c in doctor(repo.root, repo.github)}
    assert checks["operate"] == (
        "PASS",
        f"{LOCAL_CALLER} runs shipmill operate with deployments, actions, issues: write; rolls back after 3 failed"
        " checks in a row and opens an incident labelled 'incident', which holds stable",
    )
    assert checks["environment"] == (
        "PASS",
        "deploy.yml (github-pages) runs on workflow_dispatch with 'tag' and 'environment' inputs; fails a run that"
        " isn't on the tag; starts operate-self.yml after the deploy",
    )
    pages = repo.policy.environments["github-pages"]
    assert (pages.lane, pages.workflow, pages.health) == (
        Lane.STABLE,
        "deploy.yml",
        "https://shipmill.dev/health.json",
    )
    assert repo.policy.operate.rollback_after == 3


def test_the_deploy_workflow_reports_the_tag_as_the_version_operate_checks() -> None:
    """health.json names the tag without its v, which operate's version rule accepts; the
    drill's fault names another version"""
    text = (SHIPMILL / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert 'version="${TAG#v}"' in text and 'version="0.0.0-simulated-failure"' in text
    assert '"$ENVIRONMENT" != "github-pages"' in text
    assert '"$GITHUB_REF" != "refs/tags/$TAG"' in text  # a run off the tag fails (#80)
    # operate starts in a job of its own, after the deploy job, so its failure can't fail the deployment (#84)
    operate_job = text[text.index("\n  operate:\n") :]
    assert "    needs: deploy\n" in operate_job and "      actions: write" in operate_job
    deployed = Version.parse("1.2.0")
    http = FakeHttp()
    http.answer("u", '{"version": "1.2.0"}')
    assert probe(http, "u", deployed).healthy
    http.answer("u", '{"version": "0.0.0-simulated-failure"}')
    assert not probe(http, "u", deployed).healthy


def test_operate_yml_runs_one_at_a_time_and_takes_the_callers_grant() -> None:
    text = (Path(__file__).parent.parent / ".github" / "workflows" / "operate.yml").read_text()
    assert re.search(r"^    concurrency:\n      group: shipmill-operate\n      cancel-in-progress: false$", text, re.M)
    assert not re.search(r"^\s*permissions:", text, re.MULTILINE)
    assert 'cron: "*/10 * * * *"' in operate_caller_text()


# -- rollback and incidents (#31) ------------------------------------------------------------

ROLLBACK = ("deploy.yml", "v1.0.0", "v1.0.0", {"environment": "production"})


@pytest.fixture
def failing(setup: tuple[Repo, FakeHttp]) -> tuple[Repo, FakeHttp]:
    """production got v1.1.0rc1 (it ran v1.0.0 before), and its health check answers 503"""
    repo, http = setup
    repo.github.deploy("production", "v1.1.0rc1", minutes(-2), S.IN_PROGRESS, S.SUCCESS)
    http.answer(PRODUCTION, "<h1>Service Unavailable</h1>\n  database  is down", status=503)
    return repo, http


def production_writes(repo: Repo) -> list[DeploymentState]:
    """The statuses written on production's v1.1.0rc1 deployment"""
    [bad] = [d for d in repo.github.envs["production"] if d.ref == "v1.1.0rc1"]
    return [state for deployment, state, _ in repo.github.status_writes if deployment == bad.id]


def fail_three_times(repo: Repo, http: FakeHttp) -> dict[str, Report]:
    run(repo, http, minutes(0))
    run(repo, http, minutes(10))
    return run(repo, http, minutes(20))


def incident(repo: Repo) -> Issue:
    [found] = [i for n, i in repo.github.issues.items() if "incident" in repo.github.labels[n]]
    return found


def test_three_failed_checks_roll_back_to_the_last_good_tag_and_open_one_incident(
    failing: tuple[Repo, FakeHttp],
) -> None:
    repo, http = failing
    found = run(repo, http, minutes(0))
    assert "HTTP 503, failing for 0 min, 1 of 3 failed checks to roll back" in found["production"].health
    run(repo, http, minutes(10))
    assert repo.github.dispatched == [] and repo.github.issues == {}
    found = run(repo, http, minutes(20))
    # v1.0.0 ran here before: a rollback is the deploy exempt from deploying a tag at most once
    assert repo.github.dispatched == [ROLLBACK]
    issue = incident(repo)
    assert issue.title == "Incident: production fails its health checks on v1.1.0rc1"
    assert "<!-- shipmill:incident env=production tag=v1.1.0rc1 to=v1.0.0 state=rolled-back -->" in issue.body
    assert "**production** failed 3 health checks in a row on **v1.1.0rc1**, since 2026-10-05 00:00 UTC" in issue.body
    assert f"- Health check: `{PRODUCTION}`" in issue.body
    assert "- Last check: HTTP 503" in issue.body
    assert "- Body: `<h1>Service Unavailable</h1> database is down`" in issue.body
    assert "started deploy.yml with v1.0.0: https://github.com/o/demo/actions/runs/1" in issue.body
    assert "the rc, stable lanes don't release" in issue.body
    assert found["production"].action.startswith(f"marked failure; opened incident #{issue.number}; rolled back")
    # three failure statuses count the checks; a fourth run writes none, opens and starts nothing
    found = run(repo, http, minutes(30))
    assert production_writes(repo) == [S.FAILURE, S.FAILURE, S.FAILURE]
    assert repo.github.dispatched == [ROLLBACK] and len(repo.github.issues) == 1
    assert f"incident #{issue.number} open (rolled-back)" in found["production"].action
    assert "3 of 3 failed checks" in found["production"].health


def test_the_incident_comments_once_when_the_rollback_is_healthy(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    fail_three_times(repo, http)
    number = incident(repo).number
    repo.github.deploy("production", "v1.0.0", minutes(25), S.IN_PROGRESS, S.SUCCESS)  # the rollback ran
    http.answer(PRODUCTION, '{"version": "1.0.0"}')
    found = run(repo, http, minutes(30))
    assert repo.github.comments[number] == ["production is healthy again on v1.0.0 (HTTP 200, version 1.0.0)."]
    assert "state=healthy" in incident(repo).body
    assert f"comment on incident #{number}: healthy again" in found["production"].action
    found = run(repo, http, minutes(200))
    assert len(repo.github.comments[number]) == 1
    # staging baked v1.1.0rc1 long ago, but it was deployed here already: no promotion again
    assert repo.github.dispatched == [ROLLBACK]
    assert "v1.1.0rc1 was deployed here already (failure)" in found["production"].action


def test_a_rollback_that_fails_too_comments_and_stops(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    fail_three_times(repo, http)
    number = incident(repo).number
    repo.github.deploy("production", "v1.0.0", minutes(25), S.IN_PROGRESS, S.SUCCESS)  # the rollback ran
    for at in (30, 40):
        assert "fails too" not in run(repo, http, minutes(at))["production"].action
    found = run(repo, http, minutes(50))
    [comment] = repo.github.comments[number]
    assert comment.startswith("v1.0.0, the rollback, fails its health checks too (HTTP 503)")
    assert "doesn't roll production back a second time" in comment
    assert "no second rollback" in found["production"].action
    assert "state=stopped" in incident(repo).body
    found = run(repo, http, minutes(60))
    assert repo.github.dispatched == [ROLLBACK] and len(repo.github.comments[number]) == 1
    assert len(repo.github.issues) == 1
    assert "waiting for a person" in found["production"].action


def test_an_open_incident_holds_the_blocker_lanes(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    fail_three_times(repo, http)
    issue = incident(repo)
    repo.merge(1, "Added", "Feature A")
    configure(repo)  # the merge reset the checkout to main

    def plan(lane: Lane) -> Decision:
        repo.git.fetch("+refs/heads/main:refs/remotes/origin/main")
        repo.git.run("checkout", "-q", "--detach", "origin/main")
        return Planner(repo.git, repo.policy, repo.github, minutes(40)).plan(Event.MANUAL, lane)

    held = plan(Lane.RC)
    assert held.action == "skip"
    assert f"held, open 'incident' issues: #{issue.number} {issue.title}" in held.reason
    assert plan(Lane.DEV).action == "release"  # dev isn't in blocker_lanes
    repo.github.close_issue(issue.number, "Fixed by the hotfix")
    assert plan(Lane.RC).action == "release"


def test_the_hold_opens_the_incident_but_rolls_nothing_back(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    repo.github.holds = ["#7 Investigating"]
    found = fail_three_times(repo, http)
    assert repo.github.dispatched == []
    body = incident(repo).body
    assert "state=proposed" in body
    assert f"would roll back to v1.0.0, but held by {HOLD_LABEL} #7." in body
    assert f"Close the open `{HOLD_LABEL}` issues first; then approve the rollback:" in body
    assert "would roll back to v1.0.0, but held by" in found["production"].action
    with pytest.raises(ReleaseError, match=f"held by {HOLD_LABEL} #7; close it to approve a rollback"):
        approve_rollback(repo.policy, repo.github, "production", dry_run=False)
    assert repo.github.dispatched == []


def test_propose_has_the_incident_propose_and_approve_rolls_back_once(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    configure(repo, 'rollback = "propose"\n')
    fail_three_times(repo, http)
    assert repo.github.dispatched == []
    issue = incident(repo)
    assert "would roll back to v1.0.0, but rollback autonomy is propose." in issue.body
    assert "gh workflow run operate.yml -f approve-rollback=production -f dry-run=false" in issue.body
    assert approve_rollback(repo.policy, repo.github, "production", dry_run=True).startswith("would dispatch")
    assert repo.github.dispatched == []
    done = approve_rollback(repo.policy, repo.github, "production", dry_run=False)
    assert done == f"dispatched deploy.yml with v1.0.0 to production; rolled back for incident #{issue.number}"
    assert repo.github.dispatched == [ROLLBACK]
    assert "state=rolled-back" in incident(repo).body
    [comment] = repo.github.comments[issue.number]
    assert comment.startswith("Approved: rolled back, started `deploy.yml` with v1.0.0")
    with pytest.raises(ReleaseError, match="no open incident proposes a rollback of production"):
        approve_rollback(repo.policy, repo.github, "production", dry_run=False)
    run(repo, http, minutes(30))
    assert repo.github.dispatched == [ROLLBACK]


def test_observe_opens_the_incident_and_only_says_what_it_would_roll_back(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    configure(repo, 'rollback = "observe"\n')
    fail_three_times(repo, http)
    assert repo.github.dispatched == []
    body = incident(repo).body
    assert "state=failing" in body and "would roll back to v1.0.0, but rollback autonomy is observe." in body
    assert "approve-rollback" not in body


@dataclass
class RefusingIssues(FakeGitHub):
    """GitHub refusing the first issue shipmill opens, as for a job without issues: write"""

    refused: bool = False

    def create_issue(self, title: str, body: str, labels: Sequence[str] = ()) -> int:
        if not self.refused:
            self.refused = True
            raise ReleaseError("gh issue create failed: HTTP 403")
        return super().create_issue(title, body, labels)


def test_a_queued_rollback_is_not_dispatched_again(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    refusing = RefusingIssues(envs=repo.github.envs, statuses=repo.github.statuses)
    repo.github = refusing
    run(repo, http, minutes(0))
    run(repo, http, minutes(10))
    with pytest.raises(ReleaseError, match="grant `issues: write`"):
        run(repo, http, minutes(20))
    assert refusing.dispatched == [ROLLBACK] and refusing.issues == {}
    assert production_writes(repo) == [S.FAILURE, S.FAILURE]  # the third check isn't recorded: it counts again
    found = run(repo, http, minutes(30))  # the rollback's run is still queued
    assert refusing.dispatched == [ROLLBACK]
    assert "rollback to v1.0.0 started already (run 1, queued)" in found["production"].action
    assert "rollback to v1.0.0 started already (run 1, queued)" in incident(repo).body


def test_no_earlier_good_tag_opens_the_incident_without_a_rollback(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    http.answer(STAGING, "", status=500)
    found = fail_three_times(repo, http)
    assert repo.github.dispatched == []
    assert "no rollback: no earlier tag reached success here" in found["staging"].action
    assert "to=- state=failing" in incident(repo).body


def test_a_closed_incident_is_not_opened_again(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    configure(repo, 'rollback = "observe"\n')
    fail_three_times(repo, http)
    number = incident(repo).number
    repo.github.close_issue(number, "Known; fixing it")
    found = run(repo, http, minutes(30))
    assert repo.github.issues == {}
    assert f"incident #{number} for v1.1.0rc1 was closed while it failed" in found["production"].action


def test_failing_again_after_the_incident_closed_opens_another(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    configure(repo, 'rollback = "observe"\n')
    fail_three_times(repo, http)
    first = incident(repo).number
    http.answer(PRODUCTION, "ok")
    run(repo, http, minutes(30))  # healthy again
    repo.github.now = minutes(35)
    repo.github.close_issue(first, "Resolved")
    http.answer(PRODUCTION, "", status=503)
    for at in (40, 50):
        run(repo, http, minutes(at))
    found = run(repo, http, minutes(60))
    # a stretch of failed checks begun after the close: the person closed the old one, not this
    second = incident(repo).number
    assert second != first and "state=failing" in incident(repo).body
    assert f"opened incident #{second}" in found["production"].action


def test_the_rollback_tag_failing_after_its_incident_closed_opens_another(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    fail_three_times(repo, http)
    first = incident(repo).number
    repo.github.deploy("production", "v1.0.0", minutes(25), S.IN_PROGRESS, S.SUCCESS)  # the rollback ran
    http.answer(PRODUCTION, '{"version": "1.0.0"}')
    run(repo, http, minutes(30))
    repo.github.now = minutes(35)
    repo.github.close_issue(first, "Resolved")
    http.answer(PRODUCTION, "", status=503)
    for at in (40, 50):
        run(repo, http, minutes(at))
    found = run(repo, http, minutes(60))
    issue = incident(repo)
    assert issue.number != first and "env=production tag=v1.0.0 to=- state=failing" in issue.body
    assert f"opened incident #{issue.number}; no rollback" in found["production"].action
    assert repo.github.dispatched == [ROLLBACK]  # never back to v1.1.0rc1, whose checks failed


def test_a_dry_run_opens_no_incident(failing: tuple[Repo, FakeHttp]) -> None:
    repo, http = failing
    run(repo, http, minutes(0))
    run(repo, http, minutes(10))
    found = run(repo, http, minutes(20), dry_run=True)
    assert "would open an incident; would roll back: start deploy.yml with v1.0.0" in found["production"].action
    assert repo.github.issues == {} and repo.github.dispatched == []


def test_an_incident_shows_no_secret_of_the_health_url_and_caps_the_body() -> None:
    assert shown_url("https://user:pw@Example.com:8443/health?token=s3cret#x") == "https://example.com:8443/health"
    quoted = excerpt("`x`" + "a" * 1000)
    assert len(quoted) == 300 and quoted.startswith("'x'") and quoted.endswith("...")


def test_an_incident_quotes_no_token_of_the_health_body() -> None:
    body = (
        '{"error": "db down", "password": "hunter2", "api_key":"k-123", "Authorization": "Bearer abc.def"}'
        " dsn=postgres://app:s3cret@db:5432/x token=ghp_0123456789abcdefABCDEF0123456789abcd"
    )
    quoted = excerpt(body)
    for secret in ("hunter2", "k-123", "abc.def", "s3cret", "ghp_0123456789abcdefABCDEF0123456789abcd"):
        assert secret not in quoted
    assert '"error": "db down"' in quoted and "postgres://[redacted]@db:5432/x" in quoted
    assert excerpt("x " + "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZg") == "x [redacted]"  # a long opaque run


def test_the_operate_section_is_read_strictly(repo: Repo) -> None:
    configure(repo)
    assert (repo.policy.operate.rollback_after, repo.policy.operate.incident_label) == (3, "incident")
    base = POLICY + ENVIRONMENTS
    repo.write(repo.policy_file, base + '\n[operate]\nrollback_after = 5\nincident_label = "sev"\n')
    assert (repo.policy.operate.rollback_after, repo.policy.incident_label) == (5, "sev")
    for bad, match in (
        ("rollback_after = 0", r"rollback_after must be in 1\.\.20"),
        ('incident_label = " "', "incident_label must not be empty"),
        ("rollback = 3", r"unknown keys \['rollback'\]"),
    ):
        repo.write(repo.policy_file, base + f"\n[operate]\n{bad}\n")
        with pytest.raises(ReleaseError, match=match):
            _ = repo.policy
    repo.write(repo.policy_file, base + "\n[operate]\nrollback_after = 0\n")
    assert {c.name: c.status for c in doctor(repo.root, repo.github)}["policy"] == "FAIL"


def test_cli_approve_rollback(failing: tuple[Repo, FakeHttp], tmp_path: Path) -> None:
    repo, http = failing
    configure(repo, 'rollback = "propose"\n')
    fail_three_times(repo, http)
    summary = tmp_path / "summary.md"
    argv = ["--repo", str(repo.root), "operate", "--approve-rollback", "production", "--step-summary", str(summary)]
    assert main(argv, repo.github, http) == 0
    assert summary.read_text().startswith("dispatched deploy.yml with v1.0.0 to production")
    assert repo.github.dispatched == [ROLLBACK]


def test_a_deploy_proposal_is_labelled_and_approved_by_its_label(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    run(repo, http, minutes(61))
    [number] = repo.github.issues
    assert repo.github.labels[number] == (PROPOSAL_LABEL,)
    repo.github.create_issue("Bug", "something broke")
    repo.github.scan_limit = 1  # the proposal is past the page find_issue reads
    run(repo, http, minutes(71))
    assert list(repo.github.issues) == [number, number + 1]  # no duplicate
    assert approve(repo.policy, repo.github, "production", dry_run=False).endswith(f"closed #{number}")


def test_a_deployed_proposal_is_closed_when_found_by_its_label_past_the_scan(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    configure(repo, 'deploy.production = "propose"\n')
    run(repo, http, minutes(61))
    [number] = repo.github.issues
    repo.github.create_issue("Bug", "something broke")
    repo.github.scan_limit = 1
    repo.github.deploy("production", "v1.1.0rc1", minutes(62), S.IN_PROGRESS, S.SUCCESS)
    http.answer(PRODUCTION, '{"version": "v1.1.0rc1"}')
    assert run(repo, http, minutes(70))["production"].action.endswith(f"closed proposal #{number}: v1.1.0rc1 deployed")


# -- compare (spec 084) ----------------------------------------------------------------------

OLD = "https://v1-0-0rc1---staging.example.run.app"  # the previous release, still addressable
NEW = "https://staging.example.com/"
NEW_AT = NEW.rstrip("/")
ITEMS = "/api/items?limit=100"
PROBES = f"""
[environments.staging]
lane = "rc"
workflow = "deploy.yml"
health = "{STAGING}"

[[environments.staging.probes]]
name = "items"
path = "{ITEMS}"
ignore = ["/generated_at", "/items/*/updated_at"]

[[environments.staging.probes]]
name = "home"
path = "/"

[environments.production]
from = "staging"
workflow = "deploy.yml"
bake_minutes = 60
"""
SAME = f"{COMPARE_PREFIX} same answers as v1.0.0rc1 on 2 probes"


def differ(names: str) -> str:
    """The failure compare status an unexplained difference writes"""
    return f"{COMPARE_PREFIX} answers differ from v1.0.0rc1 on {names}"


def items(stamp: str, count: int = 2, request: str = "r1") -> str:
    found = [{"id": i, "updated_at": stamp} for i in range(count)]
    return json.dumps({"generated_at": stamp, "request_id": request, "items": found})


def located(repo: Repo, deployment: int, url: str) -> None:
    """The deploy job's `environment: url`, as GitHub Actions records it on the success status"""
    statuses = repo.github.statuses[deployment]
    statuses[-1] = replace(statuses[-1], environment_url=url)


def probes_asked(http: FakeHttp) -> list[str]:
    return [url for url, _ in http.asked if url != STAGING]


def compare_writes(repo: Repo) -> list[tuple[DeploymentState, str]]:
    return [(state, text) for _, state, text in repo.github.status_writes if text.startswith(COMPARE_PREFIX)]


@dataclass
class Probed:
    repo: Repo
    http: FakeHttp
    old: int  # the previous release's deployment
    new: int  # the current one's


@pytest.fixture
def probed(repo: Repo) -> Probed:
    """staging ran v1.0.0rc1 and runs v1.1.0rc1 since T0; both answer the probes alike, but
    for the time stamps the probe ignores"""
    repo.write(repo.policy_file, POLICY + PROBES)
    tag(repo, "v1.0.0rc1", T0 - dt.timedelta(days=3))
    tag(repo, "v1.1.0rc1", minutes(-5))
    old = repo.github.deploy("staging", "v1.0.0rc1", T0 - dt.timedelta(days=2), S.IN_PROGRESS, S.SUCCESS)
    new = repo.github.deploy("staging", "v1.1.0rc1", minutes(-1), S.IN_PROGRESS, S.SUCCESS)
    located(repo, old, OLD)
    located(repo, new, NEW)
    http = FakeHttp()
    http.answer(STAGING, '{"version": "1.1.0rc1"}')
    http.answer(OLD + ITEMS, items("2026-10-03T00:00:00Z"))
    http.answer(OLD + "/", "<h1>Home</h1>")
    http.answer(NEW_AT + ITEMS, items("2026-10-05T00:00:00Z"))
    http.answer(NEW_AT + "/", "<h1>Home</h1>")
    return Probed(repo, http, old, new)


def test_s084_1_an_environment_without_probes_sends_only_its_health_check(setup: tuple[Repo, FakeHttp]) -> None:
    repo, http = setup
    found = run(repo, http, minutes(10))
    assert sorted({url for url, _ in http.asked}) == [PRODUCTION, STAGING]
    assert not any("compare" in r.action for r in found.values())
    assert compare_writes(repo) == []


def test_s084_2_a_deployment_status_carries_its_environment_url(tmp_path: Path) -> None:
    statuses = [
        {"id": 1, "state": "in_progress", "created_at": "2026-10-05T00:00:00Z", "description": ""},
        {"id": 2, "state": "success", "created_at": "2026-10-05T00:01:00Z", "description": "", "environment_url": NEW},
        {"id": 3, "state": "success", "created_at": "2026-10-05T00:02:00Z", "description": SAME, "environment_url": ""},
    ]
    (tmp_path / "statuses.json").write_text(json.dumps(statuses), encoding="utf-8")
    script = tmp_path / "gh"
    script.write_text(f"#!/bin/sh\ncat {tmp_path / 'statuses.json'}\n", encoding="utf-8")
    script.chmod(0o755)
    found = GhCli(tmp_path, gh=str(script)).deployment_statuses(1000)
    assert [s.environment_url for s in found] == ["", NEW, ""]
    assert address(found) == NEW  # the newest non-empty one
    assert address(found[:1]) is None


@pytest.mark.parametrize("which", ["new", "old"])
def test_s084_2_a_release_without_an_address_is_not_compared(probed: Probed, which: str) -> None:
    repo, http = probed.repo, probed.http
    located(repo, probed.new if which == "new" else probed.old, "")
    missing = "v1.1.0rc1" if which == "new" else "v1.0.0rc1"
    for at in (0, 10):  # the next run tries again
        found = run(repo, http, minutes(at))
        assert f"not compared: {missing} has no environment_url" in found["staging"].action
    assert probes_asked(http) == [] and compare_writes(repo) == [] and repo.github.issues == {}


def test_s084_2_a_previous_release_answering_no_probe_is_unreachable(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answers[OLD + ITEMS] = Unreachable("connection refused")
    http.answers[OLD + "/"] = Unreachable("connection refused")
    found = run(repo, http, minutes(0))
    assert f"not compared: v1.0.0rc1 at {OLD} unreachable" in found["staging"].action
    assert compare_writes(repo) == [] and repo.github.issues == {}
    asked = len(probes_asked(http))
    run(repo, http, minutes(10))  # the next run tries again
    assert len(probes_asked(http)) == 2 * asked


def test_s084_3_each_probe_is_a_get_twice_to_the_previous_release_and_once_to_the_new(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: same on 2 probes" in found["staging"].action
    assert probes_asked(http) == [OLD + ITEMS, OLD + ITEMS, NEW_AT + ITEMS, OLD + "/", OLD + "/", NEW_AT + "/"]
    # through the Http protocol, which sends no body and no credential: a URL, a timeout, a read cap
    assert {timeout for _, timeout in http.asked} == {10.0}
    assert {http.limits[url] for url in probes_asked(http)} == {PROBE_BODY_LIMIT} == {1024 * 1024}
    assert http.limits[STAGING] == BODY_LIMIT  # the health check reads as before


def test_s084_3_json_noise_of_the_previous_release_is_removed(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.turns[OLD + ITEMS] = [HttpResponse(200, items("2026-10-03T00:00:00Z", request="r1"), 0.1)]
    http.answer(OLD + ITEMS, items("2026-10-03T00:00:00Z", request="r2"))  # a request id: noise
    http.answer(NEW_AT + ITEMS, items("2026-10-05T00:00:00Z", request="r3"))
    found = run(repo, http, minutes(0))
    assert "same on 2 probes" in found["staging"].action
    assert compare_writes(repo) == [(S.SUCCESS, SAME)]


def test_s084_3_a_non_json_probe_whose_previous_answers_differ_is_unstable(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.turns[OLD + "/"] = [HttpResponse(200, "<h1>Home</h1><!-- 1 -->", 0.1)]
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: same on 1 probes (unstable: home)" in found["staging"].action
    assert compare_writes(repo) == [(S.SUCCESS, f"{COMPARE_PREFIX} same answers as v1.0.0rc1 on 1 probes")]


def test_no_steady_probe_writes_nothing_and_the_next_run_tries_again(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.turns[OLD + "/"] = [HttpResponse(200, "<h1>Home</h1><!-- 1 -->", 0.1)]
    http.turns[OLD + ITEMS] = [HttpResponse(500, "", 0.1)]  # the previous release's statuses differ
    found = run(repo, http, minutes(0))
    assert "not compared: no probe answered steadily on v1.0.0rc1 (unstable: items, home)" in found["staging"].action
    assert compare_writes(repo) == []
    assert "same on 2 probes" in run(repo, http, minutes(10))["staging"].action


def test_s084_3_non_json_answers_read_the_same_only_when_identical(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + "/", "<h1>Home </h1>")
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: differs on home" in found["staging"].action
    assert compare_writes(repo) == [(S.FAILURE, differ("home"))]


@pytest.mark.parametrize(
    ("answer", "differs"),
    [
        (items("2026-10-05T00:00:00Z", count=1), True),  # half the items
        (items("2026-10-05T00:00:00Z").replace('"id"', '"key"'), True),  # a field gone
        (items("2026-10-05T00:00:00Z", request="r9"), True),  # the previous release's two answers agreed on it
        ("not json", True),
        (items("2026-10-06T00:00:00Z"), False),  # differs only at the ignore pointers
    ],
)
def test_s084_3_json_answers_differ_beyond_the_ignore_pointers(probed: Probed, answer: str, differs: bool) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + ITEMS, answer)
    found = run(repo, http, minutes(0))["staging"].action
    assert ("differs on items" in found) is differs
    assert compare_writes(repo) == ([(S.FAILURE, differ("items"))] if differs else [(S.SUCCESS, SAME)])


def test_s084_3_a_status_that_differs_is_a_difference(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + ITEMS, "", status=404)
    assert "differs on items" in run(repo, http, minutes(0))["staging"].action


def test_s084_4_a_difference_is_sent_again_and_counts_only_when_it_holds(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.turns[NEW_AT + ITEMS] = [HttpResponse(200, items("2026-10-05T00:00:00Z", count=1), 0.1)]  # once
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: same on 2 probes" in found["staging"].action
    assert probes_asked(http)[:5] == [OLD + ITEMS, OLD + ITEMS, NEW_AT + ITEMS, OLD + ITEMS, NEW_AT + ITEMS]
    assert compare_writes(repo) == [(S.SUCCESS, SAME)]


def test_s084_4_a_difference_that_holds_is_sent_three_times_to_the_previous_release(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + ITEMS, items("2026-10-05T00:00:00Z", count=1))
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: differs on items" in found["staging"].action
    assert compare_writes(repo) == [(S.FAILURE, differ("items"))]
    assert probes_asked(http).count(OLD + ITEMS) == 3


def test_s084_4_no_answer_from_the_new_release_is_a_difference(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answers[NEW_AT + "/"] = Unreachable("timed out")
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: differs on home" in found["staging"].action


def test_s084_4_no_answer_from_the_previous_release_leaves_a_probe_unchecked(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answers[OLD + "/"] = Unreachable("timed out")
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: same on 1 probes (unchecked: home)" in found["staging"].action


def test_s084_5_same_answers_write_one_success_status_and_are_not_compared_again(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    found = run(repo, http, minutes(0))
    assert "; compared with v1.0.0rc1: same on 2 probes, marked success;" in found["staging"].action
    assert compare_writes(repo) == [(S.SUCCESS, SAME)]
    assert [d for d, _, text in repo.github.status_writes if text == SAME] == [probed.new]
    asked = len(probes_asked(http))
    for at in (10, 20):
        found = run(repo, http, minutes(at))
        assert "compare" not in found["staging"].action
    assert len(probes_asked(http)) == asked and len(compare_writes(repo)) == 1


def test_a_compare_status_is_not_a_health_status(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    run(repo, http, minutes(0))  # baking for production: in_progress, then the compare's success
    run(repo, http, minutes(10))
    staging = [(s, t) for d, s, t in repo.github.status_writes if d == probed.new]
    assert staging == [(S.IN_PROGRESS, f"{STATUS_PREFIX}: baking for 60 min"), (S.SUCCESS, SAME)]  # no second
    http.answer(STAGING, "", status=500)
    assert "1 of 3 failed checks" in run(repo, http, minutes(20))["staging"].health
    assert "2 of 3 failed checks" in run(repo, http, minutes(30))["staging"].health
    http.answer(STAGING, '{"version": "1.1.0rc1"}')
    found = run(repo, http, minutes(40))  # the bake restarts at the recovery, not at the compare
    assert "baking 0 of 60 min" in found["staging"].health


def test_a_dry_run_compares_and_writes_nothing(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    found = run(repo, http, minutes(0), dry_run=True)
    assert "compared with v1.0.0rc1: same on 2 probes, would mark success" in found["staging"].action
    assert repo.github.status_writes == []


def test_s084_11_a_rollback_is_not_compared_with_the_release_it_replaced(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    back = repo.github.deploy("staging", "v1.0.0rc1", minutes(5), S.IN_PROGRESS, S.SUCCESS)
    located(repo, back, OLD)
    http.answer(STAGING, '{"version": "1.0.0rc1"}')
    found = run(repo, http, minutes(10))
    assert "compare" not in found["staging"].action
    assert probes_asked(http) == [] and compare_writes(repo) == []


def test_s084_11_a_deployment_compared_already_is_not_compared_again(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    repo.github.statuses[probed.new].append(
        DeploymentStatus(99, S.SUCCESS, minutes(0), f"{COMPARE_PREFIX} answers differ from v1.0.0rc1 on items")
    )
    run(repo, http, minutes(10))
    assert probes_asked(http) == [] and compare_writes(repo) == []


def test_s084_11_a_failed_health_check_this_run_sends_no_probe(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(STAGING, "", status=503)
    found = run(repo, http, minutes(0))
    assert found["staging"].health.startswith("unhealthy: HTTP 503")
    assert probes_asked(http) == [] and compare_writes(repo) == []


def test_without_health_a_deployment_is_compared_on_its_success(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    repo.write(repo.policy_file, repo.read(repo.policy_file).replace(f'health = "{STAGING}"\n', ""))
    found = run(repo, http, minutes(0))
    assert STAGING not in [url for url, _ in http.asked]
    assert "same on 2 probes" in found["staging"].action


def test_s084_3_an_answer_json_cannot_hold_is_compared_as_text(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    huge = "1" * 5000  # past Python's limit on an integer's digits: json.loads raises ValueError
    http.answer(OLD + "/", huge)
    http.answer(NEW_AT + "/", huge)
    assert "same on 2 probes" in run(repo, http, minutes(0))["staging"].action


# -- a difference: explained, or an incident and a rollback (#1436) ---------------------------

ROLLBACK_STAGING = ("deploy.yml", "v1.0.0rc1", "v1.0.0rc1", {"environment": "staging"})
HALF = items("2026-10-05T00:00:00Z", count=1)  # half the items the previous release answers


def land(repo: Repo) -> None:
    """Between v1.0.0rc1 and v1.1.0rc1 on main: a squash (#7), a merge commit (#8) whose
    branch holds a squash subject (#9) off the first-parent line, and a commit naming none"""
    repo.git.run("commit", "-q", "--allow-empty", "-m", "Halve the page (#7)")
    repo.git.run("checkout", "-q", "-b", "side")
    repo.git.run("commit", "-q", "--allow-empty", "-m", "Side work (#9)")
    repo.git.run("checkout", "-q", "main")
    repo.git.run("merge", "-q", "--no-ff", "side", "-m", "Merge pull request #8 from o/side")
    repo.git.run("commit", "-q", "--allow-empty", "-m", "Tidy up")
    repo.git.run("tag", "-f", "-a", "v1.1.0rc1", "-m", "v1.1.0rc1")


def rollback_autonomy(repo: Repo, level: str) -> None:
    repo.write(repo.policy_file, POLICY + PROBES + f'\n[autonomy]\nrollback = "{level}"\n')


def test_s084_6_a_difference_a_pull_request_names_is_explained(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    land(repo)
    repo.github.bodies = {7: "Halves the page.\r\n\r\nChanges answers: items\r\n", 8: "Refactor"}
    http.answer(NEW_AT + ITEMS, HALF)
    found = run(repo, http, minutes(0))
    explained = f"{COMPARE_PREFIX} differs from v1.0.0rc1 on items, explained by #7"
    assert compare_writes(repo) == [(S.SUCCESS, explained)]
    assert "compared with v1.0.0rc1: differs on items, explained by #7, marked success" in found["staging"].action
    # the first-parent subjects, newest first: #9 is off that line, so its body is never read
    assert repo.github.body_reads == [8, 7]
    assert repo.github.issues == {} and repo.github.dispatched == []


def test_s084_6_bodies_are_read_only_when_a_difference_holds(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    land(repo)
    assert "same on 2 probes" in run(repo, http, minutes(0))["staging"].action
    assert repo.github.body_reads == []


def test_s084_6_a_failed_read_of_a_body_stops_the_run_writing_nothing(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    land(repo)
    repo.github.bodies = {7: "Changes answers: items"}  # #8, read first, is not found
    http.answer(NEW_AT + ITEMS, HALF)
    with pytest.raises(ReleaseError, match=r"issues/8 failed: Not Found \(HTTP 404\)"):
        run(repo, http, minutes(0))
    # not even staging's health status: the run exits before it writes for the environment
    assert repo.github.status_writes == [] and repo.github.issues == {} and repo.github.dispatched == []


def test_s084_6_a_difference_on_a_probe_no_body_names_is_unexplained(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    land(repo)
    repo.github.bodies = {7: "Changes answers: home", 8: "Changes answers: items-v2"}
    http.answer(NEW_AT + ITEMS, HALF)
    run(repo, http, minutes(0))
    assert compare_writes(repo) == [(S.FAILURE, differ("items"))]


def test_s084_6_a_pull_requests_body_is_read_through_the_issues_endpoint(tmp_path: Path) -> None:
    script = tmp_path / "gh"
    log = tmp_path / "args"
    answer = tmp_path / "answer.json"
    script.write_text(f'#!/bin/sh\necho "$@" > {log}\ncat {answer}\n', encoding="utf-8")
    script.chmod(0o755)
    gh = GhCli(tmp_path, gh=str(script))
    answer.write_text(json.dumps({"number": 7, "body": "Changes answers: items", "pull_request": {}}), encoding="utf-8")
    assert gh.pull_body(7) == "Changes answers: items"
    assert log.read_text(encoding="utf-8").split() == ["api", "-X", "GET", "repos/{owner}/{repo}/issues/7"]
    answer.write_text(json.dumps({"number": 7, "body": None, "pull_request": {}}), encoding="utf-8")
    assert gh.pull_body(7) == ""
    # a subject's number that names an issue, which anyone may file, names no pull request
    answer.write_text(json.dumps({"number": 7, "body": "Changes answers: items"}), encoding="utf-8")
    assert gh.pull_body(7) == ""


def test_pull_numbers_read_squash_and_merge_subjects() -> None:
    subjects = ["Fix it (#12)", "Merge pull request #13 from o/b", "Fix it again (#12)", "Tidy (#x)", "Release 1.0"]
    assert pull_numbers(subjects) == [12, 13]
    assert changes_answers("Changes answers: items, `orders` ,\n  Changes answers: home\nchanges answers: x") == {
        "items",
        "orders",
        "home",
    }


def test_s084_7_an_unexplained_difference_writes_one_failure_outside_health_and_promotion(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    rollback_autonomy(repo, "observe")
    http.answer(NEW_AT + ITEMS, HALF)
    found = run(repo, http, minutes(0))
    assert "compared with v1.0.0rc1: differs on items, marked failure; opened incident" in found["staging"].action
    assert compare_writes(repo) == [(S.FAILURE, differ("items"))]
    # a health status, not the compare's, counts the bake: still from the success at T0
    assert run(repo, http, minutes(10))["staging"].health.endswith("baking 10 of 60 min")
    assert len(compare_writes(repo)) == 1  # compared once
    found = run(repo, http, minutes(61))
    assert "staging answers differently on v1.1.0rc1" in found["production"].action
    http.answer(STAGING, "", status=500)
    assert "1 of 3 failed checks" in run(repo, http, minutes(70))["staging"].health
    assert repo.github.dispatched == []


def test_s084_7_a_deployment_that_answers_differently_is_no_rollback_target(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    rollback_autonomy(repo, "observe")
    http.answer(NEW_AT + ITEMS, HALF)
    run(repo, http, minutes(0))
    repo.github.deploy("staging", "v1.2.0rc1", minutes(5), S.IN_PROGRESS, S.SUCCESS)
    http.answer(STAGING, "", status=503)
    for at in (10, 20, 30):
        found = run(repo, http, minutes(at))
    rolls = [i.body for i in repo.github.issues.values() if "tag=v1.2.0rc1" in i.body]
    assert len(rolls) == 1 and "tag=v1.2.0rc1 to=v1.0.0rc1 state=failing -->" in rolls[0]
    assert "would roll back to v1.0.0rc1" in found["staging"].action


def test_s084_7_a_promotion_from_a_source_with_only_same_answers_goes_ahead(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    run(repo, http, minutes(0))
    assert compare_writes(repo) == [(S.SUCCESS, SAME)]
    run(repo, http, minutes(61))
    assert ("deploy.yml", "v1.1.0rc1", "v1.1.0rc1", {"environment": "production"}) in repo.github.dispatched


def test_s084_8_an_unexplained_difference_opens_the_incident_at_once_quoting_no_value(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    secret = {"owner": "alice-Distinctive-7731", "items": [{"id": i, "name": "Widget-Secret-9137"} for i in range(3)]}
    changed = {"owner": "bob-Distinctive-4410", "items": [{"id": 0, "name": "Widget-Secret-9137"}]}
    http.answer(OLD + ITEMS, json.dumps(secret))
    http.answer(NEW_AT + ITEMS, json.dumps(changed))
    http.answer(OLD + "/", json.dumps({f"a{i:02}": "old-value-5521" for i in range(12)}))
    http.answer(NEW_AT + "/", json.dumps({f"a{i:02}": "new-value-6632" for i in range(12)}))
    found = run(repo, http, minutes(0))  # its first check: no failed check counted at all
    issue = incident(repo)
    assert issue.title == "Incident: staging answers differently on v1.1.0rc1 than v1.0.0rc1"
    line = "<!-- shipmill:incident env=staging tag=v1.1.0rc1 to=v1.0.0rc1 state=rolled-back cause=compare -->"
    assert issue.body.startswith(line + "\n")
    assert (
        "- `items` (`/api/items`): HTTP 200 on v1.0.0rc1, HTTP 200 on v1.1.0rc1; differs at `/items`: 3 vs 1 items,"
        " `/owner`\n" in issue.body
    )
    home = [text for text in issue.body.splitlines() if text.startswith("- `home`")]
    assert home == [
        "- `home` (`/`): HTTP 200 on v1.0.0rc1, HTTP 200 on v1.1.0rc1; differs at "
        + ", ".join(f"`/a{i:02}`" for i in range(10))
        + ", and 2 more"
    ]
    for value in ("Distinctive", "Widget-Secret", "old-value", "new-value", "limit=100", OLD, NEW_AT):
        assert value not in issue.body
    assert f"opened incident #{issue.number}; rolled back" in found["staging"].action
    assert compare_writes(repo) == [(S.FAILURE, differ("items, home"))]


def test_s084_8_the_incident_names_both_statuses(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + ITEMS, "Not Found: item-store-secret", status=404)
    http.answers[NEW_AT + "/"] = Unreachable("connection refused")
    run(repo, http, minutes(0))
    body = incident(repo).body
    assert "- `items` (`/api/items`): HTTP 200 on v1.0.0rc1, HTTP 404 on v1.1.0rc1\n" in body
    assert "- `home` (`/`): HTTP 200 on v1.0.0rc1, no HTTP answer on v1.1.0rc1\n" in body
    assert "item-store-secret" not in body and "connection refused" not in body


def test_s084_8_an_incident_line_without_a_cause_is_a_health_incident() -> None:
    old = "<!-- shipmill:incident env=production tag=v1.1.0rc1 to=v1.0.0 state=rolled-back -->\nbody"
    found = Incident.read(Issue(5, "Incident: production fails its health checks on v1.1.0rc1", old))
    assert found is not None and found.cause is Cause.HEALTH and found.state is IncidentState.ROLLED_BACK
    assert found.moved(IncidentState.HEALTHY, found.to) == old.replace("rolled-back", "healthy")  # still no cause
    compare = Incident.read(Issue(6, "t", old.replace("rolled-back -->", "rolled-back cause=compare -->")))
    assert compare is not None and compare.cause is Cause.COMPARE and compare.to == Version(1, 0, 0)
    with pytest.raises(ReleaseError, match="incident #7 has an unknown cause 'drift'"):
        Incident.read(Issue(7, "t", old.replace("rolled-back -->", "rolled-back cause=drift -->")))


@pytest.mark.parametrize("level", ["act", "propose", "hold", "observe"])
def test_s084_9_the_compare_rollback_follows_the_rollback_autonomy(probed: Probed, level: str) -> None:
    repo, http = probed.repo, probed.http
    rollback_autonomy(repo, "act" if level == "hold" else level)
    if level == "hold":
        repo.github.holds = ["#7 Investigating"]
    http.answer(NEW_AT + ITEMS, HALF)
    run(repo, http, minutes(0))
    run(repo, http, minutes(10))
    body = incident(repo).body
    if level == "act":
        assert repo.github.dispatched == [ROLLBACK_STAGING]
        assert "state=rolled-back cause=compare" in body
        return
    assert repo.github.dispatched == []
    if level == "observe":
        assert "state=failing cause=compare" in body and "but rollback autonomy is observe." in body
        with pytest.raises(ReleaseError, match="no open incident proposes a rollback of staging"):
            approve_rollback(repo.policy, repo.github, "staging", dry_run=False)
        return
    assert "state=proposed cause=compare" in body
    assert "gh workflow run operate.yml -f approve-rollback=staging -f dry-run=false" in body
    repo.github.holds = []
    approve_rollback(repo.policy, repo.github, "staging", dry_run=False)
    assert repo.github.dispatched == [ROLLBACK_STAGING]
    with pytest.raises(ReleaseError, match="no open incident proposes a rollback of staging"):
        approve_rollback(repo.policy, repo.github, "staging", dry_run=False)


def test_s084_9_a_compare_failure_comments_on_the_tags_open_incident(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    healthy = "<!-- shipmill:incident env=staging tag=v1.1.0rc1 to=v1.0.0rc1 state=healthy -->\nChecks failed."
    number = repo.github.create_issue("Incident: staging fails its health checks on v1.1.0rc1", healthy, ("incident",))
    http.answer(NEW_AT + ITEMS, HALF)
    found = run(repo, http, minutes(0))
    assert list(repo.github.issues) == [number]
    [comment] = repo.github.comments[number]
    assert comment.startswith("staging answers differently on v1.1.0rc1 than v1.0.0rc1.\n\n- `items` (`/api/items`)")
    assert "state=rolled-back cause=compare -->" in incident(repo).body
    assert repo.github.dispatched == [ROLLBACK_STAGING]
    assert f"comment on incident #{number}: answers differently; rolled back" in found["staging"].action


def test_s084_10_a_compare_incident_stays_open_on_the_bad_tag_and_heals_on_another(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + ITEMS, HALF)
    run(repo, http, minutes(0))
    number = incident(repo).number
    for at in (10, 20):  # the bad tag still runs and passes its health check
        assert "healthy again" not in run(repo, http, minutes(at))["staging"].action
    assert number not in repo.github.comments and "state=rolled-back cause=compare" in incident(repo).body
    back = repo.github.deploy("staging", "v1.0.0rc1", minutes(25), S.IN_PROGRESS, S.SUCCESS)  # the rollback ran
    located(repo, back, OLD)
    http.answer(STAGING, '{"version": "1.0.0rc1"}')
    asked = len(probes_asked(http))
    found = run(repo, http, minutes(30))
    assert repo.github.comments[number] == ["staging is healthy again on v1.0.0rc1 (HTTP 200, version 1.0.0rc1)."]
    assert "state=healthy cause=compare" in incident(repo).body
    assert f"comment on incident #{number}: healthy again" in found["staging"].action
    assert len(probes_asked(http)) == asked  # the rollback is not compared with the release it replaced
    run(repo, http, minutes(40))
    assert len(repo.github.comments[number]) == 1


def test_a_dry_run_of_a_difference_writes_nothing(probed: Probed) -> None:
    repo, http = probed.repo, probed.http
    http.answer(NEW_AT + ITEMS, HALF)
    found = run(repo, http, minutes(0), dry_run=True)
    assert (
        "differs on items, would mark failure; would open an incident; would roll back: start deploy.yml with v1.0.0rc1"
        in found["staging"].action
    )
    assert repo.github.status_writes == [] and repo.github.issues == {} and repo.github.dispatched == []
