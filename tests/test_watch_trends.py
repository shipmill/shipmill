"""The watch's DRIFT rows from trends.py (spec 078): the full report runs it for a config with
[trends] and reports each series at the report tier, never an action; no --tier or --sweep read
runs it. The reports run as subprocesses with a fake gh on PATH, the real trends.py reading it"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_watch_gate_idle import Host

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "github-ship-watch" / "scripts"
SCRIPT = SCRIPTS / "watch_state.py"
SKILL = ROOT / "skills" / "github-ship-watch" / "SKILL.md"
UTC = dt.timezone.utc  # noqa: UP017 (the script runs under 3.10 too)
RUN_URL = "https://github.com/o/r/actions/runs/{}"
CI = ".github/workflows/ci.yml"
TRENDS = 'mode = "off"\n\n[trends]\nseries = ["ci_pass_rate"]\nbucket_days = 1\nbaseline = 4\n'

# answers trends.py's reads (its repository query and the Actions runs), logs every call, and
# hands the rest to the full report's fake. The runs are made per bucket from its created
# range: bucket k days before now passes 10 of 10 runs when k is even, 9 of 10 when odd, and
# with FAKE_TRENDS=drift the newest passes 5 of 10; FAKE_TRENDS_FAIL fails the runs read
TRENDS_GH = """#!{python}
import datetime as dt, json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
joined = " ".join(args)
if args[:2] == ["api", "graphql"] and "workflows: object" in joined:
    entries = [{"name": "ci.yml", "type": "blob"}]
    repository = {"defaultBranchRef": {"name": "main"}, "workflows": {"entries": entries}}
    print(json.dumps({"data": {"repository": repository}}))
    sys.exit(0)
if args[:1] == ["api"] and any(a.endswith("/actions/runs") for a in args):
    if os.environ.get("FAKE_TRENDS_FAIL"):
        sys.stderr.write("gh: Not Found (HTTP 404)\\n")
        sys.exit(1)
    created = next(a for a in args if a.startswith("created="))[len("created="):]
    start, end = (dt.datetime.fromisoformat(t.replace("Z", "+00:00")) for t in created.split(".."))
    k = round((dt.datetime.now(dt.timezone.utc) - end) / dt.timedelta(days=1))
    failed = 5 if k == 0 and os.environ.get("FAKE_TRENDS") == "drift" else k % 2
    at = (start + dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = [
        {
            "id": i + 1,
            "name": "SECRET-NAME",
            "display_title": "SECRET-TITLE",
            "created_at": at,
            "head_branch": "main",
            "head_repository": {"full_name": "o/r"},
            "status": "completed",
            "conclusion": "failure" if i < failed else "success",
            "run_attempt": 1,
            "path": ".github/workflows/ci.yml",
            "html_url": "https://github.com/o/r/actions/runs/%d" % (i + 1),
        }
        for i in range(10)
    ]
    print(json.dumps({"total_count": len(runs), "workflow_runs": runs}))
    sys.exit(0)
sys.exit(subprocess.run([sys.executable, os.environ["FAKE_GH"], *args]).returncode)
"""


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_trends", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tr() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # trends imports metrics, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("trends_watch", SCRIPTS / "trends.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def trends_host(tmp_path: Path, config: str = TRENDS, mode: str = "drift") -> Host:
    """A checkout whose config is config, with trends.py's reads answered by TRENDS_GH"""
    host = Host(tmp_path)
    fakes = host.tmp / "fakes"
    (fakes / "gh-full").write_bytes((fakes / "gh").read_bytes())
    (fakes / "gh-full").chmod(0o700)
    (fakes / "gh").write_text(TRENDS_GH.replace("{python}", sys.executable), encoding="utf-8")
    (host.work / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    host.env |= {"FAKE_LOG": str(host.tmp / "gh.log"), "FAKE_GH": str(fakes / "gh-full"), "FAKE_TRENDS": mode}
    return host


def calls(host: Host) -> list[list[str]]:
    log = host.tmp / "gh.log"
    if not log.is_file():
        return []
    return [json.loads(c) for c in log.read_text(encoding="utf-8").splitlines()]


def trends_reads(host: Host) -> list[list[str]]:
    """trends.py's gh calls: its repository query and its runs reads, which nothing else makes"""
    return [
        c
        for c in calls(host)
        if any(a.endswith("/actions/runs") for a in c) or any("workflows: object" in a for a in c)
    ]


def rows(proc: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    assert proc.returncode in (0, 1), proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def series(
    name: str, tier: str, *, newest: float | None = 0.5, flat: bool = False, diagnosis: list[Any] | None = None
) -> dict[str, Any]:
    """One series of trends.py --json, as its as_json prints it"""
    return {
        "series": name,
        "tier": tier,
        "newest": newest,
        "mean": 0.95,
        "sigma": 0.0 if flat else 0.05,
        "deviation": None if flat else 9.0,
        "flat_baseline": flat,
        "baseline_buckets": 8,
        "buckets": [],
        "diagnosis": [] if diagnosis is None else diagnosis,
    }


def printed(*found: dict[str, Any], days: int = 7) -> str:
    return json.dumps({"repo": "o/r", "bucket_days": days, "baseline": 8, "series": list(found)})


# -- S-078-16: the full report's DRIFT rows --------------------------------------------------


def test_s078_16_one_drift_row_per_series_at_the_report_tier_and_none_below(ws: ModuleType, tmp_path: Path) -> None:
    failed = [
        {"workflow": CI, "count": 4, "url": RUN_URL.format(9)},
        {"workflow": "(other workflow)", "count": 1, "url": RUN_URL.format(3)},
    ]
    text = printed(
        series("ci_pass_rate", "report", diagnosis=failed),
        series("flaky_reruns", "log", newest=4.0),
        series("review_time", "ok", newest=3.0),
        series("lead_time", "no data", newest=None),
    )
    found = ws.drift_rows("o/r", tmp_path, text)
    assert len(found) == 1
    row = found[0]
    assert (row.state, row.subject) == ("DRIFT", "ci_pass_rate")
    assert row.detail == (
        f"50.0% against mean 95.0%, 9.0σ over 8 buckets of 7d: {CI} 4 failed, newest {RUN_URL.format(9)};"
        f" (other workflow) 1 failed, newest {RUN_URL.format(3)}"
    )
    assert row.fix == f"uv run --no-project python {SCRIPTS / 'trends.py'} o/r --repo-dir {tmp_path}"
    # reported, never an action and never an agent's
    assert not row.action and row.json()["agent"] is False and "DRIFT" not in ws.ACTION | ws.AGENT
    assert row.text().splitlines()[0].startswith("DRIFT          ci_pass_rate     50.0% against mean")


def test_s078_16_every_series_reads_as_trends_py_prints_it(ws: ModuleType, tr: ModuleType, tmp_path: Path) -> None:
    """The DRIFT detail from trends.py's own as_json, for a flat baseline and the pull series"""
    trends = tr.Trends(("ci_pass_rate", "flaky_reruns", "review_time", "lead_time"), 7, 4)
    window = tr.Window(dt.datetime(2026, 11, 1, tzinfo=UTC), dt.datetime(2026, 11, 8, tzinfo=UTC))
    flat = tr.Report("flaky_reruns", "report", [tr.Bucket(window, 3.0)], mean=0.0, sigma=0.0, flat=True, counted=4)
    flat.diagnosis = [{"workflow": CI, "count": 3, "url": RUN_URL.format(5)}]
    slow = tr.Report("review_time", "report", [tr.Bucket(window, 60.0)], 10.0, 2.0, 25.0, counted=4)
    slow.diagnosis = [{"number": 12, "hours": 80.0}, {"number": 7, "hours": 40.5}]
    lead = tr.Report("lead_time", "report", [tr.Bucket(window, 30.0)], 10.0, 5.0, 4.0, counted=4)
    text = tr.as_json("o/r", window.end, trends, [flat, slow, lead])
    found = {r.subject: r.detail for r in ws.drift_rows("o/r", tmp_path, text)}
    assert found == {
        "flaky_reruns": (
            f"3.0 against mean 0.0, flat baseline over 4 buckets of 7d: {CI} 3 green on a rerun,"
            f" newest {RUN_URL.format(5)}"
        ),
        "review_time": "2.5 d against mean 10.0 h, 25.0σ over 4 buckets of 7d: #12 80.0 h, #7 40.5 h",
        "lead_time": "30.0 h against mean 10.0 h, 4.0σ over 4 buckets of 7d",
    }


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"series": []}),  # no bucket_days
        printed(series("deploys", "report")),
        printed(series("ci_pass_rate", "drifting")),
        printed(series("ci_pass_rate", "report", newest=None)),
        printed(series("ci_pass_rate", "report", diagnosis=[{"workflow": CI, "count": "4", "url": "u"}])),
        printed(series("review_time", "report", diagnosis=[{"number": 4, "hours": 1.0, "title": "x"}])),
    ],
)
def test_s078_16_output_it_cant_read_stops_the_watch(ws: ModuleType, tmp_path: Path, bad: str) -> None:
    with pytest.raises(ws.Refused, match="trends.py printed"):
        ws.drift_rows("o/r", tmp_path, bad)


def test_s078_16_trends_py_runs_in_the_checkout_and_its_failure_exits_2(ws: ModuleType, tmp_path: Path) -> None:
    asked: list[tuple[list[str], Path | None]] = []

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        asked.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, 0, printed(series("ci_pass_rate", "ok")), "")

    assert ws.trends_rows("o/r", tmp_path, execute) == []
    assert asked == [
        ([sys.executable, str(SCRIPTS / "trends.py"), "o/r", "--repo-dir", str(tmp_path), "--json"], tmp_path)
    ]
    failing = subprocess.CompletedProcess([], 2, "", "error: gh api repos/o/r/actions/runs: boom")
    with pytest.raises(ws.Refused, match="trends.py failed with exit 2: error: gh api") as refused:
        ws.trends_rows("o/r", tmp_path, lambda cmd, cwd, env: failing)
    assert refused.value.code == 2


# proves: S-078-14
def test_s078_16_the_full_report_adds_the_drift_row_and_keeps_its_exit_code(tmp_path: Path) -> None:
    host = trends_host(tmp_path)
    drifting = host.watch("--no-host")
    found = [r for r in rows(drifting) if r["state"] == "DRIFT"]
    assert found == [
        {
            "state": "DRIFT",
            "subject": "ci_pass_rate",
            "detail": f"50.0% against mean 95.0%, 7.8σ over 4 buckets of 1d: {CI} 5 failed, newest {RUN_URL.format(5)}",
            "agent": False,
            "fix": f"uv run --no-project python {SCRIPTS / 'trends.py'} o/r --repo-dir {host.work}",
        }
    ]
    assert len(trends_reads(host)) == 6  # the repository query and the 5 buckets' runs
    assert "SECRET" not in drifting.stdout  # no run's name or title (S-078-14)
    # --no-trends makes no trends read and prints no DRIFT row; the exit code is the same
    (host.tmp / "gh.log").unlink()
    without = host.watch("--no-host", "--no-trends")
    assert not [r for r in rows(without) if r["state"] == "DRIFT"]
    assert trends_reads(host) == [] and without.returncode == drifting.returncode
    # the full report with the host's rows reads it too
    assert [r for r in rows(host.watch()) if r["state"] == "DRIFT"] == found


def test_s078_16_a_series_that_doesnt_drift_has_no_row(tmp_path: Path) -> None:
    host = trends_host(tmp_path, mode="steady")
    assert not [r for r in rows(host.watch("--no-host")) if r["state"] == "DRIFT"]
    assert len(trends_reads(host)) == 6


def test_s078_16_a_failing_trends_read_stops_the_watch_with_exit_2(tmp_path: Path) -> None:
    host = trends_host(tmp_path)
    host.env |= {"FAKE_TRENDS_FAIL": "1"}
    proc = host.watch("--no-host")
    assert proc.returncode == 2 and proc.stdout == ""
    assert "error: trends.py failed with exit 2" in proc.stderr and "HTTP 404" in proc.stderr


def test_s078_8_a_config_without_trends_makes_no_trends_read(tmp_path: Path) -> None:
    host = trends_host(tmp_path, config='mode = "off"\n')
    found = rows(host.watch("--no-host"))
    assert found and not [r for r in found if r["state"] == "DRIFT"]
    assert calls(host) and trends_reads(host) == []


@pytest.mark.parametrize(
    ("text", "configured"),
    [
        ('mode = "off"\n', False),
        ('mode = "off"\n[agents]\ntrends = 1\n', False),  # a key named trends in another table
        ("[trends_extra]\nx = 1\n", False),
        (TRENDS, True),
        ('[ "trends" ]\nseries = ["ci_pass_rate"]\n', True),
        ("[trends.x]\ny = 1\n", True),
        ("[[trends]]\ny = 1\n", True),
        ('trends.series = ["ci_pass_rate"]\n', True),
        ('trends = { series = ["ci_pass_rate"] }\n', True),
    ],
)
def test_s078_8_python_310_reads_a_trends_section_as_tomllib_does(ws: ModuleType, text: str, configured: bool) -> None:
    """Every form tomllib reads as a trends key runs trends.py on 3.10 too, which refuses the
    ones it can't read; any other config makes no trends read"""
    assert ws.trends_configured_310(text) is configured
    assert ws.trends_configured(text, Path("c.toml")) is configured  # tomllib, on this Python


# -- S-078-17: no gate read runs trends ------------------------------------------------------


@pytest.fixture(scope="module")
def gate_host(tmp_path_factory: pytest.TempPathFactory) -> Host:
    return trends_host(tmp_path_factory.mktemp("gate"))


@pytest.mark.parametrize("read", [["--tier", str(n)] for n in range(1, 8)] + [["--sweep"]], ids=lambda r: "".join(r))
def test_s078_17_no_tier_and_no_sweep_prints_a_drift_row_or_reads_trends(
    ws: ModuleType, gate_host: Host, read: list[str]
) -> None:
    assert sorted(ws.TIERS) == list(range(1, 8))  # every tier the gate walks
    log = gate_host.tmp / "gh.log"
    if log.is_file():
        log.unlink()
    found = rows(gate_host.watch(*read))
    assert not [r for r in found if r["state"] == "DRIFT"]
    assert trends_reads(gate_host) == []
    assert "DRIFT" not in {s for states in ws.TIERS.values() for s in states} | set(ws.SWEPT)


@pytest.mark.parametrize("read", [["--tier", "3"], ["--sweep"], ["--host", "sessions"]])
def test_s078_17_no_trends_goes_with_the_full_report_only(gate_host: Host, read: list[str]) -> None:
    proc = gate_host.watch(*read, "--no-trends")
    assert proc.returncode == 2 and "--no-trends goes with the full report" in proc.stderr


# -- S-078-18: the skill documents it --------------------------------------------------------


def section(text: str, heading: str) -> str:
    found = re.search(rf"^## {heading}\n(.*?)(?=^## )", text, re.MULTILINE | re.DOTALL)
    assert found is not None, heading
    return found.group(1)


def test_s078_18_skill_md_describes_the_measures_and_the_trends_section() -> None:
    text = SKILL.read_text(encoding="utf-8")
    metrics = section(text, "Metrics")
    for measure in ("Rework cycles", "First-pass merge rate", "Review time", "Plan match"):
        assert f"**{measure}**" in metrics
    trends = section(text, "Trends")
    for key in ("series", "bucket_days", "baseline", "log_sigma", "report_sigma"):
        assert re.search(rf"^{key} = ", trends, re.MULTILINE), key
    for name in ("ci_pass_rate", "flaky_reruns", "review_time", "lead_time"):
        assert f"- `{name}`: " in trends
    for tier in ("`no data`", "`ok`", "`log`", "`report`"):
        assert tier in trends
    assert "DRIFT <series> <newest> against mean <mean>, <deviation>σ over <N> buckets of <D>d: <diagnosis>" in trends
    assert "reported, never acted on" in trends and "D-58" in trends and "--no-trends" in trends
    assert re.search(r"^\| DRIFT \|.*Report only, never an agent's", text, re.MULTILINE)
