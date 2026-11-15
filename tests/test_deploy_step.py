"""Spec 063: the deploy-step zone, a changed deploy job no Proof: run ran at the head's content"""

import json
from pathlib import Path
from typing import Any

import pytest

from shipmill.config import CONFIG_PATH
from shipmill.github import FileChange, GhCli, RunAttempt, RunJob
from shipmill.workflows import jobs

from .conftest import POLICY, Repo
from .test_decide_cli import BASE, HEAD, FakePulls, commit, run, zones_of

CONFIG = CONFIG_PATH.as_posix()
DEPLOY = ".github/workflows/deploy.yml"
CI = ".github/workflows/ci.yml"
ENVIRONMENTS = '\n[environments.production]\nlane = "stable"\nworkflow = "deploy.yml"\n'
RUN_SHA = "r" * 40
BLOB = "f" * 40


def workflow(environment: bool = False, extra: str = "") -> str:
    """A deploy workflow: build on lines 8 to 11, deploy (named "Deploy app") from line 12"""
    lines = [
        "name: Deploy",  # 1
        "on:",  # 2
        "  workflow_dispatch:",  # 3
        "    inputs:",  # 4
        "      tag:",  # 5
        "        required: true",  # 6
        "jobs:",  # 7
        "  build:",  # 8
        "    runs-on: ubuntu-latest",  # 9
        "    steps:",  # 10
        "      - run: make",  # 11
        "  deploy:",  # 12
        "    name: Deploy app  # shown in the run",  # 13
        "    needs: build",  # 14
        "    runs-on: [self-hosted]",  # 15
        *(["    environment: production"] if environment else []),  # 16
        "    steps:",
        "      - run: ./deploy.sh",
    ]
    return "\n".join(lines) + "\n" + extra


def hunk(old: int, new: int, *lines: str) -> str:
    """One hunk of a unified diff, its lines given with their +, -, or space"""
    removed = sum(1 for line in lines if not line.startswith("+"))
    added = sum(1 for line in lines if not line.startswith("-"))
    return "\n".join([f"@@ -{old},{removed} +{new},{added} @@", *lines])


IN_BUILD = hunk(11, 11, "-      - run: make", "+      - run: make all")
IN_DEPLOY = hunk(14, 14, "     needs: build", "+    timeout-minutes: 9")
IN_ON = hunk(3, 3, "-  workflow_dispatch:", "+  workflow_call:")


def change(
    patch: str | None,
    base: str | None = None,
    head: str | None = None,
    status: str = "modified",
    body: str = "",
    previous: str | None = None,
) -> FakePulls:
    texts = {(HEAD, DEPLOY): workflow() if head is None else head}
    if status not in ("added", "copied"):
        texts[(BASE, previous or DEPLOY)] = workflow() if base is None else base
    return FakePulls((FileChange(DEPLOY, status, patch, previous),), texts, body=body)


def deploy_step(found: dict[str, Any]) -> dict[str, Any] | None:
    matched = [z for z in found["zones"] if z["zone"] == "deploy-step"]
    return matched[0] if matched else None


def reasons(found: dict[str, Any]) -> list[str]:
    zone = deploy_step(found)
    return [] if zone is None else str(zone["reason"]).split("; ")


def changed(repo: Repo, capsys: pytest.CaptureFixture[str], pulls: FakePulls) -> list[str]:
    """The job ids deploy-step names"""
    prefix = f"{DEPLOY}: job "
    found = run(repo, capsys, "classify", "--pr", "7", pulls=pulls)
    return [r[len(prefix) :].split()[0] for r in reasons(found) if r.startswith(prefix)]


# -- S-063-2, S-063-3: a deploy workflow ------------------------------------------------------


def test_s063_2_a_changed_job_of_an_environments_workflow_with_no_proof_is_deploy_step(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    found = run(repo, capsys, "classify", "--pr", "7", pulls=change(IN_BUILD))  # no environment: key at all
    assert zones_of(found) == {"security": "ask", "deploy-step": "ask"}
    assert [z["zone"] for z in found["zones"]] == ["security", "deploy-step"]  # after security
    assert reasons(found) == [f"{DEPLOY}: job build changed and no Proof: run ran it at this content"]
    assert deploy_step(found) == {
        "zone": "deploy-step",
        "level": "ask",
        "reason": f"{DEPLOY}: job build changed and no Proof: run ran it at this content",
        "paths": [{"path": DEPLOY, "level": "ask", "source": "default", "glob": None}],
    }


def test_s063_2_the_level_is_the_bases_never_the_changes(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + ENVIRONMENTS + '\n[decisions]\ndeploy-step = "notify"\n')
    repo.write(CONFIG, POLICY + ENVIRONMENTS + '\n[decisions]\ndeploy-step = "act"\n')  # the change's own
    found = run(repo, capsys, "classify", "--pr", "7", pulls=change(IN_BUILD))
    assert zones_of(found)["deploy-step"] == "notify"


def test_s063_3_an_environment_key_at_the_base_or_the_head_makes_a_deploy_workflow(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)  # no [environments]
    at_head = change(IN_BUILD, base=workflow(), head=workflow(environment=True))
    assert changed(repo, capsys, at_head) == ["build"]
    removed = hunk(15, 15, "     runs-on: [self-hosted]", "-    environment: production")
    at_base = change(removed, base=workflow(environment=True), head=workflow())
    assert changed(repo, capsys, at_base) == ["deploy"]
    neither = run(repo, capsys, "classify", "--pr", "7", pulls=change(IN_BUILD))
    assert zones_of(neither) == {"security": "ask"}  # a workflow with neither gets no deploy-step


def test_s063_3_a_workflow_with_neither_beside_a_deploy_workflow_names_only_the_deploy_one(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    ci = "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
    pulls = FakePulls(
        (FileChange(DEPLOY, "modified", IN_BUILD), FileChange(CI, "modified", hunk(4, 4, "+    timeout-minutes: 5"))),
        {(BASE, DEPLOY): workflow(True), (HEAD, DEPLOY): workflow(True), (BASE, CI): ci, (HEAD, CI): ci},
    )
    found = run(repo, capsys, "classify", "--pr", "7", pulls=pulls)
    assert reasons(found) == [f"{DEPLOY}: job build changed and no Proof: run ran it at this content"]


# -- S-063-4: the changed jobs follow the patch -----------------------------------------------


def test_s063_4_a_change_inside_one_job_names_that_job_alone(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    assert changed(repo, capsys, change(IN_BUILD)) == ["build"]
    head = workflow().replace("    needs: build\n", "    needs: build\n    timeout-minutes: 9\n")
    assert changed(repo, capsys, change(IN_DEPLOY, head=head)) == ["deploy"]


def test_s063_4_a_removed_line_is_placed_by_the_bases_numbers(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    """The base has two more lines in build, so its deploy block starts at line 14, the head's at 12"""
    commit(repo, POLICY + ENVIRONMENTS)
    base = workflow().replace("      - run: make\n", "      - run: make\n      - run: lint\n      - run: test\n")
    head = workflow().replace("    needs: build\n", "")
    patch = "\n".join([hunk(12, 12, "-      - run: lint", "-      - run: test"), hunk(16, 14, "-    needs: build")])
    assert changed(repo, capsys, change(patch, base=base, head=head)) == ["build", "deploy"]
    only_deploy = hunk(15, 15, "     name: Deploy app  # shown in the run", "-    needs: build")
    base_deploy = workflow().replace("      - run: make\n", "      - run: make\n      - run: lint\n      - run: test\n")
    head_deploy = base_deploy.replace("    needs: build\n", "")
    assert changed(repo, capsys, change(only_deploy, base=base_deploy, head=head_deploy)) == ["deploy"]


def test_s063_4_a_change_outside_every_job_names_every_job(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    head = workflow().replace("  workflow_dispatch:", "  workflow_call:")
    assert changed(repo, capsys, change(IN_ON, head=head)) == ["build", "deploy"]
    env = hunk(1, 1, " name: Deploy", "+env:", "+  A: 1")
    with_env = workflow().replace("name: Deploy\n", "name: Deploy\nenv:\n  A: 1\n")
    assert changed(repo, capsys, change(env, head=with_env)) == ["build", "deploy"]
    after = hunk(17, 17, "       - run: ./deploy.sh", "+concurrency: deploy")  # a top-level key after jobs:
    assert changed(repo, capsys, change(after, head=workflow() + "concurrency: deploy\n")) == ["build", "deploy"]


def test_s063_4_an_added_renamed_or_unpatched_file_names_every_job(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    assert changed(repo, capsys, change(IN_BUILD, status="added")) == ["build", "deploy"]
    renamed = change("", status="renamed", previous=".github/workflows/old.yml")
    assert changed(repo, capsys, renamed) == ["build", "deploy"]
    assert changed(repo, capsys, change(None)) == ["build", "deploy"]  # GitHub gives no patch


def test_s063_4_a_removed_file_or_a_removed_job_names_none(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    removed = FakePulls((FileChange(DEPLOY, "removed", "@@ -1,2 +0,0 @@\n-name: Deploy\n-on:"),))
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=removed)) == {"security": "ask"}
    notify = "  notify:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ./notify.sh\n"
    patch = hunk(17, 17, "       - run: ./deploy.sh", *(f"-{line}" for line in notify.splitlines()))
    gone = change(patch, base=workflow(extra=notify), head=workflow())
    assert changed(repo, capsys, gone) == []
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=gone)) == {"security": "ask"}


# -- S-063-5, S-063-6: a Proof: run covers a job ----------------------------------------------


def proved(
    patch: str,
    body: str,
    path: str = DEPLOY,
    sha: str = RUN_SHA,
    listed: tuple[RunJob, ...] = (),
    attempt: int | None = None,
) -> FakePulls:
    pulls = change(patch, body=body)
    pulls.attempts[(55, attempt)] = RunAttempt(55, attempt or 2, path, sha)
    pulls.jobs[(55, attempt or 2)] = listed
    pulls.blobs[(HEAD, DEPLOY)] = BLOB
    pulls.blobs[(RUN_SHA, DEPLOY)] = BLOB
    pulls.blobs[("o" * 40, DEPLOY)] = "e" * 40  # another content of the file
    return pulls


RUN = "https://github.com/o/demo/actions/runs/55"
PLAN = f"## Plan\n\n- Serves: G-1\n- Files: {DEPLOY}\n- Order: one\n- Proof: the deploy ran off production, {RUN}\n"
OK = "completed", "success"


def test_s063_5_a_run_of_the_same_file_and_content_with_every_leg_green_covers_the_jobs(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    head = workflow().replace("  workflow_dispatch:", "  workflow_call:")
    legs = (RunJob("build", *OK), RunJob("Deploy app (eu)", *OK), RunJob("Deploy app (us)", *OK))
    pulls = proved(IN_ON, PLAN, listed=legs)
    pulls.texts[(HEAD, DEPLOY)] = head
    found = run(repo, capsys, "classify", "--pr", "7", pulls=pulls)
    assert zones_of(found) == {"security": "ask"}  # no deploy-step reason names either job
    assert pulls.run_reads == [
        ("run", (55, None)),
        ("blob", (RUN_SHA, DEPLOY)),
        ("blob", (HEAD, DEPLOY)),
        ("jobs", (55, 2)),
    ]
    reusable = proved(IN_DEPLOY, PLAN, listed=(RunJob("Deploy app / push", *OK), RunJob("Deploy app / tag", *OK)))
    reusable.texts[(HEAD, DEPLOY)] = workflow().replace(
        "    needs: build\n", "    needs: build\n    timeout-minutes: 9\n"
    )
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=reusable)) == {"security": "ask"}


def test_s063_5_an_attempt_url_reads_that_attempt_and_a_job_url_the_latest(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    attempt = proved(IN_BUILD, f"Proof: {RUN}/attempts/1", listed=(RunJob("build", *OK),), attempt=1)
    assert deploy_step(run(repo, capsys, "classify", "--pr", "7", pulls=attempt)) is None
    assert ("jobs", (55, 1)) in attempt.run_reads
    job = proved(IN_BUILD, f"* Proof: {RUN}/job/9876.", listed=(RunJob("build", *OK),))
    assert deploy_step(run(repo, capsys, "classify", "--pr", "7", pulls=job)) is None
    assert job.run_reads[0] == ("run", (55, None))


def test_s063_5_every_request_classify_makes_is_a_get(
    tmp_path: Path, repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through GhCli against a gh that answers from a script and records each call"""
    commit(repo, POLICY + ENVIRONMENTS)
    body = f"- Proof: {RUN}"
    pull = {
        "head": {"sha": HEAD},
        "base": {"sha": "t" * 40, "repo": {"full_name": "o/demo"}},
        "labels": [],
        "body": body,
    }
    files = json.dumps({"filename": DEPLOY, "status": "modified", "patch": IN_BUILD})
    record = {"path": DEPLOY, "head_sha": RUN_SHA, "run_attempt": 2}
    build = {"name": "build", "status": "completed", "conclusion": "success"}
    (tmp_path / "workflow").write_text(workflow(), encoding="utf-8")
    script = tmp_path / "gh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{tmp_path / "args"}"\n'
        'case "$*" in\n'
        f"  *compare/*) echo {BASE} ;;\n"
        f"  *pulls/7/files*) printf '%s\\n' '{files}' ;;\n"
        f"  *pulls/7) echo '{json.dumps(pull)}' ;;\n"
        f"  *attempts/2/jobs*) echo '{json.dumps(build)}' ;;\n"
        f"  *actions/runs/55) echo '{json.dumps(record)}' ;;\n"
        f"  *contents/*--jq*) echo {BLOB} ;;\n"
        f'  *contents/*) cat "{tmp_path / "workflow"}" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    found = run(repo, capsys, "classify", "--pr", "7", pulls=GhCli(repo.root, gh=str(script)))
    assert zones_of(found) == {"security": "ask"}  # the run covers build
    calls = (tmp_path / "args").read_text(encoding="utf-8").splitlines()
    assert any("actions/runs/55/attempts/2/jobs" in c for c in calls)
    for call in calls:
        args = call.split()
        assert args[0] == "api", call
        assert not {"-f", "-F", "--field", "--raw-field", "--input"} & set(args), call  # no body: no POST
        if "-X" in args:
            assert args[args.index("-X") + 1] == "GET", call


@pytest.mark.parametrize(
    ("listed", "why"),
    [
        ((), "run 55 has no successful job build"),
        ((RunJob("build", "completed", "skipped"),), "run 55 has no successful job build"),
        ((RunJob("build", "completed", "failure"),), "run 55 has no successful job build"),
        ((RunJob("build", "in_progress", None),), "run 55 has no successful job build"),
        ((RunJob("build (a)", *OK), RunJob("build (b)", "completed", "failure")), "run 55 has no successful job build"),
        ((RunJob("builder", *OK),), "run 55 has no successful job build"),
    ],
)
def test_s063_6_a_run_whose_job_didnt_succeed_doesnt_cover_it(
    repo: Repo, capsys: pytest.CaptureFixture[str], listed: tuple[RunJob, ...], why: str
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    found = run(repo, capsys, "classify", "--pr", "7", pulls=proved(IN_BUILD, PLAN, listed=listed))
    assert reasons(found) == [f"{DEPLOY}: job build changed and no Proof: run ran it at this content", why]


def test_s063_6_a_run_of_another_path_content_or_repo_doesnt_count_and_says_why(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    job = f"{DEPLOY}: job build changed and no Proof: run ran it at this content"
    green = (RunJob("build", *OK),)
    other_path = proved(IN_BUILD, PLAN, path=CI, listed=green)
    assert reasons(run(repo, capsys, "classify", "--pr", "7", pulls=other_path)) == [job, f"run 55 ran {CI}"]
    other_content = proved(IN_BUILD, PLAN, sha="o" * 40, listed=green)
    found = run(repo, capsys, "classify", "--pr", "7", pulls=other_content)
    assert reasons(found) == [job, f"run 55 ran another content of {DEPLOY}"]
    elsewhere = proved(IN_BUILD, "Proof: https://github.com/x/other/actions/runs/55", listed=green)
    assert reasons(run(repo, capsys, "classify", "--pr", "7", pulls=elsewhere)) == [job, "run 55 is not in o/demo"]
    assert elsewhere.run_reads == []  # another repo's run is never read


def test_s063_6_a_run_url_outside_a_proof_line_or_in_a_fence_isnt_read(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + ENVIRONMENTS)
    job = f"{DEPLOY}: job build changed and no Proof: run ran it at this content"
    for body in (f"It ran: {RUN}\n", f"```\n- Proof: {RUN}\n```\n", f"~~~~\nProof: {RUN}\n~~~~\n"):
        pulls = proved(IN_BUILD, body, listed=(RunJob("build", *OK),))
        assert reasons(run(repo, capsys, "classify", "--pr", "7", pulls=pulls)) == [job], body
        assert pulls.run_reads == []


def test_s063_6_a_job_another_named_run_covers_is_not_named(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    """build runs in 55, deploy in neither: only deploy is named, and only 55's missing deploy"""
    commit(repo, POLICY + ENVIRONMENTS)
    head = workflow().replace("  workflow_dispatch:", "  workflow_call:")
    pulls = proved(IN_ON, PLAN, listed=(RunJob("build", *OK), RunJob("Deploy app", "completed", "skipped")))
    pulls.texts[(HEAD, DEPLOY)] = head
    assert reasons(run(repo, capsys, "classify", "--pr", "7", pulls=pulls)) == [
        f"{DEPLOY}: job deploy changed and no Proof: run ran it at this content",
        "run 55 has no successful job Deploy app",
    ]


# -- S-063-7: paths alone ---------------------------------------------------------------------


def test_s063_7_files_names_a_deploy_workflow_at_the_ref(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, **{DEPLOY: workflow(environment=True), CI: "on: push\njobs:\n  test:\n    runs-on: x\n"})
    found = run(repo, capsys, "classify", "--files", DEPLOY)
    assert zones_of(found) == {"security": "ask", "deploy-step": "ask"}
    assert reasons(found) == [f"{DEPLOY} is a deploy workflow, and paths alone show no run"]
    assert deploy_step(run(repo, capsys, "classify", "--files", CI)) is None
    repo.write(CI, workflow(environment=True))  # the working tree's isn't the ref's
    assert deploy_step(run(repo, capsys, "classify", "--files", CI)) is None
    repo.write(CI, "on: push\njobs:\n  test:\n    runs-on: x\n")
    commit(repo, POLICY + ENVIRONMENTS.replace("deploy.yml", "ci.yml"))  # named, with no environment: key
    assert reasons(run(repo, capsys, "classify", "--files", "./" + CI)) == [
        f"{CI} is a deploy workflow, and paths alone show no run"
    ]


# -- S-063-11: what the agents read -----------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]


def test_s063_11_the_zone_tables_and_the_proof_rule_name_deploy_step() -> None:
    needs = (ROOT / "skills/github-issue-triage/references/needs-decision.md").read_text(encoding="utf-8")
    assert "| `deploy-step` | a change to a deploy workflow's job" in needs
    spec = (ROOT / "docs/specs/030-decision-policy.md").read_text(encoding="utf-8")
    assert "| `deploy-step` |" in spec and "(063-deploy-step-first-run.md)) | `ask` | none |" in spec
    resolve = " ".join((ROOT / "skills/github-issue-resolve/SKILL.md").read_text(encoding="utf-8").split())
    assert (
        "A change to a deploy workflow's job (a workflow an `[environments]` table names, or one with an"
        " `environment:` key) names on its `Proof:` line the URL of a run of each changed job off production"
    ) in resolve
    assert (
        "when the repo has no way to run it off production, the `Proof:` line says so and the maintainer is asked"
        in (resolve)
    )


# -- the jobs of a workflow's text ------------------------------------------------------------


def test_s063_4_jobs_are_read_from_the_text_with_their_display_names() -> None:
    text = (
        workflow(environment=True)
        + "  quoted:\n    name: 'Quoted'\n  dynamic:\n    name: Deploy ${{ inputs.env }}\nconcurrency: x\n"
    )
    found = jobs(text)
    assert [(j.id, j.name, j.environment, j.start) for j in found] == [
        ("build", "build", False, 8),
        ("deploy", "Deploy app", True, 12),
        ("quoted", "quoted", False, 19),  # not a plain scalar: its id
        ("dynamic", "dynamic", False, 21),
    ]
    assert found[-1].end == 23  # concurrency: is outside every job
    assert jobs("on: push\n") == ()
