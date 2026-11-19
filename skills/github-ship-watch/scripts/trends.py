#!/usr/bin/env python3
"""Compare a repo's CI and review series with their own recent past: the drift report (spec 078).

Usage: trends.py <owner/repo> --repo-dir <dir> [--until TIME] [--json]

Reads the [trends] section of <dir>/.github/shipmill.toml, the default branch's checkout as
watch_state.py reads it (tomllib on Python 3.11+, a plain [trends] table on 3.10):

  [trends]
  series = ["ci_pass_rate", "flaky_reruns", "review_time", "lead_time"]  # at least one
  bucket_days = 7     # default; at least 1
  baseline = 8        # default; at least 4: the buckets before the newest one
  log_sigma = 1.0     # default; above 0
  report_sigma = 2.0  # default; at least log_sigma

The newest bucket is the bucket_days days ending at --until (default now; a date is its
00:00 UTC, a time needs its offset), the baseline the `baseline` buckets before it. A bucket's
value:
  ci_pass_rate   workflow runs on the default branch created in it that concluded success /
                 those that concluded success, failure, or timed_out (lower is worse)
  flaky_reruns   workflow runs created in it, on any branch, with an attempt number above 1
                 that concluded success: green only on a rerun (higher is worse)
  review_time    the median Review time of the agent PRs merged in it, as metrics.py reads it
  lead_time      the median Lead time for changes of the PRs a stable release published in it
                 first shipped, as metrics.py reads it (both higher is worse; metrics.py's own
                 functions over one read, split by bucket)
Runs are read per bucket with the API's created filter; a bucket over the 1,000 runs the API
lists is read day by day, and a day still over exits 2.

Each series' tier, from the mean and sample standard deviation σ of the baseline buckets that
have a value, and the newest bucket's distance from the mean in the worse direction, in σ (a
better bucket is 0): "no data" when the newest bucket has no value or fewer than 4 baseline
buckets have one; "ok" below log_sigma; "log" from log_sigma; "report" from report_sigma. A
flat baseline (σ 0) reads "report" with "flat baseline" when the newest bucket is worse, else
"ok". A log or report line names the up to 3 workflows with the most failed (ci_pass_rate) or
rerun-green (flaky_reruns) runs in the newest bucket, each with its count and newest run's URL,
or the up to 3 pull requests with the longest time, by number and hours. A workflow is named
by its file's path when that file is on the default branch, else "(other workflow)"; no title,
body, or branch name is printed (D-16).

One line per series, or with --json one object per series with its buckets' values. Exit 0
with or without a drift, 2 on bad input, a config without [trends], a gh failure, or a day
with more than 1,000 runs, printing no partial report. Read-only. Needs the gh CLI,
authenticated. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import statistics
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metrics import (
    Runner,
    Window,
    fail,
    fetch,
    gh_graphql,
    lead_times,
    repository,
    review_times,
    span,
    timestamp,
    until,
)

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: a plain [trends] table is read with regexes instead
    tomllib = None  # type: ignore[assignment]

POLICY = Path(".github/shipmill.toml")
SERIES = ("ci_pass_rate", "flaky_reruns", "review_time", "lead_time")
LOWER_IS_WORSE = frozenset({"ci_pass_rate"})
RUN_SERIES = frozenset({"ci_pass_rate", "flaky_reruns"})
PULL_SERIES = frozenset({"review_time", "lead_time"})
KEYS = ("series", "bucket_days", "baseline", "log_sigma", "report_sigma")
MIN_BASELINE = 4
LISTED = 1000  # the most runs the API lists for one filtered query
PER_PAGE = 100
SHOWN = 3  # workflows or pull requests a diagnosis names
FAILED = frozenset({"failure", "timed_out"})
COUNTED = frozenset({"success", *FAILED})
OTHER = "(other workflow)"
NO_DATA, OK, LOG, REPORT = "no data", "ok", "log", "report"
FLAT = "flat baseline"
GH_FIX = "; check `gh auth status` and the repo's name, then run trends.py again"
REPO = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { name }
    workflows: object(expression: "HEAD:.github/workflows") { ... on Tree { entries { name type } } }
  }
}
"""

# Runs one command (gh's arguments after "gh") and returns its finished process
Command = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


# -- the config --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Trends:
    series: tuple[str, ...]
    bucket_days: int = 7
    baseline: int = 8
    log_sigma: float = 1.0
    report_sigma: float = 2.0


def trends_config(raw: Any, where: str) -> Trends:
    """[trends] read strictly, as shipmill's config.py reads it: each refusal names its key"""
    if not isinstance(raw, dict):
        fail(f"{where}: trends must be a table")
    if unknown := sorted(set(raw) - set(KEYS)):
        fail(f"{where} [trends]: unknown keys {unknown}; allowed: {sorted(KEYS)}")
    if "series" not in raw:
        fail(f"{where} [trends]: series is required")
    names = raw["series"]
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        fail(f"{where} [trends]: series must be a list of non-empty strings")
    if not names:
        fail(f"{where} [trends]: series must name at least one of {list(SERIES)}")
    if unknown := sorted(set(names) - set(SERIES)):
        fail(f"{where} [trends]: series holds {unknown}, outside {list(SERIES)}")
    if len(set(names)) != len(names):
        fail(f"{where} [trends]: series names a series twice")
    bucket_days = integer(raw, "bucket_days", Trends.bucket_days, 1, where)
    baseline = integer(raw, "baseline", Trends.baseline, MIN_BASELINE, where)
    log_sigma = number(raw, "log_sigma", Trends.log_sigma, where)
    if log_sigma <= 0:
        fail(f"{where} [trends]: log_sigma must be above 0, got {log_sigma}")
    report_sigma = number(raw, "report_sigma", Trends.report_sigma, where)
    if report_sigma < log_sigma:
        fail(f"{where} [trends]: report_sigma must be at least log_sigma ({log_sigma}), got {report_sigma}")
    return Trends(tuple(names), bucket_days, baseline, log_sigma, report_sigma)


def integer(raw: dict[str, Any], key: str, default: int, low: int, where: str) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        fail(f"{where} [trends]: {key} must be an integer, got {value!r}")
    if value < low:
        fail(f"{where} [trends]: {key} must be {low} or more, got {value}")
    return value


def number(raw: dict[str, Any], key: str, default: float, where: str) -> float:
    value = raw.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        fail(f"{where} [trends]: {key} must be a number, got {value!r}")
    return float(value)


HEADER = re.compile(r"^\s*(\[\[?)\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$")
PLAIN_KEY = re.compile(r"^\s*([A-Za-z_]+)\s*=\s*(.*?)\s*(?:#[^\"\]]*)?$")
PLAIN_LIST = re.compile(r'^\[\s*(?:"[^"\\]*"\s*(?:,\s*"[^"\\]*"\s*)*,?\s*)?\]$')
PLAIN_INT = re.compile(r"^[+-]?\d+$")
PLAIN_FLOAT = re.compile(r"^[+-]?\d+\.\d+$")


def plain_trends(text: str, where: str) -> dict[str, Any] | None:
    """Python 3.10's reading: a plain [trends] table whose series is on one line and whose
    numbers are plain; None without the table. Any other form is refused, never misread"""
    unreadable = (
        f"{where}: can't read [trends] on Python 3.10: use 3.11+, or a plain [trends] table with series on one line"
    )
    found: dict[str, Any] | None = None
    inside = False
    top = True  # before the first header: a root key there could be a dotted trends key
    for line in text.splitlines():
        header = HEADER.match(line)
        if header is not None:
            top = False
            name = ".".join(p.strip().strip("\"'") for p in header.group(2).split("."))
            if name.startswith("trends."):
                fail(unreadable)
            inside = header.group(1) == "[" and name == "trends"
            if inside:
                if found is not None:
                    fail(f"{where}: [trends] appears twice")
                found = {}
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if top and re.match(r"^[\"']?trends[\"']?\s*[.=]", stripped):
            fail(unreadable)
        if not inside or found is None:
            continue
        key = PLAIN_KEY.match(line)
        if key is None:
            fail(unreadable)
        value = key.group(2)
        if PLAIN_LIST.match(value):
            found[key.group(1)] = re.findall(r'"([^"\\]*)"', value)
        elif PLAIN_INT.match(value):
            found[key.group(1)] = int(value)
        elif PLAIN_FLOAT.match(value):
            found[key.group(1)] = float(value)
        elif value in ("true", "false"):
            found[key.group(1)] = value == "true"
        else:
            fail(unreadable)
    return found


def read_trends(repo_dir: Path) -> Trends:
    """The checkout's [trends]; a config without it exits 2 naming the fix"""
    path = repo_dir / POLICY
    where = str(path)
    fix = (
        f"add a [trends] section with its series to {POLICY} on the default branch"
        ' (series = ["ci_pass_rate", "flaky_reruns", "review_time", "lead_time"], spec 078)'
    )
    if not path.is_file():
        fail(f"no {where}: {fix}")
    text = path.read_text(encoding="utf-8")
    if tomllib is None:
        raw = plain_trends(text, where)
    else:
        try:
            raw = tomllib.loads(text).get("trends")
        except tomllib.TOMLDecodeError as exc:
            fail(f"{where}: {exc}")
    if raw is None:
        fail(f"{where} has no [trends] section: {fix}")
    return trends_config(raw, where)


# -- the buckets -------------------------------------------------------------------------------


def buckets(trends: Trends, end: dt.datetime) -> list[Window]:
    """The baseline buckets, oldest first, then the newest one, which ends at end"""
    size = dt.timedelta(days=trends.bucket_days)
    count = trends.baseline + 1
    return [Window(end - size * (count - i), end - size * (count - i - 1)) for i in range(count)]


def iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017 (3.10)


def gh_json(command: Command, args: list[str]) -> Any:
    proc = command(args)
    if proc.returncode != 0:
        fail(f"gh {' '.join(args[:4])}: {proc.stderr.strip()}{GH_FIX}")
    try:
        return json.loads(proc.stdout)
    except ValueError:
        fail(f"gh {' '.join(args[:4])} printed no JSON{GH_FIX}")


def listed(command: Command, repo: str, window: Window) -> list[dict[str, Any]] | None:
    """Every workflow run created in the window (both ends included, as a metrics.py window),
    None when the API counts more than it lists"""
    created = f"created={iso(window.start)}..{iso(window.end)}"
    found: list[dict[str, Any]] = []
    page = 1
    while True:
        args = ["api", "-X", "GET", f"repos/{repo}/actions/runs", "-f", created, "-f", f"per_page={PER_PAGE}"]
        body = gh_json(command, [*args, "-f", f"page={page}"])
        if not isinstance(body, dict) or not isinstance(body.get("workflow_runs"), list):
            fail(f"gh api repos/{repo}/actions/runs returned no workflow_runs{GH_FIX}")
        total = body.get("total_count")
        if not isinstance(total, int):
            fail(f"gh api repos/{repo}/actions/runs returned no total_count{GH_FIX}")
        if total > LISTED:
            return None
        runs = body["workflow_runs"]
        found += runs
        if not runs or len(found) >= total or page * PER_PAGE >= LISTED:
            return found
        page += 1


def bucket_runs(command: Command, repo: str, window: Window) -> list[dict[str, Any]]:
    """The bucket's runs, read whole or, past what the API lists, day by day"""
    whole = listed(command, repo, window)
    if whole is not None:
        return whole
    seen: dict[Any, dict[str, Any]] = {}
    start = window.start
    while start < window.end:
        day = Window(start, min(start + dt.timedelta(days=1), window.end))
        runs = listed(command, repo, day)
        if runs is None:
            fail(
                f"{repo} has more than {LISTED:,} workflow runs created from {iso(day.start)} to {iso(day.end)},"
                f" more than GitHub lists for one query, so they can't be counted: take ci_pass_rate and"
                f" flaky_reruns out of [trends] series in {POLICY}"
            )
        for r in runs:
            seen[r.get("id")] = r  # the day ends overlap: a run on a boundary is listed twice
        start = day.end
    return list(seen.values())


@dataclass
class Bucket:
    window: Window
    value: float | None
    runs: list[dict[str, Any]] = field(default_factory=list)  # the runs it counted, for the diagnosis
    pulls: list[tuple[int, float]] = field(default_factory=list)  # (number, hours), for the diagnosis


def default_run(run: dict[str, Any], repo: str, branch: str) -> bool:
    head = (run.get("head_repository") or {}).get("full_name") or ""
    return run.get("head_branch") == branch and head.lower() == repo.lower()


def created_in(run: dict[str, Any], window: Window) -> bool:
    return timestamp(run["created_at"]) in window


def ci_pass_rate(runs: list[dict[str, Any]], window: Window, repo: str, branch: str) -> Bucket:
    counted = [
        r
        for r in runs
        if created_in(r, window)
        and default_run(r, repo, branch)
        and r.get("status") == "completed"
        and r.get("conclusion") in COUNTED
    ]
    passed = sum(r["conclusion"] == "success" for r in counted)
    failed = [r for r in counted if r["conclusion"] in FAILED]
    return Bucket(window, passed / len(counted) if counted else None, runs=failed)


def flaky_reruns(runs: list[dict[str, Any]], window: Window) -> Bucket:
    mine = [r for r in runs if created_in(r, window)]
    flaky = [r for r in mine if (r.get("run_attempt") or 1) > 1 and r.get("conclusion") == "success"]
    return Bucket(window, float(len(flaky)) if mine else None, runs=flaky)


def median_bucket(window: Window, found: list[tuple[int, float]]) -> Bucket:
    return Bucket(window, statistics.median(h for _, h in found) if found else None, pulls=found)


# -- the band ----------------------------------------------------------------------------------


@dataclass
class Report:
    series: str
    tier: str
    buckets: list[Bucket]
    mean: float | None = None
    sigma: float | None = None
    deviation: float | None = None  # in σ; None for no data or a flat baseline
    flat: bool = False
    counted: int = 0  # baseline buckets with a value
    diagnosis: list[dict[str, Any]] = field(default_factory=list)

    @property
    def newest(self) -> float | None:
        return self.buckets[-1].value


def band(series: str, found: list[Bucket], trends: Trends) -> Report:
    """The newest bucket against the baseline's mean and sample σ, in the series' worse direction"""
    values = [b.value for b in found[:-1] if b.value is not None]
    newest = found[-1].value
    report = Report(series, NO_DATA, found, counted=len(values))
    if len(values) < MIN_BASELINE:
        return report
    report.mean = statistics.mean(values)
    report.sigma = statistics.stdev(values)
    if newest is None:
        return report
    worse_by = report.mean - newest if series in LOWER_IS_WORSE else newest - report.mean
    if report.sigma == 0:
        report.flat = worse_by > 0
        report.tier = REPORT if report.flat else OK
        report.deviation = None if report.flat else 0.0
        return report
    report.deviation = max(worse_by, 0.0) / report.sigma
    report.tier = (
        REPORT if report.deviation >= trends.report_sigma else LOG if report.deviation >= trends.log_sigma else OK
    )
    return report


def workflow_name(run: dict[str, Any], files: frozenset[str]) -> str:
    path = str(run.get("path") or "").split("@", 1)[0]
    return path if path in files else OTHER


def diagnose(report: Report, files: frozenset[str]) -> list[dict[str, Any]]:
    """The newest bucket's up to 3 workflows by count, or pull requests by hours"""
    newest = report.buckets[-1]
    if report.series in PULL_SERIES:
        longest = sorted(newest.pulls, key=lambda p: (-p[1], p[0]))[:SHOWN]
        return [{"number": n, "hours": round(h, 1)} for n, h in longest]
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in newest.runs:
        groups.setdefault(workflow_name(r, files), []).append(r)
    ranked = []
    for name, runs in groups.items():
        latest = max(runs, key=lambda r: (timestamp(r["created_at"]), r.get("id") or 0))
        ranked.append({"workflow": name, "count": len(runs), "url": latest.get("html_url"), "at": latest["created_at"]})
    ranked.sort(key=lambda g: (-g["count"], -timestamp(g["at"]).timestamp(), g["workflow"]))
    return [{k: g[k] for k in ("workflow", "count", "url")} for g in ranked[:SHOWN]]


# -- the reads ---------------------------------------------------------------------------------


def reports(repo: str, trends: Trends, end: dt.datetime, command: Command, graphql: Runner) -> list[Report]:
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    windows = buckets(trends, end)
    series: dict[str, list[Bucket]] = {}
    files: frozenset[str] = frozenset()
    if RUN_SERIES & set(trends.series):
        held = repository(graphql, REPO, {"owner": owner, "name": name})
        if not held.get("defaultBranchRef"):
            fail(f"{repo} has no default branch")
        branch = held["defaultBranchRef"]["name"]
        entries = (held.get("workflows") or {}).get("entries") or []
        files = frozenset(f".github/workflows/{e['name']}" for e in entries if e.get("type") == "blob")
        runs = [bucket_runs(command, repo, w) for w in windows]
        series["ci_pass_rate"] = [ci_pass_rate(r, w, repo, branch) for r, w in zip(runs, windows, strict=True)]
        series["flaky_reruns"] = [flaky_reruns(r, w) for r, w in zip(runs, windows, strict=True)]
    if PULL_SERIES & set(trends.series):
        # one read over the whole span, split by bucket with metrics.py's own functions
        data = fetch(repo, Window(windows[0].start, end), frozenset(), "incident", "release-blocker", run=graphql)
        series["review_time"] = [median_bucket(w, review_times(data, w)) for w in windows]
        series["lead_time"] = [median_bucket(w, lead_times(data, w)) for w in windows]
    found = []
    for s in trends.series:
        report = band(s, series[s], trends)
        if report.tier in (LOG, REPORT):
            report.diagnosis = diagnose(report, files)
        found.append(report)
    return found


# -- the output --------------------------------------------------------------------------------


def shown(series: str, value: float | None) -> str:
    if value is None:
        return "none"
    if series == "ci_pass_rate":
        return f"{value * 100:.1f}%"
    if series == "flaky_reruns":
        return f"{value:.1f}"
    return span(value)


def deviation_text(report: Report) -> str:
    if report.flat:
        return FLAT
    return "none" if report.deviation is None else f"{report.deviation:.1f}σ"


def diagnosis_text(report: Report) -> str:
    if report.series in PULL_SERIES:
        return ", ".join(f"#{d['number']} {d['hours']:.1f} h" for d in report.diagnosis)
    what = "failed" if report.series == "ci_pass_rate" else "green on a rerun"
    return "; ".join(f"{d['workflow']} {d['count']} {what}, newest {d['url']}" for d in report.diagnosis)


def line(report: Report, trends: Trends) -> str:
    s = report.series
    text = (
        f"{s:<13} {report.tier:<8} newest {shown(s, report.newest)}, mean {shown(s, report.mean)},"
        f" σ {shown(s, report.sigma)}, deviation {deviation_text(report)}"
        f" over {report.counted} buckets of {trends.bucket_days}d"
    )
    return text + (f": {diagnosis_text(report)}" if report.diagnosis else "")


def as_json(repo: str, end: dt.datetime, trends: Trends, found: list[Report]) -> str:
    return json.dumps(
        {
            "repo": repo,
            "until": end.isoformat(),
            "bucket_days": trends.bucket_days,
            "baseline": trends.baseline,
            "log_sigma": trends.log_sigma,
            "report_sigma": trends.report_sigma,
            "series": [
                {
                    "series": r.series,
                    "tier": r.tier,
                    "newest": r.newest,
                    "mean": r.mean,
                    "sigma": r.sigma,
                    "deviation": r.deviation,
                    "flat_baseline": r.flat,
                    "baseline_buckets": r.counted,
                    "buckets": [
                        {"start": b.window.start.isoformat(), "end": b.window.end.isoformat(), "value": b.value}
                        for b in r.buckets
                    ],
                    "diagnosis": r.diagnosis,
                }
                for r in found
            ],
        },
        indent=2,
        sort_keys=True,
    )


def main(
    argv: Sequence[str] | None = None,
    command: Command = run_command,
    graphql: Runner = gh_graphql,
    now: dt.datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--repo-dir", type=Path, required=True, help="the repo's checkout, on its default branch")
    parser.add_argument("--until", help="the newest bucket's end: a date or a time with its offset (default now)")
    parser.add_argument("--json", action="store_true", help="one object per series with its buckets' values")
    args = parser.parse_args(argv)
    trends = read_trends(args.repo_dir)
    moment = (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)  # noqa: UP017 (3.10 has no dt.UTC)
    end = moment if args.until is None else until(args.until, moment)
    found = reports(args.repo, trends, end, command, graphql)  # every read before any output
    print(as_json(args.repo, end, trends, found) if args.json else "\n".join(line(r, trends) for r in found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
