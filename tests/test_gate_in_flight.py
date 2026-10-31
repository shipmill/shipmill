"""Spec 048: a QUIET tick says what is in flight, from the change check's one query and the
state directory alone (#818). The change check runs against the fake GraphQL and REST readers
of test_gate_walk, which record every call"""

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill.agents import Mode
from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.gate import (
    LAST_RESULT,
    RECORD,
    TICK,
    Action,
    InFlight,
    LastResult,
    Launch,
    Process,
    Session,
    TickRecord,
    load_tick,
    save_launch,
    save_tick,
    state_dir,
    tick_lines,
    tick_record,
)
from shipmill.gitrepo import Git
from shipmill.walk import CURSOR_OVERLAP, Changes, Flight, Landed, check, item_key

from .test_gate import FakeClaude, checkout
from .test_gate_headless import PID, STARTED, log_of
from .test_gate_walk import (
    INCIDENT,
    LATER,
    NOW,
    ONE,
    REPO,
    Gh,
    Source,
    cfg,
    changed,
    graphql_answer,
    pull,
    runs,
    tick,
)

__all__ = ["checkout"]  # the fixture, imported for the tests below

WORKFLOWS = ("release.yml",)
MERGED = "2026-10-27T09:00:00Z"  # 3 h before NOW
OLDER = "2026-10-26T09:00:00Z"
NONE_LINE = (
    "in flight: no open pull request; no landed pull request in the last 10 commits;"
    " no session has ended with a result yet"
)


@dataclass
class Checked(Source):
    """test_gate_walk's logging state read, its change check the real one, against a Gh that
    records its calls"""

    gh: Gh = field(default_factory=lambda: Gh([], runs()))

    def changes(self, since: dt.datetime | None) -> Changes:
        self.reads.append("changes")
        return check(REPO, since, "incident", WORKFLOWS, self.gh.graphql, self.gh.read, NOW)


def answering(answer: dict[str, Any], ticks: int = 1, tiers: dict[int, list[Finding]] | None = None) -> Checked:
    """A read whose change check answers ticks times with answer; tiers, each tier's rows"""
    answers = [json.loads(json.dumps(answer)) for _ in range(ticks)]
    return Checked(tiers=tiers or {}, gh=Gh(answers, runs((1, "release.yml", "success"))))


INCIDENTS = {1: [INCIDENT]}  # tier 1 holds an incident: the walk launches


def in_flight_answer() -> dict[str, Any]:
    pulls = [pull(771, rollup="PENDING"), pull(772), pull(773, rollup="EXPECTED"), pull(774, rollup="FAILURE")]
    return graphql_answer(pulls=pulls, landed=[(770, MERGED), (768, OLDER)])


# -- S-048-21: the change check's query


def test_s048_21_the_change_check_reads_the_last_10_commits_merged_pull_requests_in_one_query() -> None:
    gh = Gh([graphql_answer(landed=[(765, OLDER), (770, MERGED), (771, None)])], runs())
    found = check(REPO, NOW, "incident", (), gh.graphql, gh.read, NOW)
    assert len(gh.queries) == 1
    assert "history(first: 10)" in gh.queries[0] and "associatedPullRequests(first: 1)" in gh.queries[0]
    assert "mergedAt" in gh.queries[0]
    assert found.flight is not None and found.flight.landed == Landed(770, dt.datetime.fromisoformat(MERGED))


def test_s048_21_a_change_to_the_commits_alone_leaves_the_signature_as_it_was() -> None:
    before = changed(graphql_answer(pulls=[pull(3)]))
    after = changed(graphql_answer(pulls=[pull(3)], landed=[(770, MERGED), (768, OLDER)]))
    assert after.signature == before.signature
    # the signature the change check gave this answer before spec 048: a cursor written then still matches
    assert before.signature == "7a1b401959bd01be"


def test_s048_21_a_later_page_asks_for_no_history() -> None:
    from shipmill.walk import change_query

    assert "history" not in change_query(("pulls",), {"pulls": "c1"}, first=False)


@pytest.mark.parametrize(
    "commit",
    [{"associatedPullRequests": None}, {"associatedPullRequests": {"nodes": [{"number": 7, "mergedAt": "soon"}]}}],
)
def test_s048_21_an_unreadable_commit_fails_the_check(commit: dict[str, Any]) -> None:
    answer = graphql_answer()
    answer["data"]["repository"]["defaultBranchRef"]["target"]["history"]["nodes"] = [commit]
    with pytest.raises(ReleaseError, match="for a commit of the default branch"):
        changed(answer)
    del answer["data"]["repository"]["defaultBranchRef"]["target"]["history"]
    with pytest.raises(ReleaseError, match="no history for the default branch"):
        changed(answer)


# -- S-048-22: the QUIET lines


def test_s048_22_open_pull_requests_group_by_their_heads_rollup() -> None:
    none_yet = pull(775)
    none_yet["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = None
    draft, fork = pull(776, rollup="FAILURE"), pull(777, rollup="FAILURE")
    draft["isDraft"], fork["isCrossRepository"] = True, True
    pulls = [*in_flight_answer()["data"]["repository"]["pulls"]["nodes"], pull(778, rollup="ERROR")]
    found = changed(graphql_answer(pulls=[*pulls, none_yet, draft, fork]))
    assert found.flight == Flight((771, 773, 775), (772,), (774, 778), None)
    with pytest.raises(ReleaseError, match="check rollup 'NEW'"):
        changed(graphql_answer(pulls=[pull(9, rollup="NEW")]))


def test_s048_22_the_line_reads_as_the_specs_example() -> None:
    result = LastResult("5f", "PRS_OPEN #770", NOW - dt.timedelta(hours=3))
    flight = InFlight((771, 773), (772,), (), Landed(770, NOW - dt.timedelta(hours=3)), result)
    assert flight.line(NOW) == (
        "in flight: 2 wait on CI (#771, #773), 1 waits to land (#772); last landed #770 3 h ago;"
        " last result: session 5f on PRS_OPEN #770, ended 3 h ago"
    )
    failing = InFlight((771,), (772, 773), (774,), None, None)
    assert failing.line(NOW).startswith(
        "in flight: 1 waits on CI (#771), 2 wait to land (#772, #773), 1 fails CI (#774);"
    )


def test_s048_22_each_part_has_its_wording_when_there_is_none() -> None:
    assert InFlight((), (), (), None, None).line(NOW) == NONE_LINE


def test_s048_22_both_quiet_lines_end_with_what_is_in_flight(checkout: Git) -> None:
    source = answering(in_flight_answer(), ticks=2)
    walked = tick(checkout, source)
    flight = (
        "in flight: 2 wait on CI (#771, #773), 1 waits to land (#772), 1 fails CI (#774);"
        " last landed #770 3 h ago; no session has ended with a result yet"
    )
    assert (walked.action, walked.reason) == (Action.QUIET, f"nothing needs an agent; read tiers 1-8; {flight}")
    quiet = tick(checkout, source, LATER)
    cursor = (NOW - CURSOR_OVERLAP).isoformat(timespec="minutes")
    assert quiet.reason == f"no change since {cursor}; {flight}"  # LATER is 15 minutes on: still 3 h
    assert tick_lines(quiet, None, (), (), dry_run=False) == [f"QUIET: no change since {cursor}; {flight}"]


def test_s048_22_a_tick_that_isnt_quiet_says_nothing_of_it(checkout: Git) -> None:
    decision = tick(checkout, answering(in_flight_answer(), tiers=INCIDENTS))
    assert decision.action is Action.LAUNCH and "in flight" not in decision.reason and decision.in_flight is None


# -- S-048-23: no read beyond the change check


def test_s048_23_a_quiet_tick_with_no_change_runs_no_read_beyond_the_change_check(checkout: Git) -> None:
    source = answering(in_flight_answer(), ticks=2)
    tick(checkout, source)
    source.reads.clear()
    source.gh.queries.clear()
    source.gh.paths.clear()
    quiet = tick(checkout, source, LATER)
    assert quiet.action is Action.QUIET and quiet.in_flight is not None
    assert source.reads == ["changes"]  # no tier, no sweep
    assert len(source.gh.queries) == 1  # the change check's one query
    assert source.gh.paths == [f"repos/{REPO}/actions/workflows/release.yml/runs?per_page=10"]


# -- S-048-24: last-result.json


def stream_log(git: Git, result: dict[str, Any] | None, seconds: int = 300) -> Path:
    """A headless launch of INCIDENT at NOW, its process gone, whose stream-json log ended
    seconds after it with result as its last event"""
    save_launch(
        state_dir(git) / RECORD,
        Launch(item_key(INCIDENT), str(ONE), NOW, Process(PID, STARTED), item=INCIDENT.brief()),
    )
    log = log_of(git, ONE)
    log.parent.mkdir(parents=True, exist_ok=True)
    events = [{"type": "system", "subtype": "init"}, *([] if result is None else [{"type": "result", **result}])]
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    os.utime(log, (NOW.timestamp() + seconds, NOW.timestamp() + seconds))
    return log


def last_result(git: Git) -> Any:
    return json.loads((state_dir(git) / LAST_RESULT).read_text(encoding="utf-8"))


def test_s048_24_the_first_tick_after_a_result_writes_last_result_json(checkout: Git) -> None:
    stream_log(checkout, {"is_error": False, "result": "landed #770"})
    at = NOW + dt.timedelta(seconds=300)
    source = answering(graphql_answer(), ticks=2)
    quiet = tick(checkout, source, LATER, cfg(Mode.HEADLESS))
    assert last_result(checkout) == {"session": str(ONE), "item": "INCIDENT_OPEN #9", "at": at.isoformat()}
    assert quiet.in_flight is not None and quiet.in_flight.result == LastResult(str(ONE), "INCIDENT_OPEN #9", at)
    assert quiet.reason.endswith(f"; last result: session {ONE} on INCIDENT_OPEN #9, ended 10 min ago")
    # a later tick finds it recorded and writes nothing
    (state_dir(checkout) / LAST_RESULT).write_text(
        json.dumps({"session": str(ONE), "item": "INCIDENT_OPEN #9", "at": NOW.isoformat()}), encoding="utf-8"
    )
    tick(checkout, source, LATER + dt.timedelta(minutes=15), cfg(Mode.HEADLESS))
    assert last_result(checkout)["at"] == NOW.isoformat()


@pytest.mark.parametrize(
    ("result", "seconds"),
    [(None, 5), ({"is_error": True, "result": "API Error"}, 300), (None, 300)],
    ids=["dead", "an error result", "no result"],
)
def test_s048_24_a_session_without_a_result_writes_none(
    checkout: Git, result: dict[str, Any] | None, seconds: int
) -> None:
    stream_log(checkout, result, seconds)
    quiet = tick(checkout, answering(graphql_answer(), ticks=2), LATER, cfg(Mode.HEADLESS, sweep_hours=48))
    assert not (state_dir(checkout) / LAST_RESULT).exists()
    assert quiet.in_flight is None or quiet.in_flight.result is None


def test_s048_24_a_dead_session_with_a_result_writes_none(checkout: Git) -> None:
    stream_log(checkout, {"is_error": False, "result": "Failed to authenticate. Please run /login"})
    tick(checkout, answering(graphql_answer(), ticks=2), LATER, cfg(Mode.HEADLESS))
    assert not (state_dir(checkout) / LAST_RESULT).exists()


def test_s048_24_an_interactive_session_listed_done_ends_at_the_tick_that_saw_it(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, Launch(item_key(INCIDENT), "s1", NOW, item=INCIDENT.brief()))
    claude = FakeClaude(listed=[Session("s1", "x", None, "done")])
    tick(checkout, answering(graphql_answer()), LATER, claude=claude)
    assert last_result(checkout) == {"session": "s1", "item": "INCIDENT_OPEN #9", "at": LATER.isoformat()}


def test_s048_24_an_interactive_session_done_within_dead_within_writes_none(checkout: Git) -> None:
    save_launch(state_dir(checkout) / RECORD, Launch(item_key(INCIDENT), "s1", NOW, item=INCIDENT.brief()))
    claude = FakeClaude(listed=[Session("s1", "x", None, "done")])
    tick(checkout, answering(graphql_answer()), NOW + dt.timedelta(seconds=30), claude=claude)
    assert not (state_dir(checkout) / LAST_RESULT).exists()


def test_s048_24_a_dry_run_writes_no_last_result_json(checkout: Git) -> None:
    stream_log(checkout, {"is_error": False, "result": "done"})
    quiet = tick(checkout, answering(graphql_answer()), LATER, cfg(Mode.HEADLESS), dry_run=True)
    assert not (state_dir(checkout) / LAST_RESULT).exists()
    assert quiet.in_flight is not None and quiet.in_flight.result is not None  # it still says so


def test_s048_24_a_malformed_last_result_json_fails_the_tick_before_it_acts(checkout: Git) -> None:
    path = state_dir(checkout) / LAST_RESULT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"session": "s1"}\n', encoding="utf-8")
    claude = FakeClaude()
    with pytest.raises(ReleaseError, match="last-result.json is malformed .*; delete it to start over") as raised:
        tick(checkout, answering(graphql_answer(), tiers=INCIDENTS), claude=claude)
    assert raised.value.fix == f"rm {path}"
    assert (claude.launched, claude.started) == ([], [])
    assert path.read_text(encoding="utf-8") == '{"session": "s1"}\n'


# -- S-048-25: --json and tick.json


def test_s048_25_json_prints_in_flight_on_quiet_and_null_otherwise(checkout: Git) -> None:
    quiet = tick(checkout, answering(in_flight_answer()))
    assert tick_record(quiet, None, (), (), dry_run=False)["in_flight"] == {
        "ci": [771, 773],
        "landing": [772],
        "failing": [774],
        "landed": {"number": 770, "at": dt.datetime.fromisoformat(MERGED).isoformat()},
        "result": None,
        "with_person": [],
    }
    written = json.loads((state_dir(checkout) / TICK).read_text(encoding="utf-8"))
    assert written["in_flight"] == tick_record(quiet, None, (), (), dry_run=False)["in_flight"]
    launch = tick(checkout, answering(in_flight_answer(), tiers=INCIDENTS), LATER, walk_now=True)
    assert launch.action is Action.LAUNCH and tick_record(launch, "s1", (), (), dry_run=False)["in_flight"] is None
    assert json.loads((state_dir(checkout) / TICK).read_text(encoding="utf-8"))["in_flight"] is None


def test_s048_25_tick_json_round_trips_in_flight(tmp_path: Path) -> None:
    result = LastResult("s1", "INCIDENT_OPEN #9", NOW)
    flight = InFlight((771,), (), (774,), Landed(770, NOW), result)
    record = TickRecord(NOW, "QUIET", "no change since x; in flight: ...", None, None, None, flight)
    path = tmp_path / TICK
    save_tick(path, record)
    assert load_tick(path) == record
    data = json.loads(path.read_text(encoding="utf-8"))
    data["in_flight"]["ci"] = ["#771"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReleaseError, match=r"tick\.json is malformed \(in_flight\.ci must be a pull request number\)"):
        load_tick(path)


# -- #853: a person's pull request waits on that person, not to land


def held(number: int, *logins: str, label: str = "role:maintainer") -> dict[str, Any]:
    """An open pull request the maintainer holds for their own merge: labelled and assigned"""
    found: dict[str, Any] = pull(number)
    found["labels"]["nodes"] = [{"name": label}]
    found["assignees"]["nodes"] = [{"login": login} for login in logins]
    return found


def test_853_a_persons_pull_request_is_in_flight_as_waiting_on_them(checkout: Git) -> None:
    pulls = [pull(772), held(160, "romamo"), held(158, "romamo", label="Human"), held(161), held(159, "ann", "bo")]
    quiet = tick(checkout, answering(graphql_answer(pulls=pulls)))
    assert quiet.action is Action.QUIET  # watch_state.py's tier 3 prints no item for them (test_watch_tiers)
    assert quiet.reason.endswith(
        "in flight: 2 wait to land (#161, #772), 2 wait on @romamo (#158, #160), 1 waits on @ann @bo (#159);"
        " no landed pull request in the last 10 commits; no session has ended with a result yet"
    )
    found = changed(graphql_answer(pulls=pulls))
    assert found.flight is not None
    assert found.flight.with_person == ((158, ("romamo",)), (159, ("ann", "bo")), (160, ("romamo",)))
    assert 160 not in found.flight.landing and 161 in found.flight.landing  # labelled, no assignee: a session's
    assert prs_assignees(found) == {158: ["romamo"], 159: ["ann", "bo"], 160: ["romamo"], 161: [], 772: []}
    assert quiet.in_flight is not None and quiet.in_flight.record()["with_person"] == [
        {"number": 158, "assignees": ["romamo"]},
        {"number": 159, "assignees": ["ann", "bo"]},
        {"number": 160, "assignees": ["romamo"]},
    ]


def prs_assignees(changes: Changes) -> dict[int, list[str]]:
    """watch_state.py --known's pull requests' assignees, as gh pr list prints them"""
    found: list[dict[str, Any]] = json.loads(json.dumps(changes.known))["prs"]
    return {int(p["number"]): [a["login"] for a in p["assignees"]] for p in found}


def test_853_tick_json_round_trips_with_person_and_reads_one_written_before_it(tmp_path: Path) -> None:
    flight = InFlight((), (772,), (), None, None, ((160, ("romamo",)),))
    record = TickRecord(NOW, "QUIET", "no change since x; in flight: ...", None, None, None, flight)
    path = tmp_path / TICK
    save_tick(path, record)
    assert load_tick(path) == record
    assert flight.line(NOW).startswith("in flight: 1 waits to land (#772), 1 waits on @romamo (#160);")
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["in_flight"]["with_person"]  # a tick.json a shipmill before #853 wrote
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_tick(path)
    assert loaded is not None and loaded.in_flight == InFlight((), (772,), (), None, None)
    data["in_flight"]["with_person"] = [{"number": 160, "assignees": ["not a login"]}]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReleaseError, match=r"in_flight\.with_person\.assignees must be a list of logins"):
        load_tick(path)
