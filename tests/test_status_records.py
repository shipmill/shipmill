"""Spec 094: one record per open item in `status --summary --json`, from the same code as
`status --item --json`, with finer holders, a schema version, and a fleet form over this
host's gate jobs"""

import json
import plistlib
import subprocess
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.item_status import Condition, Holder, Who
from shipmill.launchd import label
from shipmill.status import Facts, Issue, Pull, Row
from shipmill.status_summary import Item, items, own_holder
from tests.test_status_item import NONE, OPEN
from tests.test_status_picture import REPO, facts, host, repo_with_release
from tests.test_status_summary import SummaryFake, configured, run_summary

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


def test_s094_1_every_open_item_has_one_record_on_its_split_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    code, out, _ = run_summary(root, capsys, "--json")
    found = json.loads(out)
    assert code == 0 and [i["number"] for i in found["items"]] == sorted(OPEN)
    keys = {"number", "kind", "holder", "via", "accept", "why", "clears", "waits_on", "conditions"}
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
        (Issue(5, "BLOCKED", note="veto window of #8 until 2026-11-26T10:00:00Z"), Holder.NOBODY),
    ],
)
def test_s094_4_each_condition_has_its_finer_holder(issue: Issue, holder: Holder) -> None:
    assert records(facts(issues=[issue]))[5].holder is holder


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


def test_s094_8_item_json_agrees_with_the_summarys_record(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = configured(repo_with_release(tmp_path / "repo"))
    main(["--repo", str(root), "status", "--summary", "--json"], state=LinkedFake(), login=host)
    summary = {i["number"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert summary[2]["via"] == 9  # counts with its pull request
    for number in (2, 4, 9):
        main(["--repo", str(root), "status", "--item", str(number), "--json"], state=LinkedFake(), login=host)
        item = json.loads(capsys.readouterr().out)
        assert item["schema"] == 1  # S-094-9
        assert {k: item[k] for k in summary[number] if k != "number"} == {
            k: v for k, v in summary[number].items() if k != "number"
        }


def gate_job(home: Path, repo: str, checkout: Path) -> None:
    """A gate job's plist as shipmill launchd writes it"""
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    args = ["/u/bin/uvx", "--from", "shipmill@latest", "shipmill", "--repo", str(checkout), "gate", repo]
    job = {"Label": label(repo), "ProgramArguments": args, "WorkingDirectory": str(checkout), "StartInterval": 1800}
    (agents / f"{label(repo)}.plist").write_bytes(plistlib.dumps(job))


def run_fleet(home: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = main(["status", "--summary", "--host", *args], state=SummaryFake(), login=host, home=home)
    return code, capsys.readouterr().out


def test_s094_10_the_fleet_form_summarizes_every_gate_job(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    gate_job(home, REPO, configured(repo_with_release(tmp_path / "web")))
    gate_job(home, "acme/api", configured(repo_with_release(tmp_path / "api", "acme/api")))
    code, out = run_fleet(home, capsys, "--json")
    found = json.loads(out)
    assert code == 0 and out.count("\n") == 1
    assert found["schema"] == 1 and [r["repo"] for r in found["repos"]] == ["acme/api", REPO]  # plist order
    assert all(set(r) == {"schema", "repo", "gate", "totals", "split", "items"} for r in found["repos"])
    code, text = run_fleet(home, capsys)
    assert code == 0 and text.startswith("acme/api: 1 open issue") and f"\n\n{REPO}: 1 open issue" in text
    empty = tmp_path / "nobody"
    assert run_fleet(empty, capsys, "--json") == (0, '{"schema": 1, "repos": []}\n')
    assert run_fleet(empty, capsys) == (0, "no gate job on this host\n")


def test_s094_11_a_failed_repo_is_its_entry_and_the_rest_print(
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


@pytest.mark.parametrize("args", [["--host"], ["--host", "--json"], ["--summary", "--host", REPO]])
def test_s094_11_host_without_summary_or_with_a_repo_exits_2(tmp_path: Path, args: list[str]) -> None:
    fake = SummaryFake()
    with pytest.raises(ReleaseError, match="--host reads every gate job on this host"):
        main(["status", *args], state=fake, login=host, home=tmp_path)
    assert fake.seen == []
