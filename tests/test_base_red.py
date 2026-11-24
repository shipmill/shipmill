"""github-pr-triage's base_red.py reads a red default branch and the merges that may have turned
it red (spec 079), end to end with a stand-in gh on PATH answering as GitHub recorded"""

import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-pr-triage" / "scripts" / "base_red.py"
BOT = "shipmill-demo[bot]"
REPO = "demo/app"
API = "repos/{owner}/{repo}"
WORKFLOW = 77  # the CI workflow's id
ACTIONS = 15368  # GitHub Actions' app id
OTHER_APP = 4242
SHAS = [f"{i:x}" * 40 for i in range(1, 15)]  # SHAS[0] is the head, each the next one's child
HEAD = SHAS[0]


def run_url(run: int) -> str:
    return f"https://github.com/demo/app/actions/runs/{run}"


FAKE_GH = """#!{python}
import json, os, sys
fake = json.loads(open(os.environ["FAKE_GH_DATA"]).read())
args = sys.argv[1:]
with open(os.environ["FAKE_GH_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
endpoint = [a for a in args[1:] if a.startswith("repos/") or a == "graphql"][0]
answer = fake.get(endpoint)
if answer is None:
    sys.exit("gh: Not Found (HTTP 404)")
if "fail" in answer:
    sys.exit(answer["fail"])
if "lines" in answer:
    for item in answer["lines"]:  # every page, one object a line, as gh --paginate --jq prints them
        print(json.dumps(item))
else:
    print(json.dumps(answer["json"]))
"""


def job(
    conclusion: str | None,
    status: str = "completed",
    name: str = "test",
    run: int = 900,
    job_id: int = 901,
    started: str | None = "2026-11-19T08:00:00Z",
    app: int = ACTIONS,
) -> dict[str, Any]:
    """A check run as the check-runs API lists it: an Actions job's, or, with another app,
    a check run whose URL names no Actions run"""
    url = f"{run_url(run)}/job/{job_id}" if app == ACTIONS else f"https://ci.example.com/runs/{job_id}"
    return {
        "id": job_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started,
        "html_url": url,
        "details_url": url,
        "check_suite": {"id": run + 7},
        "app": {"id": app},
    }


def workflow_run(run: int, conclusion: str | None = "failure", status: str = "completed") -> dict[str, Any]:
    return {
        "id": run,
        "workflow_id": WORKFLOW,
        "check_suite_id": run + 7,
        "status": status,
        "conclusion": conclusion,
        "html_url": run_url(run),
    }


@dataclass
class GitHubAnswers:
    """What GitHub answers each `gh api` endpoint base_red.py reads; None of a key: a 404"""

    answers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def json(self, endpoint: str, data: Any) -> None:
        self.answers[endpoint] = {"json": data}

    def lines(self, endpoint: str, items: list[dict[str, Any]]) -> None:
        self.answers[endpoint] = {"lines": items}

    def head(self, runs: list[dict[str, Any]], statuses: list[dict[str, Any]] | None = None) -> None:
        """main's head: its commit statuses and its check runs, every attempt"""
        found = statuses or []
        self.json(
            f"{API}/commits/main/status?per_page=100", {"sha": HEAD, "total_count": len(found), "statuses": found}
        )
        self.lines(f"{API}/commits/{HEAD}/check-runs?per_page=100&filter=all", runs)

    def attempt(self, run: int, attempt: int) -> None:
        self.json(f"{API}/actions/runs/{run}", {**workflow_run(run), "run_attempt": attempt})

    def history(self, count: int, per_page: int = 30) -> None:
        """The first-parent history from the head, SHAS[0] to SHAS[count - 1], the last a root"""
        commits = [
            {
                "sha": SHAS[i],
                "parents": [{"sha": SHAS[i + 1]}] if i + 1 < count else [],
                "commit": {"committer": {"date": f"2026-11-{19 - i:02d}T07:00:00Z"}},
            }
            for i in range(count)
        ]
        self.json(f"{API}/commits?sha={HEAD}&per_page={per_page}", commits)

    def commit_runs(
        self, index: int, runs: list[dict[str, Any]], workflow_runs: list[dict[str, Any]] | None = None
    ) -> None:
        """The check's runs named test on SHAS[index], and the workflow's runs there"""
        sha = SHAS[index]
        self.lines(f"{API}/commits/{sha}/check-runs?check_name=test&filter=all&per_page=100", runs)
        wruns = workflow_runs if workflow_runs is not None else [workflow_run(r["check_suite"]["id"] - 7) for r in runs]
        self.lines(f"{API}/actions/runs?head_sha={sha}&per_page=100", wruns)

    def pull(self, index: int, number: int | None, merged_by: str | None = BOT) -> None:
        """The pull request SHAS[index] is the merge commit of (None: a direct push)"""
        sha = SHAS[index]
        merged = [{"number": number, "merged_at": "2026-11-18T10:00:00Z", "merge_commit_sha": sha}] if number else []
        self.json(f"{API}/commits/{sha}/pulls", merged)
        if number:
            self.json(f"{API}/pulls/{number}", {"number": number, "merged_by": {"login": merged_by}})

    def tags(self, *tags: tuple[str, str, str]) -> None:
        """The newest tags, (name, sha, commit date), as the GraphQL refs query answers"""
        nodes = [
            {"name": name, "target": {"__typename": "Commit", "oid": sha, "committedDate": date}}
            for name, sha, date in tags
        ]
        self.json("graphql", {"data": {"repository": {"refs": {"nodes": nodes}}}})

    def issues(self, *items: dict[str, Any]) -> None:
        self.lines(f"{API}/issues?state=open&per_page=100", list(items))

    def config(self, text: str | None) -> None:
        """The head's .github folder, and its shipmill.toml holding text (None: no config there)"""
        listed = [{"name": "workflows", "type": "dir"}]
        if text is not None:
            listed.append({"name": "shipmill.toml", "type": "file"})
            content = base64.b64encode(text.encode()).decode()
            self.json(f"{API}/contents/.github/shipmill.toml?ref={HEAD}", {"encoding": "base64", "content": content})
        self.json(f"{API}/contents/.github?ref={HEAD}", listed)


def base_red(tmp_path: Path, github: GitHubAnswers, *args: str) -> subprocess.CompletedProcess[str]:
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    data = tmp_path / "gh.json"
    answers = {f"{API}/issues?state=open&per_page=100": {"lines": []}, **github.answers}  # none open unless given
    data.write_text(json.dumps(answers), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(data),
        "FAKE_GH_CALLS": str(tmp_path / "gh-calls"),
    }
    cmd = [sys.executable, str(SCRIPT), REPO, "--branch", "main", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, cwd=tmp_path)


def endpoints(tmp_path: Path) -> list[str]:
    calls = (tmp_path / "gh-calls").read_text().splitlines()
    return [[a for a in json.loads(c)[1:] if a.startswith("repos/") or a == "graphql"][0] for c in calls]


def at(index: int) -> str:
    return SHAS[index][:7]


GREEN_LINE = f"GREEN main@{at(0)}\n"


# -- S-079-2: GREEN and RERUN_DUE ------------------------------------------------------------


def test_s079_2_a_head_with_no_completed_failure_reads_green(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head(
        [
            job("success"),
            job(None, "in_progress", name="lint", job_id=902),
            job(None, "queued", name="docs", job_id=903, started=None),
            job("cancelled", name="build", job_id=904),
            job("skipped", name="deploy", job_id=905),
            job("neutral", name="report", job_id=906),
            job("stale", name="old", job_id=907),
        ],
        [{"context": "ci/ext", "state": "pending", "target_url": "https://ci.example.com/1"}],
    )
    proc = base_red(tmp_path, github)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, GREEN_LINE, "")
    assert endpoints(tmp_path) == [
        f"{API}/commits/main/status?per_page=100",
        f"{API}/commits/{HEAD}/check-runs?per_page=100&filter=all",
    ]


def test_s079_2_a_newer_green_run_of_a_failed_check_reads_green(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head([job("failure"), job("success", job_id=911, started="2026-11-19T09:00:00Z")])
    proc = base_red(tmp_path, github)
    assert (proc.returncode, proc.stdout) == (0, GREEN_LINE), proc.stderr


def test_s079_2_a_failed_job_on_its_first_attempt_reads_rerun_due(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head(
        [job("failure"), job("failure", name="lint", run=910, job_id=912), job("success", name="ok", job_id=913)]
    )
    github.attempt(900, 1)
    github.attempt(910, 2)
    proc = base_red(tmp_path, github)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"RERUN_DUE main@{at(0)}\nrerun: {run_url(900)}\n"
    assert not any("/commits?sha=" in e for e in endpoints(tmp_path))  # no merge is blamed before the rerun


def test_1310_a_check_rerunning_a_failure_is_never_green(tmp_path: Path) -> None:
    """As pr_gate.py reads it (#1310): the merge gate says `base: pending`, so this never says GREEN"""
    github = GitHubAnswers()
    github.head([job("failure"), job(None, "in_progress", job_id=911, started="2026-11-19T09:00:00Z")])
    proc = base_red(tmp_path, github)
    assert (proc.returncode, proc.stdout) == (0, f"PENDING main@{at(0)}\npending: {run_url(900)}\n"), proc.stderr


# -- #1485: a lane's release workflow dispatched on the branch runs for a tag, not the head ----

RELEASE_CONFIG = '[lanes.stable]\ndispatch = ["publish.yml"]\nafter_publish = ["move-major-tag.yml"]\n'
CONFIG_READS = [f"{API}/contents/.github?ref={HEAD}", f"{API}/contents/.github/shipmill.toml?ref={HEAD}"]


def dispatched(github: GitHubAnswers, run: int, event: str, workflow: str) -> None:
    """The workflow run a failed job of the head belongs to, on its first attempt"""
    path = f".github/workflows/{workflow}"
    github.json(f"{API}/actions/runs/{run}", {**workflow_run(run), "run_attempt": 1, "event": event, "path": path})


@pytest.mark.parametrize("workflow", ["publish.yml", "move-major-tag.yml"])
def test_1485_a_failed_dispatched_release_run_on_the_head_reads_green(tmp_path: Path, workflow: str) -> None:
    github = GitHubAnswers()
    github.head([job("failure", name="publish")])
    dispatched(github, 900, "workflow_dispatch", workflow)
    github.config(RELEASE_CONFIG)
    proc = base_red(tmp_path, github)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, GREEN_LINE, "")


@pytest.mark.parametrize(
    ("event", "workflow", "reads"),
    [
        pytest.param("push", "publish.yml", [], id="a release workflow on push"),
        pytest.param("pull_request", "publish.yml", [], id="a release workflow on a pull request"),
        pytest.param("workflow_dispatch", "nightly.yml", CONFIG_READS, id="a dispatched workflow no lane names"),
    ],
)
def test_1485_any_other_failed_run_on_the_head_stays_red(
    tmp_path: Path, event: str, workflow: str, reads: list[str]
) -> None:
    github = GitHubAnswers()
    github.head([job("failure")])
    dispatched(github, 900, event, workflow)
    github.config(RELEASE_CONFIG)
    proc = base_red(tmp_path, github)
    assert (proc.returncode, proc.stdout) == (0, f"RERUN_DUE main@{at(0)}\nrerun: {run_url(900)}\n"), proc.stderr
    assert [e for e in endpoints(tmp_path) if "/contents/" in e] == reads  # the config only for a dispatched run


def test_1485_a_release_run_failing_beside_a_ci_job_leaves_the_ci_job_red(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head([job("failure"), job("failure", name="publish", run=910, job_id=911)])
    dispatched(github, 900, "push", "ci.yml")
    dispatched(github, 910, "workflow_dispatch", "publish.yml")
    github.config(RELEASE_CONFIG)
    proc = base_red(tmp_path, github, "--json")
    assert proc.returncode == 0, proc.stderr
    reading = json.loads(proc.stdout)
    assert (reading["state"], reading["failed"]) == ("RERUN_DUE", [{"check": "test", "url": run_url(900)}])


def test_1485_a_head_without_the_config_reads_a_dispatched_run_red(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head([job("failure", name="publish")])
    dispatched(github, 900, "workflow_dispatch", "publish.yml")
    github.config(None)
    proc = base_red(tmp_path, github)
    assert (proc.returncode, proc.stdout) == (0, f"RERUN_DUE main@{at(0)}\nrerun: {run_url(900)}\n"), proc.stderr


# -- S-079-3: CULPRIT, CANDIDATES, and NO_GREEN -----------------------------------------------


def red_head(github: GitHubAnswers, count: int, per_page: int = 30) -> None:
    """main's head failed test on its second attempt; its history is count commits long"""
    github.head(
        [job("failure", started="2026-11-19T08:00:00Z"), job("failure", job_id=911, started="2026-11-19T09:00:00Z")]
    )
    github.attempt(900, 2)
    github.history(count, per_page)
    github.tags()


def test_s079_3_b_directly_after_a_is_the_one_culprit(tmp_path: Path) -> None:
    github = GitHubAnswers()
    red_head(github, 5)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])  # B
    github.commit_runs(2, [job("success", run=700, job_id=701)])  # A
    github.pull(1, 12)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"CULPRIT main@{at(0)}\ncandidate: {at(1)} #12; revertable\n"
    assert not any(SHAS[3] in e for e in endpoints(tmp_path))  # the walk stops at the last green


def test_s079_3_the_unjudged_commits_between_a_and_b_are_candidates_oldest_first(tmp_path: Path) -> None:
    github = GitHubAnswers()
    red_head(github, 6)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])  # B, the first red
    github.commit_runs(2, [], [])  # no run of the check
    github.commit_runs(3, [job(None, "in_progress", run=600, job_id=601)])  # never completed
    github.commit_runs(4, [job("success", run=500, job_id=501)])  # A
    for index, number in ((1, 12), (2, 11), (3, 10)):
        github.pull(index, number)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        f"CANDIDATES main@{at(0)}",
        f"candidate: {at(3)} #10; revertable; unjudged",
        f"candidate: {at(2)} #11; revertable; unjudged",
        f"candidate: {at(1)} #12; revertable",
    ]


def test_s079_3_a_red_after_b_is_not_a_candidate(tmp_path: Path) -> None:
    """The head and a red between it and B are after the first red: not candidates"""
    github = GitHubAnswers()
    red_head(github, 6)
    github.commit_runs(1, [job("failure", run=850, job_id=851)])  # red, after B
    github.commit_runs(2, [], [])  # unjudged, after B
    github.commit_runs(3, [job("failure", run=800, job_id=801)])  # B
    github.commit_runs(4, [job("success", run=500, job_id=501)])  # A
    github.pull(3, 12)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.stdout == f"CULPRIT main@{at(0)}\ncandidate: {at(3)} #12; revertable\n", proc.stderr


def test_s079_3_a_check_green_on_none_of_the_limit_commits_reads_no_green(tmp_path: Path) -> None:
    github = GitHubAnswers()
    red_head(github, 6, per_page=3)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])
    github.commit_runs(2, [job("failure", run=700, job_id=701)])
    github.commit_runs(3, [job("success", run=600, job_id=601)])  # past --limit 3: never read
    proc = base_red(tmp_path, github, "--limit", "3")
    assert (proc.returncode, proc.stdout) == (0, f"NO_GREEN main@{at(0)}\n"), proc.stderr
    assert not any(SHAS[3] in e for e in endpoints(tmp_path))


def test_s079_3_a_commit_status_is_walked_by_its_context(tmp_path: Path) -> None:
    """A commit status can't be re-run, so it is walked as it fails"""
    github = GitHubAnswers()
    failing = {"context": "ci/ext", "state": "failure", "target_url": "https://ci.example.com/9"}
    github.head([], [failing])
    github.history(4)
    github.tags()
    for index, state in ((1, "error"), (2, "success")):
        status = {**failing, "state": state}
        github.json(f"{API}/commits/{SHAS[index]}/status?per_page=100", {"total_count": 1, "statuses": [status]})
    github.pull(1, 12)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.stdout == f"CULPRIT main@{at(0)}\ncandidate: {at(1)} #12; revertable\n", proc.stderr


def test_s079_3_another_workflows_job_of_the_same_name_is_not_the_check(tmp_path: Path) -> None:
    """Its green says nothing of the check: the commit is unjudged, and the head, the first red,
    is a candidate too"""
    github = GitHubAnswers()
    red_head(github, 4)
    other = {**workflow_run(800, "success"), "workflow_id": WORKFLOW + 1}
    github.commit_runs(1, [job("success", run=800, job_id=801)], [other])  # another workflow's test
    github.commit_runs(2, [job("success", run=700, job_id=701)])
    github.pull(0, 13)
    github.pull(1, 12)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.stdout.splitlines() == [
        f"CANDIDATES main@{at(0)}",
        f"candidate: {at(1)} #12; revertable; unjudged",
        f"candidate: {at(0)} #13; revertable",
    ], proc.stderr


# -- S-079-4: whether a candidate is revertable ------------------------------------------------


def test_s079_4_each_candidate_names_its_pull_request_and_why_it_is_not_revertable(tmp_path: Path) -> None:
    github = GitHubAnswers()
    red_head(github, 6)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])  # merged by a person
    github.commit_runs(2, [], [])  # a direct push, no run
    github.commit_runs(3, [job("cancelled", run=600, job_id=601)], [workflow_run(600, "cancelled")])  # the gate's
    github.commit_runs(4, [job("success", run=500, job_id=501)])
    github.pull(1, 12, merged_by="amy")
    github.pull(2, None)
    github.pull(3, 10)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        f"CANDIDATES main@{at(0)}",
        f"candidate: {at(3)} #10; revertable; unjudged, rerun: {run_url(600)}",
        f"candidate: {at(2)} no pull request; not revertable: no pull request; unjudged",
        f"candidate: {at(1)} #12; not revertable: merged by a person",
    ]


def test_s079_4_without_a_bot_login_no_merge_is_the_gates(tmp_path: Path) -> None:
    github = GitHubAnswers()
    red_head(github, 4)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])
    github.commit_runs(2, [job("success", run=700, job_id=701)])
    github.pull(1, 12)
    proc = base_red(tmp_path, github)
    assert proc.stdout.splitlines()[1] == f"candidate: {at(1)} #12; not revertable: merged by a person", proc.stderr


@pytest.mark.parametrize("on_path", [True, False])
def test_s079_4_a_tagged_commit_is_released_in_its_tag(tmp_path: Path, on_path: bool) -> None:
    """A tag on the walked history at or after it holds it; another tag no older than it holds
    it when GitHub's compare finds the tag ahead of it"""
    github = GitHubAnswers()
    red_head(github, 4)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])
    github.commit_runs(2, [job("success", run=700, job_id=701)])
    github.pull(1, 12)
    release = "f" * 40
    old = ("v1.0.0", SHAS[2], "2026-11-17T07:00:00Z")  # older than the candidate: holds nothing
    github.tags(("v1.2.0", HEAD if on_path else release, "2026-11-19T07:00:00Z"), old)
    github.json(f"{API}/compare/{SHAS[1]}...{release}", {"status": "ahead"})
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.stdout.splitlines()[1] == f"candidate: {at(1)} #12; not revertable: released in v1.2.0", proc.stderr
    assert (f"{API}/compare/{SHAS[1]}...{release}" in endpoints(tmp_path)) is not on_path


def test_s079_4_a_tag_the_compare_finds_behind_holds_nothing(tmp_path: Path) -> None:
    github = GitHubAnswers()
    red_head(github, 4)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])
    github.commit_runs(2, [job("success", run=700, job_id=701)])
    github.pull(1, 12)
    hotfix = "e" * 40
    github.tags(("v1.1.1", hotfix, "2026-11-19T07:00:00Z"))
    github.json(f"{API}/compare/{SHAS[1]}...{hotfix}", {"status": "diverged"})
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.stdout.splitlines()[1] == f"candidate: {at(1)} #12; revertable", proc.stderr


# -- S-079-5: repair, asked, --json, and exit 2 --------------------------------------------------


def pull_request(number: int, body: str) -> dict[str, Any]:
    return {"number": number, "body": body, "user": {"login": BOT}, "pull_request": {"url": "x"}}


def issue(number: int, body: str, login: str = BOT) -> dict[str, Any]:
    return {"number": number, "body": body, "user": {"login": login}}


MARKER = "<!-- shipmill:base-red main -->"


def culprit(github: GitHubAnswers) -> None:
    red_head(github, 4)
    github.commit_runs(1, [job("failure", run=800, job_id=801)])
    github.commit_runs(2, [job("success", run=700, job_id=701)])
    github.pull(1, 12)
    github.issues(
        pull_request(40, f"Reverts #12\nRepairs: {run_url(900)}\n"),
        pull_request(42, f"Repairs: {run_url(899)}\n"),  # another run
        pull_request(43, f"Fixes it. Repairs: {run_url(900)}\n"),  # mid-line names nothing
        issue(41, f"{MARKER}\nThe base is red."),
        issue(44, f"{MARKER}\nA person's.", login="amy"),
        issue(45, "<!-- shipmill:base-red release -->\nAnother branch."),
        issue(46, f"Quoting it:\n{MARKER}"),
    )


def test_s079_5_repair_and_asked_name_the_open_pull_request_and_issue(tmp_path: Path) -> None:
    github = GitHubAnswers()
    culprit(github)
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        f"CULPRIT main@{at(0)}",
        f"candidate: {at(1)} #12; revertable",
        "repair: #40",
        "asked: #41",
    ]


def test_s079_5_a_green_reading_still_names_the_question_issue(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head([job("success")])
    github.issues(issue(41, f"{MARKER}\nThe base is red."))
    proc = base_red(tmp_path, github, "--bot-login", BOT)
    assert (proc.returncode, proc.stdout) == (0, GREEN_LINE + "asked: #41\n"), proc.stderr


def test_s079_5_json_prints_one_object_with_the_specs_keys(tmp_path: Path) -> None:
    github = GitHubAnswers()
    culprit(github)
    proc = base_red(tmp_path, github, "--bot-login", BOT, "--json")
    assert proc.returncode == 0, proc.stderr
    found = json.loads(proc.stdout)
    assert {"state", "branch", "sha", "failed", "rerun", "candidates", "repair", "asked"} <= set(found)
    assert (found["state"], found["branch"], found["sha"]) == ("CULPRIT", "main", HEAD)
    assert found["failed"] == [{"check": "test", "url": run_url(900)}]
    assert found["rerun"] == [] and found["repair"] == [40] and found["asked"] == [41]
    assert found["candidates"] == [
        {
            "sha": SHAS[1],
            "pull": 12,
            "merged_by": BOT,
            "revertable": True,
            "reason": None,
            "unjudged": False,
            "rerun": [],
        }
    ]


def test_s079_5_the_default_branch_is_read_without_branch(tmp_path: Path) -> None:
    github = GitHubAnswers()
    github.head([job("success")])
    github.json(API, {"default_branch": "main"})
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    (tmp_path / "gh.json").write_text(json.dumps(github.answers), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(tmp_path / "gh.json"),
        "FAKE_GH_CALLS": str(tmp_path / "gh-calls"),
    }
    proc = subprocess.run([sys.executable, str(SCRIPT), REPO], capture_output=True, text=True, env=env, check=False)
    assert (proc.returncode, proc.stdout) == (0, GREEN_LINE), proc.stderr
    assert endpoints(tmp_path)[0] == API


def broken_history(github: GitHubAnswers) -> None:
    culprit(github)
    github.answers[f"{API}/commits/{SHAS[2]}/check-runs?check_name=test&filter=all&per_page=100"] = {
        "fail": "gh: Server Error (HTTP 502)"
    }


@pytest.mark.parametrize(
    ("setup", "args", "error"),
    [
        pytest.param(broken_history, (), "HTTP 502", id="a failed read"),
        pytest.param(culprit, ("--limit", "1"), "--limit is at least 2, got 1", id="a limit below 2"),
        pytest.param(culprit, ("--branch", "nope"), "Not Found", id="an unknown branch"),
    ],
)
def test_s079_5_a_failed_read_a_limit_below_2_or_an_unknown_branch_exits_2_with_no_reading(
    tmp_path: Path, setup: Any, args: tuple[str, ...], error: str
) -> None:
    github = GitHubAnswers()
    setup(github)
    proc = base_red(tmp_path, github, "--bot-login", BOT, *args)
    assert (proc.returncode, proc.stdout) == (2, ""), proc.stdout
    assert error in proc.stderr


# -- S-079-14: the session's steps in ci-failures.md, and the watch's row in its SKILL.md

SKILLS = SCRIPT.parents[2]


def folded(path: Path) -> str:
    """A file with its line wrapping folded, so a statement reads as one line"""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_s079_14_ci_failures_holds_the_four_steps_for_a_red_default_branch() -> None:
    text = folded(SKILLS / "github-pr-triage" / "references" / "ci-failures.md")
    section = text.split("## A red default branch ", 1)[1].split(" ## ", 1)[0]
    steps = section.split("### The watch's BASE_RED row ", 1)[1]
    assert "Under `observe` it reports the row and changes nothing" in steps
    assert "Under `propose` or `act` it reads the branch itself, `scripts/base_red.py <owner/repo>" in steps
    # each step in its order, keyed to the lines base_red.py prints
    order = [
        "1. **RERUN_DUE: re-run once.** Re-run each run a `rerun: <run URL>` line names, once,"
        " `gh run rerun <id> --failed` through `shipmill gh`, and leave",
        "2. **CANDIDATES with a run to re-run: re-run the unjudged candidates' cancelled runs.** Re-run every run a"
        " candidate's `unjudged, rerun: <run URL>` part names",
        "3. **CULPRIT, or CANDIDATES with no run left to re-run, at most three and every one `revertable`: revert.**",
        "`revert open <PR>... --run <failed run URL>` (`shipmill revert open`)",
        "4. **Anything else: ask on one issue per branch.** A candidate `not revertable` (`no pull request`, `merged by"
        " a person`, `released in <tag>`), more than three candidates, NO_GREEN, a `revert open` that exits 2 on a"
        " conflict, or a revert pull request whose own head fails the check it repairs: no revert.",
        "its body's first line `<!-- shipmill:base-red <branch> -->`",
        "[needs-decision protocol](../../github-issue-triage/references/needs-decision.md)",
        "One such issue is open per branch at a time",
        "the row reads `green again, close #Q`: close it with a comment naming the head,"
        ' `gh issue close <Q> --comment "<branch>@<sha7> is green again"` through `shipmill gh`',
    ]
    at = [steps.find(part) for part in order]
    assert -1 not in at, [part for part, i in zip(order, at, strict=True) if i == -1]
    assert at == sorted(at)
    # the marker is the one base_red.py reads as asked, and the CLI's own usage
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'ASKED = "<!-- shipmill:base-red {branch} -->"' in script
    usage = subprocess.run(
        [sys.executable, "-m", "shipmill", "revert", "open", "--help"], capture_output=True, text=True, check=True
    ).stdout
    assert "--run RUN PR [PR ...]" in usage


def test_s079_14_pr_triage_and_the_watch_name_the_steps_and_the_row() -> None:
    rule_1 = folded(SKILLS / "github-pr-triage" / "SKILL.md").split(" 1. **Merge only on a finished", 1)[1]
    rule_1 = rule_1.split(" 2. **", 1)[0]
    assert (
        'reports it under `[autonomy] revert = "observe"`, and under `propose` or `act` takes the four steps' in rule_1
    )
    assert "(references/ci-failures.md#the-watchs-base_red-row)" in rule_1
    watch = folded(SKILLS / "github-ship-watch" / "SKILL.md")
    row = watch.split("| BASE_RED | ", 1)[1].split(" |", 1)[0]
    for words in ("`rerun due`", "`culprit #N`", "`candidates #A #B`", "`repair open: #R`", "`asked in #Q`"):
        assert words in row, words
    assert "`green again, close #Q`" in row
    assert "Give the user the row's fix" in row
    assert "[ci-failures.md](../github-pr-triage/references/ci-failures.md)" in row
    agent = watch.split("| by its reading | BASE_RED | ", 1)[1].split(" |", 1)[0]
    assert "Never under `observe`" in agent
