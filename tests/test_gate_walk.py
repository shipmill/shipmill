"""Spec 046: a gate tick checks for change first, then walks the work tiers to the next
untaken item. A fake source logs every read the tick makes; the change check runs against a
fake GraphQL and REST reader"""

import datetime as dt
import json
import os
import re
import tomllib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from shipmill.agents import AgentsConfig, Mode
from shipmill.autonomy import Autonomy, AutonomyPolicy, Hold
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.gate import (
    DECISIONS,
    RECORD,
    Action,
    Deaths,
    Decision,
    Launch,
    Process,
    StateRead,
    WatchState,
    gate,
    save_launch,
    state_dir,
    tick_lines,
    tick_record,
)
from shipmill.gitrepo import Git
from shipmill.land_window import LandWindow
from shipmill.land_window import read as read_window
from shipmill.walk import (
    CURSOR,
    CURSOR_OVERLAP,
    HANDED,
    SWEEP,
    Changes,
    Cursor,
    Hand,
    Handed,
    Swept,
    check,
    item_key,
    window_change,
)

from .test_gate import NO_PRUNE, FakeClaude, FakeNotifier, checkout, host
from .test_gate_headless import PID, STARTED, log_of

__all__ = ["checkout"]  # the fixture, imported for the tests below

NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.UTC)
LATER = NOW + dt.timedelta(minutes=15)
REPO = "romamo/demo"
INCIDENT = Finding("INCIDENT_OPEN", "#9", "staging is down; open 10 min, no PR links it", True, (), "resolve #9")
BOT_FAILED = Finding("BOT_FAILED", "release.yml", "failure: https://x.test/runs/5", True, (), "gh run rerun 5")
PRS = Finding("PRS_OPEN", REPO, "#3", False, ((3, "a" * 40),), None)
DECIDED = Finding("ISSUES", REPO, "DECIDED #4", True, (), "triage")
NEW = Finding("ISSUES", REPO, "NEW #5 #6", True, (), "triage")
NEEDS_PR = Finding("ISSUES", REPO, "NEEDS_PR #7", True, (), "triage")
STALLED = Finding("BOT_STALLED", "release.yml", "due and not running", True, (), "gh workflow run")
PLANS = Finding("PLANS", REPO, "PLAN_DUE G-1", True, (), "intake")
WAITING = Finding("NEEDS_DECISION", REPO, "#8", False, (), "answer")
ONE = uuid.UUID("11111111-1111-4111-8111-111111111111")


@dataclass
class Source:
    """A state read that logs each read: the change check answers with the signature, the
    updated items and the tag given; each tier and the sweep with their rows"""

    tiers: dict[int, list[Finding]] = field(default_factory=dict)
    swept: list[Finding] = field(default_factory=list)
    signature: str = "sig"
    updated: tuple[int, ...] = ()
    asked: bool = False
    tag: str | None = None
    reads: list[str] = field(default_factory=list)
    window: bool = False  # spec 056: the land window opened, or its spacing passed, with a queue

    def changes(self, since: dt.datetime | None) -> Changes:
        self.reads.append("changes")
        return Changes(self.signature, self.updated, self.asked, self.tag, window=self.window)

    def tier(self, number: int, changes: Changes) -> list[Finding]:
        self.reads.append(f"tier {number}")
        return list(self.tiers.get(number, []))

    def sweep(self, changes: Changes) -> list[Finding]:
        self.reads.append("sweep")
        return list(self.swept)


def cfg(mode: Mode = Mode.INTERACTIVE, land: Autonomy = Autonomy.PROPOSE, **keys: Any) -> AgentsConfig:
    return AgentsConfig(prompt="/t", prs=None, retry_hours=24, mode=mode, autonomy=AutonomyPolicy(land=land), **keys)


def tick(
    git: Git,
    source: Source,
    now: dt.datetime = NOW,
    agents: AgentsConfig | None = None,
    claude: FakeClaude | None = None,
    notifier: FakeNotifier | None = None,
    **flags: Any,
) -> Decision:
    decision, _, _, _ = gate(
        git,
        REPO,
        lambda: agents or cfg(),
        claude or FakeClaude(),
        lambda _: source,
        now,
        Hold,
        notifier or FakeNotifier(),
        NO_PRUNE,
        login=host,
        started=lambda pid: None,
        new_session=lambda: ONE,
        **flags,
    )
    return decision


def walked(git: Git, source: Source) -> Decision:
    """A tick after a first one: the cursor, the sweep, and handed.json are as it left them"""
    tick(git, source)
    source.reads.clear()
    return tick(git, source, LATER)


def handed(git: Git) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((state_dir(git) / HANDED).read_text())
    return found


# -- the change check


def test_s046_1_no_change_reads_nothing_more_and_is_quiet(checkout: Git) -> None:
    source = Source({1: [INCIDENT]}, signature="same")
    claude = FakeClaude()
    first = tick(checkout, source, claude=claude)
    assert first.action is Action.LAUNCH
    (state_dir(checkout) / RECORD).unlink()  # the session ended: no dead last session, no gate.json
    source.reads.clear()
    decision = tick(checkout, source, LATER, claude=claude)
    cursor = (NOW - CURSOR_OVERLAP).isoformat(timespec="minutes")
    assert (decision.action, decision.reason) == (Action.QUIET, f"no change since {cursor}")
    assert source.reads == ["changes"]  # no tier, no sweep: no watch_state.py run
    assert len(claude.launched) == 1


@pytest.mark.parametrize(
    "change",
    ["updated", "signature", "handed past retry_hours", "dead last session", "no cursor"],
)
def test_s046_2_each_change_makes_the_tick_walk(checkout: Git, change: str) -> None:
    source = Source({1: [INCIDENT]}, signature="same")
    tick(checkout, source)
    (state_dir(checkout) / RECORD).unlink()
    now = LATER
    if change == "updated":
        source.updated = (12,)
    elif change == "signature":
        source.signature = "moved"  # a new head, rollup, default head, tag, incident, or run
    elif change == "handed past retry_hours":
        now = NOW + dt.timedelta(hours=25)
    elif change == "dead last session":
        dead_launch(checkout, INCIDENT, None)  # its launch recorded its hand, as every launch does
    else:
        (state_dir(checkout) / CURSOR).unlink()
    source.reads.clear()
    decision = tick(checkout, source, now, agents=cfg(sweep_hours=48))
    assert decision.walk is not None and decision.walk.change and "tier 1" in source.reads


def graphql_answer(
    head: str = "h1",
    tag: str | None = "v1.0.0",
    pulls: Sequence[dict[str, Any]] = (),
    incidents: Sequence[int] = (),
    updated: Sequence[int] = (),
    more: bool = False,
    landed: Sequence[tuple[int, str | None]] = (),
) -> dict[str, Any]:
    """landed: the default branch's last commits' pull requests, each its number and mergedAt
    (None for one not merged), as the change check's history reads them (spec 048)"""

    def page(nodes: list[dict[str, Any]], has: bool = False) -> dict[str, Any]:
        return {"pageInfo": {"hasNextPage": has, "endCursor": "c1" if has else None}, "nodes": nodes}

    issue = {
        "title": "down",
        "createdAt": "2026-10-27T10:00:00Z",
        "author": {"login": "amy"},
        "labels": {"nodes": [{"name": "incident"}]},
        "closedByPullRequestsReferences": {"nodes": []},
    }
    commits = [{"associatedPullRequests": {"nodes": [{"number": n, "mergedAt": at}]}} for n, at in landed]
    return {
        "data": {
            "repository": {
                "defaultBranchRef": {"name": "main", "target": {"oid": head, "history": {"nodes": commits}}},
                "latestRelease": None if tag is None else {"tagName": tag},
                "updated": page([{"number": n, "labels": {"nodes": []}} for n in updated]),
                "pulls": page(list(pulls), more),
                "incidents": page([{"number": n, **issue} for n in incidents]),
            }
        }
    }


def pull(number: int, head: str = "a" * 40, rollup: str = "SUCCESS", updated: str = "2026-10-27T09:00:00Z") -> Any:
    return {
        "number": number,
        "updatedAt": updated,
        "isDraft": False,
        "isCrossRepository": False,
        "headRefOid": head,
        "labels": {"nodes": []},
        "assignees": {"nodes": []},
        "author": {"__typename": "User", "login": "amy"},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": rollup}}}]},
    }


def runs(*found: tuple[int, str, str | None]) -> dict[str, Any]:
    return {
        "workflow_runs": [
            {
                "id": run_id,
                "path": f".github/workflows/{name}",
                "status": "completed" if conclusion else "in_progress",
                "conclusion": conclusion,
                "created_at": "2026-10-27T11:00:00Z",
                "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
            }
            for run_id, name, conclusion in found
        ]
    }


def prs_of(changes: Changes) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = json.loads(json.dumps(changes.known))["prs"]
    return found


@dataclass
class Gh:
    answers: list[dict[str, Any]]
    rest: dict[str, Any]
    queries: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)

    def graphql(self, query: str, variables: Mapping[str, str]) -> dict[str, Any]:
        self.queries.append(query)
        return self.answers.pop(0)

    def read(self, path: str) -> Any:
        """GitHub's runs reads: the newest per_page runs of one workflow's file, or of every
        workflow for the repo-wide read"""
        self.paths.append(path)
        found = re.fullmatch(rf"repos/{REPO}/actions/(?:workflows/(?P<file>[^/]+)/)?runs\?per_page=(?P<n>\d+)", path)
        if found is None:
            raise ReleaseError(f"gh api {path} failed: HTTP 404")
        mine = [r for r in self.rest["workflow_runs"] if found["file"] in (None, r["path"].rsplit("/", 1)[-1])]
        newest = sorted(mine, key=lambda r: r["id"], reverse=True)[: int(found["n"])]
        return {"total_count": len(mine), "workflow_runs": newest}


def changed(answer: dict[str, Any], found: dict[str, Any] | None = None) -> Changes:
    gh = Gh([answer], found or runs((1, "release.yml", "success")))
    return check(REPO, NOW, "incident", ("release.yml", "ops.yml"), gh.graphql, gh.read, NOW)


@pytest.mark.parametrize(
    ("what", "answer", "found"),
    [
        ("a new pull request head", graphql_answer(pulls=[pull(3, head="b" * 40)]), None),
        ("a changed check rollup", graphql_answer(pulls=[pull(3, rollup="FAILURE")]), None),
        ("a moved default head", graphql_answer(head="h2", pulls=[pull(3)]), None),
        ("a new release tag", graphql_answer(tag="v1.1.0", pulls=[pull(3)]), None),
        ("a new open incident", graphql_answer(pulls=[pull(3)], incidents=[9]), None),
        ("a failed release run", graphql_answer(pulls=[pull(3)]), runs((2, "release.yml", "failure"))),
        (
            "a running operate run",
            graphql_answer(pulls=[pull(3)]),
            runs((1, "release.yml", "success"), (2, "ops.yml", None)),
        ),
    ],
)
def test_s046_2_each_github_change_moves_the_signature(what: str, answer: dict[str, Any], found: Any) -> None:
    before = changed(graphql_answer(pulls=[pull(3)]))
    assert changed(answer, found).signature != before.signature, what


def test_s046_2_a_success_after_a_success_and_another_workflow_are_no_change() -> None:
    before = changed(graphql_answer(pulls=[pull(3)]), runs((1, "ops.yml", "success")))
    again = changed(graphql_answer(pulls=[pull(3)]), runs((2, "ops.yml", "success"), (3, "ci.yml", "failure")))
    assert again.signature == before.signature


def test_s046_2_an_updated_item_is_a_change_and_one_labelled_needs_decision_is_asked() -> None:
    found = changed(graphql_answer(pulls=[pull(3, updated="2026-10-27T12:30:00Z")], updated=[12]))
    assert (found.updated, found.asked) == ((3, 12), False)
    answer = graphql_answer(updated=[12])
    answer["data"]["repository"]["updated"]["nodes"][0]["labels"]["nodes"] = [{"name": "needs-decision"}]
    assert changed(answer).asked


def test_s046_3_the_change_check_is_one_query_and_one_runs_read_per_watched_workflow() -> None:
    gh = Gh([graphql_answer(pulls=[pull(3)], incidents=[9])], runs((1, "release.yml", "success")))
    found = check(REPO, NOW, "incident", ("release.yml",), gh.graphql, gh.read, NOW)
    assert len(gh.queries) == 1 and gh.paths == [f"repos/{REPO}/actions/workflows/release.yml/runs?per_page=10"]
    assert "pullRequests(states: OPEN, first: 100" in gh.queries[0] and "latestRelease" in gh.queries[0]
    assert [p["number"] for p in prs_of(found)] == [3]
    assert json.loads(json.dumps(found.known))["runs"][0]["workflow"] == "release.yml"


@pytest.mark.parametrize(
    "watched", [(), ("release.yml",), ("release.yml", "ops.yml"), ("release.yml", "a.yml", "b.yml")]
)
def test_s046_3_each_watched_workflow_is_read_once_with_at_most_10_runs(watched: tuple[str, ...]) -> None:
    # #762: no repo-wide actions/runs read; three or more workflows are read concurrently
    found = runs(*((n, w, "success") for n, w in enumerate(watched, start=1)), (99, "ci.yml", "failure"))
    gh = Gh([graphql_answer()], found)
    changes = check(REPO, NOW, "incident", watched, gh.graphql, gh.read, NOW)
    assert sorted(gh.paths) == sorted(f"repos/{REPO}/actions/workflows/{w}/runs?per_page=10" for w in watched)
    assert not any("/actions/runs" in p for p in gh.paths)
    assert sorted(r["workflow"] for r in json.loads(json.dumps(changes.known))["runs"]) == sorted(watched)


def test_s046_2_a_release_run_behind_100_newer_ci_runs_is_still_a_change() -> None:
    # #762: the repo-wide read of the newest 100 runs never saw the release run finish
    ci = [(n, "ci.yml", "success") for n in range(3, 103)]
    going = changed(graphql_answer(), runs((2, "release.yml", None), *ci))
    failed = changed(graphql_answer(), runs((2, "release.yml", "failure"), *ci))
    assert failed.signature != going.signature


def test_s046_3_a_watched_workflow_github_doesnt_know_fails_the_check() -> None:
    gh = Gh([graphql_answer()], runs())

    def read(path: str) -> Any:
        if "/workflows/gone.yml/" in path:
            raise ReleaseError(f"gh api {path} failed: gh: Not Found (HTTP 404)")
        return gh.read(path)

    with pytest.raises(ReleaseError, match=r"workflows/gone\.yml/runs.*HTTP 404"):
        check(REPO, NOW, "incident", ("release.yml", "gone.yml", "ops.yml"), gh.graphql, read, NOW)


def test_s046_3_more_than_100_pull_requests_are_paged() -> None:
    second = graphql_answer(pulls=[pull(4)])
    del second["data"]["repository"]["defaultBranchRef"]
    gh = Gh([graphql_answer(pulls=[pull(3)], more=True), second], runs())
    found = check(REPO, NOW, "incident", (), gh.graphql, gh.read, NOW)
    assert len(gh.queries) == 2 and 'after: "c1"' in gh.queries[1] and "latestRelease" not in gh.queries[1]
    assert [p["number"] for p in prs_of(found)] == [3, 4]


# -- the walk


def test_s046_4_a_walk_reads_no_tier_below_the_one_with_an_untaken_item(checkout: Git) -> None:
    source = Source({1: [], 2: [BOT_FAILED], 3: [PRS], 6: [NEW]})
    decision = tick(checkout, source)
    assert (decision.action, decision.work, decision.tier) == (Action.LAUNCH, (BOT_FAILED,), 2)
    assert source.reads == ["changes", "sweep", "tier 1", "tier 2"]
    assert decision.walk is not None and decision.walk.tiers == (1, 2)


def test_s046_5_an_untaken_item_in_tier_3_reads_no_triage_and_no_notices(checkout: Git) -> None:
    source = Source({3: [PRS], 4: [DECIDED], 6: [NEW]}, tag="v1.1.0")
    tick(checkout, source)
    assert source.reads == ["changes", "sweep", "tier 1", "tier 2", "tier 3"]
    # tier 4 and 6 run triage_state.py: neither ran, and no tier runs shipped.py since D-69
    assert not {"tier 4", "tier 6", "tier 8"} & set(source.reads)


def test_s046_6_tiers_1_and_3_get_the_change_checks_data(checkout: Git) -> None:
    # WatchState hands a tier the change check's data in known.json, so watch_state.py reads
    # none of it again (tests/test_watch_tiers.py runs tiers 1 and 3 against a gh that logs)
    from shipmill.gate import StateRead, WatchState

    seen: list[list[str]] = []

    def run(cmd: list[str]) -> Any:
        seen.append(cmd)
        return __import__("subprocess").CompletedProcess(cmd, 0, "", "")

    known = {"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []}
    source = WatchState(REPO, checkout.root, StateRead(), state_dir(checkout), NOW, run=run)
    for number in (1, 3):
        assert source.tier(number, Changes("sig", known=known)) == []
    path = state_dir(checkout) / "known.json"
    assert all(cmd[-4:] == ["--tier", str(n), "--known", str(path)] for cmd, n in zip(seen, (1, 3), strict=True))
    assert json.loads(path.read_text()) == known


def test_s046_8_a_sweep_runs_when_due_and_its_rows_serve_tiers_2_5_and_7(checkout: Git) -> None:
    upgrade = Finding("UPGRADE_PENDING", "#11", "x: ask", True, (), "watch")
    source = Source(swept=[STALLED, upgrade, PLANS])
    first = tick(checkout, source, agents=cfg(sweep_hours=6))
    assert first.walk is not None and first.walk.sweep and first.work == (STALLED,)
    stored = Swept.load(state_dir(checkout) / SWEEP)
    assert stored is not None and stored.at == NOW and set(stored.rows) == {STALLED, upgrade, PLANS}
    # between sweeps the tiers read the stored rows: each handed item gives way to the next
    for expected in (upgrade, PLANS):
        source.reads.clear()
        source.signature = expected.state  # a change, so the tick walks
        decision = tick(checkout, source, NOW + dt.timedelta(hours=1), agents=cfg(sweep_hours=6))
        assert "sweep" not in source.reads and decision.work == (expected,)
    # sweep_hours later it sweeps again, with or without a change
    source.reads.clear()
    later = tick(checkout, source, NOW + dt.timedelta(hours=6), agents=cfg(sweep_hours=6))
    assert "sweep" in source.reads and later.walk is not None and later.walk.sweep


def test_d69_an_unannounced_row_a_sweep_stored_before_d69_is_never_an_item(checkout: Git) -> None:
    # D-69 (#921): no tier 8, and a new tag runs no check of its own; a sweep.json written
    # before the upgrade keeps loading, and its UNANNOUNCED row is never handed
    old = Finding("UNANNOUNCED", "v1.0.0", "#5 (since v0.9.0)", True, (), "post")
    Swept(NOW, (old,), "v1.0.0").save(state_dir(checkout) / SWEEP)
    source = Source(tag="v1.1.0", signature="tagged")
    decision = tick(checkout, source, NOW + dt.timedelta(hours=1), agents=cfg(sweep_hours=6))
    assert "sweep" not in source.reads and not any(r.startswith("tier 8") for r in source.reads)
    assert decision.action is Action.QUIET and decision.work == ()


def test_s046_10_sweep_hours_defaults_to_6_and_is_refused_outside_1_to_168() -> None:
    def read(text: str) -> AgentsConfig:
        return AgentsConfig.parse(Table({"prompt": "/t", **json.loads(text)}, "[agents]"))

    assert read("{}").sweep_hours == 6
    assert read('{"sweep_hours": 168}').sweep_hours == 168
    for bad in ('{"sweep_hours": 0}', '{"sweep_hours": 169}', '{"sweep_hours": "6"}', '{"sweep_hours": 1.5}'):
        with pytest.raises(ReleaseError, match="sweep_hours"):
            read(bad)


def test_s046_11_the_cursor_is_the_walks_start_less_5_minutes(checkout: Git) -> None:
    tick(checkout, Source({1: [INCIDENT]}, signature="s1"))
    assert Cursor.load(state_dir(checkout) / CURSOR) == Cursor(NOW - dt.timedelta(minutes=5), "s1")


def test_s046_11_a_failed_read_writes_no_cursor_or_sweep(checkout: Git) -> None:
    @dataclass
    class Failing(Source):
        def tier(self, number: int, changes: Changes) -> list[Finding]:
            raise ReleaseError("watch_state.py --tier 1 failed (exit 2): error")

    with pytest.raises(ReleaseError, match="--tier 1 failed"):
        tick(checkout, Failing())
    assert not (state_dir(checkout) / CURSOR).exists() and not (state_dir(checkout) / SWEEP).exists()


def test_s046_12_tiers_4_and_6_hold_one_item_per_triage_state(checkout: Git) -> None:
    unplaced = Finding("SOMETHING_NEW", REPO, "", True, (), "fix")
    source = Source({4: [DECIDED], 6: [NEEDS_PR, unplaced, NEW]})
    assert tick(checkout, source).work == (DECIDED,)  # tier 4, ahead of tier 6's NEW
    order: list[Finding] = []
    for minutes in (0, 15, 30):
        source.signature = f"next {minutes}"  # a change, so each tick walks
        order += tick(checkout, source, LATER + dt.timedelta(minutes=minutes)).work
    # tier 6 in its fixed order: NEW, then NEEDS_PR, then a state no tier names
    assert order == [NEW, NEEDS_PR, unplaced]


def test_s046_13_a_launch_names_one_item_with_its_tier_and_records_it(checkout: Git) -> None:
    claude = FakeClaude()
    decision = tick(checkout, Source({1: [INCIDENT], 2: [BOT_FAILED]}), claude=claude)
    assert decision.work == (INCIDENT,)
    _, text = claude.launched[0]
    assert "\n- INCIDENT_OPEN #9 (tier 1)\n  fix: resolve #9\n" in text
    assert "BOT_FAILED" not in text and "staging is down" not in text  # one item, never its detail
    assert handed(checkout) == {item_key(INCIDENT): {"session": "s1", "at": NOW.isoformat()}}


def test_s046_14_a_handed_item_gives_way_and_every_item_handed_is_unchanged(checkout: Git) -> None:
    source = Source({1: [INCIDENT], 2: [BOT_FAILED]})
    tick(checkout, source)
    source.signature = "next"
    second = tick(checkout, source, LATER)
    assert (second.action, second.work) == (Action.LAUNCH, (BOT_FAILED,))
    source.signature = "again"
    third = tick(checkout, source, LATER + dt.timedelta(minutes=15))
    assert (third.action, third.work) == (Action.UNCHANGED, (INCIDENT,))
    again = (NOW + dt.timedelta(hours=24)).isoformat(timespec="minutes")
    assert third.reason.startswith("every item was handed; the first, INCIDENT_OPEN #9 (tier 1), went to session s1;")
    assert f"retried after {again}; read tiers 1-7" in third.reason


def dead_launch(git: Git, item: Finding, deaths: Deaths | None) -> None:
    """A headless launch of item at NOW whose session died 5 s later"""
    save_launch(state_dir(git) / RECORD, Launch(item_key(item), str(ONE), NOW, Process(PID, STARTED), deaths))
    Handed({item_key(item): Hand(str(ONE), NOW)}).save(state_dir(git) / HANDED)
    log = log_of(git, ONE)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    os.utime(log, (NOW.timestamp() + 5, NOW.timestamp() + 5))


def test_s046_15_a_dead_sessions_item_is_handed_again(checkout: Git) -> None:
    dead_launch(checkout, INCIDENT, None)
    claude = FakeClaude()
    decision = tick(checkout, Source({1: [INCIDENT], 2: [BOT_FAILED]}), LATER, cfg(Mode.HEADLESS), claude)
    assert (decision.action, decision.work) == (Action.SESSION_DEAD, (INCIDENT,))
    assert len(claude.started) == 1


def test_s046_15_after_dead_streak_dead_sessions_the_walk_goes_past_the_item(checkout: Git) -> None:
    dead_launch(checkout, INCIDENT, Deaths(2, NOW - dt.timedelta(minutes=30)))
    decision = tick(checkout, Source({1: [INCIDENT], 2: [BOT_FAILED]}), LATER, cfg(Mode.HEADLESS), FakeClaude())
    assert decision.work == (BOT_FAILED,)


def test_s046_16_untrusted_and_waiting_items_are_never_items(checkout: Git) -> None:
    # with --trusted-only, watch_state.py prints them in UNTRUSTED and NEEDS_DECISION, neither an
    # agent row (tests/test_watch_tiers.py); a walk hands neither
    untrusted = Finding("UNTRUSTED", REPO, "#20 #21", False, (), "review")
    source = Source({3: [untrusted, WAITING], 4: [WAITING], 6: [untrusted]})
    decision = tick(checkout, source, agents=cfg(Mode.HEADLESS))
    assert (decision.action, decision.work) == (Action.QUIET, ())


def test_s046_17_a_walk_above_tier_4_reads_it_only_for_an_updated_needs_decision_item(checkout: Git) -> None:
    notifier = FakeNotifier()
    source = Source({1: [INCIDENT], 4: [WAITING]}, asked=True)
    first = tick(checkout, source, agents=cfg(Mode.HEADLESS), notifier=notifier)
    assert "tier 4" in source.reads and [a.item for a in first.decisions] == [8]
    assert notifier.sent and (state_dir(checkout) / DECISIONS).is_file()
    # no updated needs-decision item: the reminders come from needs-decision.json, read from nowhere
    source.asked, source.signature = False, "next"
    source.tiers[2] = [BOT_FAILED]  # the walk stops at tier 2, above tier 4
    source.reads.clear()
    later = NOW + dt.timedelta(hours=5)  # past remind_hours
    decision = tick(checkout, source, later, agents=cfg(Mode.HEADLESS), notifier=notifier)
    assert "tier 4" not in source.reads
    assert [(a.item, a.notified) for a in decision.decisions] == [(8, True)] and len(notifier.sent) == 2


def test_s046_18_json_prints_walk_and_item_and_the_line_names_how_far(checkout: Git) -> None:
    decision = tick(checkout, Source({2: [BOT_FAILED]}))
    record = tick_record(decision, "s1", (), (), dry_run=False)
    assert record["walk"] == {"change": True, "tiers": [1, 2], "sweep": True}
    assert record["item"] == "BOT_FAILED release.yml"
    line = tick_lines(decision, "s1", (), (), dry_run=False)[0]
    assert line == "LAUNCH: BOT_FAILED release.yml needs an agent (tier 2); read tiers 1-2"
    quiet = tick(checkout, Source(signature="other"), LATER)
    assert tick_record(quiet, None, (), (), dry_run=False)["item"] is None


def test_s046_19_a_dry_run_writes_no_record_and_walk_and_sweep_force_them(checkout: Git) -> None:
    source = Source({1: [INCIDENT]}, signature="same")
    tick(checkout, source, dry_run=True)
    for name in (CURSOR, SWEEP, HANDED):
        assert not (state_dir(checkout) / name).exists()
    tick(checkout, source)
    (state_dir(checkout) / RECORD).unlink()
    source.reads.clear()
    quiet = tick(checkout, source, LATER)
    assert quiet.action is Action.QUIET and source.reads == ["changes"]
    source.reads.clear()
    forced = tick(checkout, source, LATER, walk_now=True, sweep_now=True)
    assert forced.walk is not None and forced.walk.change and forced.walk.sweep
    assert source.reads[:3] == ["changes", "sweep", "tier 1"]


def test_s046_2_a_handed_item_past_retry_hours_is_one_change_not_one_every_tick(checkout: Git) -> None:
    source = Source({1: [INCIDENT]}, signature="same")
    tick(checkout, source)  # gate.json and handed.json record the launch
    source.tiers = {}  # the incident closed
    day = NOW + dt.timedelta(hours=25)
    expired = tick(checkout, source, day, agents=cfg(sweep_hours=48))
    assert expired.walk is not None and expired.walk.change
    source.reads.clear()
    after = tick(checkout, source, day + dt.timedelta(minutes=15), agents=cfg(sweep_hours=48))
    assert after.reason.startswith("no change since") and source.reads == ["changes"]


# review findings: each a regression test


def test_s046_3_a_later_page_declares_only_the_variables_it_uses() -> None:
    from shipmill.walk import change_query

    page = change_query(("pulls",), {"pulls": "c1"}, first=False)
    assert "$since" not in page and "$label" not in page  # GitHub refuses a variable declared and unused
    second = graphql_answer(pulls=[pull(4)])
    gh = Gh([graphql_answer(pulls=[pull(3)], more=True), second], runs())
    sent: list[Mapping[str, str]] = []

    def graphql(query: str, variables: Mapping[str, str]) -> dict[str, Any]:
        sent.append(variables)
        return gh.graphql(query, variables)

    check(REPO, NOW, "incident", (), graphql, gh.read, NOW)
    assert set(sent[1]) == {"owner", "name"}


def test_s046_13_an_incident_that_only_aged_is_still_handed(checkout: Git) -> None:
    source = Source({1: [INCIDENT]})
    tick(checkout, source)
    older = Finding("INCIDENT_OPEN", "#9", "staging is down; open 25 min, no PR links it", True, (), "resolve #9")
    source.tiers, source.signature = {1: [older]}, "commented"
    assert tick(checkout, source, LATER).action is Action.UNCHANGED


def test_s046_15_a_capped_item_is_no_change_on_every_tick_and_its_deaths_stay_its_own(checkout: Git) -> None:
    dead_launch(checkout, INCIDENT, Deaths(2, NOW - dt.timedelta(minutes=30)))
    source = Source({1: [INCIDENT], 2: [BOT_FAILED]})
    first = tick(checkout, source, LATER, cfg(Mode.HEADLESS, sweep_hours=48), FakeClaude())
    assert first.work == (BOT_FAILED,)
    record = json.loads((state_dir(checkout) / RECORD).read_text())
    assert "dead" not in record  # another item starts its own run of dead sessions


def test_s046_2_a_dead_session_is_one_change_not_one_every_tick(checkout: Git) -> None:
    dead_launch(checkout, INCIDENT, None)
    source = Source({}, signature="same")  # the dead session's incident closed: nothing to launch
    first = tick(checkout, source, LATER, cfg(Mode.HEADLESS, sweep_hours=48), FakeClaude())
    assert first.walk is not None and first.walk.change
    source.reads.clear()
    after = tick(checkout, source, LATER + dt.timedelta(minutes=15), cfg(Mode.HEADLESS, sweep_hours=48), FakeClaude())
    assert after.reason.startswith("no change since") and source.reads == ["changes"]


def test_s046_2_a_run_still_going_is_no_change() -> None:
    done = changed(graphql_answer(pulls=[pull(3)]), runs((1, "ops.yml", "success")))
    going = changed(graphql_answer(pulls=[pull(3)]), runs((2, "ops.yml", None), (1, "ops.yml", "success")))
    assert going.signature == done.signature


def test_s046_11_a_failed_tier_4_read_for_notifications_writes_no_sweep(checkout: Git) -> None:
    @dataclass
    class Failing(Source):
        def tier(self, number: int, changes: Changes) -> list[Finding]:
            if number == 4:
                raise ReleaseError("watch_state.py --tier 4 failed (exit 2): error")
            return super().tier(number, changes)

    with pytest.raises(ReleaseError, match="--tier 4 failed"):
        tick(checkout, Failing({1: [INCIDENT]}, asked=True), agents=cfg(Mode.HEADLESS))
    assert not (state_dir(checkout) / SWEEP).exists()


def test_s046_17_an_answered_item_is_read_again_when_it_is_updated(checkout: Git) -> None:
    source = Source({1: [INCIDENT], 4: [WAITING]}, asked=True)
    tick(checkout, source, agents=cfg(Mode.HEADLESS))
    # the label moved to decided: the update carries no needs-decision label, but #8 is waiting in the record
    source.tiers = {1: [INCIDENT], 2: [BOT_FAILED], 4: []}
    source.asked, source.updated, source.signature = False, (8,), "answered"
    source.reads.clear()
    decision = tick(checkout, source, LATER, agents=cfg(Mode.HEADLESS))
    assert "tier 4" in source.reads and decision.decisions == ()
    assert not (state_dir(checkout) / DECISIONS).exists()


def test_s046_12_subjects_order_by_number() -> None:
    from shipmill.walk import order

    ten, nine = (Finding("INCIDENT_OPEN", f"#{n}", "", True) for n in (10, 9))
    assert order([ten, nine]) == [nine, ten]


def test_914_an_agent_draft_is_an_item_only_when_land_isnt_observe() -> None:
    """Marking the App's own draft ready is a land-stage write: like PRS_OPEN, AGENT_DRAFT is
    handed only when land is propose or act, though watch_state.py marks it an agent's row"""
    from shipmill.walk import Rows, walk

    draft = Finding("AGENT_DRAFT", REPO, "#20", True, (), "mark each ready, then land it: ...")
    rows = Rows((draft,))
    swept = Swept(NOW, (), None)
    for lands, item in ((False, None), (True, draft)):
        found = walk(rows, rows.changes(None), swept, Handed(), NOW, dt.timedelta(hours=6), lands)
        assert (found.item, found.tier) == (item, None if item is None else 3)
        assert draft in found.rows  # read and reported either way


def test_926_a_handed_item_a_full_walk_misses_is_handed_again_when_it_returns(checkout: Git) -> None:
    """#926: the session asks on #3 and ends; while the question waits, #3 leaves PRS_OPEN and a
    full walk drops its hand, so the same row, back once the answer took the label off, goes to a
    session on the next tick instead of waiting out retry_hours"""
    source = Source({3: [PRS]})
    assert tick(checkout, source).work == (PRS,)
    source.tiers, source.signature = {3: [Finding("NEEDS_DECISION", REPO, "#3", False, (), "answer")]}, "asked"
    asked = tick(checkout, source, LATER)
    assert (asked.action, handed(checkout)) == (Action.QUIET, {})
    source.tiers, source.signature = {3: [PRS]}, "answered"
    answered = tick(checkout, source, LATER + dt.timedelta(minutes=15))
    assert (answered.action, answered.work) == (Action.LAUNCH, (PRS,))


def test_926_a_walk_that_stops_early_keeps_the_hands_of_tiers_it_didnt_read(checkout: Git) -> None:
    source = Source({6: [NEW]})
    tick(checkout, source)
    source.tiers, source.signature = {1: [INCIDENT], 6: [NEW]}, "incident"
    assert tick(checkout, source, LATER).work == (INCIDENT,)
    assert set(handed(checkout)) == {item_key(NEW), item_key(INCIDENT)}


# -- spec 056: the land window's queue drains when the window opens

LAND_DUE = Finding("LAND_DUE", "#5", "Deploy: the land window is open; queued since 2026-11-16 07:00 UTC", False)
WINDOW = """
[land.window]
timezone = "Asia/Nicosia"
open = ["Mon-Thu 10:00-18:00", "Fri 10:00-14:00"]
closed = ["12:00-12:30"]
labels = ["rollout:normal", "rollout:high"]
queued_label = "rollout:queued"
spacing_minutes = 30
"""
MONDAY = dt.datetime(2026, 11, 16, 0, 0, tzinfo=dt.UTC)  # Nicosia is UTC+2 in November: it opens at 08:00 UTC


def utc(hour: int, minute: int = 0) -> dt.datetime:
    return MONDAY.replace(hour=hour, minute=minute)


def land_window(text: str = WINDOW) -> LandWindow:
    found = read_window(Table(tomllib.loads(text), ".github/shipmill.toml"))
    assert found is not None
    return found


def never_read() -> dt.datetime | None:
    raise AssertionError("the last held merge was read")


@pytest.mark.parametrize(
    ("since", "now", "why"),
    [
        (utc(7, 50), utc(8, 5), "closed at since, open now: the window opened"),
        (utc(9, 55), utc(10, 31), "closed for 12:00-12:30 local and open again since"),
    ],
)
def test_s056_11_the_window_opening_since_the_cursor_is_a_change(
    since: dt.datetime, now: dt.datetime, why: str
) -> None:
    assert window_change(land_window(), True, since, now, never_read), why


@pytest.mark.parametrize(
    ("queued", "since", "now", "why"),
    [
        (False, utc(7, 50), utc(8, 5), "no queued pull request: the opening counts for nothing"),
        (True, utc(7, 0), utc(7, 50), "closed then and now"),
        (True, utc(8, 50), utc(10, 5), "closed between: it is closed now"),
        (True, None, utc(8, 5), "no cursor: the tick walks anyway"),
    ],
)
def test_s056_11_no_opening_with_a_queue_is_no_change(
    queued: bool, since: dt.datetime | None, now: dt.datetime, why: str
) -> None:
    assert not window_change(land_window(), queued, since, now, never_read), why


@pytest.mark.parametrize(
    ("last", "change"),
    [
        (utc(8, 45), True),  # its spacing passes at 09:15 UTC, after the cursor at 09:10
        (utc(8, 30), False),  # passed at 09:00 UTC, before the cursor: the last walk saw it
        (utc(9, 0), False),  # passes at 09:30 UTC, after now
        (None, False),  # no held merge: nothing holds the next one
    ],
)
def test_s056_11_next_merge_passing_since_the_cursor_while_open_is_a_change(
    last: dt.datetime | None, change: bool
) -> None:
    reads: list[str] = []

    def held() -> dt.datetime | None:
        reads.append("last held merge")
        return last

    assert window_change(land_window(), True, utc(9, 10), utc(9, 20), held) is change
    assert reads == ["last held merge"]
    unspaced = land_window(WINDOW.replace("spacing_minutes = 30", "spacing_minutes = 0"))
    assert not window_change(unspaced, True, utc(9, 10), utc(9, 20), never_read)  # open throughout, no spacing


def test_s056_11_an_open_window_is_one_change_not_one_every_tick(checkout: Git) -> None:
    """With nothing else changed on GitHub, the window opening makes the tick walk and hand the
    queue's head; the next tick, with no new opening, is quiet"""
    source = Source({3: [LAND_DUE]}, signature="same")
    tick(checkout, source, agents=cfg(land=Autonomy.ACT))
    (state_dir(checkout) / RECORD).unlink()
    source.reads.clear()
    source.window = True
    opened = tick(checkout, source, LATER, agents=cfg(land=Autonomy.ACT, sweep_hours=48))
    assert opened.walk is not None and opened.walk.change and "tier 3" in source.reads
    source.window, source.reads = False, []
    quiet = tick(checkout, source, LATER + dt.timedelta(minutes=15), agents=cfg(land=Autonomy.ACT, sweep_hours=48))
    assert quiet.action is Action.QUIET and source.reads == ["changes"]


def queued_pull(number: int, *labels: str, draft: bool = False) -> Any:
    return {**pull(number), "labels": {"nodes": [{"name": n} for n in labels]}, "isDraft": draft}


@pytest.mark.parametrize(
    ("pulls", "change"),
    [
        ([queued_pull(5, "rollout:queued")], True),
        ([queued_pull(5, "rollout:high"), queued_pull(6, "rollout:queued", draft=True)], False),
    ],
)
def test_s056_11_the_gates_change_check_reads_the_window_and_the_queue(
    tmp_path: Any, pulls: list[Any], change: bool
) -> None:
    """WatchState's change check: the queue from the labels its one query read, the window from
    the checkout's config; with the cursor before the opening, a queue makes it a change"""
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(f'mode = "off"\n{WINDOW}', encoding="utf-8")
    queries: list[str] = []

    def gh(cmd: list[str], cwd: Any) -> str:
        query = next(a for a in cmd if a.startswith("query="))
        queries.append(query)
        return json.dumps(graphql_answer(pulls=pulls))

    source = WatchState(REPO, tmp_path, StateRead(), tmp_path / "state", utc(8, 5), gh=gh)
    found = source.changes(utc(7, 50) - CURSOR_OVERLAP)
    assert found.window is change
    assert len(queries) == 1  # the opening reads no last held merge
    assert source.changes(None).window is False  # no cursor: the tick walks anyway


def test_s056_12_land_due_comes_before_prs_open_and_only_when_land_isnt_observe() -> None:
    from shipmill.walk import TIERS, Rows, walk

    assert TIERS[3][:2] == ("LAND_DUE", "PRS_OPEN")
    rows = Rows((PRS, LAND_DUE))
    swept = Swept(NOW, (), None)
    for lands, item in ((False, None), (True, LAND_DUE)):
        found = walk(rows, rows.changes(None), swept, Handed(), NOW, dt.timedelta(hours=6), lands)
        assert (found.item, found.tier) == (item, None if item is None else 3)
        assert LAND_DUE in found.rows  # read and reported either way
    handed_due = Handed().handing(LAND_DUE, "s1", NOW)
    found = walk(rows, rows.changes(None), swept, handed_due, NOW, dt.timedelta(hours=6), True)
    assert found.item == PRS  # the queue's head handed: the walk goes on to PRS_OPEN
