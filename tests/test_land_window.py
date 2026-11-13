"""Spec 056: the land window's config, `[land.window]`, and `shipmill window`"""

import datetime as dt
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from shipmill import land_window
from shipmill.cli import main
from shipmill.config import Table
from shipmill.doctor import doctor
from shipmill.errors import ReleaseError
from shipmill.land_window import LandWindow

from .conftest import POLICY, Repo
from .test_decide_cli import commit

WINDOW = """
[land.window]
timezone = "Asia/Nicosia"
open = ["Mon-Thu 10:00-18:00", "Fri 10:00-14:00"]
closed = ["12:00-12:30"]
labels = ["rollout:normal", "rollout:high"]
queued_label = "rollout:queued"
spacing_minutes = 30
bypass_labels = ["revert", "incident"]
"""
# Monday 2026-11-16, 11:00 in Nicosia (UTC+2 in November)
MONDAY = dt.datetime(2026, 11, 16, 9, 0, tzinfo=dt.UTC)


class FakeGraphql:
    """GitHub's GraphQL for last_held_merge: each label's merged pull requests, newest updated
    first, served MERGED_PAGE at a time; records each query"""

    def __init__(self, merged: Mapping[str, Sequence[dict[str, str]]] | None = None, default: str = "main") -> None:
        self.merged = merged or {}
        self.default = default
        self.queries: list[str] = []

    def graphql(self, query: str) -> Any:
        self.queries.append(query)
        repository: dict[str, Any] = {"defaultBranchRef": {"name": self.default}}
        for alias, label, after in re.findall(
            r'(l\d+): pullRequests\(states: MERGED, labels: \["([^"]*)"\], first: \d+(?:, after: "(\d+)")?', query
        ):
            nodes = list(self.merged.get(label, ()))
            start = int(after) if after else 0
            page = nodes[start : start + land_window.MERGED_PAGE]
            more = start + land_window.MERGED_PAGE < len(nodes)
            info = {"hasNextPage": more, "endCursor": str(start + land_window.MERGED_PAGE) if more else None}
            repository[alias] = {"pageInfo": info, "nodes": page}
        return {"data": {"repository": repository}}


def pr(merged: str, updated: str | None = None, base: str = "main") -> dict[str, str]:
    return {"mergedAt": merged, "updatedAt": updated or merged, "baseRefName": base}


def window(text: str) -> LandWindow:
    """The section's body parsed as the config reads it"""
    found = land_window.read(Table(tomllib.loads(text), "shipmill.toml"))
    assert found is not None
    return found


def run_window(
    repo: Repo, capsys: pytest.CaptureFixture[str], now: dt.datetime, github: FakeGraphql | None = None
) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "window", "--json"], graphql=lambda: github or FakeGraphql(), now=now) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


# -- S-056-1: the section is read strictly --------------------------------------------------


@pytest.mark.parametrize(
    ("body", "named"),
    [
        (WINDOW + "start = 1\n", r"\[land.window\]: unknown keys \['start'\]"),
        (WINDOW.replace('timezone = "Asia/Nicosia"\n', ""), r"\[land.window\]: timezone is required"),
        (re.sub(r"\nlabels = .*\n", "\n", WINDOW), r"\[land.window\]: labels is required"),
        (WINDOW.replace("Asia/Nicosia", "Mars/Olympus"), r"\[land.window\]: timezone 'Mars/Olympus' is not a known"),
        (WINDOW.replace("Fri 10:00-14:00", "Fri 10-14"), r"\[land.window\] open: an entry is '\[<days> \]HH:MM-HH:MM'"),
        (WINDOW.replace("12:00-12:30", "12:30-12:00"), r"\[land.window\] closed: .*doesn't end after it starts"),
        (WINDOW.replace("12:00-12:30", "12:00-25:00"), r"\[land.window\] closed: .*isn't a time of day"),
        (WINDOW.replace("Mon-Thu", "Mon-Funday"), r"\[land.window\] open: window 'Mon-Funday 10:00-18:00': days are"),
        (WINDOW.replace("spacing_minutes = 30", "spacing_minutes = -5"), r"spacing_minutes must be 0 or more"),
        (WINDOW.replace('"incident"', '"rollout:high"'), r"\['rollout:high'\] in both labels and bypass_labels"),
    ],
)
def test_s056_1_a_malformed_section_exits_2_naming_the_key_and_doctor_fails_with_it(
    repo: Repo, capsys: pytest.CaptureFixture[str], body: str, named: str
) -> None:
    commit(repo, POLICY + body)
    with pytest.raises(ReleaseError, match=named) as refused:
        main(["--repo", str(repo.root), "window", "--json"], graphql=FakeGraphql, now=MONDAY)
    assert capsys.readouterr().out == ""
    message = str(refused.value)
    [policy] = [c for c in doctor(repo.root, repo.github) if c.name == "policy"]
    assert policy.status == "FAIL"
    # the same message, after where each read the config: the ref, or the checkout's file
    assert policy.detail.partition("[land.window]")[1:] == message.partition("[land.window]")[1:]


def test_s056_1_a_well_formed_section_passes_doctor(repo: Repo) -> None:
    commit(repo, POLICY + WINDOW)
    [policy] = [c for c in doctor(repo.root, repo.github) if c.name == "policy"]
    assert policy.status == "PASS"


# -- S-056-2: open or closed at a moment, in the window's zone -----------------------------


def test_s056_2_window_json_reads_open_inside_an_open_entry_and_prints_closes(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + WINDOW)
    found = run_window(repo, capsys, MONDAY)
    assert found == {
        "configured": True,
        "timezone": "Asia/Nicosia",
        "open": True,
        "opens": None,
        "closes": "2026-11-16T12:00:00+02:00",  # the closed entry, read daily
        "labels": ["rollout:normal", "rollout:high"],
        "bypass_labels": ["revert", "incident"],
        "queued_label": "rollout:queued",
        "spacing_minutes": 30,
        "last_held_merge": None,
        "next_merge": "2026-11-16T11:00:00+02:00",
    }


@pytest.mark.parametrize(
    ("now", "opens"),
    [
        (dt.datetime(2026, 11, 16, 10, 10, tzinfo=dt.UTC), "2026-11-16T12:30:00+02:00"),  # inside closed
        (dt.datetime(2026, 11, 19, 18, 0, tzinfo=dt.UTC), "2026-11-20T10:00:00+02:00"),  # Thu 20:00, overnight
        (dt.datetime(2026, 11, 20, 13, 0, tzinfo=dt.UTC), "2026-11-23T10:00:00+02:00"),  # Fri 15:00, the week end
        (dt.datetime(2026, 11, 16, 16, 0, tzinfo=dt.UTC), "2026-11-17T10:00:00+02:00"),  # the end is not inside
    ],
)
def test_s056_2_window_json_reads_closed_outside_and_prints_opens(
    repo: Repo, capsys: pytest.CaptureFixture[str], now: dt.datetime, opens: str
) -> None:
    commit(repo, POLICY + WINDOW)
    found = run_window(repo, capsys, now)
    assert (found["open"], found["opens"], found["closes"]) == (False, opens, None)


def test_s056_2_the_start_is_inside() -> None:
    w = window(WINDOW)
    assert w.is_open(dt.datetime(2026, 11, 16, 8, 0, tzinfo=dt.UTC))  # Mon 10:00 Nicosia
    assert not w.is_open(dt.datetime(2026, 11, 16, 7, 59, 59, tzinfo=dt.UTC))


def test_s056_2_the_day_of_week_is_the_zones_not_utcs() -> None:
    w = window('[land.window]\ntimezone = "Asia/Nicosia"\nopen = ["Mon 00:00-02:00"]\nlabels = ["x"]\n')
    sunday_in_utc = dt.datetime(2026, 11, 15, 23, 30, tzinfo=dt.UTC)  # Monday 01:30 in Nicosia
    assert w.is_open(sunday_in_utc)
    assert w.state(sunday_in_utc).closes == dt.datetime(2026, 11, 16, 2, 0, tzinfo=w.zone)


def test_s056_2_an_entry_without_days_is_daily() -> None:
    w = window('[land.window]\ntimezone = "UTC"\nopen = ["09:00-17:00"]\nlabels = ["x"]\n')
    for day in range(16, 23):  # Monday to Sunday
        assert w.is_open(dt.datetime(2026, 11, day, 12, 0, tzinfo=dt.UTC))
        assert not w.is_open(dt.datetime(2026, 11, day, 18, 0, tzinfo=dt.UTC))


def test_s056_2_without_open_the_window_is_open_outside_closed() -> None:
    w = window('[land.window]\ntimezone = "UTC"\nclosed = ["08:00-08:30"]\nlabels = ["x"]\n')
    at = dt.datetime(2026, 11, 16, 7, 0, tzinfo=dt.UTC)
    assert w.state(at) == land_window.WindowState(True, None, at.replace(hour=8))
    inside = at.replace(hour=8, minute=10)
    assert w.state(inside) == land_window.WindowState(False, at.replace(hour=8, minute=30), None)
    always = window('[land.window]\ntimezone = "UTC"\nlabels = ["x"]\n')
    assert always.state(at) == land_window.WindowState(True, None, None)  # nothing ever closes it


def test_s056_2_a_window_across_midnight_is_two_entries_read_as_one() -> None:
    w = window('[land.window]\ntimezone = "UTC"\nopen = ["Fri 22:00-24:00", "Sat 00:00-02:00"]\nlabels = ["x"]\n')
    friday = dt.datetime(2026, 11, 20, 23, 0, tzinfo=dt.UTC)
    assert w.state(friday) == land_window.WindowState(True, None, dt.datetime(2026, 11, 21, 2, 0, tzinfo=dt.UTC))
    saturday = dt.datetime(2026, 11, 21, 3, 0, tzinfo=dt.UTC)
    assert w.state(saturday).opens == dt.datetime(2026, 11, 27, 22, 0, tzinfo=dt.UTC)


def test_s056_2_spring_forward_opens_when_the_clock_jumps_into_the_entry() -> None:
    # Berlin, 2026-03-29: 02:00 CET jumps to 03:00 CEST; 02:30 never shows on the clock
    w = window('[land.window]\ntimezone = "Europe/Berlin"\nopen = ["Sun 02:30-05:00"]\nlabels = ["x"]\n')
    before = dt.datetime(2026, 3, 29, 0, 30, tzinfo=dt.UTC)  # 01:30 CET
    state = w.state(before)
    assert not state.open
    assert state.opens == dt.datetime(2026, 3, 29, 1, 0, tzinfo=dt.UTC)  # 03:00 CEST
    assert w.state(state.opens).closes == dt.datetime(2026, 3, 29, 3, 0, tzinfo=dt.UTC)  # 05:00 CEST


def test_s056_2_fall_back_reads_the_repeated_hour_on_the_wall_clock() -> None:
    # Berlin, 2026-10-25: 03:00 CEST falls back to 02:00 CET; 02:00-02:30 shows twice
    w = window('[land.window]\ntimezone = "Europe/Berlin"\nclosed = ["02:00-02:30"]\nlabels = ["x"]\n')
    first = dt.datetime(2026, 10, 25, 0, 15, tzinfo=dt.UTC)  # 02:15 CEST
    assert w.state(first) == land_window.WindowState(False, dt.datetime(2026, 10, 25, 0, 30, tzinfo=dt.UTC), None)
    between = dt.datetime(2026, 10, 25, 0, 45, tzinfo=dt.UTC)  # 02:45 CEST
    assert w.state(between) == land_window.WindowState(True, None, dt.datetime(2026, 10, 25, 1, 0, tzinfo=dt.UTC))
    again = dt.datetime(2026, 10, 25, 1, 15, tzinfo=dt.UTC)  # 02:15 CET
    assert w.state(again) == land_window.WindowState(False, dt.datetime(2026, 10, 25, 1, 30, tzinfo=dt.UTC), None)


def test_s056_2_without_the_section_window_prints_configured_false_and_reads_no_github(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)

    def unread() -> FakeGraphql:
        raise AssertionError("GitHub should not be read without [land.window]")

    assert main(["--repo", str(repo.root), "window", "--json"], graphql=unread, now=MONDAY) == 0
    assert json.loads(capsys.readouterr().out) == {"configured": False}


def test_s056_2_window_reads_the_config_at_the_ref_never_the_working_tree(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    repo.write(repo.policy_file, POLICY + WINDOW)  # uncommitted: a change's own section isn't read
    assert run_window(repo, capsys, MONDAY) == {"configured": False}


def test_s056_2_the_text_form_prints_a_line_per_key(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + WINDOW)
    assert main(["--repo", str(repo.root), "window"], graphql=FakeGraphql, now=MONDAY) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == ["configured: true", "timezone: Asia/Nicosia", "open: true"]
    assert "labels: rollout:normal, rollout:high" in out and "opens: null" in out


# -- S-056-3: last_held_merge and next_merge ----------------------------------------------


def test_s056_3_next_merge_is_the_last_held_merge_plus_the_spacing(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + WINDOW)
    github = FakeGraphql(
        {
            "rollout:normal": [pr("2026-11-16T08:40:00Z"), pr("2026-11-16T08:00:00Z")],
            "rollout:high": [pr("2026-11-16T08:50:00Z", base="release/1.x"), pr("2026-11-15T08:00:00Z")],
        }
    )
    found = run_window(repo, capsys, MONDAY, github)
    assert found["last_held_merge"] == "2026-11-16T10:40:00+02:00"  # another base's merge isn't counted
    assert found["next_merge"] == "2026-11-16T11:10:00+02:00"
    assert len(github.queries) == 1  # every label in one read


def test_s056_3_next_merge_is_now_once_the_spacing_passed_or_is_0(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGraphql({"rollout:high": [pr("2026-11-16T08:00:00Z")]})
    commit(repo, POLICY + WINDOW)
    found = run_window(repo, capsys, MONDAY, github)
    assert (found["last_held_merge"], found["next_merge"]) == ("2026-11-16T10:00:00+02:00", "2026-11-16T11:00:00+02:00")
    commit(repo, POLICY + WINDOW.replace("spacing_minutes = 30", "spacing_minutes = 0"))
    github = FakeGraphql({"rollout:high": [pr("2026-11-16T08:59:00Z")]})
    found = run_window(repo, capsys, MONDAY, github)
    assert (found["last_held_merge"], found["next_merge"]) == ("2026-11-16T10:59:00+02:00", "2026-11-16T11:00:00+02:00")


def test_s056_3_a_label_reads_its_next_page_only_while_it_may_hold_a_newer_merge() -> None:
    # an old merge updated lately (a comment) fills a page; the newest merge is on the next one
    stale = [pr("2026-01-01T00:00:00Z", "2026-11-16T08:30:00Z")] * land_window.MERGED_PAGE
    github = FakeGraphql(
        {"a": [*stale, pr("2026-11-16T08:20:00Z"), pr("2026-11-01T00:00:00Z")], "b": [pr("2026-11-16T07:00:00Z")]}
    )
    assert land_window.last_held_merge(github, ["a", "b"]) == dt.datetime(2026, 11, 16, 8, 20, tzinfo=dt.UTC)
    assert len(github.queries) == 2
    assert "l0: pullRequests" in github.queries[1] and "l1:" not in github.queries[1]
    # a full page updated before the newest merge found is the end of the read
    older = [pr("2026-10-01T00:00:00Z")] * (land_window.MERGED_PAGE + 1)
    github = FakeGraphql({"a": [pr("2026-11-16T08:20:00Z")], "b": older})
    assert land_window.last_held_merge(github, ["a", "b"]) == dt.datetime(2026, 11, 16, 8, 20, tzinfo=dt.UTC)
    assert len(github.queries) == 1


def test_s056_3_reads_are_bounded_and_one_that_cant_tell_is_refused() -> None:
    stale = [pr("2026-01-01T00:00:00Z", "2026-11-16T08:30:00Z")] * (land_window.MERGED_PAGE * land_window.MERGED_PAGES)
    github = FakeGraphql({"a": [*stale, pr("2026-11-16T08:20:00Z")]})
    with pytest.raises(ReleaseError, match="can't tell the last held merge"):
        land_window.last_held_merge(github, ["a"])
    assert len(github.queries) == land_window.MERGED_PAGES


def test_s056_3_no_held_merge_reads_null_and_next_merge_now() -> None:
    w = window(WINDOW)
    assert land_window.last_held_merge(FakeGraphql(), w.labels) is None
    found = land_window.record(w, MONDAY, None)
    assert (found["last_held_merge"], found["next_merge"]) == (None, "2026-11-16T11:00:00+02:00")


@pytest.mark.parametrize(
    "answer",
    [
        {"errors": [{"message": "bad"}]},
        {"data": {"repository": None}},
        {"data": {"repository": {"defaultBranchRef": {"name": "main"}, "l0": {"nodes": []}}}},
        {"data": {"repository": {"defaultBranchRef": {"name": "main"}, "l0": {"pageInfo": {"hasNextPage": False},
         "nodes": [{"mergedAt": None, "updatedAt": "2026-11-16T08:00:00Z", "baseRefName": "main"}]}}}},
    ],
)  # fmt: skip
def test_s056_3_a_malformed_answer_is_refused(answer: dict[str, Any]) -> None:
    class Answer:
        def graphql(self, query: str) -> Any:
            return answer

    with pytest.raises(ReleaseError, match="gh api graphql printed"):
        land_window.last_held_merge(Answer(), ["a"])


def test_a_pull_request_is_held_by_a_label_and_let_through_by_a_bypass() -> None:
    w = window(WINDOW)
    assert w.held(["rollout:high", "docs"]) == ("rollout:high",)
    assert w.held(["rollout:high", "revert"]) == ()
    assert w.held(["docs"]) == ()
