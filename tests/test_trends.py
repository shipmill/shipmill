"""The github-ship-watch skill's drift report, trends.py (spec 078), over scripted runs and a
fake GraphQL runner"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_metrics import END, agent, day, ok, page, pull, release, review

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts"
SCRIPT = SCRIPTS / "trends.py"
CI = ".github/workflows/ci.yml"
RELEASE = ".github/workflows/release.yml"
LINT = ".github/workflows/lint.yml"
ON_DEFAULT = ("ci.yml", "release.yml", "lint.yml")


@pytest.fixture(scope="module")
def tr() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # trends imports metrics, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("trends", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses look their module up by name
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


@pytest.fixture(scope="module")
def mx(tr: ModuleType) -> ModuleType:
    return sys.modules[tr.Window.__module__]  # the metrics module trends reads


def at(days: float) -> dt.datetime:
    return END - dt.timedelta(days=days)


def stamp(moment: str) -> dt.datetime:
    return dt.datetime.fromisoformat(moment.replace("Z", "+00:00"))


def run(
    number: int,
    days: float,
    conclusion: str | None = "success",
    *,
    branch: str = "main",
    attempt: int = 1,
    path: str = CI,
    repo: str = "o/r",
    status: str = "completed",
) -> dict[str, Any]:
    """A workflow run as the Actions API lists it, with text an outsider may have written"""
    return {
        "id": number,
        "name": "Evil workflow name",
        "display_title": "Evil title",
        "path": path,
        "head_branch": branch,
        "head_repository": {"full_name": repo},
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "created_at": day(days),
        "html_url": f"https://github.com/o/r/actions/runs/{number}",
    }


class Runs:
    """Answers `gh api repos/o/r/actions/runs` from scripted runs, 100 a page; total gives the
    total_count GitHub would report for a created range, from its start, end, and real count"""

    def __init__(
        self,
        runs: list[dict[str, Any]],
        total: Callable[[dt.datetime, dt.datetime, int], int] | None = None,
        broken: bool = False,
    ) -> None:
        self.runs = runs
        self.total = total
        self.broken = broken
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if self.broken:
            return subprocess.CompletedProcess(args, 1, "", "HTTP 502: Bad Gateway")
        assert args[:4] == ["api", "-X", "GET", "repos/o/r/actions/runs"]
        start, end = (stamp(t) for t in next(a for a in args if a.startswith("created="))[8:].split(".."))
        number = int(next(a for a in args if a.startswith("page="))[5:])
        found = [r for r in self.runs if start <= stamp(r["created_at"]) <= end]
        total = len(found) if self.total is None else self.total(start, end, len(found))
        body = {"total_count": total, "workflow_runs": found[(number - 1) * 100 : number * 100]}
        return subprocess.CompletedProcess(args, 0, json.dumps(body), "")


def never(args: list[str]) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"no run should be read: {args}")


class Forge:
    """The GraphQL side: the default branch and its workflow files, and metrics.py's reads"""

    def __init__(self, tr: ModuleType, mx: ModuleType, pulls: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[str] = []
        self.answers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            tr.REPO: lambda v: ok(
                {
                    "defaultBranchRef": {"name": "main"},
                    "workflows": {"entries": [{"name": n, "type": "blob"} for n in ON_DEFAULT]},
                }
            ),
            mx.RELEASES: lambda v: ok(
                {"releases": page([release("v1.2.0", day(2)), release("v1.1.0", day(10)), release("v1.0.0", day(60))])}
            ),
            mx.COMPARE: self.compare,
            mx.LINE: lambda v: ok({"line": None}),
            mx.PULLS: lambda v: ok({"pullRequests": page(pulls or [])}),
            mx.DEPLOYMENTS: lambda v: ok({"deployments": page([], totalCount=0)}),
            mx.LABELLED: lambda v: ok({"issues": page([])}),
        }

    def compare(self, v: dict[str, Any]) -> dict[str, Any]:
        commits = {
            "refs/tags/v1.1.0": [{"oid": "m1", "committedDate": day(12)}, {"oid": "m2", "committedDate": day(11)}],
            "refs/tags/v1.2.0": [{"oid": "m3", "committedDate": day(3)}],
        }
        return ok({"base": {"compare": {"commits": page(commits[v["head"]])}}})

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(query)
        return self.answers[query](variables)


def config(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".github").mkdir(exist_ok=True)
    (tmp_path / ".github" / "shipmill.toml").write_text(f'name = "demo"\nmode = "off"\n{body}', encoding="utf-8")
    return tmp_path


def trends(tr: ModuleType, **kw: Any) -> Any:
    return tr.Trends(**{"series": ("ci_pass_rate",), "baseline": 4, **kw})


def middle(k: int, baseline: int = 4) -> float:
    """The middle of bucket k, oldest first, in days before END, for 7-day buckets"""
    return (baseline + 1 - k) * 7 - 3.5


# -- S-078-8: the config ---------------------------------------------------------------------------


def test_s078_8_trends_py_reads_the_section_and_its_defaults(tr: ModuleType, tmp_path: Path) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["ci_pass_rate", "lead_time"]\n')
    assert tr.read_trends(repo) == tr.Trends(("ci_pass_rate", "lead_time"), 7, 8, 1.0, 2.0)


@pytest.mark.parametrize(
    ("body", "refused"),
    [
        ("bucket_days = 7", "series is required"),
        ("series = []", "series must name at least one of"),
        ('series = ["ci_pass_rate", "uptime"]', "series holds ['uptime']"),
        ('series = ["lead_time"]\ncolour = 1', "unknown keys ['colour']"),
        ('series = ["lead_time"]\nbucket_days = 0', "bucket_days must be 1 or more, got 0"),
        ('series = ["lead_time"]\nbaseline = 3', "baseline must be 4 or more, got 3"),
        ('series = ["lead_time"]\nlog_sigma = 0', "log_sigma must be above 0, got 0.0"),
        ('series = ["lead_time"]\nlog_sigma = 1.5\nreport_sigma = 1.0', "report_sigma must be at least log_sigma"),
    ],
)
def test_s078_8_trends_py_refuses_a_bad_section_naming_the_key(
    tr: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str, refused: str
) -> None:
    repo = config(tmp_path, f"[trends]\n{body}\n")
    with pytest.raises(SystemExit) as exc:
        tr.read_trends(repo)
    assert exc.value.code == 2
    assert refused in capsys.readouterr().err


def test_s078_8_the_310_reading_takes_a_plain_table_and_refuses_another_form(
    tr: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        'name = "demo"\n[agents]\ntrends = 1\n[trends]\nseries = ["ci_pass_rate", "review_time"]  # two\n'
        "bucket_days = 3\nlog_sigma = 1.5\n"
    )
    raw = tr.plain_trends(text, "f")
    assert raw == {"series": ["ci_pass_rate", "review_time"], "bucket_days": 3, "log_sigma": 1.5}
    assert tr.trends_config(raw, "f") == tr.Trends(("ci_pass_rate", "review_time"), 3, 8, 1.5, 2.0)
    assert tr.plain_trends('name = "demo"\n', "f") is None
    for unreadable in ('[trends]\nseries = [\n  "lead_time",\n]\n', 'trends.series = ["lead_time"]\n'):
        with pytest.raises(SystemExit):
            tr.plain_trends(unreadable, "f")
        assert "can't read [trends] on Python 3.10" in capsys.readouterr().err


# -- S-078-9: the run series -----------------------------------------------------------------------


def test_s078_9_ci_pass_rate_and_flaky_reruns_count_the_bucket_s_runs(tr: ModuleType) -> None:
    w = tr.Window(at(7), END)
    runs = [
        run(1, 1),
        run(2, 2, "failure"),
        run(3, 3, "timed_out"),
        run(4, 4, "cancelled"),  # left out
        run(5, 5, None, status="in_progress"),  # unfinished: left out
        run(6, 1, "skipped"),  # left out
        run(7, 2, "failure", branch="feature"),  # not the default branch
        run(8, 2, "failure", repo="fork/r"),  # a fork's main is not the default branch
        run(9, 3, "success", branch="feature", attempt=2),  # green on a rerun, any branch
        run(10, 3, "success", attempt=3),  # green on a rerun, on main
        run(11, 3, "failure", attempt=2),  # a rerun that stayed red
        run(12, 9, "success", attempt=2),  # another bucket
    ]
    rate = tr.ci_pass_rate(runs, w, "o/r", "main")
    assert rate.value == pytest.approx(2 / 5)  # #1 and #10 of #1, #2, #3, #10, #11
    assert sorted(r["id"] for r in rate.runs) == [2, 3, 11]
    flaky = tr.flaky_reruns(runs, w)
    assert flaky.value == 2.0
    assert sorted(r["id"] for r in flaky.runs) == [9, 10]


def test_s078_9_a_bucket_without_counted_runs_has_no_value(tr: ModuleType) -> None:
    w = tr.Window(at(7), END)
    assert tr.ci_pass_rate([run(1, 1, "cancelled")], w, "o/r", "main").value is None
    assert tr.flaky_reruns([], w).value is None
    assert tr.flaky_reruns([run(1, 1)], w).value == 0.0


def test_s078_9_a_bucket_over_1000_runs_is_read_day_by_day(tr: ModuleType) -> None:
    runs = [run(i, 0.5 + i % 7, "failure" if i % 2 else "success") for i in range(1, 15)]
    big = Runs(runs, total=lambda s, e, n: 1500 if e - s > dt.timedelta(days=1) else n)
    found = tr.bucket_runs(big, "o/r", tr.Window(at(7), END))
    assert sorted(r["id"] for r in found) == list(range(1, 15))
    assert len(big.calls) == 1 + 7  # the bucket, then each day


# -- S-078-10: the pull request series -------------------------------------------------------------


def pulls() -> list[dict[str, Any]]:
    return [
        agent(1, merged=day(12), created=day(14), merge="m1", reviews=(review("APPROVED", day(13)),)),
        agent(2, merged=day(11), created=day(12.5), merge="m2", reviews=(review("APPROVED", day(12)),)),
        agent(3, merged=day(3), created=day(5), merge="m3", reviews=(review("CHANGES_REQUESTED", day(4)),)),
        pull(4, day(20), "m4"),  # a person's PR
    ]


def test_s078_10_review_and_lead_time_equal_metrics_py_for_each_bucket_as_its_window(
    tr: ModuleType, mx: ModuleType
) -> None:
    config = tr.Trends(("review_time", "lead_time"), 7, 4)
    found = {r.series: r for r in tr.reports("o/r", config, END, never, Forge(tr, mx, pulls()))}
    for k, window in enumerate(tr.buckets(config, END)):
        data = mx.fetch("o/r", window, frozenset(), "incident", "release-blocker", run=Forge(tr, mx, pulls()))
        assert found["review_time"].buckets[k].value == mx.review_time(data, window).value
        assert found["lead_time"].buckets[k].value == mx.lead_time(data, window).value
    assert [b.value for b in found["review_time"].buckets] == [None, None, None, pytest.approx(18.0), 24.0]
    assert [b.value for b in found["lead_time"].buckets] == [None, None, None, pytest.approx(78.0), 72.0]


def test_s078_10_the_pull_request_series_read_once_over_the_span(tr: ModuleType, mx: ModuleType) -> None:
    forge = Forge(tr, mx, pulls())
    tr.reports("o/r", tr.Trends(("review_time", "lead_time"), 7, 4), END, never, forge)
    assert forge.calls.count(mx.PULLS) == 1
    assert tr.REPO not in forge.calls  # no run series: no default branch or workflow read


# -- S-078-11 and S-078-12: the band ---------------------------------------------------------------


def buckets(tr: ModuleType, *values: float | None) -> list[Any]:
    return [tr.Bucket(tr.Window(at(i + 1), at(i)), v) for i, v in enumerate(values)]


@pytest.mark.parametrize(
    ("series", "newest", "tier", "deviation"),
    [
        ("review_time", 12.0, "ok", 0.0),
        ("review_time", 12.5, "ok", 0.5),
        ("review_time", 13.0, "log", 1.0),  # at log_sigma
        ("review_time", 13.9, "log", 1.9),  # 2.12 population σ would report it
        ("review_time", 14.0, "report", 2.0),  # at report_sigma
        ("review_time", -50.0, "ok", 0.0),  # better than the mean, however far
        ("ci_pass_rate", 9.0, "report", 3.0),  # lower is worse
        ("ci_pass_rate", 40.0, "ok", 0.0),
    ],
)
def test_s078_11_the_tier_is_the_worse_way_distance_in_sample_sigma(
    tr: ModuleType, series: str, newest: float, tier: str, deviation: float
) -> None:
    report = tr.band(series, buckets(tr, 11.0, 13.0, 11.0, 13.0, 12.0, newest), trends(tr, baseline=5))
    assert report.mean == pytest.approx(12.0)
    assert report.sigma == pytest.approx(1.0)  # sample; the population σ is 0.894
    assert (report.tier, report.deviation) == (tier, pytest.approx(deviation, abs=1e-3))


def test_s078_11_the_bands_are_the_configured_sigmas(tr: ModuleType) -> None:
    found = buckets(tr, 11.0, 13.0, 11.0, 13.0, 14.0)  # 1.73σ
    assert tr.band("lead_time", found, trends(tr)).tier == "log"
    assert tr.band("lead_time", found, trends(tr, log_sigma=0.5, report_sigma=1.5)).tier == "report"
    assert tr.band("lead_time", found, trends(tr, log_sigma=2.0, report_sigma=3.0)).tier == "ok"


def test_s078_12_no_data_for_a_newest_bucket_without_a_value_or_a_short_baseline(tr: ModuleType) -> None:
    assert tr.band("lead_time", buckets(tr, 1.0, 2.0, 3.0, 4.0, None), trends(tr)).tier == "no data"
    short = tr.band("lead_time", buckets(tr, 1.0, None, 3.0, 4.0, 90.0), trends(tr))
    assert (short.tier, short.counted) == ("no data", 3)
    # a longer baseline with 4 values is enough
    assert tr.band("lead_time", buckets(tr, 1.0, None, 3.0, 4.0, 2.0, 2.5), trends(tr, baseline=5)).tier == "ok"


def test_s078_12_a_flat_baseline_reports_a_worse_bucket_and_passes_an_equal_or_better_one(tr: ModuleType) -> None:
    worse = tr.band("flaky_reruns", buckets(tr, 2.0, 2.0, 2.0, 2.0, 3.0), trends(tr))
    assert (worse.tier, worse.flat, worse.deviation) == ("report", True, None)
    assert "deviation flat baseline" in tr.line(worse, trends(tr))
    for newest in (2.0, 0.0):
        same = tr.band("flaky_reruns", buckets(tr, 2.0, 2.0, 2.0, 2.0, newest), trends(tr))
        assert (same.tier, same.flat) == ("ok", False)
    rate = tr.band("ci_pass_rate", buckets(tr, 1.0, 1.0, 1.0, 1.0, 0.9), trends(tr))
    assert (rate.tier, rate.flat) == ("report", True)


# -- S-078-13 and S-078-14: the output -------------------------------------------------------------


def drifting() -> list[dict[str, Any]]:
    """A main that went red in the newest bucket, and a green newest bucket for reruns"""
    runs: list[dict[str, Any]] = []
    n = 0
    for k, passed in enumerate((9, 8, 9, 10)):
        for i in range(10):
            n += 1
            runs.append(run(n, middle(k) + i * 0.01, "success" if i < passed else "failure"))
        n += 1
        runs.append(run(n, middle(k), "success", branch="secret-branch", attempt=2 if k % 2 == 0 else 1))
    newest = [
        run(100, 3.1),
        run(101, 3.0),
        run(102, 2.9),
        run(103, 2.0, "failure"),
        run(104, 1.0, "failure"),  # ci.yml's newest failure
        run(105, 2.5, "timed_out", path=RELEASE),
        run(106, 2.4, "failure", path=LINT),
        run(107, 1.5, "failure", path=".github/workflows/evil.yml"),  # not on the default branch
        run(108, 1.4, "failure", path=".github/workflows/evil2.yml"),
        run(109, 1.3, "failure", path="dynamic/pages/pages-build-deployment"),
        run(110, 1.2, "success", branch="secret-branch"),
    ]
    return runs + newest


def test_s078_13_one_line_per_series_with_tier_values_and_a_diagnosis(
    tr: ModuleType, mx: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["ci_pass_rate", "flaky_reruns"]\nbaseline = 4\n')
    code = tr.main(["o/r", "--repo-dir", str(repo)], Runs(drifting()), Forge(tr, mx), END)
    assert code == 0
    rate, flaky = capsys.readouterr().out.splitlines()
    assert rate.startswith(
        "ci_pass_rate  report   newest 30.0%, mean 90.0%, σ 8.2%, deviation 7.3σ over 4 buckets of 7d: "
    )
    # up to 3 workflows, most failed first, the newest on a tie: the files off the default branch are one
    assert rate.endswith(
        ": (other workflow) 3 failed, newest https://github.com/o/r/actions/runs/109;"
        " .github/workflows/ci.yml 2 failed, newest https://github.com/o/r/actions/runs/104;"
        " .github/workflows/lint.yml 1 failed, newest https://github.com/o/r/actions/runs/106"
    )
    assert flaky.startswith("flaky_reruns  ok       newest 0.0, mean 0.5, σ 0.6, deviation 0.0σ over 4 buckets of 7d")
    assert ":" not in flaky.split("7d", 1)[1]  # no diagnosis for ok


def test_s078_13_json_gives_each_series_its_buckets_values(
    tr: ModuleType, mx: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["ci_pass_rate", "flaky_reruns"]\nbaseline = 4\n')
    assert tr.main(["o/r", "--repo-dir", str(repo), "--json"], Runs(drifting()), Forge(tr, mx), END) == 0
    found = json.loads(capsys.readouterr().out)
    rate, flaky = found["series"]
    assert (rate["series"], rate["tier"], rate["baseline_buckets"]) == ("ci_pass_rate", "report", 4)
    assert [b["value"] for b in rate["buckets"]] == [0.9, 0.8, 0.9, 1.0, 0.3]
    assert rate["buckets"][-1]["end"] == END.isoformat()
    assert rate["diagnosis"][1] == {"workflow": CI, "count": 2, "url": "https://github.com/o/r/actions/runs/104"}
    assert [b["value"] for b in flaky["buckets"]] == [1.0, 0.0, 1.0, 0.0, 0.0]
    assert flaky["diagnosis"] == []


def test_s078_13_a_pull_request_series_names_its_3_longest_by_number_and_hours(tr: ModuleType) -> None:
    found = buckets(tr, 10.0, 12.0, 10.0, 12.0, 40.0)
    found[-1].pulls = [(7, 20.0), (8, 60.0), (9, 40.0), (10, 5.0)]
    report = tr.band("review_time", found, trends(tr))
    report.diagnosis = tr.diagnose(report, frozenset())
    assert report.diagnosis == [
        {"number": 8, "hours": 60.0},
        {"number": 9, "hours": 40.0},
        {"number": 7, "hours": 20.0},
    ]
    assert tr.line(report, trends(tr)).endswith(": #8 60.0 h, #9 40.0 h, #7 20.0 h")


def test_s078_14_no_title_body_or_branch_name_is_printed(
    tr: ModuleType, mx: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["ci_pass_rate", "flaky_reruns"]\nbaseline = 4\n')
    for form in ([], ["--json"]):
        tr.main(["o/r", "--repo-dir", str(repo), *form], Runs(drifting()), Forge(tr, mx), END)
        out = capsys.readouterr().out
        assert "(other workflow)" in out
        for text in ("Evil", "secret-branch", "evil.yml", "dynamic/pages"):
            assert text not in out


def test_s078_14_a_workflow_is_named_by_its_path_only_when_on_the_default_branch(tr: ModuleType) -> None:
    files = frozenset({CI})
    assert tr.workflow_name(run(1, 1), files) == CI
    assert tr.workflow_name(run(1, 1, path=CI + "@refs/heads/main"), files) == CI
    assert tr.workflow_name(run(1, 1, path=RELEASE), files) == "(other workflow)"


# -- S-078-15: the exit codes ----------------------------------------------------------------------


def test_s078_15_exit_0_with_and_without_a_drift(
    tr: ModuleType, mx: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["flaky_reruns"]\nbaseline = 4\n')
    steady = [run(k, middle(k)) for k in range(5)]
    assert tr.main(["o/r", "--repo-dir", str(repo)], Runs(steady), Forge(tr, mx), END) == 0
    assert capsys.readouterr().out.startswith("flaky_reruns  ok ")
    assert tr.main(["o/r", "--repo-dir", str(repo)], Runs(drifting()), Forge(tr, mx), END) == 0


def test_s078_15_a_config_without_trends_exits_2_naming_the_fix_and_reads_nothing(
    tr: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, "")

    def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("no GitHub read without [trends]")

    with pytest.raises(SystemExit) as exc:
        tr.main(["o/r", "--repo-dir", str(repo)], never, graphql, END)
    assert exc.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "has no [trends] section: add a [trends] section with its series to .github/shipmill.toml" in err


def test_s078_15_a_failed_gh_read_exits_2_with_no_partial_report(
    tr: ModuleType, mx: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["flaky_reruns", "lead_time"]\nbaseline = 4\n')
    with pytest.raises(SystemExit) as exc:
        tr.main(["o/r", "--repo-dir", str(repo)], Runs([], broken=True), Forge(tr, mx), END)
    assert exc.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "HTTP 502: Bad Gateway; check `gh auth status`" in err


def test_s078_15_a_day_over_1000_runs_exits_2_naming_it(
    tr: ModuleType, mx: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = config(tmp_path, '[trends]\nseries = ["ci_pass_rate"]\nbaseline = 4\n')
    with pytest.raises(SystemExit) as exc:
        tr.main(["o/r", "--repo-dir", str(repo)], Runs([], total=lambda s, e, n: 1001), Forge(tr, mx), END)
    assert exc.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "more than 1,000 workflow runs created from 2026-08-27T00:00:00Z to 2026-08-28T00:00:00Z" in err
    assert "take ci_pass_rate and flaky_reruns out of [trends] series" in err
