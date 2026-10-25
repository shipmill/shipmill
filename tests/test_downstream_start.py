"""Spec 032: `shipmill downstream start` and the reusable .github/workflows/downstream.yml"""

import datetime as dt
import json
import re
import subprocess
import sys
import textwrap
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from shipmill.app import Answer
from shipmill.cli import main
from shipmill.downstream import (
    FORK_TITLE,
    AppDispatcher,
    Check,
    CommitSha,
    Conclusion,
    Downstream,
    DownstreamConfig,
    GhLibrary,
    HeadMoved,
    Pull,
    Status,
    Written,
    key_problem,
    parse_pull,
    start,
)
from shipmill.errors import ReleaseError

from .conftest import POLICY
from .test_app import FakeSigner, key_file

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "downstream.yml"
APP = 123456
LIBRARY = "example-org/library"
SHA = "0123456789abcdef0123456789abcdef01234567"
NOW = dt.datetime(2026, 10, 20, 9, 30, tzinfo=dt.UTC)
REQUIRED = Downstream("consumer-app", "example-org/consumer-app", "library-tests.yml", "release", False, 45)
REPORT_ONLY = Downstream("private-app", "example-org/private-app", "tests.yaml", None, True, 30)
CONFIG = DownstreamConfig(APP, 30, (REQUIRED, REPORT_ONLY))
SAME = Pull(12, SHA, LIBRARY, LIBRARY, "main")
FORK = Pull(12, SHA, "stranger/library", LIBRARY, "main")
FORK_COMMAND = f"gh workflow run downstream.yml -f pr=12 -f sha={SHA}"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"  # a commit pushed after the person read SHA
SECTION = (
    "\n[downstream]\napp_id = 123456\n"
    '\n[downstream.consumer-app]\nrepo = "example-org/consumer-app"\nworkflow = "library-tests.yml"\nref = "release"\n'
    "timeout_minutes = 45\n"
    '\n[downstream.private-app]\nrepo = "example-org/private-app"\nworkflow = "tests.yaml"\nreport_only = true\n'
)


def clock() -> dt.datetime:
    return NOW


@dataclass
class FakeLibrary:
    """The library's repository: the pull request, the checks written on it, collect's dispatches"""

    answer: Pull | None = SAME  # None: the pull request can't be read
    refuse_writes: bool = False
    checks: dict[int, tuple[str, Check]] = field(default_factory=dict)
    created: int = 0
    collects: list[tuple[str, int, str]] = field(default_factory=list)

    def pull(self, number: int) -> Pull:
        if self.answer is None:
            raise ReleaseError(f"gh api repos/{{owner}}/{{repo}}/pulls/{number} failed: Not Found (HTTP 404)")
        return replace(self.answer, number=number)

    def find_check(self, sha: str, name: str) -> int | None:
        ids = [i for i, (s, c) in self.checks.items() if s == sha and c.name == name]
        return max(ids) if ids else None

    def read_check(self, sha: str, name: str) -> Written | None:
        found = self.find_check(sha, name)
        return None if found is None else Written(found, self.checks[found][1])

    def create_check(self, sha: str, check: Check) -> int:
        if self.refuse_writes:
            raise ReleaseError("gh api -X POST repos/{owner}/{repo}/check-runs failed: (HTTP 403)")
        self.created += 1
        self.checks[self.created] = (sha, check)
        return self.created

    def update_check(self, check_id: int, check: Check) -> None:
        if self.refuse_writes:
            raise ReleaseError("gh api -X PATCH failed: (HTTP 403)")
        self.checks[check_id] = (self.checks[check_id][0], check)

    def dispatch_collect(self, ref: str, pr: int, sha: str) -> None:
        self.collects.append((ref, pr, sha))

    def check(self, name: str) -> Check:
        found = self.find_check(SHA, f"downstream: {name}")
        assert found is not None, name
        return self.checks[found][1]


@dataclass
class DownstreamApi:
    """GitHub's REST API as the App sees it: installed on the repos in installed, each token
    limited to the one repository asked for, and each dispatch answered from statuses"""

    installed: dict[str, dict[str, str]] = field(
        default_factory=lambda: {r: {"actions": "write", "metadata": "read"} for r in (REQUIRED.repo, REPORT_ONLY.repo)}
    )
    statuses: dict[str, int] = field(default_factory=dict)  # repo -> the dispatch's answer, 204 by default
    app_status: int = 200
    minted: list[Mapping[str, object]] = field(default_factory=list)
    dispatched: list[tuple[str, str, Mapping[str, object]]] = field(default_factory=list)

    def _ids(self) -> list[str]:
        return sorted(self.installed)

    def get(self, path: str, token: str | None) -> Answer:
        if path == "/app":
            return Answer(self.app_status, json.dumps({"slug": "library-downstream"}))
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)/installation", path):
            repo = m[1]
            if repo not in self.installed:
                return Answer(404, '{"message": "Not Found"}')
            return Answer(200, json.dumps({"id": self._ids().index(repo) + 1, "permissions": self.installed[repo]}))
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)", path):
            assert token == f"token-for-{m[1]}"
            return Answer(200, json.dumps({"default_branch": "trunk"}))
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        if m := re.fullmatch(r"/app/installations/(\d+)/access_tokens", path):
            repo = self._ids()[int(m[1]) - 1]
            self.minted.append(body)
            return Answer(
                201,
                json.dumps(
                    {
                        "token": f"token-for-{repo}",
                        "expires_at": "2026-10-20T10:30:00Z",
                        "repositories": [{"full_name": repo}],
                    }
                ),
            )
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)/actions/workflows/([^/]+)/dispatches", path):
            self.dispatched.append((m[1], token, body))
            status = self.statuses.get(m[1], 204)
            return Answer(status, "" if status == 204 else '{"message": "refused"}')
        raise AssertionError(f"unexpected POST {path}")


def run(
    library: FakeLibrary,
    api: DownstreamApi,
    key: Path,
    actor: str | None = None,
    origin: str | None = None,
    config: DownstreamConfig = CONFIG,
    sha: str | None = SHA,
) -> list[str]:
    """start as the reusable workflow runs it: a person's start (an actor) pinned to sha"""
    signer = FakeSigner()
    dispatcher = AppDispatcher(APP, key, signer, api, clock)
    pinned = CommitSha(sha) if actor is not None and sha is not None else None
    key_check = key_problem(APP, key, signer, api, clock)
    return start(config, library, dispatcher, key_check, 12, actor, origin, clock, pinned)


# S-032-4


def jobs(text: str) -> dict[str, str]:
    """Each job's block of the workflow, by name"""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z-]+):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_s032_4_the_reusable_workflow_checks_out_the_default_branch_and_no_pull_request_ref() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^on:\n  workflow_call:\n", text, flags=re.M)
    assert "pull_request_target:" not in text.split("\njobs:\n", 1)[1]
    checkouts = re.findall(r"- uses: actions/checkout@\S+\n        with:\n          ref: (.+)\n", text)
    assert checkouts and set(checkouts) == {"${{ github.event.repository.default_branch }}"}
    assert text.count("actions/checkout@") == len(checkouts)
    assert "refs/pull" not in text and "merge_commit_sha" not in text
    # the pin step reads the head's SHA to compare it (S-032-24); no expression names a head ref
    for expression in re.findall(r"\$\{\{(.*?)\}\}", text):
        for pr_ref in ("pull_request.head", "head_ref", "head.sha"):
            assert pr_ref not in expression, expression
    assert text.count("persist-credentials: false") == len(checkouts)


def test_s032_4_start_runs_when_collect_is_empty_and_collect_otherwise() -> None:
    found = jobs(WORKFLOW.read_text(encoding="utf-8"))
    assert "if: inputs.collect == ''" in found["start"]
    assert 'args=(downstream start --pr "$PR" --app-key "$key")' in found["start"]
    assert '--actor "$GITHUB_TRIGGERING_ACTOR" --sha "$SHA"' in found["start"]
    assert "group: downstream-${{ inputs.pr }}" in found["start"]
    assert "if: inputs.collect != ''" in found["limit"]
    assert "needs: limit" in found["collect"]
    assert 'shipmill downstream collect --pr "$PR" --head "$HEAD_SHA" --app-key "$key"' in found["collect"]
    assert "group: downstream-collect-${{ inputs.pr }}" in found["collect"]
    for name in ("start", "collect"):
        assert "(umask 077;" in found[name]  # the key's file is 0600, in RUNNER_TEMP, outside the checkout
        assert '"$RUNNER_TEMP/shipmill-downstream-key.pem"' in found[name]


def test_s032_4_ci_runs_actionlint_on_the_reusable_workflow() -> None:
    """actionlint's run in CI covers every file in .github/workflows, downstream.yml among them"""
    assert WORKFLOW.parent.joinpath("downstream.yml").is_file()
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "actionlint .github/workflows/*.yml" in ci


# S-032-5


def test_s032_5_start_writes_a_check_per_downstream_and_dispatches_each(tmp_path: Path) -> None:
    library, api = FakeLibrary(), DownstreamApi()
    lines = run(library, api, key_file(tmp_path))

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.status, required.conclusion, required.title) == (Status.IN_PROGRESS, None, "running")
    assert (report_only.status, report_only.conclusion, report_only.title) == (
        Status.COMPLETED,
        Conclusion.NEUTRAL,
        "report-only: running",
    )
    assert library.created == 2
    consumer_id = f"{LIBRARY}#12@{SHA}/consumer-app"
    private_id = f"{LIBRARY}#12@{SHA}/private-app"
    assert required.external_id == f"{consumer_id} 2026-10-20T09:30:00+00:00"
    assert report_only.external_id == f"{private_id} 2026-10-20T09:30:00+00:00"
    assert SHA in required.summary and consumer_id in required.summary
    assert api.dispatched == [
        (
            "example-org/consumer-app",
            "token-for-example-org/consumer-app",
            {"ref": "release", "inputs": {"library-repo": LIBRARY, "library-ref": SHA, "shipmill-id": consumer_id}},
        ),
        (
            "example-org/private-app",
            "token-for-example-org/private-app",
            {"ref": "trunk", "inputs": {"library-repo": LIBRARY, "library-ref": SHA, "shipmill-id": private_id}},
        ),
    ]
    assert library.collects == [("main", 12, SHA)]
    assert lines[-1] == f"started downstream.yml on main to collect the results for {SHA}"


def test_s032_5_each_token_is_minted_for_the_app_and_limited_to_its_downstream(tmp_path: Path) -> None:
    api = DownstreamApi()
    run(FakeLibrary(), api, key_file(tmp_path))
    assert api.minted == [
        {"repositories": ["consumer-app"], "permissions": {"actions": "write", "metadata": "read"}},
        {"repositories": ["private-app"], "permissions": {"actions": "write", "metadata": "read"}},
    ]


def test_s032_5_the_cli_starts_from_the_policy_and_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + SECTION, encoding="utf-8")
    library, api = FakeLibrary(), DownstreamApi()
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    assert main(argv, api=api, signer=FakeSigner(), library=library) == 0
    assert [c.name for _, c in library.checks.values()] == ["downstream: consumer-app", "downstream: private-app"]
    assert library.collects == [("main", 12, SHA)]
    assert "downstream: consumer-app: started library-tests.yml in example-org/consumer-app" in capsys.readouterr().out


def test_start_refuses_a_downstream_that_is_the_librarys_own_repository(tmp_path: Path) -> None:
    """Spec 032, The config: a downstream's repo is not the library's own when origin tells it"""
    library, api = FakeLibrary(), DownstreamApi()
    own = DownstreamConfig(APP, 30, (REQUIRED, replace(REPORT_ONLY, name="itself", repo=LIBRARY)))
    with pytest.raises(ReleaseError, match=r"\[downstream.itself\] names example-org/library, this library's own"):
        run(library, api, key_file(tmp_path), origin="Example-Org/Library", config=own)
    assert library.checks == {} and api.dispatched == []


def test_the_cli_reads_the_librarys_repository_from_origin(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", "https://github.com/example-org/consumer-app.git"],
        check=True,
    )
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + SECTION, encoding="utf-8")
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    with pytest.raises(ReleaseError, match=r"\[downstream.consumer-app\] names example-org/consumer-app"):
        main(argv, api=DownstreamApi(), signer=FakeSigner(), library=FakeLibrary())


# S-032-6


def test_s032_6_a_second_start_updates_the_checks_it_wrote(tmp_path: Path) -> None:
    library, api = FakeLibrary(), DownstreamApi()
    run(library, api, key_file(tmp_path))
    first = dict(library.checks)
    run(library, api, key_file(tmp_path))
    assert library.created == 2
    assert sorted(library.checks) == sorted(first) == [1, 2]
    assert len(api.dispatched) == 4


# S-032-7


def test_s032_7_a_refused_dispatch_fails_the_check_and_start_goes_on(tmp_path: Path) -> None:
    library = FakeLibrary()
    api = DownstreamApi(statuses={REQUIRED.repo: 404, REPORT_ONLY.repo: 403})
    run(library, api, key_file(tmp_path))

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.status, required.conclusion, required.title) == (
        Status.COMPLETED,
        Conclusion.FAILURE,
        "couldn't start: 404",
    )
    assert "GitHub answered 404" in required.summary
    assert "library-tests.yml doesn't exist on release in example-org/consumer-app, or has no workflow_dispatch" in (
        required.summary
    )
    assert (report_only.status, report_only.conclusion, report_only.title) == (
        Status.COMPLETED,
        Conclusion.NEUTRAL,
        "report-only: couldn't start: 403",
    )
    assert "GitHub answered 403" in report_only.summary
    assert f"the App {APP} is not installed on example-org/private-app, or lacks Actions: read and write" in (
        report_only.summary
    )
    assert len(api.dispatched) == 2  # the second downstream was still dispatched
    assert library.collects == []  # no run started, so nothing to collect


def test_s032_7_an_app_not_installed_on_a_downstream_fails_only_its_check(tmp_path: Path) -> None:
    library = FakeLibrary()
    api = DownstreamApi()
    del api.installed[REQUIRED.repo]
    run(library, api, key_file(tmp_path))
    required = library.check("consumer-app")
    assert (required.conclusion, required.title) == (Conclusion.FAILURE, "couldn't start: 404")
    assert f"the App {APP} is not installed on example-org/consumer-app" in required.summary
    assert [d[0] for d in api.dispatched] == [REPORT_ONLY.repo]
    assert library.check("private-app").title == "report-only: running"
    assert library.collects == [("main", 12, SHA)]


def test_s032_7_an_installation_without_actions_write_fails_the_check_with_403(tmp_path: Path) -> None:
    library = FakeLibrary()
    api = DownstreamApi()
    api.installed[REQUIRED.repo] = {"actions": "read", "metadata": "read"}
    run(library, api, key_file(tmp_path))
    required = library.check("consumer-app")
    assert (required.conclusion, required.title) == (Conclusion.FAILURE, "couldn't start: 403")


# S-032-17


def test_s032_17_a_forks_pull_request_dispatches_nothing_and_waits_for_a_person(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=FORK), DownstreamApi()
    lines = run(library, api, key_file(tmp_path))

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.status, required.conclusion, required.title) == (
        Status.COMPLETED,
        Conclusion.ACTION_REQUIRED,
        FORK_TITLE,
    )
    assert (report_only.status, report_only.conclusion, report_only.title) == (
        Status.COMPLETED,
        Conclusion.NEUTRAL,
        FORK_TITLE,
    )
    assert FORK_TITLE == "a fork's pull request runs downstream tests only by hand"
    for check in (required, report_only):
        assert f"```\n{FORK_COMMAND}\n```" in check.summary  # the full head SHA start read
    assert required.details_url == f"https://github.com/{LIBRARY}/actions/workflows/downstream.yml"
    assert api.dispatched == [] and api.minted == [] and library.collects == []
    assert lines == [f"downstream: {n}: waits for a person: {FORK_COMMAND}" for n in ("consumer-app", "private-app")]


def test_s032_17_a_deleted_forks_pull_request_is_a_forks(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=replace(FORK, head_repo=None)), DownstreamApi()
    run(library, api, key_file(tmp_path))
    assert library.check("consumer-app").conclusion is Conclusion.ACTION_REQUIRED
    assert api.dispatched == []


# S-032-12


def test_s032_12_a_persons_start_dispatches_a_forks_pull_request_and_updates_its_checks(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=FORK), DownstreamApi()
    run(library, api, key_file(tmp_path))
    run(library, api, key_file(tmp_path), actor="maintainer")
    assert library.created == 2
    assert library.check("consumer-app").status is Status.IN_PROGRESS
    assert library.check("private-app").title == "report-only: running"
    assert [d[0] for d in api.dispatched] == [REQUIRED.repo, REPORT_ONLY.repo]
    assert library.collects == [("main", 12, SHA)]


def test_s032_12_a_bots_start_on_a_forks_pull_request_writes_nothing_and_exits_2(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=FORK), DownstreamApi()
    with pytest.raises(
        ReleaseError, match=r"^a fork's downstream run is started by a person, not shipmill-app\[bot\]$"
    ):
        run(library, api, key_file(tmp_path), actor="shipmill-app[bot]")
    assert library.checks == {} and api.dispatched == []


def test_s032_12_a_bot_starts_a_pull_request_from_the_repository_as_a_person_does(tmp_path: Path) -> None:
    library, api = FakeLibrary(), DownstreamApi()
    run(library, api, key_file(tmp_path), actor="shipmill-app[bot]")
    assert [d[0] for d in api.dispatched] == [REQUIRED.repo, REPORT_ONLY.repo]
    assert library.check("consumer-app").status is Status.IN_PROGRESS


# S-032-18: a person's start is pinned to the head they read


def moved_line(current: str) -> str:
    return f"the head of #12 is {current}, not {SHA}; read the new commits and start again with -f sha={current}"


def test_s032_18_a_start_for_a_head_that_moved_writes_mints_and_dispatches_nothing(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=replace(SAME, head_sha=OTHER)), DownstreamApi()
    with pytest.raises(HeadMoved) as moved:
        run(library, api, key_file(tmp_path), actor="maintainer", sha=SHA)
    assert str(moved.value) == moved_line(OTHER)
    assert moved_line(OTHER) == (
        f"the head of #12 is {OTHER}, not {SHA}; read the new commits and start again with -f sha={OTHER}"
    )
    assert not isinstance(moved.value, ReleaseError)  # exit 1, not the exit 2 of a bad setup
    assert library.checks == {} and api.minted == [] and api.dispatched == [] and library.collects == []


def test_s032_18_a_forks_held_checks_stay_as_they_were(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=replace(FORK, head_sha=OTHER)), DownstreamApi()
    run(library, api, key_file(tmp_path))  # pull_request_target holds the fork's head OTHER
    held = dict(library.checks)
    with pytest.raises(HeadMoved):
        run(library, api, key_file(tmp_path), actor="maintainer", sha=SHA)  # the person read SHA
    assert library.checks == held
    assert all(c.conclusion is Conclusion.ACTION_REQUIRED for _, c in held.values() if "consumer" in c.name)
    assert api.minted == [] and api.dispatched == []


def test_s032_18_the_cli_exits_1_with_the_line_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + SECTION, encoding="utf-8")
    library, api = FakeLibrary(answer=replace(SAME, head_sha=OTHER)), DownstreamApi()
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    argv += ["--actor", "maintainer", "--sha", SHA]
    assert main(argv, api=api, signer=FakeSigner(), library=library) == 1
    err = capsys.readouterr().err
    assert err == f"shipmill: {moved_line(OTHER)}\n"
    assert library.checks == {} and api.minted == [] and api.dispatched == []


# S-032-19


@pytest.mark.parametrize(
    "sha",
    [
        None,  # a caller written before the sha input, or a dispatch without it
        "",
        SHA[:12],
        SHA.upper(),
        SHA + "0",
        "0123456789abcdef0123456789abcdef0123456g",
        f"{SHA}\n::error::injected",
    ],
)
def test_s032_19_a_dispatched_start_without_a_full_sha_exits_2_and_writes_nothing(
    tmp_path: Path, sha: str | None
) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + SECTION, encoding="utf-8")
    library, api = FakeLibrary(), DownstreamApi()
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    argv += ["--actor", "maintainer"] + ([] if sha is None else ["--sha", sha])
    with pytest.raises(ReleaseError, match=r"--sha.*`shipmill init --downstream --force`") as refused:
        main(argv, api=api, signer=FakeSigner(), library=library)
    assert "sha input" in str(refused.value)
    assert library.checks == {} and api.minted == [] and api.dispatched == [] and library.collects == []


def test_s032_19_start_itself_refuses_a_persons_start_without_a_sha(tmp_path: Path) -> None:
    library, api = FakeLibrary(), DownstreamApi()
    with pytest.raises(ReleaseError, match="shipmill init --downstream --force"):
        run(library, api, key_file(tmp_path), actor="maintainer", sha=None)
    assert library.checks == {} and api.dispatched == []


def test_s032_19_a_sha_without_a_persons_start_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + SECTION, encoding="utf-8")
    library = FakeLibrary()
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    with pytest.raises(ReleaseError, match="--sha pins a workflow_dispatch start"):
        main([*argv, "--sha", SHA], api=DownstreamApi(), signer=FakeSigner(), library=library)
    assert library.checks == {}


def test_s032_19_a_pull_request_target_start_needs_no_sha(tmp_path: Path) -> None:
    library, api = FakeLibrary(), DownstreamApi()
    run(library, api, key_file(tmp_path), actor=None, sha=None)
    assert [d[0] for d in api.dispatched] == [REQUIRED.repo, REPORT_ONLY.repo]


def test_s032_19_a_commit_sha_is_40_lowercase_hexadecimal_characters() -> None:
    assert str(CommitSha(SHA)) == SHA
    for bad in ("", SHA[:39], SHA.upper(), SHA + "a", " " + SHA[1:]):
        with pytest.raises(ReleaseError, match="40 lowercase hexadecimal characters"):
            CommitSha(bad)


# S-032-20


def test_s032_20_a_start_for_the_head_tests_that_sha(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=FORK), DownstreamApi()
    run(library, api, key_file(tmp_path), actor="maintainer", sha=SHA)
    sid = f"{LIBRARY}#12@{SHA}/consumer-app"
    assert api.dispatched[0][2] == {
        "ref": "release",
        "inputs": {"library-repo": LIBRARY, "library-ref": SHA, "shipmill-id": sid},
    }
    assert {s for s, _ in library.checks.values()} == {SHA}
    assert library.check("consumer-app").external_id.startswith(f"{sid} ")
    assert library.collects == [("main", 12, SHA)]


def test_s032_20_the_collect_dispatch_carries_pr_sha_and_collect(tmp_path: Path) -> None:
    calls = gh_library(tmp_path)
    GhLibrary(tmp_path, str(tmp_path / "gh")).dispatch_collect("main", 12, SHA)
    [call] = calls()
    assert call["args"] == [
        "workflow", "run", "downstream.yml", "--ref", "main", "-f", "pr=12", "-f", f"sha={SHA}", "-f", f"collect={SHA}",
    ]  # fmt: skip


def test_s032_20_a_caller_without_the_sha_input_refusing_collect_names_the_fix(tmp_path: Path) -> None:
    gh = tmp_path / "gh"
    refused = "could not create workflow dispatch event: HTTP 422: Unexpected inputs provided"
    gh.write_text(f"#!/bin/sh\necho '{refused}' >&2\nexit 1\n", encoding="utf-8")
    gh.chmod(0o755)
    with pytest.raises(ReleaseError, match="rewritten with `shipmill init --downstream --force`"):
        GhLibrary(tmp_path, str(gh)).dispatch_collect("main", 12, SHA)


# S-032-21: the reusable workflow takes sha and passes it to start


def test_s032_21_the_reusable_workflow_takes_an_optional_sha_and_passes_it_on_a_dispatch() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    inputs = text.split("    inputs:\n", 1)[1].split("    secrets:\n", 1)[0]
    sha = inputs.split("      sha:\n", 1)[1].split("\n      collect:\n", 1)[0]
    assert "type: string" in sha and 'default: ""' in sha and "required: true" not in sha
    start_job = jobs(text)["start"]
    assert "SHA: ${{ inputs.sha }}" in start_job
    assert '[ "$EVENT" = workflow_dispatch ] && args+=(--actor "$GITHUB_TRIGGERING_ACTOR" --sha "$SHA")' in start_job


# S-032-24: the reusable workflow compares the SHA before any key reaches the disk

PIN = "Check the head is the one the person read"


def step_script(name: str) -> str:
    """A step's run script in the reusable workflow, dedented as the runner runs it"""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    begin = lines.index(f"      - name: {name}")
    at = next(i for i in range(begin, len(lines)) if lines[i] == "        run: |")
    body: list[str] = []
    for line in lines[at + 1 :]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


def start_steps() -> list[str]:
    """The start job's steps, each as its text"""
    return re.split(r"\n(?=      - )", jobs(WORKFLOW.read_text(encoding="utf-8"))["start"])[1:]


def test_s032_24_the_comparison_runs_before_the_key_file_and_any_token() -> None:
    steps = start_steps()
    pin = next(i for i, s in enumerate(steps) if f"name: {PIN}" in s)
    checkout = next(i for i, s in enumerate(steps) if "uses: actions/checkout@" in s)
    assert pin == checkout + 1  # the first step after the default branch's checkout
    assert "if: github.event_name == 'workflow_dispatch'" in steps[pin]
    assert "secrets." not in steps[pin] and "shipmill-downstream-key" not in steps[pin]
    for i, step in enumerate(steps):  # every step that holds the key or runs shipmill comes after
        if "secrets.downstream-key" in step or "shipmill-downstream-key" in step or "uvx" in step:
            assert i > pin, step


def pin(tmp_path: Path, head: str, sha: str) -> tuple[int, str, list[str]]:
    """The pin step as bash with GitHub's env and a gh that answers the pull request's head"""
    log = tmp_path / "gh.log"
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(f'#!/bin/sh\necho "$*" >> {log}\necho {head}\n', encoding="utf-8")
    gh.chmod(0o755)
    env = {"PATH": f"{gh.parent}:/usr/bin:/bin", "GH_TOKEN": "t", "REPO": LIBRARY, "PR": "12", "SHA": sha}
    env["RUNNER_TEMP"] = str(tmp_path)
    proc = subprocess.run(["bash", "-e", "-c", step_script(PIN)], env=env, capture_output=True, text=True, check=False)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc.returncode, proc.stdout, calls


def test_s032_24_a_moved_head_exits_1_naming_both_shas_with_no_key_file(tmp_path: Path) -> None:
    code, out, calls = pin(tmp_path, OTHER, SHA)
    assert code == 1
    assert out == (
        f"::error::the head of #12 is {OTHER}, not {SHA}; read the new commits and start again with -f sha={OTHER}\n"
    )
    assert calls == [f"api repos/{LIBRARY}/pulls/12 --jq .head.sha"]
    assert not (tmp_path / "shipmill-downstream-key.pem").exists()


def test_s032_24_the_head_the_person_read_goes_on(tmp_path: Path) -> None:
    code, out, _ = pin(tmp_path, SHA, SHA)
    assert code == 0
    assert out == f"the head of #12 is {SHA}, the one the person read\n"


@pytest.mark.parametrize("sha", ["", SHA[:12], SHA.upper(), f"{SHA}\n::warning::x"])
def test_s032_24_a_missing_or_malformed_sha_exits_before_reading_anything(tmp_path: Path, sha: str) -> None:
    code, out, calls = pin(tmp_path, SHA, sha)
    assert code == 2
    assert out.startswith("::error::shipmill: a workflow_dispatch start needs the sha input")
    assert "shipmill init --downstream --force" in out and "::warning::" not in out
    assert calls == []


# S-032-13


def test_s032_13_start_exits_2_when_the_config_doesnt_parse(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    broken = SECTION.replace('workflow = "tests.yaml"', 'workflow = "tests"')
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + broken, encoding="utf-8")
    library = FakeLibrary()
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    with pytest.raises(ReleaseError, match="workflow names a file"):
        main(argv, api=DownstreamApi(), signer=FakeSigner(), library=library)
    assert library.checks == {}


def test_s032_13_start_exits_2_without_a_downstream_section(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY, encoding="utf-8")
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", str(key_file(tmp_path))]
    with pytest.raises(ReleaseError, match=r"has no \[downstream\] section"):
        main(argv, api=DownstreamApi(), signer=FakeSigner(), library=FakeLibrary())


def test_s032_13_start_exits_2_when_the_pull_request_cant_be_read(tmp_path: Path) -> None:
    library, api = FakeLibrary(answer=None), DownstreamApi()
    with pytest.raises(ReleaseError, match="HTTP 404"):
        run(library, api, key_file(tmp_path))
    assert api.dispatched == []


def test_s032_13_start_exits_2_when_a_check_cant_be_written(tmp_path: Path) -> None:
    library, api = FakeLibrary(refuse_writes=True), DownstreamApi()
    with pytest.raises(ReleaseError, match="check-runs failed"):
        run(library, api, key_file(tmp_path))
    assert api.dispatched == []


def test_s032_13_an_empty_key_writes_every_check_with_the_reason_and_exits_2(tmp_path: Path) -> None:
    key = tmp_path / "empty.pem"
    key.write_bytes(b"")
    key.chmod(0o600)
    library, api = FakeLibrary(), DownstreamApi()
    with pytest.raises(ReleaseError, match="is empty"):
        run(library, api, key)
    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.status, required.conclusion) == (Status.COMPLETED, Conclusion.FAILURE)
    assert (report_only.status, report_only.conclusion) == (Status.COMPLETED, Conclusion.NEUTRAL)
    for check in (required, report_only):
        assert f"the App private key {key} is empty" in check.summary
    assert api.dispatched == [] and library.collects == []


def test_s032_13_a_key_that_isnt_a_private_key_writes_every_check_and_exits_2(tmp_path: Path) -> None:
    @dataclass
    class Refusing:
        def sign(self, key: Path, data: bytes) -> bytes:
            raise ReleaseError(f"openssl could not sign with the App private key {key}: unable to load key")

    key = key_file(tmp_path)
    library, api = FakeLibrary(), DownstreamApi()
    dispatcher = AppDispatcher(APP, key, Refusing(), api, clock)
    with pytest.raises(ReleaseError, match="could not sign"):
        start(CONFIG, library, dispatcher, key_problem(APP, key, Refusing(), api, clock), 12, None, None, clock)
    assert library.check("consumer-app").conclusion is Conclusion.FAILURE
    assert library.check("private-app").conclusion is Conclusion.NEUTRAL
    assert "unable to load key" in library.check("consumer-app").summary
    assert api.dispatched == []


def test_s032_13_a_key_github_refuses_writes_every_check_and_exits_2(tmp_path: Path) -> None:
    library, api = FakeLibrary(), DownstreamApi(app_status=401)
    with pytest.raises(ReleaseError, match="GitHub refused the JWT"):
        run(library, api, key_file(tmp_path))
    assert library.check("consumer-app").conclusion is Conclusion.FAILURE
    assert api.dispatched == []


def test_start_records_an_unexpected_dispatch_error_on_the_check_before_exit_2(tmp_path: Path) -> None:
    library = FakeLibrary()
    api = DownstreamApi(statuses={REQUIRED.repo: 500})
    with pytest.raises(ReleaseError, match="answered 500"):
        run(library, api, key_file(tmp_path))
    required = library.check("consumer-app")
    assert (required.conclusion, required.title) == (Conclusion.FAILURE, "couldn't start")


def test_start_still_collects_the_runs_it_started_before_an_unexpected_dispatch_error(tmp_path: Path) -> None:
    """A downstream already dispatched keeps a collector when a later one ends start with exit 2,
    so its in-progress check doesn't hold the pull request with nothing to conclude it"""
    library = FakeLibrary()
    api = DownstreamApi(statuses={REPORT_ONLY.repo: 500})
    with pytest.raises(ReleaseError, match="answered 500"):
        run(library, api, key_file(tmp_path))
    assert library.check("consumer-app").status is Status.IN_PROGRESS
    assert library.collects == [("main", 12, SHA)]


def test_the_cli_refuses_an_empty_actor(tmp_path: Path) -> None:
    argv = ["--repo", str(tmp_path), "downstream", "start", "--pr", "12", "--app-key", "k", "--actor", ""]
    with pytest.raises(ReleaseError, match="--actor names who started the run"):
        main(argv, library=FakeLibrary())


# GitHub's pull request answer


def pull_answer(head_repo: object = None) -> dict[str, object]:
    return {
        "number": 12,
        "head": {"sha": SHA, "repo": head_repo},
        "base": {"repo": {"full_name": LIBRARY, "default_branch": "main"}},
    }


def test_parse_pull_reads_the_head_and_the_base() -> None:
    assert parse_pull(pull_answer({"full_name": LIBRARY}), 12) == SAME
    assert parse_pull(pull_answer({"full_name": "stranger/library"}), 12).fork
    assert parse_pull(pull_answer(None), 12).fork
    assert not SAME.fork


def test_parse_pull_refuses_a_short_sha_or_another_number() -> None:
    short = pull_answer({"full_name": LIBRARY})
    short["head"] = {"sha": SHA[:12], "repo": {"full_name": LIBRARY}}
    with pytest.raises(ReleaseError, match="no full head SHA"):
        parse_pull(short, 12)
    with pytest.raises(ReleaseError, match="no matching number"):
        parse_pull(pull_answer(), 13)


# GhLibrary, through a gh that records its calls

FAKE_GH = """\
import json, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(__file__).with_name("calls.jsonl")
with log.open("a") as out:
    out.write(json.dumps({"args": args, "stdin": sys.stdin.read() if "--input" in args else ""}) + "\\n")
path = next((a for a in args if a.startswith("repos/")), "")
if path.endswith("/check-runs") and "GET" in args:
    runs = [
        {"id": 5, "name": "downstream: consumer-app", "app": {"slug": "github-actions"}},
        {"id": 9, "name": "downstream: consumer-app", "app": {"slug": "another-app"}},
        {"id": 7, "name": "downstream: consumer-app", "app": {"slug": "github-actions"}},
    ]
    print(json.dumps({"total_count": 3, "check_runs": runs}))
elif path.endswith("/check-runs"):
    print(json.dumps({"id": 11}))
elif "/check-runs/" in path:
    print(json.dumps({"id": 7}))
elif "/pulls/" in path:
    print(json.dumps({"number": 12, "head": {"sha": "THE_SHA", "repo": None},
                      "base": {"repo": {"full_name": "THE_LIBRARY", "default_branch": "main"}}}))
""".replace("THE_SHA", SHA).replace("THE_LIBRARY", LIBRARY)


def gh_library(tmp_path: Path) -> Callable[[], list[dict[str, object]]]:
    """A gh at tmp_path/gh that records its calls; the calls it recorded so far"""
    script = tmp_path / "fake_gh.py"
    script.write_text(FAKE_GH, encoding="utf-8")
    gh = tmp_path / "gh"
    gh.write_text(f'#!/bin/sh\nexec {sys.executable} {script} "$@"\n', encoding="utf-8")
    gh.chmod(0o755)

    def calls() -> list[dict[str, object]]:
        return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]

    return calls


def test_gh_library_reads_and_writes_through_gh(tmp_path: Path) -> None:
    gh_library(tmp_path)
    library = GhLibrary(tmp_path, str(tmp_path / "gh"))

    assert library.pull(12) == replace(FORK, head_repo=None)
    assert library.find_check(SHA, "downstream: consumer-app") == 7  # the newest this workflow's App wrote
    check = Check("downstream: consumer-app", Status.IN_PROGRESS, None, "running", "Testing", external_id="x 1")
    assert library.create_check(SHA, check) == 11
    library.update_check(7, replace(check, status=Status.COMPLETED, conclusion=Conclusion.FAILURE))
    library.dispatch_collect("main", 12, SHA)

    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    created, updated = json.loads(calls[2]["stdin"]), json.loads(calls[3]["stdin"])
    assert created == {
        "name": "downstream: consumer-app",
        "status": "in_progress",
        "output": {"title": "running", "summary": "Testing"},
        "external_id": "x 1",
        "head_sha": SHA,
    }
    assert updated["conclusion"] == "failure" and "head_sha" not in updated
    assert calls[3]["args"][:4] == ["api", "-X", "PATCH", "repos/{owner}/{repo}/check-runs/7"]
    collect = ["workflow", "run", "downstream.yml", "--ref", "main", "-f", "pr=12"]
    collect += ["-f", f"sha={SHA}", "-f", f"collect={SHA}"]
    assert calls[4]["args"] == collect
