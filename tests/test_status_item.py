"""Spec 088: `shipmill status --item REF` says why one open issue or pull request is not closed"""

import dataclasses
import datetime as dt
import importlib.util
import json
import plistlib
import re
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.app import default_key
from shipmill.autonomy import Autonomy, AutonomyPolicy
from shipmill.cli import _parser, _status, main
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.gate import skills_dir
from shipmill.item_status import (
    VERDICT_WAITS,
    Kind,
    PullDetail,
    Ref,
    Who,
    bucket,
    explain,
    parse_pull_detail,
    parse_ref,
)
from shipmill.land_window import LandWindow
from shipmill.launchd import label
from shipmill.status import ISSUE_LINES, TRIAGE_VERDICTS, Facts, Issue, Pull, Row, parse_issues, report
from tests import test_app
from tests.test_status_picture import REPO, VERSION_JSON, facts, gate, host, repo_with_release

NONE = PullDetail((), "", ())
ITEM = re.compile(r"repos/[^/]+/[^/]+/issues/(\d+)")  # #1469: the item's own state, read first
OPEN, CLOSED = {4, 9}, {7}  # the Fake's open issue and pull request, and a closed issue
NO_PULLS: dict[str, object] = {"closedByPullRequestsReferences": {"nodes": []}}


def why(found: Facts, number: int, detail: PullDetail = NONE, window: LandWindow | None = None) -> list[str]:
    return [c.reason for c in explain(found, Ref(str(number), number, None), lambda _: detail, window).conditions]


def whos(found: Facts, number: int, detail: PullDetail = NONE) -> list[tuple[str, Who]]:
    return [
        (c.reason, c.who) for c in explain(found, Ref(str(number), number, None), lambda _: detail, None).conditions
    ]


def triage_state() -> ModuleType:
    path = skills_dir() / "github-issue-triage" / "scripts" / "triage_state.py"
    spec = importlib.util.spec_from_file_location("triage_state_088", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fake:
    """The picture's reads, with one open issue #4 (TRIAGED as an opportunity) and one open
    pull request #9 whose check fails; every command it is given is kept"""

    def __init__(self, item: dict[str, object] | None = None, chain: list[dict[str, object]] | None = None) -> None:
        self.seen: list[list[str]] = []
        self.item = item if item is not None else {"__typename": "Issue", "comments": {"nodes": []}, **NO_PULLS}
        self.chain = chain if chain is not None else []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.seen.append(cmd)
        if cmd[1].endswith("chains.py"):  # #1473: the walk of what waits on the item
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"rows": self.chain}), "")
        if cmd[:3] == ["gh", "api", "graphql"] and "issueOrPullRequest" in cmd[4]:  # #1473: the item's own read
            data = {"data": {"repository": {"issueOrPullRequest": self.item}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(data), "")
        if cmd[1].endswith("watch_state.py") and "--host" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[1].endswith("watch_state.py"):
            rows = [{"state": "PRS_OPEN", "subject": REPO, "detail": "#9", "agent": False}, VERSION_JSON]
            return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(r) + "\n" for r in rows), "")
        if cmd[1].endswith("triage_state.py"):
            line = {"number": 4, "state": "TRIAGED", "title": "t", "note": "", "verdict": "opportunity"}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(line) + "\n", "")
        if cmd[:3] == ["gh", "pr", "list"]:
            pull = {"number": 9, "isDraft": False, "mergeStateStatus": "UNSTABLE", "baseRefName": "main", "labels": []}
            if "statusCheckRollup" in cmd[cmd.index("--json") + 1]:  # S-094-10: the checks of every pull request
                rollup = [{"__typename": "CheckRun", "name": "check", "status": "COMPLETED", "conclusion": "FAILURE"}]
                pull = {"number": 9, "statusCheckRollup": rollup, "reviewDecision": "", "labels": []}
            return subprocess.CompletedProcess(cmd, 0, json.dumps([pull]), "")
        if cmd[:3] == ["gh", "pr", "view"]:
            rollup = [{"__typename": "CheckRun", "name": "check", "status": "COMPLETED", "conclusion": "FAILURE"}]
            out = {"statusCheckRollup": rollup, "reviewDecision": "", "labels": []}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
        if cmd[:2] == ["gh", "api"] and (found := ITEM.fullmatch(cmd[2])) is not None:
            number = int(found[1])
            if number in OPEN | CLOSED:
                return subprocess.CompletedProcess(cmd, 0, "open\n" if number in OPEN else "closed\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "gh: Not Found (HTTP 404)\n")
        answers = {
            ("gh", "repo"): "main\n",
            ("gh", "release"): '{"tagName": "v1.0.0", "publishedAt": "2026-10-06T12:00:00Z"}',
            ("gh", "api"): '{"data": {"search": {"nodes": []}}}',
            ("gh", "issue"): "[]",
        }
        return subprocess.CompletedProcess(cmd, 0, answers[(cmd[0], cmd[1])], "")


def run_item(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, Fake]:
    fake = Fake()
    code = main(["--repo", str(root), "status", "--item", *args], state=fake, login=host)
    return code, capsys.readouterr().out, fake


def test_s088_1_a_number_and_its_url_give_the_same_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo_with_release(tmp_path / "repo")
    by_number = run_item(root, capsys, "4")
    by_url = run_item(root, capsys, f"https://github.com/{REPO}/issues/4")
    assert by_number[:2] == by_url[:2] and by_number[0] == 0
    assert by_number[1].startswith(f"{REPO}#4 (https://github.com/{REPO}/issues/4): parked\n")
    pull_number = run_item(root, capsys, "9")
    pull_url = run_item(root, capsys, f"https://github.com/{REPO}/pull/9/")
    assert pull_number[:2] == pull_url[:2] and pull_number[0] == 0
    assert "  why:  check check failed\n" in pull_number[1]


@pytest.mark.parametrize(
    "given",
    ["four", "#4", "https://github.com/acme/web/issues/", "https://gitlab.com/acme/web/issues/4", "-4", "0"],
)
def test_s088_2_a_ref_that_is_no_number_nor_url_exits_2_naming_it(given: str) -> None:
    with pytest.raises(ReleaseError, match="--item"):
        parse_ref(given, REPO)


def test_s088_2_a_url_of_another_repo_is_refused_and_case_is_ignored() -> None:
    with pytest.raises(ReleaseError, match="an item of other/repo"):
        parse_ref("https://github.com/other/repo/issues/4", REPO)
    assert parse_ref("https://github.com/ACME/Web/pull/4#top", REPO) == Ref(
        "https://github.com/ACME/Web/pull/4#top", 4, Kind.PULL
    )


@pytest.mark.parametrize("given", ["5", f"https://github.com/{REPO}/pull/4", f"https://github.com/{REPO}/issues/9"])
def test_s088_2_no_open_item_or_the_wrong_kind_exits_2_naming_the_ref(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], given: str
) -> None:
    root = repo_with_release(tmp_path / "repo")
    with pytest.raises(ReleaseError, match=re.escape(f"--item {given!r}")):  # run() prints it and exits 2
        main(["--repo", str(root), "status", "--item", given], state=Fake(), login=host)
    assert capsys.readouterr().out == ""
    with pytest.raises(ReleaseError, match=re.escape(f"--item {given!r}")):
        explain(
            facts(issues=[Issue(4, "TRIAGED")], pulls=[Pull(9, False, "CLEAN", "main")]),
            parse_ref(given, REPO),
            lambda _: NONE,
            None,
        )


def test_s088_2_item_cant_be_combined_with_rows(tmp_path: Path) -> None:
    root = repo_with_release(tmp_path / "repo")
    with pytest.raises(ReleaseError, match="can't be combined with --rows"):
        main(["--repo", str(root), "status", "--item", "4", "--rows"], state=Fake(), login=host)


@pytest.mark.parametrize(("label", "states"), ISSUE_LINES)
def test_s088_3_an_issue_is_in_the_bucket_of_the_line_the_picture_lists_it_on(
    label: str, states: tuple[str, ...]
) -> None:
    for state in states:
        found = facts(issues=[Issue(4, state)])
        assert bucket(found, 4, Kind.ISSUE) == label
        listed = [line for line in report(found).lines if "/issues/4" in line]
        assert listed and listed[0].strip().startswith(label)


def test_s088_3_pull_requests_and_the_rest_read_their_bucket() -> None:
    drafts = facts(pulls=[Pull(9, True, "CLEAN", "main")])
    assert bucket(drafts, 9, Kind.PULL) == "drafts"
    landing = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    assert bucket(landing, 9, Kind.PULL) == "to land"
    asked = facts(Row("NEEDS_DECISION", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    assert bucket(asked, 9, Kind.PULL) == "needs decision"
    assert bucket(facts(pulls=[Pull(9, False, "CLEAN", "main")]), 9, Kind.PULL) == "open"
    assert bucket(facts(issues=[Issue(4, "UPSTREAM")]), 4, Kind.ISSUE) == "open"


EVERY_STATE = sorted({s for _, states in ISSUE_LINES for s in states} | {"NEEDS_DECISION", "UPSTREAM"})


@pytest.mark.parametrize("state", EVERY_STATE)
@pytest.mark.parametrize("configured", [True, False])
def test_s088_4_every_open_item_names_a_condition_with_who_clears_it(state: str, configured: bool) -> None:
    found = facts(
        issues=[Issue(4, state, assignees=("amy",) if state == "WITH_PERSON" else ())],
        pulls=[Pull(9, False, "CLEAN", "main")],
        gate=gate() if configured else gate(agents=None),
    )
    for number in (4, 9):
        explained = explain(found, Ref(str(number), number, None), lambda _: NONE, None)
        assert explained.conditions
        assert all(c.clears.strip() and c.who in set(Who) for c in explained.conditions)


def test_s088_5_a_hold_no_gate_and_a_stage_below_act_are_the_maintainers() -> None:
    held = facts(Row("HOLD", "#77", "hold", False), issues=[Issue(4, "NEW")])
    assert ("the shipmill-hold issue #77 holds what the gate does", Who.MAINTAINER) in whos(held, 4)
    ungated = facts(issues=[Issue(4, "NEW")], gate=gate(agents=None))
    assert whos(ungated, 4)[0] == ("no gate works on it: no [agents] in .github/shipmill.toml", Who.MAINTAINER)
    observed = facts(issues=[Issue(4, "NEEDS_PR")], autonomy=AutonomyPolicy(fix=Autonomy.OBSERVE))
    assert ("[autonomy] fix is observe: no session acts on it", Who.MAINTAINER) in whos(observed, 4)
    proposed = facts(issues=[Issue(4, "NEW")], autonomy=AutonomyPolicy(triage=Autonomy.PROPOSE))
    assert ("[autonomy] triage is propose: a session proposes and waits for your answer", Who.MAINTAINER) in whos(
        proposed, 4
    )
    landing = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    observing = dataclasses.replace(landing, autonomy=AutonomyPolicy(land=Autonomy.OBSERVE))
    assert ("[autonomy] land is observe: no session acts on it", Who.MAINTAINER) in whos(observing, 9)


@pytest.mark.parametrize(
    ("issue", "reason", "who"),
    [
        (Issue(4, "NEEDS_DECISION"), "waits on the answer to its needs-decision question", Who.MAINTAINER),
        (Issue(4, "BLOCKED", "acme/web#5:open acme/web#6:closed"), "waits on acme/web#5 (open)", Who.EVENT),
        (Issue(4, "BLOCKED", "labelled blocked"), "labelled blocked", Who.MAINTAINER),
        (Issue(4, "POSTPONED"), "postponed", Who.EVENT),
        (Issue(4, "WITH_PERSON", assignees=("amy",)), "a person's item: waits on @amy", Who.PERSON),
        (Issue(4, "IN_PROGRESS", "#9:open"), "its pull request #9 is open", Who.EVENT),
        (Issue(4, "UPSTREAM"), "an upstream report: waits on the repo that owns the fault", Who.EVENT),
    ],
)
def test_s088_6_an_issues_state_gives_its_condition(issue: Issue, reason: str, who: Who) -> None:
    found = whos(facts(issues=[issue]), 4)
    assert (reason, who) in found
    assert not any("acme/web#6" in r for r, _ in found)  # a closed hold holds nothing


def test_1487_an_unowned_upstream_report_waits_on_the_maintainer() -> None:
    found = explain(facts(issues=[Issue(4, "UPSTREAM_UNOWNED")]), Ref("4", 4, None), lambda _: NONE, None)
    reason = "an upstream report nobody linked or took: waits for you to report it where it belongs"
    assert any(c.reason == reason and c.who is Who.MAINTAINER and c.clears.strip() for c in found.conditions)


def said(body: str) -> dict[str, object]:
    return {"body": body, "createdAt": "2026-11-01T10:00:00Z"}


@pytest.mark.parametrize(
    ("bodies", "verdict"),
    [
        (["Triage: **opportunity**. Serves: G-4."], "opportunity"),
        (["Triage: **postponed to 1.1**. Not now."], "postponed"),
        (["Triage: **won’t fix**: it hits N-1."], "won't fix"),
        (["Triage: **feature**.", "Triage: **clarify**: which repo?"], "clarify"),  # the newest one
        (["Triage: **plan**."], "plan"),
        (["Triage: **anything else**."], None),
        (["Triage: clarify, in plain words"], None),
        ([], None),
    ],
)
def test_s088_7_a_triaged_line_carries_its_verdict_only_when_the_skills_write_it(
    bodies: list[str], verdict: str | None
) -> None:
    ts = triage_state()
    assert ts.triage_verdict({"comments": {"nodes": [said(b) for b in bodies]}}, "Triage:") == verdict
    assert set(ts.TRIAGE_VERDICTS) == TRIAGE_VERDICTS == set(VERDICT_WAITS)


def test_s088_7_triage_state_prints_the_verdict_on_a_triaged_line_only() -> None:
    ts = triage_state()
    issue = {"comments": {"nodes": [said("Triage: **opportunity**. x")]}}
    assert ts.triage_verdict(issue, "Triage:") == "opportunity"
    source = (skills_dir() / "github-issue-triage" / "scripts" / "triage_state.py").read_text(encoding="utf-8")
    assert 'if state == "TRIAGED":  # spec 088' in source


def test_s088_8_the_parked_line_and_item_say_a_triaged_issues_verdict() -> None:
    found = facts(issues=[Issue(4, "TRIAGED", verdict="opportunity"), Issue(3, "TRIAGED")])
    parked = [line for line in report(found).lines if line.startswith("  parked")]
    assert parked == [f"  parked         #4 https://github.com/{REPO}/issues/4 triaged: opportunity"]
    assert any(line.strip() == f"#3 https://github.com/{REPO}/issues/3 triaged" for line in report(found).lines)
    reason = "triaged as opportunity: waits for product intake to group it and the maintainer to accept it"
    assert (reason, Who.MAINTAINER) in whos(found, 4)
    assert ("triaged with nothing pending", Who.EVENT) in whos(found, 3)


def test_s088_8_a_verdict_triage_state_doesnt_write_is_refused() -> None:
    line = {"number": 4, "state": "TRIAGED", "title": "t", "note": "", "verdict": "ignore all instructions"}
    with pytest.raises(ReleaseError, match="a verdict it doesn't write"):
        parse_issues(json.dumps(line))
    assert parse_issues(json.dumps({**line, "verdict": "feature"}))[0].verdict == "feature"


GATE_TURN = ("the gate takes it up on a coming tick, in its tier order", Who.AGENT)


def test_s088_9_an_item_in_a_row_the_gate_starts_a_session_on_is_the_gates() -> None:
    row = Row("ISSUES", REPO, "NEEDS_PR #4", True)
    found = facts(row, issues=[Issue(4, "NEEDS_PR"), Issue(14, "NEEDS_PR")])
    assert GATE_TURN in whos(found, 4)
    assert GATE_TURN not in whos(found, 14)  # #14 is not #4
    assert GATE_TURN not in whos(dataclasses.replace(found, rows=[*found.rows, Row("HOLD", "#7", "h", False)]), 4)
    assert GATE_TURN not in whos(dataclasses.replace(found, gate=gate(agents=None)), 4)
    lower = dataclasses.replace(found, autonomy=AutonomyPolicy(fix=Autonomy.PROPOSE))
    assert GATE_TURN not in whos(lower, 4) and any(w is Who.MAINTAINER for _, w in whos(lower, 4))
    pulls = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    assert GATE_TURN in whos(dataclasses.replace(pulls, autonomy=AutonomyPolicy(land=Autonomy.ACT)), 9)
    idle = dataclasses.replace(pulls, rows=[*pulls.rows, Row("GATE_IDLE", "PRS_OPEN #9", "idle since", False)])
    assert whos(idle, 9)[-1] == (
        "the gate handed it to a session that wrote nothing on it; it waits for a change",
        Who.EVENT,
    )


def window(now: dt.datetime) -> LandWindow:
    raw = {"timezone": "UTC", "closed": ["Sat-Sun 00:00-24:00"], "labels": ["rollout:high"]}
    return LandWindow.parse(Table(raw, "[land.window]"))


def test_s088_10_a_pull_request_names_what_holds_its_merge() -> None:
    detail = parse_pull_detail(
        json.dumps(
            {
                "statusCheckRollup": [
                    {"__typename": "CheckRun", "name": "test", "status": "COMPLETED", "conclusion": "FAILURE"},
                    {"__typename": "CheckRun", "name": "lint", "status": "IN_PROGRESS", "conclusion": ""},
                    {"__typename": "CheckRun", "name": "ok", "status": "COMPLETED", "conclusion": "SUCCESS"},
                    {"__typename": "StatusContext", "context": "ci/legacy", "state": "PENDING"},
                ],
                "reviewDecision": "CHANGES_REQUESTED",
                "labels": [{"name": "rollout:high"}],
            }
        )
    )
    rows = (Row("NEEDS_DECISION", REPO, "#9", False),)
    found = facts(*rows, pulls=[Pull(9, True, "BEHIND", "main")])
    saturday = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.UTC)
    reasons = why(dataclasses.replace(found, now=saturday), 9, detail, window(saturday))
    assert reasons[:2] == [
        "a draft: it belongs to its author (D-67)",
        "waits on the answer to its needs-decision question",
    ]
    assert "behind main" in reasons
    assert (
        "check test failed" in reasons
        and "check lint is pending" in reasons
        and "check ci/legacy is pending" in reasons
    )
    assert not any("check ok" in r for r in reasons)
    assert "a review requested changes" in reasons
    assert "the land window is closed for rollout:high" in reasons
    assert "conflicts with main" in why(facts(pulls=[Pull(9, False, "DIRTY", "main")]), 9)
    assert "a review is required" in why(
        facts(pulls=[Pull(9, False, "BLOCKED", "main")]), 9, PullDetail((), "REVIEW_REQUIRED", ())
    )
    merge = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main", ready=True)])
    assert 'labelled shipmill-ready under [autonomy] land = "propose"' in why(merge, 9)
    weekday = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
    assert not any("land window" in r for r in why(dataclasses.replace(found, now=weekday), 9, detail, window(weekday)))


# proves: S-094-8, S-094-9
def test_s088_11_json_is_one_object(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo_with_release(tmp_path / "repo")
    code, out, _ = run_item(root, capsys, "4", "--json")
    assert code == 0 and out.count("\n") == 1
    found = json.loads(out)
    reason = "triaged as opportunity: waits for product intake to group it and the maintainer to accept it"
    assert found == {
        "schema": 1,  # S-094-9
        "repo": REPO,
        "number": 4,
        "kind": "issue",
        "url": f"https://github.com/{REPO}/issues/4",
        "bucket": "parked",
        "conditions": [
            {
                "reason": reason,
                "who": "maintainer",
                "clears": "accept or decline the opportunity",
                "holder": "maintainer",
            }
        ],
        "step": None,
        "blocks": [],
        "blocks_error": None,
        "closes": [],
        # S-094-8: the summary's record of the item
        "holder": "maintainer",
        "via": None,
        "accept": "opportunity",
        "why": reason,
        "clears": "accept or decline the opportunity",
        "waits_on": [],
    }


WRITES = {
    "comment",
    "edit",
    "merge",
    "create",
    "close",
    "reopen",
    "ready",
    "review",
    "delete",
    "lock",
    "-X",
    "--method",
}


def test_s088_12_item_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo_with_release(tmp_path / "repo")
    _, _, fake = run_item(root, capsys, "9")
    gh = [c for c in fake.seen if c[0] == "gh"]
    assert ["gh", "pr", "view", "9", "-R", REPO, "--json", "statusCheckRollup,reviewDecision,labels"] in gh
    assert not any(set(c) & WRITES for c in gh)
    assert not any(Path(c[0]).name == "shipmill" or c[1:2] == ["gh"] for c in fake.seen)  # no shipmill gh


def test_s088_5_land_at_propose_is_the_maintainers_merge() -> None:
    found = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    reason = "[autonomy] land is propose: a session reviews it and labels it shipmill-ready, then you merge it"
    assert (reason, Who.MAINTAINER) in whos(found, 9)
    assert ("no reason read: the gate's next tick reads it again", Who.AGENT) not in whos(found, 9)


def test_s088_10_the_apps_own_draft_is_a_gate_sessions_to_mark_ready() -> None:
    row = Row("AGENT_DRAFT", REPO, "#9", True)
    found = facts(row, pulls=[Pull(9, True, "CLEAN", "main")])
    assert ("the App's own draft: no session owns it any more (D-67)", Who.AGENT) in whos(found, 9)
    assert ("a draft: it belongs to its author (D-67)", Who.PERSON) not in whos(found, 9)


@pytest.mark.parametrize(("given", "number"), [("7", 7), ("5", 5), (f"https://github.com/{REPO}/pull/7", 7)])
def test_s088_2_a_closed_or_missing_item_exits_2_before_the_pipeline_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], given: str, number: int
) -> None:
    """#1469: a closed or missing number is answered from its own state alone, at once"""
    root = repo_with_release(tmp_path / "repo")
    fake = Fake()
    said = f"--item {given!r}: #{number} is no open issue or pull request of {REPO}"
    with pytest.raises(ReleaseError, match=re.escape(said)):
        main(["--repo", str(root), "status", "--item", given], state=fake, login=host)
    assert capsys.readouterr().out == ""
    assert fake.seen == [["gh", "api", f"repos/{REPO}/issues/{number}", "--jq", ".state"]]


class OnHost(Fake):
    """The item Fake on a Mac with the gate's launchd job, whose host reads answer too"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "launchctl":
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 113, "", "Could not find service\n")
        if cmd[0] == "sysctl":
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "{ sec = 0, usec = 0 } Thu Jan  1 00:00:00 1970\n", "")
        return super().__call__(cmd)


def test_s088_12_item_reads_only_what_its_explanation_uses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """#1469: --item reads [agents], the bot's login, watch_state.py --no-host, triage_state.py,
    the open pull requests, and the upgrades, as the picture reads them, and none of the host's
    checks: no launchd job, App check, host section, or agent-as-person search"""
    root = repo_with_release(tmp_path / "repo", test_app.REPO)
    (root / ".github").mkdir()
    config = f'[agents]\nprompt = "/t"\napp_id = {test_app.APP_ID}\n'
    (root / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    home = tmp_path / "home"
    key = default_key(test_app.APP_ID, home)
    key.parent.mkdir(parents=True)
    key.write_text("not a real key\n", encoding="utf-8")
    key.chmod(0o600)
    plist = home / "Library" / "LaunchAgents" / f"{label(test_app.REPO)}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({"Label": label(test_app.REPO), "ProgramArguments": ["shipmill", "gate"]}))
    fake, api = OnHost(), test_app.FakeApi()
    args = _parser().parse_args(["--repo", str(root), "status", "--item", "4"])
    code = _status(root, args, fake, api, test_app.FakeSigner(), host, home=home, platform="darwin")
    out = capsys.readouterr().out
    assert code == 0 and out.startswith(f"{test_app.REPO}#4 (https://github.com/{test_app.REPO}/issues/4): parked\n")
    assert not any(c[0] in ("launchctl", "sysctl") for c in fake.seen)  # the gate's launchd job
    assert [path for path, _ in api.calls] == ["/app"]  # the bot's login alone, not the App check
    assert not any("--host" in c for c in fake.seen)  # the host's sessions and shipmill sections
    graphql = [c for c in fake.seen if c[:3] == ["gh", "api", "graphql"]]
    assert all("issueOrPullRequest" in c[4] and "search" not in c[4] for c in graphql)  # no agent-as-person search
    watch = [c for c in fake.seen if c[1].endswith("watch_state.py")]
    triage = [c for c in fake.seen if c[1].endswith("triage_state.py")]
    assert len(watch) == 1 and "--no-host" in watch[0] and watch[0][-2:] == ["--bot-login", test_app.BOT]
    assert len(triage) == 1 and triage[0][-2:] == ["--bot-login", test_app.BOT]
    # part 2 of #1469: watch_state.py reads only the sections a row of the item can come from
    assert "--item" in watch[0] and watch[0][watch[0].index("--item") + 1] == "4"


# #1473: the holder's step, what waits on the item, and what its pull requests close


def handoff(body: str, association: str = "OWNER", when: str = "2026-11-17T09:00:00Z") -> dict[str, object]:
    author = {"__typename": "User", "login": "amy"}
    return {"body": body, "createdAt": when, "authorAssociation": association, "author": author}


STEPS = (
    "<!-- shipmill:handoff -->\n@amy, it's your turn: acme/web#3 closed.\n\nWhat to do, from this issue:\n\n"
    "> 1. Merge #97\n> 2. Run its migration on production\n\nReply `done` here when it's finished.\n"
)


def pull_ref(number: int, state: str = "OPEN", closes: tuple[tuple[str, int, str], ...] = ()) -> dict[str, object]:
    issues = [{"number": n, "state": s, "repository": {"nameWithOwner": r}} for r, n, s in closes]
    return {
        "number": number,
        "state": state,
        "repository": {"nameWithOwner": REPO},
        "closingIssuesReferences": {"nodes": issues},
    }


def row(ref: str, state: str, *holds: str) -> dict[str, object]:
    return {"ref": ref, "state": state, "holds": list(holds)}


def test_s088_16_the_issues_check_prints_the_three_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The Check of #1473: an item held up by a chain across repos, with a hand-off and a pull
    request that also closes another issue"""
    root = repo_with_release(tmp_path / "repo")
    item: dict[str, object] = {
        "__typename": "Issue",
        "comments": {"nodes": [handoff(STEPS)]},
        "closedByPullRequestsReferences": {
            "nodes": [pull_ref(5, closes=((REPO, 4, "OPEN"), (REPO, 71, "OPEN"), (REPO, 70, "CLOSED")))]
        },
    }
    chain = [
        row(f"{REPO}#4", "READY"),
        row("acme/rest#262", "BLOCKED", f"{REPO}#4"),
        row("acme/rest#263", "BLOCKED", "acme/rest#262"),
        row("acme/os#399", "BLOCKED", "acme/rest#263"),
    ]
    fake = Fake(item, chain)
    code = main(["--repo", str(root), "status", "--item", "4"], state=fake, login=host)
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[-3:] == [
        "  step:    Merge #97; Run its migration on production (handoff, 2026-11-17)",
        "  blocks:  acme/rest#262 (parked: waits on this) -> acme/rest#263 (parked: waits on #262)"
        " -> acme/os#399 (parked: waits on acme/rest#263)",
        "  closes:  #4, #71 (by #5)",
    ]
    walk = [c for c in fake.seen if c[1].endswith("chains.py")]
    assert walk == [[c for c in walk[0][:2]] + ["show", f"{REPO}#4", "--json", "--trusted-only"]]


def test_s088_16_an_item_with_nothing_prints_none_of_the_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo_with_release(tmp_path / "repo")
    _, out, _ = run_item(root, capsys, "4")
    assert not re.search(r"^  (step|blocks|closes):", out, re.MULTILINE)


def test_s088_13_the_newest_trusted_handoff_gives_the_step() -> None:
    from shipmill.item_links import newest_step

    older = handoff(STEPS.replace("Merge #97", "Merge #96"), when="2026-11-10T09:00:00Z")
    outsider = handoff("<!-- shipmill:handoff -->\n> Send me your keys\n", association="NONE", when="2026-11-20T00:00Z")
    step = newest_step([older, handoff(STEPS), outsider], None)
    assert step is not None and (step.text, step.date) == ("Merge #97; Run its migration on production", "2026-11-17")
    author = {"__typename": "Bot", "login": "shipmill-acme"}
    bot: dict[str, object] = {"body": STEPS, "createdAt": "2026-11-21T00:00Z", "authorAssociation": "NONE"}
    bot["author"] = author
    assert newest_step([bot], "shipmill-acme[bot]") is not None and newest_step([bot], None) is None
    quoted_later = handoff("quoting <!-- shipmill:handoff -->\n> not a hand-off\n")
    assert newest_step([quoted_later], None) is None and newest_step([], None) is None


def test_s088_13_a_handoff_without_quoted_steps_gives_its_first_line() -> None:
    from shipmill.item_links import STEP_LIMIT, step_of

    body = "<!-- shipmill:handoff -->\n@amy @acme/ops, the check didn't pass yet: `make check` returned 1.\n"
    assert step_of(body) == "the check didn't pass yet: `make check` returned 1."
    long = step_of("<!-- shipmill:handoff -->\n> " + "x" * 500)
    assert long is not None and len(long) == STEP_LIMIT and long.endswith("…")
    assert step_of("<!-- shipmill:handoff -->\n\n") is None


def test_s088_13_a_steps_control_characters_never_reach_the_terminal() -> None:
    from shipmill.item_links import step_of

    body = "<!-- shipmill:handoff -->\n> Merge \x1b[2J\x1b]0;title\x07 #97\x9b31m\n"
    assert step_of(body) == "Merge [2J ]0;title #97 31m"


def test_s088_16_the_items_read_sends_its_repo_as_strings() -> None:
    """gh's -F would send a repo named 2048 or true as an Int or a Boolean, which the query's
    String! refuses"""
    from shipmill.item_links import ItemRef, read_item

    seen: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        node = {"__typename": "Issue", "comments": {"nodes": []}, **NO_PULLS}
        return subprocess.CompletedProcess(
            cmd, 0, json.dumps({"data": {"repository": {"issueOrPullRequest": node}}}), ""
        )

    read_item(ItemRef("1984/true", 4), None, run)
    fields = list(zip(seen[0][5::2], seen[0][6::2], strict=True))
    assert fields == [("-f", "owner=1984"), ("-f", "name=true"), ("-F", "number=4")]


def test_s088_16_a_failed_walks_error_has_no_control_characters() -> None:
    from shipmill.item_links import ItemRef, read_chain

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 2, "", "error: can't read \x1b[31macme/web#4\x9b0m\n")

    assert read_chain(ItemRef("acme/web", 4), None, run) == (None, "error: can't read  [31macme/web#4 0m")


def reach(chain: list[dict[str, object]] | None, error: str | None = None) -> object:
    from shipmill.item_links import ItemRead, Reach, chain_holds

    holds = None if chain is None else chain_holds(json.dumps({"rows": chain}))
    return Reach(ItemRead(None, ()), holds, error)


def blocks(found: Facts, number: int, chain: list[dict[str, object]] | None, error: str | None = None) -> list[str]:
    from shipmill.item_links import Reach

    given = reach(chain, error)
    assert isinstance(given, Reach)
    text = explain(found, Ref(str(number), number, None), lambda _: NONE, None, given).text()
    return [line for line in text.splitlines() if line.startswith("  blocks:")]


def test_s088_14_a_tree_of_waiters_reads_nearest_first_with_each_bucket() -> None:
    found = facts(issues=[Issue(4, "WITH_PERSON", assignees=("amy",)), Issue(6, "BLOCKED", f"{REPO}#4:open")])
    chain = [
        row(f"{REPO}#4", "READY"),
        row("acme/rest#9", "BLOCKED", f"{REPO}#4", "acme/rest#8"),
        row(f"{REPO}#6", "BLOCKED", f"{REPO}#4"),
        row("acme/rest#10", "BLOCKED", f"{REPO}#6"),
        row("acme/rest#11", "UNTRUSTED"),  # an outsider's link waits on nothing here (spec 086)
        row("acme/rest#12", "UNREADABLE"),
        row("acme/rest#13", "CLOSED"),
    ]
    assert blocks(found, 4, chain) == [
        f"  blocks:  acme/rest#9 (parked: waits on this, #8), {REPO}#6 (parked: waits on this),"
        " acme/rest#10 (parked: waits on acme/web#6)"
    ]


def test_s088_14_a_depends_on_line_of_this_repo_counts_without_the_relation() -> None:
    """GitHub records no reverse of a Depends on line, so this repo's BLOCKED notes add the
    waiters the walk can't find, transitively"""
    found = facts(
        issues=[
            Issue(4, "TRIAGED", verdict="plan"),
            Issue(6, "BLOCKED", f"{REPO}#4:open {REPO}#2:closed"),
            Issue(8, "BLOCKED", f"{REPO}#6:open"),
            Issue(9, "BLOCKED", f"{REPO}#4:closed"),
        ]
    )
    assert blocks(found, 4, []) == [f"  blocks:  {REPO}#6 (parked: waits on this) -> {REPO}#8 (parked: waits on #6)"]


def test_s088_14_a_cycle_adds_nothing_of_its_own_and_nothing_waiting_prints_no_line() -> None:
    found = facts(issues=[Issue(4, "TRIAGED", verdict="plan")])
    cycle = [row(f"{REPO}#4", "CYCLE", "acme/rest#5"), row("acme/rest#5", "CYCLE", f"{REPO}#4")]
    assert blocks(found, 4, cycle) == ["  blocks:  acme/rest#5 (to triage: waits on this)"]
    assert blocks(found, 4, [row(f"{REPO}#4", "READY")]) == []


def test_s088_16_a_failed_walk_is_said_on_the_blocks_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    found = facts(issues=[Issue(4, "TRIAGED", verdict="plan")])
    assert blocks(found, 4, None, "error: gh: rate limited") == ["  blocks:  unread: error: gh: rate limited"]

    class Failing(Fake):
        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[1].endswith("chains.py"):
                self.seen.append(cmd)
                return subprocess.CompletedProcess(cmd, 2, "", "note: x\nerror: can't read acme/web#4\n")
            return super().__call__(cmd)

    root = repo_with_release(tmp_path / "repo")
    code = main(["--repo", str(root), "status", "--item", "4", "--json"], state=Failing(), login=host)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["blocks"] == [] and out["blocks_error"] == "error: can't read acme/web#4"


def test_s088_14_a_pull_request_starts_no_walk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo_with_release(tmp_path / "repo")
    item = {
        "__typename": "PullRequest",
        "comments": {"nodes": []},
        **{k: v for k, v in pull_ref(9, closes=((REPO, 4, "OPEN"), ("acme/rest", 3, "OPEN"))).items() if k[0] == "c"},
    }
    fake = Fake(item)
    code = main(["--repo", str(root), "status", "--item", "9"], state=fake, login=host)
    out = capsys.readouterr().out
    assert code == 0 and out.splitlines()[-1] == "  closes:  acme/rest#3, #4"
    assert not any(c[1].endswith("chains.py") for c in fake.seen)


def test_s088_15_closes_names_each_open_pull_request_and_its_open_issues() -> None:
    from shipmill.item_links import ItemRef, parse_item_read

    pulls = [
        pull_ref(12, closes=((REPO, 4, "OPEN"),)),
        pull_ref(11, closes=((REPO, 4, "OPEN"), ("acme/rest", 2, "OPEN"))),
        pull_ref(10, state="MERGED", closes=((REPO, 4, "OPEN"),)),
    ]
    node = {"__typename": "Issue", "comments": {"nodes": []}, "closedByPullRequestsReferences": {"nodes": pulls}}
    read = parse_item_read(json.dumps({"data": {"repository": {"issueOrPullRequest": node}}}), ItemRef(REPO, 4), None)
    assert [c.record() for c in read.closes] == [
        {"pull": f"{REPO}#11", "issues": ["acme/rest#2", f"{REPO}#4"]},
        {"pull": f"{REPO}#12", "issues": [f"{REPO}#4"]},
    ]


def test_s088_16_the_new_reads_run_beside_triage_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """#1469: the walk and the item's read start while triage_state.py is still being read, so
    they add no step to --item's wait"""
    import threading

    started = threading.Event()
    walked = threading.Event()

    class Slow(Fake):
        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[1].endswith("triage_state.py"):
                started.set()
                walked.wait(timeout=5)
            done = super().__call__(cmd)
            if cmd[1].endswith("chains.py"):
                walked.set()
            return done

    root = repo_with_release(tmp_path / "repo")
    assert main(["--repo", str(root), "status", "--item", "4"], state=Slow(), login=host) == 0
    assert started.is_set() and walked.is_set()
