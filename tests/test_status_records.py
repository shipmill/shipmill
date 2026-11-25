"""Spec 094: `shipmill queue`, one record per open item from one read of the repo's facts, by
the same code as `status --item --json`, with finer holders, a schema version, and a fleet
form over this host's gate jobs read one at a time"""

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from shipmill.agents import Login, Team
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.item_links import ItemRef
from shipmill.item_status import Condition, Holder, Who
from shipmill.launchd import label
from shipmill.queue import Item, items, own_holder
from shipmill.status import Facts, Issue, Pull, Row, parse_issues
from shipmill.status_summary import Holder as SummaryHolder
from shipmill.status_summary import split
from tests.test_status_item import NONE, OPEN, WRITES
from tests.test_status_picture import REPO, facts, host, repo_with_release
from tests.test_status_summary import SummaryFake, configured
from tests.test_triage_off_milestone import FAKE_GH
from tests.test_triage_off_milestone import SCRIPT as TRIAGE_STATE
from tests.test_triage_state import first_page, open_issue

OTHER = "other/lib"


def records(found: Facts) -> dict[int, Item]:
    return items(found, lambda _: NONE, None)


class LinkedFake(SummaryFake):
    """SummaryFake's picture, plus an open issue #2 whose pull request is #9"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("triage_state.py"):
            self.seen.append(cmd)
            lines = [
                {"number": 2, "state": "IN_PROGRESS", "title": "t", "note": "#9:open", "verdict": None},
                {"number": 4, "state": "TRIAGED", "title": "t", "note": "", "verdict": "opportunity"},
            ]
            return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(line) + "\n" for line in lines), "")
        if cmd[:3] == ["gh", "api", "repos/acme/web/issues/2"]:
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "open\n", "")
        return super().__call__(cmd)


def run_queue(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, SummaryFake]:
    fake = SummaryFake()
    code = main(["--repo", str(root), "queue", *args], state=fake, login=host)
    return code, capsys.readouterr().out, fake


# proves: S-094-9
def test_s094_1_every_open_item_has_one_record_on_its_split_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    code, out, _ = run_queue(root, capsys, "--json")
    found = json.loads(out)
    assert code == 0 and out.count("\n") == 1
    assert list(found) == ["schema", "repo", "totals", "split", "items"]  # S-094-9: the schema first
    assert found["schema"] == 1 and found["repo"] == REPO and found["totals"] == {"issues": 1, "pulls": 1}
    assert list(found["split"]) == ["maintainer", "agent", "attention", "people", "elsewhere", "postponed", "nobody"]
    assert [i["number"] for i in found["items"]] == sorted(OPEN)
    keys = {"number", "kind", "holder", "via", "accept", "why", "clears", "waits_on", "parent", "blocks", "conditions"}
    assert all(set(i) == keys for i in found["items"])
    for record in found["items"]:
        line = found["split"][record["holder"]]
        assert record["number"] in line["issues" if record["kind"] == "issue" else "pulls"]


def test_s094_2_own_conditions_or_the_item_it_counts_with_give_why_and_clears() -> None:
    found = facts(
        issues=[Issue(2, "IN_PROGRESS", note="#9:open"), Issue(3, "NEEDS_DECISION")],
        pulls=[Pull(9, False, "DIRTY", "main")],
    )
    got = records(found)
    assert got[9].via is None and got[9].holder is Holder.AGENT
    assert (got[9].why, got[9].clears) == ("conflicts with main", "a session rebases it")
    assert got[2].via == 9 and got[2].holder is Holder.AGENT
    assert (got[2].why, got[2].clears) == (got[9].why, got[9].clears)
    assert got[3].via is None and got[3].why == "waits on the answer to its needs-decision question"


def test_s094_3_waits_on_names_the_open_targets() -> None:
    note = f"waits on {REPO}#11:open, {REPO}#12:closed, {OTHER}#2:open, {OTHER}#3:merged"
    found = facts(
        issues=[
            Issue(3, "BLOCKED", note=note),
            Issue(11, "NEEDS_PR"),
            Issue(2, "IN_PROGRESS", note="#9:open #10:merged"),
        ]
    )
    got = records(found)
    assert got[3].waits_on == (f"{REPO}#11", f"{OTHER}#2")
    assert got[2].waits_on == (f"{REPO}#9",)
    assert got[11].waits_on == ()


@pytest.mark.parametrize(
    ("issue", "holder"),
    [
        (Issue(5, "WITH_PERSON", assignees=("amy",)), Holder.PEOPLE),
        (Issue(5, "TRIAGED", verdict="clarify"), Holder.PEOPLE),
        (Issue(5, "BLOCKED", note=f"waits on {OTHER}#2:open"), Holder.ELSEWHERE),
        (Issue(5, "UPSTREAM"), Holder.ELSEWHERE),
        (Issue(5, "TRIAGED", verdict="upstream"), Holder.ELSEWHERE),
        (Issue(5, "BLOCKED", note="labelled blocked"), Holder.ELSEWHERE),
        (Issue(5, "POSTPONED"), Holder.POSTPONED),
        (Issue(5, "TRIAGED", verdict="postponed"), Holder.POSTPONED),
        (Issue(5, "BLOCKED", note=f"children 0/1 closed waits on {REPO}#6:open"), Holder.POSTPONED),
        (Issue(5, "BLOCKED", note=f"children 0/1 closed waits on {OTHER}#6:open"), Holder.POSTPONED),
        (Issue(5, "BLOCKED", note="veto window of #8 until 2026-11-26T10:00:00Z"), Holder.NOBODY),
    ],
)
def test_s094_4_each_condition_has_its_finer_holder(issue: Issue, holder: Holder) -> None:
    assert records(facts(issues=[issue]))[5].holder is holder


MAINTAINER = (Login("octocat"), Team.parse("@acme/core"))


@pytest.mark.parametrize(
    ("assignees", "teams", "holder"),
    [
        (("octocat",), (), Holder.MAINTAINER),
        (("amy", "OctoCat"), (), Holder.MAINTAINER),  # theirs too, logins compared case-blind
        ((), ("@ACME/core",), Holder.MAINTAINER),
        (("amy",), (), Holder.PEOPLE),
        (("amy",), ("@acme/legal",), Holder.PEOPLE),
    ],
)
def test_s094_4_an_item_assigned_to_the_maintainer_waits_on_them(
    assignees: tuple[str, ...], teams: tuple[str, ...], holder: Holder
) -> None:
    issue = Issue(5, "WITH_PERSON", assignees=assignees, teams=teams)
    got = records(facts(issues=[issue], maintainer=MAINTAINER))[5]
    assert got.holder is holder
    assert got.why.startswith("assigned to you: ") is (holder is Holder.MAINTAINER)
    assert [c.who for c in got.conditions] == [Who.MAINTAINER if holder is Holder.MAINTAINER else Who.PERSON]


class PersonFake(SummaryFake):
    """SummaryFake's picture, plus a person's item #2 assigned to the host's login, the
    maintainer with no [agents.roles], and #3 assigned to someone else"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("triage_state.py"):
            self.seen.append(cmd)
            lines = [
                {"number": 2, "state": "WITH_PERSON", "note": "with @octocat", "assignees": ["octocat"]},
                {"number": 3, "state": "WITH_PERSON", "note": "with @amy", "assignees": ["amy"]},
            ]
            return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(line) + "\n" for line in lines), "")
        if cmd[:2] == ["gh", "api"] and cmd[2] in ("repos/acme/web/issues/2", "repos/acme/web/issues/3"):
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "open\n", "")
        return super().__call__(cmd)


# proves: S-094-8, S-094-13
def test_s094_4_queue_summary_and_item_put_the_maintainers_item_on_waits_on_you(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    main(["--repo", str(root), "queue", "--json"], state=PersonFake(), login=host)
    found = json.loads(capsys.readouterr().out)
    queued = {i["number"]: i for i in found["items"]}
    assert queued[2]["holder"] == "maintainer"
    assert queued[2]["why"] == "assigned to you: a person's item: waits on @octocat"
    assert queued[3]["holder"] == "people"
    assert found["split"]["maintainer"]["issues"] == [2] and found["split"]["people"]["issues"] == [3]
    main(["--repo", str(root), "status", "--item", "2", "--json"], state=PersonFake(), login=host)
    item = json.loads(capsys.readouterr().out)
    assert {k: item[k] for k in queued[2] if k != "number"} == {k: v for k, v in queued[2].items() if k != "number"}
    main(["--repo", str(root), "status", "--summary", "--json"], state=PersonFake(), login=host)
    summary = json.loads(capsys.readouterr().out)
    assert 2 in summary["split"]["maintainer"]["issues"] and 3 in summary["split"]["nobody"]["issues"]


def test_s094_4_a_wait_on_an_item_of_this_repo_is_nobody_and_counts_with_it() -> None:
    found = facts(issues=[Issue(5, "BLOCKED", note=f"waits on {REPO}#6:open"), Issue(6, "POSTPONED")])
    got = records(found)
    assert next(c for c in got[5].conditions).holder is Holder.NOBODY
    assert got[5].holder is Holder.POSTPONED and got[5].via == 6


@pytest.mark.parametrize(
    ("holders", "first"),
    [
        ((Holder.NOBODY, Holder.POSTPONED, Holder.ELSEWHERE, Holder.PEOPLE), Holder.PEOPLE),
        ((Holder.NOBODY, Holder.POSTPONED, Holder.ELSEWHERE), Holder.ELSEWHERE),
        ((Holder.NOBODY, Holder.POSTPONED), Holder.POSTPONED),
        ((Holder.POSTPONED, Holder.AGENT), Holder.AGENT),
    ],
)
def test_s094_5_the_first_holder_in_order(holders: tuple[Holder, ...], first: Holder) -> None:
    assert own_holder([Condition(str(i), Who.EVENT, "c", where=h) for i, h in enumerate(holders)]) is first


def test_s094_5_a_parent_moving_through_its_children_counts_by_its_own_conditions() -> None:
    parent = Issue(5, "BLOCKED", note=f"children 0/1 closed waits on {REPO}#6:open")
    got = records(facts(Row("ISSUES", REPO, "NEEDS_PR #6", True), issues=[parent, Issue(6, "NEEDS_PR")]))
    assert got[6].holder is Holder.AGENT
    assert got[5].holder is Holder.POSTPONED and got[5].via is None


def test_s094_6_opportunities_and_plans_are_marked_to_accept() -> None:
    issues = [
        Issue(1, "TRIAGED", verdict="opportunity"),
        Issue(2, "TRIAGED", verdict="plan"),
        Issue(3, "TRIAGED", verdict="feature"),
        Issue(4, "NEEDS_DECISION"),
    ]
    got = records(facts(issues=issues))
    assert [(got[n].accept, got[n].holder) for n in (1, 2)] == [
        ("opportunity", Holder.MAINTAINER),
        ("plan", Holder.MAINTAINER),
    ]
    assert got[3].accept is None and got[4].accept is None


def test_s094_7_the_text_names_each_item_under_its_holder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    code, out, _ = run_queue(root, capsys)
    assert code == 0
    assert out.splitlines() == [
        f"{REPO}: 1 open issue, 1 pull request",
        "  waits on you",
        "    #4 issue: triaged as opportunity: waits for product intake to group it and the maintainer to accept it"
        " (clears: accept or decline the opportunity)",
        "  agent takes it",
        "    #9 pull: check check failed (clears: a session fixes the cause or reruns a flake)",
        "  needs attention: none",
        "  waits on people: none",
        "  waits elsewhere: none",
        "  postponed: none",
        "  waits on nobody: none",
    ]


def test_s094_10_one_read_of_the_facts_and_no_read_per_item(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    _, _, fake = run_queue(root, capsys, "--json")
    gh = [c for c in fake.seen if c[0] == "gh"]
    detail = ["gh", "pr", "list", "-R", REPO, "--json", "number,statusCheckRollup,reviewDecision,labels", "-L", "1000"]
    assert gh.count(detail) == 1
    assert not any(c[1:3] == ["pr", "view"] for c in gh)  # no read per item
    assert not any(c[1:3] == ["api", f"repos/{REPO}/issues/4"] for c in gh)
    assert not any(set(c) & WRITES for c in gh)
    assert not any(Path(c[0]).name == "shipmill" or c[1:2] == ["gh"] for c in fake.seen)  # no shipmill gh


# proves: S-094-9
def test_s094_8_item_json_agrees_with_the_queues_record(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    main(["--repo", str(root), "queue", "--json"], state=LinkedFake(), login=host)
    summary = {i["number"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert summary[2]["via"] == 9  # counts with its pull request
    for number in (2, 4, 9):
        main(["--repo", str(root), "status", "--item", str(number), "--json"], state=LinkedFake(), login=host)
        item = json.loads(capsys.readouterr().out)
        assert next(iter(item)) == "schema" and item["schema"] == 1  # S-094-9
        assert {k: item[k] for k in summary[number] if k != "number"} == {
            k: v for k, v in summary[number].items() if k != "number"
        }


class RetryFake(LinkedFake):
    """LinkedFake's picture with a GATE_RETRY row naming #9 alone, which watch_state.py --item
    keeps only for #9, as its item_row does"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("watch_state.py") and "--host" not in cmd:
            proc = super().__call__(cmd)
            retry = {
                "state": "GATE_RETRY",
                "subject": "PRS_OPEN #9",
                "detail": "after 2026-11-25T12:15:00+00:00",
                "agent": False,
            }
            rows = [json.loads(line) for line in proc.stdout.splitlines()] + [retry]
            if "--item" in cmd:
                shown = cmd[cmd.index("--item") + 1]
                rows = [
                    r
                    for r in rows
                    if r["state"] == "SHIPMILL_VERSION" or f"#{shown}" in f"{r['subject']} {r['detail']}"
                ]
            return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(r) + "\n" for r in rows), "")
        return super().__call__(cmd)


def test_s094_8_item_json_reads_the_rows_of_the_items_it_counts_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    main(["--repo", str(root), "queue", "--json"], state=RetryFake(), login=host)
    summary = {i["number"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert summary[2]["holder"] == "attention" and summary[2]["via"] == 9
    fake = RetryFake()
    main(["--repo", str(root), "status", "--item", "2", "--json"], state=fake, login=host)
    item = json.loads(capsys.readouterr().out)
    assert {k: item[k] for k in summary[2] if k != "number"} == {k: v for k, v in summary[2].items() if k != "number"}
    # without --json, --item keeps reading only the rows that can name it (#1469)
    main(["--repo", str(root), "status", "--item", "2"], state=(text := RetryFake()), login=host)
    capsys.readouterr()
    assert any("--item" in c for c in text.seen if c[1].endswith("watch_state.py"))
    assert not any("--item" in c for c in fake.seen if c[1].endswith("watch_state.py"))


def gate_job(home: Path, repo: str, checkout: Path) -> None:
    """A gate job's plist as shipmill launchd writes it"""
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    args = ["/u/bin/uvx", "--from", "shipmill@latest", "shipmill", "--repo", str(checkout), "gate", repo]
    job = {"Label": label(repo), "ProgramArguments": args, "WorkingDirectory": str(checkout), "StartInterval": 1800}
    (agents / f"{label(repo)}.plist").write_bytes(plistlib.dumps(job))


def run_fleet(
    home: Path, capsys: pytest.CaptureFixture[str], *args: str, fake: SummaryFake | None = None
) -> tuple[int, str]:
    code = main(["queue", "--fleet", *args], state=fake or SummaryFake(), login=host, home=home)
    return code, capsys.readouterr().out


class LimitedFake(SummaryFake):
    """SummaryFake's picture, whose reads of one repo GitHub refuses for its rate limit"""

    def __init__(self, limited: str) -> None:
        super().__init__()
        self.limited = limited

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "gh" and self.limited in cmd:
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "GraphQL: API rate limit already exceeded for user ID 1.\n")
        return super().__call__(cmd)


def test_s094_11_the_fleet_form_reads_every_gate_job(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    gate_job(home, REPO, configured(repo_with_release(tmp_path / "web")))
    gate_job(home, "acme/api", configured(repo_with_release(tmp_path / "api", "acme/api")))
    code, out = run_fleet(home, capsys, "--json")
    found = json.loads(out)
    assert code == 0 and out.count("\n") == 1
    assert found["schema"] == 1 and [r["repo"] for r in found["repos"]] == ["acme/api", REPO]  # plist order
    assert all(list(r) == ["schema", "repo", "totals", "split", "items"] for r in found["repos"])
    code, text = run_fleet(home, capsys)
    assert code == 0 and text.startswith("acme/api: 1 open issue") and f"\n\n{REPO}: 1 open issue" in text
    empty = tmp_path / "nobody"
    assert run_fleet(empty, capsys, "--json") == (0, '{"schema": 1, "repos": []}\n')
    assert run_fleet(empty, capsys) == (0, "no gate job on this host\n")


def test_s094_12_a_failed_repo_is_its_entry_and_the_rest_print(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    gate_job(home, REPO, configured(repo_with_release(tmp_path / "web")))
    gate_job(home, "acme/api", repo_with_release(tmp_path / "api", "acme/elsewhere"))  # another repo's checkout
    code, out = run_fleet(home, capsys, "--json")
    api, web = json.loads(out)["repos"]
    assert code == 2
    assert api["repo"] == "acme/api" and set(api) == {"schema", "repo", "error"} and "not acme/api" in api["error"]
    assert web["repo"] == REPO and "items" in web
    code, text = run_fleet(home, capsys)
    assert code == 2 and text.startswith("acme/api: unread: ") and f"{REPO}: 1 open issue" in text


def test_s094_12_a_rate_limit_stops_the_fleet_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    gate_job(home, "acme/api", configured(repo_with_release(tmp_path / "api", "acme/api")))
    gate_job(home, "acme/cli", configured(repo_with_release(tmp_path / "cli", "acme/cli")))
    gate_job(home, REPO, configured(repo_with_release(tmp_path / "web")))
    fake = LimitedFake("acme/api")
    code, out = run_fleet(home, capsys, "--json", fake=fake)
    api, cli, web = json.loads(out)["repos"]
    assert code == 2 and "rate limit" in str(api["error"])
    for entry, repo in ((cli, "acme/cli"), (web, REPO)):
        assert entry == {
            "schema": 1,
            "repo": repo,
            "error": "not read: GitHub's rate limit was reached on an earlier repo",
        }
    assert not any(repo in c for c in fake.seen for repo in ("acme/cli", REPO))  # nothing of theirs was read


class StateLimitedFake(SummaryFake):
    """SummaryFake's picture, whose watch_state.py run for one repo fails on GitHub's rate limit"""

    def __init__(self, limited: str) -> None:
        super().__init__()
        self.limited = limited

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("watch_state.py") and self.limited in cmd:
            self.seen.append(cmd)
            said = f"error: gh repo view {self.limited}: GraphQL: API rate limit already exceeded for user ID 1.\n"
            return subprocess.CompletedProcess(cmd, 2, "", said)
        return super().__call__(cmd)


def test_s094_12_a_rate_limit_in_watch_state_stops_the_fleet_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    gate_job(home, "acme/api", configured(repo_with_release(tmp_path / "api", "acme/api")))
    gate_job(home, REPO, configured(repo_with_release(tmp_path / "web")))
    fake = StateLimitedFake("acme/api")
    code, out = run_fleet(home, capsys, "--json", fake=fake)
    api, web = json.loads(out)["repos"]
    assert code == 2 and "watch_state.py failed (exit 2)" in str(api["error"]) and "rate limit" in str(api["error"])
    assert web["error"] == "not read: GitHub's rate limit was reached on an earlier repo"
    assert not any(REPO in c for c in fake.seen)


def test_s094_10_a_pull_request_missing_from_the_detail_list_reads_no_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class NewPull(SummaryFake):
        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["gh", "pr", "list"] and "statusCheckRollup" in cmd[cmd.index("--json") + 1]:
                self.seen.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "[]", "")  # #9 opened between the two lists
            return super().__call__(cmd)

    root = configured(repo_with_release(tmp_path / "repo"))
    fake = NewPull()
    assert main(["--repo", str(root), "queue", "--json"], state=fake, login=host) == 0
    record = {i["number"]: i for i in json.loads(capsys.readouterr().out)["items"]}[9]
    assert not any(c[1:3] == ["pr", "view"] for c in fake.seen)
    assert "check" not in record["why"]  # no checks read for it yet


def test_s094_12_fleet_with_a_repo_exits_2(tmp_path: Path) -> None:
    fake = SummaryFake()
    with pytest.raises(ReleaseError, match="--fleet reads every gate job on this host"):
        main(["queue", "--fleet", REPO], state=fake, login=host, home=tmp_path)
    assert fake.seen == []


def test_s094_13_the_summary_keeps_its_four_lines_and_folds_the_finer_holders() -> None:
    issues = [Issue(1, "WITH_PERSON", assignees=("amy",)), Issue(2, "UPSTREAM"), Issue(3, "POSTPONED")]
    found = facts(issues=issues)
    assert {records(found)[n].holder for n in (1, 2, 3)} == {Holder.PEOPLE, Holder.ELSEWHERE, Holder.POSTPONED}
    assert split(found, lambda _: NONE, None).issues == {SummaryHolder.NOBODY: (1, 2, 3)}


def test_s094_13_the_summary_counts_the_maintainers_assigned_item_as_waiting_on_you() -> None:
    issues = [Issue(1, "WITH_PERSON", assignees=("octocat",)), Issue(2, "WITH_PERSON", assignees=("amy",))]
    found = facts(issues=issues, maintainer=MAINTAINER)
    assert split(found, lambda _: NONE, None).issues == {SummaryHolder.MAINTAINER: (1,), SummaryHolder.NOBODY: (2,)}


class ChainFake(SummaryFake):
    """SummaryFake's picture, whose triage_state.py gives each repo the lines in lines; acme/web's
    #4 has #5 waiting on it, #6 on #5, and its umbrella #7"""

    def __init__(self, lines: dict[str, list[dict[str, object]]] | None = None) -> None:
        super().__init__()
        self.lines = lines if lines is not None else {REPO: WEB}

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("triage_state.py") and cmd[2] in self.lines:
            self.seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(r) + "\n" for r in self.lines[cmd[2]]), "")
        return super().__call__(cmd)


WEB: list[dict[str, object]] = [
    {"number": 4, "state": "TRIAGED", "title": "t", "note": "", "verdict": "opportunity", "parent": f"{REPO}#7"},
    {"number": 5, "state": "BLOCKED", "title": "t", "note": f"waits on {REPO}#4:open"},
    {"number": 6, "state": "BLOCKED", "title": "t", "note": f"waits on {REPO}#5:open, {OTHER}#2:open"},
    {"number": 7, "state": "BLOCKED", "title": "t", "note": f"children 0/1 closed waits on {REPO}#4:open(child)"},
]


def test_s094_14_blocks_and_parent_come_from_the_facts() -> None:
    found = facts(
        issues=[
            Issue(4, "NEEDS_PR", parent=f"{OTHER}#7"),
            Issue(5, "BLOCKED", note=f"waits on {REPO}#4:open"),
            Issue(6, "BLOCKED", note=f"waits on {REPO}#5:open, {REPO}#4:closed"),
            Issue(8, "NEEDS_PR"),
        ]
    )
    got = records(found)
    assert [(str(w.ref), w.waits_on) for w in got[4].blocks] == [
        (f"{REPO}#5", (ItemRef(REPO, 4),)),  # nearest first, as --item's walk lists them
        (f"{REPO}#6", (ItemRef(REPO, 5),)),  # a closed hold holds nothing
    ]
    assert got[4].parent == f"{OTHER}#7" and got[5].parent is None
    assert got[8].blocks == () and got[6].blocks == ()
    assert got[4].record()["blocks"] == [
        {"ref": f"{REPO}#5", "bucket": "parked", "waits_on": [f"{REPO}#4"]},
        {"ref": f"{REPO}#6", "bucket": "parked", "waits_on": [f"{REPO}#5"]},
    ]


# proves: S-094-10, S-094-9
def test_s094_14_queue_prints_blocks_and_parent_with_no_read_per_item(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    fake = ChainFake()
    main(["--repo", str(root), "queue", "--json"], state=fake, login=host)
    found = json.loads(capsys.readouterr().out)
    assert found["schema"] == 1
    got = {i["number"]: i for i in found["items"]}
    assert got[4]["parent"] == f"{REPO}#7" and got[5]["parent"] is None and got[9]["parent"] is None
    assert [b["ref"] for b in got[4]["blocks"]] == [
        f"{REPO}#5",
        f"{REPO}#7",
        f"{REPO}#6",
    ]  # a parent waits on its child
    assert got[6]["blocks"] == [] and got[9]["blocks"] == []
    gh = [c for c in fake.seen if c[0] == "gh"]
    assert not any(c[1:3] in (["pr", "view"], ["issue", "view"]) for c in gh)
    assert not any(c[1:3] == ["api", "graphql"] and "issueOrPullRequest" in c[4] for c in gh)  # no item's own read
    assert not any(c[1].endswith("chains.py") for c in fake.seen)  # no walk per item


def test_s094_14_triage_states_parent_is_strict() -> None:
    line = {"number": 4, "state": "NEW", "title": "t", "note": "", "parent": "acme/web#7"}
    assert parse_issues(json.dumps(line))[0].parent == "acme/web#7"
    assert parse_issues(json.dumps({k: v for k, v in line.items() if k != "parent"}))[0].parent is None
    for bad in ("#7", "acme/web", 7, "acme/web#0"):
        with pytest.raises(ReleaseError, match="parent"):
            parse_issues(json.dumps(line | {"parent": bad}))


@pytest.mark.parametrize(("state", "shown"), [("OPEN", "Acme/Home#3"), ("CLOSED", None)])
def test_s094_14_triage_state_prints_an_open_parent(tmp_path: Path, state: str, shown: str | None) -> None:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    item = open_issue(7, [])
    item["parent"] = {"number": 3, "state": state, "repository": {"nameWithOwner": "Acme/Home"}, "milestone": None}
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({"data": {"repository": first_page([item])}}), encoding="utf-8")
    env = {"PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "FAKE_GH_DATA": str(data)}
    proc = subprocess.run(
        [sys.executable, str(TRIAGE_STATE), "o/r", "--json"], capture_output=True, text=True, check=False, env=env
    )
    line = json.loads(proc.stdout.splitlines()[0])
    assert line["number"] == 7, proc.stderr
    assert line.get("parent") == shown


def test_s094_15_the_fleet_lists_another_repos_waiters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    gate_job(home, "acme/api", configured(repo_with_release(tmp_path / "api", "acme/api")))
    gate_job(home, REPO, configured(repo_with_release(tmp_path / "web")))
    api = [
        {"number": 2, "state": "BLOCKED", "title": "t", "note": f"waits on {REPO}#4:open"},
        {"number": 4, "state": "NEEDS_PR", "title": "t", "note": ""},
    ]
    fake = ChainFake({"acme/api": api, REPO: WEB})
    code, out = run_fleet(home, capsys, "--json", fake=fake)
    assert code == 0
    by = {r["repo"]: {i["number"]: i for i in r["items"]} for r in json.loads(out)["repos"]}
    web = by[REPO][4]["blocks"]
    assert {"ref": "acme/api#2", "bucket": "parked", "waits_on": [f"{REPO}#4"]} in web
    assert [b["ref"] for b in web] == ["acme/api#2", f"{REPO}#5", f"{REPO}#7", f"{REPO}#6"]
    assert by["acme/api"][4]["blocks"] == []  # acme/api#4 is not acme/web#4
    triage = [c for c in fake.seen if c[1].endswith("triage_state.py")]
    assert sorted(c[2] for c in triage) == ["acme/api", REPO]  # one read of each repo


def test_s094_16_item_json_carries_the_queues_parent_and_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    main(["--repo", str(root), "queue", "--json"], state=ChainFake(), login=host)
    summary = {i["number"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    for number in (4, 9):  # the fake's open items
        main(["--repo", str(root), "status", "--item", str(number), "--json"], state=ChainFake(), login=host)
        item = json.loads(capsys.readouterr().out)
        assert item["schema"] == 1
        assert {k: item[k] for k in summary[number] if k != "number"} == {
            k: v for k, v in summary[number].items() if k != "number"
        }
    assert summary[4]["parent"] == f"{REPO}#7" and len(summary[4]["blocks"]) == 3
