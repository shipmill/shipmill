"""Spec 032: `shipmill downstream collect` reads each downstream run back into its check"""

import datetime as dt
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app import Answer
from shipmill.cli import main
from shipmill.downstream import (
    RUN_NAME_RULE,
    AppRuns,
    Check,
    Conclusion,
    DownstreamConfig,
    GhLibrary,
    Status,
    collect,
    job_name,
)
from shipmill.errors import ReleaseError

from .conftest import POLICY
from .test_app import FakeSigner, key_file
from .test_downstream_start import (
    APP,
    CONFIG,
    FORK,
    LIBRARY,
    NOW,
    REPORT_ONLY,
    REQUIRED,
    SECTION,
    SHA,
    DownstreamApi,
    FakeLibrary,
    run,
)

CONSUMER_ID = f"{LIBRARY}#12@{SHA}/consumer-app"
PRIVATE_ID = f"{LIBRARY}#12@{SHA}/private-app"
CONSUMER_RUNS = f"/repos/{REQUIRED.repo}/actions/workflows/{REQUIRED.workflow}/runs"
PRIVATE_RUNS = f"/repos/{REPORT_ONLY.repo}/actions/workflows/{REPORT_ONLY.workflow}/runs"
CONSUMER_RUN = f"https://github.com/{REQUIRED.repo}/actions/runs/101"
PRIVATE_RUN = f"https://github.com/{REPORT_ONLY.repo}/actions/runs/202"
LOG_LINE = "AssertionError: secret-token-from-the-downstream"  # what a downstream's log could hold


@dataclass
class Clock:
    """The time collect reads, moved only by its sleep: no test waits"""

    now: dt.datetime = NOW
    slept: list[float] = field(default_factory=list)

    def __call__(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


def a_run(
    run_id: int,
    sid: str,
    status: str = "completed",
    conclusion: str | None = "success",
    created: str = "2026-10-20T09:30:05Z",
) -> dict[str, object]:
    return {
        "id": run_id,
        "display_title": f"library {SHA} ({sid})",
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "created_at": created,
        "event": "workflow_dispatch",
    }


@dataclass
class RunsApi(DownstreamApi):
    """The downstream repositories' runs as the App reads them: each workflow's runs as a
    timeline, each entry shown from its offset after NOW, and each run's jobs"""

    clock: Clock = field(default_factory=Clock)
    timelines: dict[str, list[tuple[dt.timedelta, list[dict[str, object]]]]] = field(default_factory=dict)
    jobs: dict[int, list[dict[str, object]]] = field(default_factory=dict)
    read: list[str] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.read.append(path)
        base, _, query = path.partition("?")
        if base in self.timelines:
            assert token == f"token-for-{base.split('/')[2]}/{base.split('/')[3]}"
            asked = urllib.parse.parse_qs(query)
            assert asked["event"] == ["workflow_dispatch"]
            since = dt.datetime.fromisoformat(asked["created"][0].removeprefix(">="))
            shown: list[dict[str, object]] = []
            for offset, runs in self.timelines[base]:
                if self.clock.now - NOW >= offset:
                    shown = runs
            created = [r for r in shown if dt.datetime.fromisoformat(str(r["created_at"])) >= since]
            return Answer(200, json.dumps({"total_count": len(created), "workflow_runs": created}))
        if m := re.fullmatch(r"/repos/[^/]+/[^/]+/actions/runs/(\d+)/jobs", base):
            assert query == "filter=latest&per_page=100"
            return Answer(200, json.dumps({"total_count": 1, "jobs": self.jobs.get(int(m[1]), [])}))
        return super().get(path, token)


@dataclass
class RecordingLibrary(FakeLibrary):
    """The library, keeping every update so a test sees each check concluded once"""

    updates: list[tuple[int, Check]] = field(default_factory=list)

    def update_check(self, check_id: int, check: Check) -> None:
        super().update_check(check_id, check)
        self.updates.append((check_id, check))

    def concluded(self, name: str) -> list[Check]:
        found = self.find_check(SHA, f"downstream: {name}")
        return [c for i, c in self.updates if i == found and c.title not in {"running", "report-only: running"}]


def started(tmp_path: Path) -> tuple[RecordingLibrary, RunsApi, Path]:
    """The checks `downstream start` wrote at NOW for both downstreams"""
    library, key = RecordingLibrary(), key_file(tmp_path)
    run(library, DownstreamApi(), key)
    library.updates.clear()
    api = RunsApi()
    api.clock = Clock()
    return library, api, key


def collected(library: RecordingLibrary, api: RunsApi, key: Path, config: DownstreamConfig = CONFIG) -> list[str]:
    runs = AppRuns(APP, key, FakeSigner(), api, api.clock)
    return collect(config, library, runs, 12, SHA, api.clock, api.clock.sleep)


# S-032-8


def test_s032_8_a_passed_run_links_the_check_and_concludes_it(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID)])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    lines = collected(library, api, key)

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.status, required.conclusion, required.title) == (Status.COMPLETED, Conclusion.SUCCESS, "passed")
    assert required.details_url == CONSUMER_RUN
    assert (report_only.status, report_only.conclusion, report_only.title) == (
        Status.COMPLETED,
        Conclusion.NEUTRAL,
        "report-only: passed",
    )
    assert report_only.details_url == PRIVATE_RUN
    assert required.external_id == f"{CONSUMER_ID} 2026-10-20T09:30:00+00:00"  # kept for a later collect
    assert lines == ["downstream: consumer-app: passed", "downstream: private-app: report-only: passed"]
    assert api.clock.slept == []


def test_s032_8_any_other_conclusion_fails_a_required_check_and_a_report_only_stays_neutral(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID, conclusion="cancelled")])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID, conclusion="failure")])]
    collected(library, api, key)

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.conclusion, required.title) == (Conclusion.FAILURE, "failed: cancelled")
    assert (report_only.conclusion, report_only.title) == (Conclusion.NEUTRAL, "report-only: failed: failure")


def test_s032_8_it_polls_every_30_seconds_and_concludes_each_check_once(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    running = a_run(101, CONSUMER_ID, status="in_progress")
    api.timelines[CONSUMER_RUNS] = [
        (dt.timedelta(), []),
        (dt.timedelta(seconds=40), [running]),
        (dt.timedelta(minutes=5), [a_run(101, CONSUMER_ID, conclusion="failure")]),
    ]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)

    assert set(api.clock.slept) == {30} and api.clock.now == NOW + dt.timedelta(minutes=5)
    assert [c.title for c in library.concluded("consumer-app")] == ["failed: failure"]
    assert [c.title for c in library.concluded("private-app")] == ["report-only: passed"]
    linked = [c for _, c in library.updates if c.title == "running"]
    assert len(linked) == 1 and linked[0].details_url == CONSUMER_RUN  # linked once, while it ran
    assert linked[0].status is Status.IN_PROGRESS


def test_s032_8_a_run_past_its_timeout_concludes_timed_out_and_is_left_running(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID, status="in_progress")])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID, status="queued")])]
    collected(library, api, key)

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.conclusion, required.title) == (Conclusion.TIMED_OUT, "timed out after 45 minutes")
    assert required.details_url == CONSUMER_RUN
    assert "left running" in required.summary
    assert (report_only.conclusion, report_only.title) == (
        Conclusion.NEUTRAL,
        "report-only: timed out after 30 minutes",
    )
    assert api.clock.now == NOW + dt.timedelta(minutes=45)
    assert len(library.concluded("consumer-app")) == len(library.concluded("private-app")) == 1


def test_s032_8_only_a_dispatch_run_created_after_the_dispatch_with_the_id_counts(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    earlier = a_run(90, CONSUMER_ID, conclusion="failure", created="2026-10-20T09:29:59Z")  # a previous start's
    longer = a_run(95, f"{CONSUMER_ID}-2", conclusion="failure")  # another downstream's id that starts with it
    other_sha = a_run(96, CONSUMER_ID.replace(SHA, "f" * 40), conclusion="failure")
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [earlier, longer, other_sha, a_run(101, CONSUMER_ID)])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)

    assert library.check("consumer-app").title == "passed"
    assert library.check("consumer-app").details_url == CONSUMER_RUN
    asked = [p for p in api.read if p.startswith(CONSUMER_RUNS)]
    assert asked and urllib.parse.parse_qs(asked[0].partition("?")[2])["created"] == [">=2026-10-20T09:30:00Z"]


def test_s032_8_a_run_of_a_library_whose_name_ends_with_this_ones_is_not_this_ones(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    other = a_run(102, f"the-{CONSUMER_ID}", conclusion="failure")  # the-example-org/library, same SHA and PR
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID), other])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)
    assert library.check("consumer-app").title == "passed"
    assert library.check("consumer-app").details_url == CONSUMER_RUN


def test_s032_8_each_read_uses_a_token_limited_to_its_downstream_and_to_reading(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID)])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)
    assert api.minted == [
        {"repositories": ["consumer-app"], "permissions": {"actions": "read", "metadata": "read"}},
        {"repositories": ["private-app"], "permissions": {"actions": "read", "metadata": "read"}},
    ]


def test_s032_8_the_cli_collects_from_the_policy_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library, api, key = started(tmp_path)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(POLICY + SECTION, encoding="utf-8")
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID)])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    argv = ["--repo", str(tmp_path), "downstream", "collect", "--pr", "12", "--head", SHA, "--app-key", str(key)]
    assert main(argv, api=api, signer=FakeSigner(), library=library) == 0
    assert library.check("consumer-app").conclusion is Conclusion.SUCCESS
    assert "downstream: consumer-app: passed" in capsys.readouterr().out


def test_collect_leaves_a_concluded_check_alone(tmp_path: Path) -> None:
    library, api = RecordingLibrary(answer=FORK), RunsApi()
    run(library, DownstreamApi(), key_file(tmp_path))  # a fork's checks: action_required, waiting for a person
    lines = collected(library, api, key_file(tmp_path))
    assert library.updates == [] and api.read == []
    assert (
        lines[0]
        == "downstream: consumer-app: already concluded: a fork's pull request runs downstream tests only by hand"
    )


def test_collect_names_a_downstream_without_a_check(tmp_path: Path) -> None:
    library, api = RecordingLibrary(), RunsApi()
    assert (
        collected(library, api, key_file(tmp_path))[0]
        == f"downstream: consumer-app: no check on {SHA}; nothing to collect"
    )


def test_an_app_no_longer_installed_fails_the_check_naming_the_fix(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    del api.installed[REQUIRED.repo]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)
    required = library.check("consumer-app")
    assert (required.conclusion, required.title) == (Conclusion.FAILURE, "couldn't read: 404")
    assert f"the App {APP} is not installed on {REQUIRED.repo}" in required.summary


def test_collect_exits_2_for_a_short_head(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    runs = AppRuns(APP, key, FakeSigner(), api, api.clock)
    with pytest.raises(ReleaseError, match="--head is the full 40-character head SHA"):
        collect(CONFIG, library, runs, 12, SHA[:12], api.clock, api.clock.sleep)


def test_collect_exits_2_for_a_check_start_didnt_write(tmp_path: Path) -> None:
    library = RecordingLibrary()
    library.create_check(SHA, Check("downstream: consumer-app", Status.IN_PROGRESS, None, "running", "", "junk"))
    with pytest.raises(ReleaseError, match="not the shipmill-id and dispatch time"):
        collected(library, RunsApi(), key_file(tmp_path))


def test_s032_13_collect_exits_2_when_a_check_cant_be_written(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    library.refuse_writes = True
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID)])]
    with pytest.raises(ReleaseError, match="HTTP 403"):
        collected(library, api, key)


def test_s032_13_collect_exits_2_when_the_pull_request_cant_be_read(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    library.answer = None
    with pytest.raises(ReleaseError, match="HTTP 404"):
        collected(library, api, key)
    assert library.updates == []


# S-032-9


def test_s032_9_no_run_within_2_minutes_fails_naming_the_run_name_rule(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [])]
    lines = collected(library, api, key)

    required, report_only = library.check("consumer-app"), library.check("private-app")
    assert (required.conclusion, required.title) == (Conclusion.FAILURE, "couldn't start: no run")
    assert (report_only.conclusion, report_only.title) == (Conclusion.NEUTRAL, "report-only: couldn't start: no run")
    assert f"no run of library-tests.yml in {REQUIRED.repo} has {CONSUMER_ID} in its run-name within 2 minutes" in (
        required.summary
    )
    for check in (required, report_only):
        assert RUN_NAME_RULE == "its run-name must contain inputs.shipmill-id" and RUN_NAME_RULE in check.summary
    assert api.clock.now == NOW + dt.timedelta(minutes=2)
    assert lines == [
        "downstream: consumer-app: couldn't start: no run",
        "downstream: private-app: report-only: couldn't start: no run",
    ]


def test_s032_9_a_run_whose_run_name_lacks_the_id_is_never_found(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    unnamed = {**a_run(101, CONSUMER_ID), "display_title": "Tests against the library"}
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [unnamed])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)
    assert library.check("consumer-app").title == "couldn't start: no run"
    assert library.check("private-app").title == "report-only: passed"


def test_s032_9_a_run_found_within_2_minutes_is_not_a_missing_one(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), []), (dt.timedelta(seconds=90), [a_run(101, CONSUMER_ID)])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    collected(library, api, key)
    assert library.check("consumer-app").title == "passed"


# S-032-10


def test_s032_10_the_summary_names_the_sha_links_the_run_and_lists_failed_jobs_without_logs(tmp_path: Path) -> None:
    library, api, key = started(tmp_path)
    api.timelines[CONSUMER_RUNS] = [(dt.timedelta(), [a_run(101, CONSUMER_ID, conclusion="failure")])]
    api.timelines[PRIVATE_RUNS] = [(dt.timedelta(), [a_run(202, PRIVATE_ID)])]
    api.jobs[101] = [
        {"name": "lint", "conclusion": "success", "steps": [{"name": LOG_LINE}]},
        {"name": "tests (3.14)", "conclusion": "failure"},
        {"name": "e2e", "conclusion": "timed_out"},
        {"name": "docs", "conclusion": "skipped"},
        {"name": "deploy", "conclusion": None},
    ]
    collected(library, api, key)

    summary = library.check("consumer-app").summary
    assert SHA in summary and f"Tested {LIBRARY} at {SHA}" in summary
    assert CONSUMER_RUN in summary
    assert "Failed jobs:\n- `tests (3.14)`\n- `e2e`" in summary
    assert "lint" not in summary and "docs" not in summary and "deploy" not in summary
    assert LOG_LINE not in summary
    assert not any("log" in path for path in api.read)  # no log is ever fetched
    assert "Failed jobs: none" in library.check("private-app").summary
    assert PRIVATE_RUN in library.check("private-app").summary


def test_s032_10_a_job_name_shows_on_one_line_without_a_backtick() -> None:
    assert job_name("tests`\n## injected\r\n`") == "tests ## injected"
    assert len(job_name("x" * 300)) == 100


# GhLibrary reads a check back

FAKE_GH = """\
import json, sys
print(json.dumps({"total_count": 2, "check_runs": [
    {"id": 5, "name": "downstream: consumer-app", "app": {"slug": "github-actions"}, "status": "completed",
     "conclusion": "success", "external_id": "old", "details_url": None,
     "output": {"title": "passed", "summary": None}},
    {"id": 7, "name": "downstream: consumer-app", "app": {"slug": "github-actions"}, "status": "in_progress",
     "conclusion": None, "external_id": "x 1", "details_url": "https://example.test/7",
     "output": {"title": "running", "summary": "Testing"}},
]}))
"""


def test_gh_library_reads_the_newest_check_back(tmp_path: Path) -> None:
    script = tmp_path / "fake_gh.py"
    script.write_text(FAKE_GH, encoding="utf-8")
    gh = tmp_path / "gh"
    gh.write_text(f'#!/bin/sh\nexec {sys.executable} {script} "$@"\n', encoding="utf-8")
    gh.chmod(0o755)
    written = GhLibrary(tmp_path, str(gh)).read_check(SHA, "downstream: consumer-app")
    assert written is not None and written.id == 7
    assert written.check == Check(
        "downstream: consumer-app", Status.IN_PROGRESS, None, "running", "Testing", "x 1", "https://example.test/7"
    )
