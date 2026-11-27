"""The watch's SPEC_DUE and FEEDBACK_DUE rows from product intake's feedback (spec 074), read
without the network: the rows from intake_state.py's lines, and the full report, --sweep, and
--tier 7 run as the gate runs them, with a fake gh on PATH"""

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

from shipmill import walk as gate_walk
from shipmill.findings import Finding
from shipmill.gate import parse_findings
from shipmill.status import Row as StatusRow
from shipmill.status import report

from .test_status_picture import REPO as STATUS_REPO
from .test_status_picture import facts
from .test_watch_gate_idle import Host

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
BOT = "shipmill-app[bot]"
NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)  # noqa: UP017 (the script runs under 3.10 too)
SECRET = "SECRET-TEXT"  # every title, body, and note an issue holds: never in a row (D-16)
TRIAGE_FIX = "/shipmill:github-issue-triage o/r"
INTAKE_FIX = "/shipmill:product-intake o/r"


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_feedback", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def ago(hours: float, now: dt.datetime = NOW) -> str:
    return (now - dt.timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def line(
    number: int,
    state: str = "NEW_FEEDBACK",
    kind: str = "issue",
    handed: str | None = None,
    author: str | None = "amy",
    association: str | None = "OWNER",
) -> dict[str, Any]:
    """One NEW_FEEDBACK or ACCEPTED line as intake_state.py --json prints it (spec 074)"""
    found = {
        "number": number,
        "kind": kind,
        "state": state,
        "title": SECRET,
        "thumbs": 0,
        "members": [],
        "note": SECRET,
    }
    return found | {"author": author, "association": association, "handed": handed}


def lines(*rows: dict[str, Any], level: str = "propose") -> str:
    plan = {"goal": "G-1", "kind": "goal", "number": None, "state": "PLAN_DUE", "title": SECRET, "note": "no-work"}
    other = {"number": 40, "kind": "opportunity", "state": "OPPORTUNITY_OPEN", "title": SECRET, "note": ""}
    shown = [{"autonomy": level}, *rows, other | {"thumbs": 0, "members": []}, plan | {"author": None}]
    return "\n".join(json.dumps(r, sort_keys=True) for r in shown) + "\n"


def by_state(found: Any) -> dict[str, Any]:
    return {r.state: r for r in found.rows}


# -- S-074-3: one intake_state.py run per repo ------------------------------------------------


def completed(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


def test_s074_3_intake_state_runs_without_plans_and_with_them(ws: ModuleType, tmp_path: Path) -> None:
    asked: list[list[str]] = []

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        asked.append(cmd)
        assert cwd == tmp_path
        return completed(1, lines(line(4)))

    # no docs/product.md: no --plans, and none of the flags only --plans takes
    ws.intake_run("o/r", tmp_path, False, "shipmill==1.2.3", BOT, 3, execute, roles=["maintainer=amy"])
    assert asked[-1][1:] == [str(ws.INTAKE_STATE), "o/r", "--json", "--bot-login", BOT]
    ws.intake_run("o/r", tmp_path, True, None, BOT, 3, execute, roles=["maintainer=amy"])
    want = [str(ws.INTAKE_STATE), "o/r", "--plans", "--goals", "--projects", "--json", "--wip", "3", "--bot-login", BOT]
    assert asked[-1][1:] == [*want, "--role", "maintainer=amy"]
    # a run that exits 2 stops the watch
    for plans in (False, True):
        with pytest.raises(ws.Refused, match="exit 2: boom"):
            ws.intake_run("o/r", tmp_path, plans, "t", execute=lambda cmd, cwd, env: completed(2, err="boom"))


# -- the full report, --sweep, and --tier 7, as the gate reads them ------------------------

# answers intake_state.py's reads of the open issues and the opportunities from FAKE_INTAKE (or
# fails them with FAKE_INTAKE_FAIL), logs every call, and hands the rest to the full report's fake
FEEDBACK_GH = """#!{python}
import json, os, subprocess, sys
args = sys.argv[1:]
joined = " ".join(args)
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["api", "graphql"] and "issues(" in joined and "open:" not in joined:
    if os.environ.get("FAKE_INTAKE_FAIL"):
        sys.stderr.write("boom\\n")
        sys.exit(1)
    data = json.loads(os.environ["FAKE_INTAKE"])
    nodes = data["opportunities"] if "labels: [$label]" in joined else data["open"]
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
    print(json.dumps({"data": {"repository": {"hasDiscussionsEnabled": False, "issues": page}}}))
    sys.exit(0)
sys.exit(subprocess.run([sys.executable, os.environ["FAKE_GH"], *args]).returncode)
"""
# a uvx that logs its call and fails, so intake_state.py --plans exits 2 at its goals read
FAILING_UVX = """#!{python}
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["uvx", *sys.argv[1:]]) + "\\n")
sys.stderr.write("boom\\n")
sys.exit(1)
"""


def node(
    number: int,
    *labels: str,
    association: str = "OWNER",
    comments: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """One open issue as intake_state.py's GraphQL read returns it; every text field is SECRET"""
    said = [
        {"body": body, "createdAt": at, "author": {"__typename": "User", "login": "amy"}, "authorAssociation": "OWNER"}
        for body, at in comments
    ]
    return {
        "number": number,
        "title": SECRET,
        "url": f"https://github.com/o/r/issues/{number}",
        "state": "OPEN",
        "stateReason": None,
        "closedAt": None,
        "body": SECRET,
        "milestone": None,
        "author": {"__typename": "User", "login": f"user{number}"},
        "authorAssociation": association,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "reactions": {"totalCount": 0},
        "comments": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": said},
    }


def handed(hours: float) -> tuple[tuple[str, str], ...]:
    """Triage's hand-off comment, posted hours before the real now (the script reads the clock)"""
    return ((f"Triage: **opportunity**. {SECRET}", ago(hours, dt.datetime.now(dt.timezone.utc))),)  # noqa: UP017


def feedback_host(tmp_path: Path, level: str = "propose", *, outsider: bool = False) -> Host:
    """A checkout without docs/product.md, whose intake holds an accepted opportunity (#30), a
    request handed over two days ago (#31), one handed over an hour ago (#32), and one triage
    never handed over (#33); with outsider, #31 is opened by someone with no association"""
    host = Host(tmp_path)
    fakes = host.tmp / "fakes"
    (fakes / "gh-full").write_bytes((fakes / "gh").read_bytes())
    (fakes / "gh-full").chmod(0o700)
    (fakes / "gh").write_text(FEEDBACK_GH.replace("{python}", sys.executable), encoding="utf-8")
    config = f'mode = "off"\n\n[autonomy]\nintake = "{level}"\n'
    (host.work / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    opportunity = node(30, "opportunity", "planned")
    open_issues = [
        node(31, association="NONE" if outsider else "OWNER", comments=handed(48)),
        node(32, comments=handed(1)),
        node(33),
    ]
    intake = {"open": open_issues, "opportunities": [opportunity]}
    host.env |= {
        "FAKE_LOG": str(host.tmp / "gh.log"),
        "FAKE_GH": str(fakes / "gh-full"),
        "FAKE_INTAKE": json.dumps(intake),
    }
    return host


def shown(proc: subprocess.CompletedProcess[str]) -> dict[str, dict[str, Any]]:
    assert proc.returncode in (0, 1), proc.stderr
    return {row["state"]: row for row in map(json.loads, proc.stdout.splitlines())}


def calls(host: Host) -> list[list[str]]:
    return [json.loads(c) for c in (host.tmp / "gh.log").read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def propose(tmp_path_factory: pytest.TempPathFactory) -> Host:
    return feedback_host(tmp_path_factory.mktemp("propose"))


@pytest.fixture(scope="module")
def observe(tmp_path_factory: pytest.TempPathFactory) -> Host:
    return feedback_host(tmp_path_factory.mktemp("observe"), "observe")


def test_s074_3_the_watch_runs_intake_state_on_a_checkout_without_a_direction(propose: Host) -> None:
    rows = shown(propose.watch("--no-host"))
    assert {"SPEC_DUE", "FEEDBACK_DUE"} <= set(rows)
    reads = [c for c in calls(propose) if c[:2] == ["api", "graphql"] and "hasDiscussionsEnabled" in " ".join(c)]
    assert reads  # intake_state.py read the open issues, without --plans: no uvx on this host
    assert not any(c[0] == "uvx" for c in calls(propose))


def test_s074_3_a_failing_intake_state_run_stops_the_watch_with_exit_2(tmp_path: Path) -> None:
    host = feedback_host(tmp_path)
    host.env |= {"FAKE_INTAKE_FAIL": "1"}
    proc = host.watch("--no-host")
    assert proc.returncode == 2 and "error: intake_state.py failed with exit 2" in proc.stderr
    # with docs/product.md the run takes --plans, and its goals read failing stops the watch too
    host.env.pop("FAKE_INTAKE_FAIL")
    (host.work / "docs").mkdir()
    (host.work / "docs" / "product.md").write_text("# r\n", encoding="utf-8")
    (host.tmp / "fakes" / "uvx").write_text(FAILING_UVX.replace("{python}", sys.executable), encoding="utf-8")
    (host.tmp / "fakes" / "uvx").chmod(0o700)
    proc = host.watch("--no-host")
    assert proc.returncode == 2 and "error: intake_state.py --plans failed with exit 2" in proc.stderr
    assert any(c[0] == "uvx" and "product" in c and "show" in c for c in calls(host))


# -- S-074-4: SPEC_DUE --------------------------------------------------------------------


def test_s074_4_spec_due_names_every_accepted_opportunity_oldest_first(ws: ModuleType) -> None:
    text = lines(line(9, "ACCEPTED", "opportunity"), line(5, "ACCEPTED", "opportunity"), line(7, handed=None))
    row = by_state(ws.feedback_rows(text, "o/r", NOW))["SPEC_DUE"]
    assert (row.subject, row.detail, row.fix) == ("o/r", "ACCEPTED #5 #9", TRIAGE_FIX)
    assert row.json()["agent"] is True and row.action
    # none accepted: no SPEC_DUE row, and the other feedback lines make none either
    assert "SPEC_DUE" not in by_state(ws.feedback_rows(lines(line(7, handed=ago(48))), "o/r", NOW))
    assert ws.feedback_rows(lines(), "o/r", NOW) == ws.Feedback([], frozenset())


def test_s074_4_the_full_report_lists_spec_due(propose: Host) -> None:
    row = shown(propose.watch("--no-host"))["SPEC_DUE"]
    assert (row["subject"], row["detail"], row["fix"], row["agent"]) == ("o/r", "ACCEPTED #30", TRIAGE_FIX, True)


# -- S-074-5: FEEDBACK_DUE ----------------------------------------------------------------


def test_s074_5_feedback_due_names_the_requests_handed_over_a_day_ago_oldest_hand_off_first(ws: ModuleType) -> None:
    text = lines(
        line(3, handed=ago(25)),
        line(4, handed=ago(23.9)),  # handed over less than 24 hours before: in no row
        line(7, handed=ago(48)),
        line(8, handed=ago(24)),  # exactly FEEDBACK_AFTER: due
        line(6, handed=None),  # triage never handed it over: triage's (NEW)
        line(10, kind="discussion", handed=None, association=None),  # a discussion: in no row
    )
    row = by_state(ws.feedback_rows(text, "o/r", NOW))["FEEDBACK_DUE"]
    assert (row.subject, row.detail, row.fix) == ("o/r", "NEW_FEEDBACK #7 #3 #8", INTAKE_FIX)
    assert dt.timedelta(hours=24) == ws.FEEDBACK_AFTER
    early = lines(line(4, handed=ago(23.9)), line(6), line(10, kind="discussion", association=None))
    assert ws.feedback_rows(early, "o/r", NOW).rows == []


def test_s074_5_the_full_report_lists_only_the_request_handed_over_two_days_ago(propose: Host) -> None:
    row = shown(propose.watch("--no-host"))["FEEDBACK_DUE"]
    assert (row["detail"], row["fix"]) == ("NEW_FEEDBACK #31", INTAKE_FIX)


@pytest.mark.parametrize(
    "bad",
    [
        {"number": "4"},
        {"number": True},
        {"handed": "yesterday"},
        {"handed": "2026-11-18T10:00:00"},  # no time zone
        {"author": ""},
        {"association": "owner"},
        {"kind": "issue", "state": "ACCEPTED"},
        {"kind": "opportunity", "state": "NEW_FEEDBACK"},
    ],
)
def test_s074_5_a_malformed_feedback_line_is_refused(ws: ModuleType, bad: dict[str, Any]) -> None:
    with pytest.raises(ws.Refused, match="malformed feedback row"):
        ws.feedback_rows(lines(line(4, handed=ago(48)) | bad), "o/r", NOW)
    missing = {k: v for k, v in line(4).items() if k != "handed"}
    with pytest.raises(ws.Refused, match="malformed feedback row"):
        ws.feedback_rows(lines(missing), "o/r", NOW)


def test_s074_5_intake_states_first_line_must_be_its_autonomy_line(ws: ModuleType) -> None:
    for first in ("", json.dumps({"autonomy": "act"}), json.dumps({"autonomy": "propose", "x": 1}), "not json"):
        with pytest.raises(ws.Refused, match="autonomy line"):
            ws.feedback_rows(first + "\n" + json.dumps(line(4)), "o/r", NOW)


# -- S-074-6: report-only under intake = "observe" ------------------------------------------


def test_s074_6_feedback_due_is_report_only_under_observe(ws: ModuleType) -> None:
    text = lines(line(5, "ACCEPTED", "opportunity"), line(7, handed=ago(48)), level="observe")
    rows = by_state(ws.feedback_rows(text, "o/r", NOW))
    assert rows["FEEDBACK_DUE"].report_only and not rows["FEEDBACK_DUE"].action
    assert rows["FEEDBACK_DUE"].json()["agent"] is False
    assert not rows["SPEC_DUE"].report_only and rows["SPEC_DUE"].json()["agent"] is True
    proposed = by_state(ws.feedback_rows(text.replace('"observe"', '"propose"'), "o/r", NOW))
    assert not proposed["FEEDBACK_DUE"].report_only and proposed["FEEDBACK_DUE"].json()["agent"] is True
    with pytest.raises(ValueError, match="only a FEEDBACK_DUE row"):
        ws.Row("SPEC_DUE", "o/r", "ACCEPTED #5", TRIAGE_FIX, report_only=True)


@pytest.mark.parametrize("read", [["--no-host"], ["--sweep"], ["--tier", "7"]], ids=["full", "sweep", "tier7"])
def test_s074_6_spec_due_prints_in_every_read_and_feedback_due_only_where_its_level_lets_it(
    observe: Host, propose: Host, read: list[str]
) -> None:
    under_observe, under_propose = shown(observe.watch(*read)), shown(propose.watch(*read))
    assert "SPEC_DUE" in under_observe and "SPEC_DUE" in under_propose
    assert under_propose["FEEDBACK_DUE"]["agent"] is True
    if read == ["--no-host"]:  # the full report prints it, as no agent's row
        assert under_observe["FEEDBACK_DUE"]["agent"] is False
    else:  # the gate's reads never print a report-only row
        assert "FEEDBACK_DUE" not in under_observe


def test_s074_6_an_observe_feedback_due_alone_changes_no_exit_code(ws: ModuleType, tmp_path: Path) -> None:
    host = feedback_host(tmp_path, "observe")
    intake = json.loads(host.env["FAKE_INTAKE"]) | {"opportunities": []}
    host.env |= {"FAKE_INTAKE": json.dumps(intake)}
    proc = host.watch("--no-host")
    rows = shown(proc)
    assert rows["FEEDBACK_DUE"]["agent"] is False and "SPEC_DUE" not in rows
    assert proc.returncode == (1 if any(s in ws.ACTION for s in set(rows) - {"FEEDBACK_DUE"}) else 0)


# -- S-074-7: --trusted-only ----------------------------------------------------------------


def test_s074_7_an_outsiders_request_or_opportunity_is_in_untrusted_and_no_row(ws: ModuleType) -> None:
    text = lines(
        line(20, handed=ago(48), author="drive-by", association="NONE"),
        line(21, "ACCEPTED", "opportunity", author="drive-by", association="CONTRIBUTOR"),
        line(22, handed=ago(48), author="Shipmill-App[bot]", association="NONE"),  # the --bot-login, any case
        line(23, "ACCEPTED", "opportunity", association="MEMBER"),
        line(24, handed=None, author=None, association="NONE"),  # handed over or not, an outsider's
    )
    found = ws.feedback_rows(text, "o/r", NOW, BOT, trusted_only=True)
    assert {r.state: r.detail for r in found.rows} == {"SPEC_DUE": "ACCEPTED #23", "FEEDBACK_DUE": "NEW_FEEDBACK #22"}
    assert found.untrusted == frozenset({20, 21, 24})
    # without --trusted-only every one is listed, and none is untrusted
    loose = ws.feedback_rows(text, "o/r", NOW, BOT)
    assert {r.detail for r in loose.rows} == {"ACCEPTED #21 #23", "NEW_FEEDBACK #20 #22"}
    assert loose.untrusted == frozenset()


def test_s074_7_the_full_report_lists_an_outsiders_request_in_untrusted(tmp_path: Path) -> None:
    host = feedback_host(tmp_path, outsider=True)
    rows = shown(host.watch("--no-host", "--trusted-only", "--bot-login", BOT))
    assert "FEEDBACK_DUE" not in rows and rows["UNTRUSTED"]["detail"] == "#31"
    assert rows["SPEC_DUE"]["detail"] == "ACCEPTED #30"


# -- S-074-8: tier 7 and the sweep, in both files ------------------------------------------


def test_s074_8_tier_7_and_the_swept_sections_match_in_both_files(ws: ModuleType) -> None:
    tier = ("DIRECTION_PENDING", "PLANS", "SPEC_DUE", "FEEDBACK_DUE")
    assert ws.TIERS[7] == gate_walk.TIERS[7] == tier
    assert {"SPEC_DUE", "FEEDBACK_DUE"} <= set(ws.SWEPT) and {"SPEC_DUE", "FEEDBACK_DUE"} <= gate_walk.SWEPT
    assert set(ws.SWEPT) == gate_walk.SWEPT
    assert {"SPEC_DUE", "FEEDBACK_DUE"} <= ws.AGENT <= ws.ACTION


def test_s074_8_a_tick_takes_them_from_the_sweep_and_hands_the_first_not_handed(ws: ModuleType) -> None:
    text = lines(line(5, "ACCEPTED", "opportunity"), line(7, handed=ago(48)))
    printed = "\n".join(json.dumps(r.json(), sort_keys=True) for r in ws.feedback_rows(text, "o/r", NOW).rows)
    spec_due, feedback_due = parse_findings(printed)
    swept = gate_walk.Swept(NOW, (feedback_due, spec_due), None)
    source = gate_walk.Rows(())
    retry = dt.timedelta(hours=6)
    found = gate_walk.walk(source, gate_walk.Changes("sig"), swept, gate_walk.Handed(), NOW, retry, False)
    assert (found.item, found.tier) == (spec_due, 7)
    handed = gate_walk.Handed().handing(spec_due, "s1", NOW)
    found = gate_walk.walk(source, gate_walk.Changes("sig"), swept, handed, NOW, retry, False)
    assert (found.item, found.tier) == (feedback_due, 7)
    # past retry_hours the first is handed again
    later = NOW + retry + dt.timedelta(minutes=1)
    found = gate_walk.walk(source, gate_walk.Changes("sig"), swept, handed, later, retry, False)
    assert found.item == spec_due
    # a sweep row read under observe is no agent's, so never an item
    quiet = replace_agent(feedback_due)
    found = gate_walk.walk(
        source, gate_walk.Changes("sig"), gate_walk.Swept(NOW, (quiet,), None), handed, NOW, retry, False
    )
    assert found.item is None


def replace_agent(finding: Finding) -> Finding:
    return Finding(finding.state, finding.subject, finding.detail, False, (), finding.fix)


def test_s074_8_shipmill_status_lists_both_rows_with_their_fix() -> None:
    rows = (
        StatusRow("SPEC_DUE", STATUS_REPO, "ACCEPTED #5 #9", True, TRIAGE_FIX),
        StatusRow("FEEDBACK_DUE", STATUS_REPO, "NEW_FEEDBACK #7", True, INTAKE_FIX),
    )
    text = report(facts(*rows)).text(STATUS_REPO).splitlines()
    spec = next(i for i, t in enumerate(text) if re.match(r"\s+spec due\s+", t))
    assert "#5" in text[spec] and "#9" in text[spec + 1] and text[spec + 2].split() == ["fix:", *TRIAGE_FIX.split()]
    due = next(i for i, t in enumerate(text) if re.match(r"\s+feedback due\s+", t))
    assert "#7" in text[due] and text[due + 1].split() == ["fix:", *INTAKE_FIX.split()]


# -- S-074-9: numbers only -----------------------------------------------------------------


@pytest.mark.parametrize("read", [["--no-host"], ["--sweep"], ["--tier", "7"]], ids=["full", "sweep", "tier7"])
def test_s074_9_no_row_holds_an_issues_title_or_body(propose: Host, read: list[str]) -> None:
    table = [sys.executable, str(SCRIPT), "o/r", "--repo-dir", str(propose.work), *read]
    proc = subprocess.run(table, capture_output=True, text=True, env=propose.env, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    assert "FEEDBACK_DUE" in proc.stdout and SECRET not in proc.stdout
    as_json = propose.watch(*read)
    assert SECRET not in as_json.stdout
    for state in ("SPEC_DUE", "FEEDBACK_DUE"):
        assert re.fullmatch(r"(ACCEPTED|NEW_FEEDBACK)( #\d+)+", str(shown(as_json)[state]["detail"]))


def test_s074_9_the_rows_are_built_from_numbers_only(ws: ModuleType) -> None:
    text = lines(line(5, "ACCEPTED", "opportunity"), line(7, handed=ago(48)))
    for row in ws.feedback_rows(text, "o/r", NOW).rows:
        assert SECRET not in row.text() and SECRET not in json.dumps(row.json())
