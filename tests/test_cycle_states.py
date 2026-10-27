"""Spec 041, #716: triage_state.py reads CYCLE, ship-watch reports CHAIN_CYCLE, and status
and the fleet count both"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.status import Row, Verdict, parse_issues, report

from .test_chains_show import GATED, proc, triage_lines, trusted_only
from .test_chains_show import Forge as ShowForge
from .test_status_picture import URL, facts, lines
from .test_triage_human import BOT, node, person, run_script, said
from .test_triage_state import first_page, forward, open_issue

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "skills" / "github-issue-triage"
WATCH = ROOT / "skills" / "github-ship-watch"
REPO = ("o", "r")
TRIAGED = {"body": "Triage: implement", "createdAt": "2026-09-01T10:00:00Z"}
QUESTION = "<!-- shipmill:needs-decision -->\n@amy Decision needed: which link is wrong?"


def load(name: str, path: Path) -> ModuleType:
    sys.path.insert(0, str(path.parent))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses look their module up by name
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_cycle_states", TRIAGE / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    return load("chains_cycle_states", TRIAGE / "scripts" / "chains.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_cycle_states", WATCH / "scripts" / "watch_state.py")


@pytest.fixture(scope="module")
def fl() -> ModuleType:
    return load("fleet_cycle_states", WATCH / "scripts" / "fleet.py")


def issue(
    number: int,
    body: str = "",
    labels: tuple[str, ...] = (),
    comments: tuple[dict[str, Any], ...] = (),
    association: str = "OWNER",
    triaged: bool = True,
    blocked_by: tuple[str, ...] = (),
    children: tuple[str, ...] = (),
) -> dict[str, Any]:
    """An open issue of o/r an OWNER opened, triaged unless said otherwise"""
    item = open_issue(number, [*([TRIAGED] if triaged else []), *comments], labels=labels)
    item["body"] = body
    item["author"] = {"__typename": "User", "login": "amy" if association == "OWNER" else "mallory"}
    item["authorAssociation"] = association
    item["blockedBy"] = forward([node(r) for r in blocked_by])
    item["subIssues"] = forward([node(r) for r in children])
    return item


def states(
    tmp_path: Path, *items: dict[str, Any], flags: tuple[str, ...] = ()
) -> tuple[int, dict[int, tuple[str, str]]]:
    where = tmp_path / f"run{len(list(tmp_path.iterdir()))}"
    where.mkdir()
    done = run_script(where, first_page(list(items)), *flags)
    assert done.returncode in (0, 1), done.stderr
    rows = [json.loads(line) for line in done.stdout.splitlines()]
    return done.returncode, {r["number"]: (r["state"], r["note"]) for r in rows}


def test_s041_12_an_issue_on_a_cycle_of_the_repos_open_issues_reads_cycle(tmp_path: Path) -> None:
    # #3 and #5 hold each other; #9 waits on the cycle without being on it; #11 names #3
    # but is untriaged, so its holds aren't read and the loop through it is none
    code, found = states(
        tmp_path,
        issue(3, "Depends on #5\n"),
        issue(5, "Build it.\n\nDepends on #3 (decided there)\n"),
        issue(9, "Depends on #3\n"),
        issue(11, "Depends on #3\n", triaged=False),
    )
    assert found[3] == ("CYCLE", "cycle o/r#3 -> o/r#5 -> o/r#3 | o/r#5:unknown")
    assert found[5] == ("CYCLE", "cycle o/r#3 -> o/r#5 -> o/r#3 | o/r#3:unknown")
    assert found[9][0] == "BLOCKED" and found[11][0] == "NEW"
    assert code == 1
    # A loop through the forge's own relations, cased as GitHub spells them, is a cycle too
    _, native = states(tmp_path, issue(3, blocked_by=("O/R#5",)), issue(5, children=("o/r#3",)))
    assert native[3][1].startswith("cycle o/r#3 -> o/r#5 -> o/r#3 | ")
    assert native[5][0] == "CYCLE"


def test_s041_12_cycles_reads_only_open_issues_whose_holds_triage_reads(ts: ModuleType) -> None:
    assert "CYCLE" in ts.ACTION
    loop = [("o", "r", 3), ("o", "r", 5), ("o", "r", 3)]
    two = [issue(3, "Depends on #5\n"), issue(5, "Depends on #3\n")]
    assert ts.cycles(two, REPO, "Triage:", set()) == {3: loop, 5: loop}
    # A person's item counts as triaged from the start
    held = person(body="Depends on #5\n")
    held["number"] = 3
    assert ts.cycles([held, two[1]], REPO, "Triage:", set()) == {3: loop, 5: loop}
    # A closed hold isn't among the open issues; an UNTRUSTED one has no links; another
    # repo's issue of the same number is no link; an issue naming itself is no loop
    assert ts.cycles(two[:1], REPO, "Triage:", set()) == {}
    assert ts.cycles(two, REPO, "Triage:", {5}) == {}
    assert ts.cycles([issue(3, "Depends on x/y#5\n"), two[1]], REPO, "Triage:", set()) == {}
    assert ts.cycles([issue(3, "Depends on #3\n")], REPO, "Triage:", set()) == {}


def test_s041_12_with_trusted_only_no_loop_runs_through_an_untrusted_issue(tmp_path: Path) -> None:
    outsider = issue(5, "Depends on #3\n", association="NONE")
    _, found = states(tmp_path, issue(3, "Depends on #5\n"), outsider, flags=("--trusted-only",))
    assert found[5][0] == "UNTRUSTED" and found[3][0] == "BLOCKED"
    _, everyone = states(tmp_path, issue(3, "Depends on #5\n"), outsider)
    assert everyone[3][0] == "CYCLE" and everyone[5][0] == "CYCLE"


def test_s041_13_a_loop_waits_on_its_malformed_or_needs_decision_issue(tmp_path: Path) -> None:
    # #3 -> #5 -> #9 -> #3; #5's line is malformed, so it reads MALFORMED_DEPENDS and the
    # others wait on its fix
    code, found = states(
        tmp_path, issue(3, "Depends on #5\n"), issue(5, "Depends on #9 once deployed\n"), issue(9, "Depends on #3\n")
    )
    loop = "cycle o/r#3 -> o/r#5 -> o/r#9 -> o/r#3"
    assert found[5][0] == "MALFORMED_DEPENDS"
    assert found[3] == ("BLOCKED", f"{loop} waits on o/r#5 | o/r#5:unknown")
    assert found[9] == ("BLOCKED", f"{loop} waits on o/r#5 | o/r#3:unknown")
    assert code == 1  # MALFORMED_DEPENDS is the action
    # #9 labelled needs-decision: it waits on the question, and so do the others
    asked = issue(9, "Depends on #3\n", labels=("needs-decision",))
    code, found = states(tmp_path, issue(3, "Depends on #5\n"), issue(5, "Depends on #9\n"), asked)
    assert found[9] == ("NEEDS_DECISION", "labelled, no question")
    assert found[3] == ("BLOCKED", f"{loop} waits on o/r#9 | o/r#5:unknown")
    assert found[5] == ("BLOCKED", f"{loop} waits on o/r#9 | o/r#9:unknown")
    assert code == 0  # the question waits on the maintainer: no session starts
    # Answered, it reads DECIDED and the others still wait until the label comes off
    reply = said("1", "2026-09-03T10:00:00Z", by="amy", association="OWNER", bot=False)
    answered = issue(9, "Depends on #3\n", ("needs-decision",), (said(QUESTION, "2026-09-02T10:00:00Z"), reply))
    _, found = states(tmp_path, issue(3, "Depends on #5\n"), issue(5, "Depends on #9\n"), answered)
    assert found[9][0] == "DECIDED" and found[3][1].startswith(f"{loop} waits on o/r#9")


@pytest.mark.parametrize(
    ("other", "flags", "state"),
    [
        ({"association": "NONE"}, ("--trusted-only",), "UNTRUSTED"),
        ({"labels": ("upstream",)}, (), "UPSTREAM"),
        ({"labels": ("needs-decision",)}, (), "NEEDS_DECISION"),
        (
            {
                "labels": ("needs-decision",),
                "comments": (
                    said(QUESTION, "2026-09-02T10:00:00Z"),
                    said("2", "2026-09-03T10:00:00Z", by="amy", association="OWNER", bot=False),
                ),
            },
            (),
            "DECIDED",
        ),
        (
            {
                "labels": ("decided",),
                "comments": (
                    said("<!-- shipmill:decided zone=interpretation -->\nDecided.", "2026-09-02T10:00:00Z"),
                    said("veto: keep it", "2026-09-03T10:00:00Z", by="amy", association="OWNER", bot=False),
                ),
            },
            (),
            "VETOED",
        ),
    ],
)
def test_s041_13_an_issue_on_a_cycle_reads_its_gated_state(
    tmp_path: Path, other: dict[str, Any], flags: tuple[str, ...], state: str
) -> None:
    _, found = states(tmp_path, issue(3, "Depends on #5\n"), issue(5, "Depends on #3\n", **other), flags=flags)
    assert found[5][0] == state


def test_s041_13_off_milestone_and_the_earlier_states_win_over_cycle(ts: ModuleType) -> None:
    loop = [("o", "r", 3), ("o", "r", 5), ("o", "r", 3)]
    item = issue(3, "Depends on #5\n")
    verdict = ts.classify_open(item, "Triage:", "postponed", {}, None, REPO, cycle=(loop, None))
    assert verdict == ("CYCLE", "cycle o/r#3 -> o/r#5 -> o/r#3 | o/r#5:?")
    item["parent"] = {"number": 1, "repository": {"nameWithOwner": "o/r"}, "milestone": {"title": "v1"}}
    verdict = ts.classify_open(item, "Triage:", "postponed", {}, None, REPO, cycle=(loop, None))
    assert verdict == ("OFF_MILESTONE", "parent #1 is in milestone v1, this is in no milestone")
    # UNFILLED and MALFORMED_DEPENDS come first; CYCLE before BLOCKED and a person's HANDOFF_DUE
    unfilled = issue(3, "Depends on #5\nDepends on #{B1}\n")
    assert ts.classify_open(unfilled, "Triage:", "postponed", {}, None, REPO, cycle=(loop, None))[0] == "UNFILLED"
    loose = issue(3, "Depends on #5 deployed\n")
    assert ts.classify_open(loose, "Triage:", "postponed", {}, None, REPO, cycle=(loop, None))[0] == "MALFORMED_DEPENDS"
    held = person(body="Depends on #5\n")
    found = ts.classify_open(held, "Triage:", "postponed", {}, None, REPO, BOT, {}, cycle=(loop, None))
    assert found[0] == "CYCLE"


def test_s041_14_cycle_and_malformed_depends_are_triage_actions_in_the_watch_status_and_fleet(
    ws: ModuleType, fl: ModuleType
) -> None:
    assert {"CYCLE", "MALFORMED_DEPENDS"} <= ws.TRIAGE_ACTION
    rows_of = ((3, "CYCLE"), (4, "MALFORMED_DEPENDS"))
    triage = "\n".join(
        json.dumps({"number": n, "state": s, "title": "t", "note": ""}) for n, s in (*rows_of, (5, "BLOCKED"))
    )
    rows = ws.intake("o/r", 1, triage, [], lambda n: [])
    assert [(r.state, r.detail) for r in rows] == [
        ("ISSUES", "CYCLE #3; MALFORMED_DEPENDS #4"),
        ("ISSUES_OPEN", "BLOCKED #5"),
    ]
    # The fleet counts the watch's ISSUES row as an action
    issues = fl.Row("ISSUES", "o/r", rows[0].detail)
    assert fl.exit_code([fl.RepoReport("o/r", (issues,), None)]) == 1
    # Status lists both on its "to triage" line, never "parked"
    listed = "".join(f"{json.dumps({'number': n, 'state': s, 'title': 't', 'note': ''})}\n" for n, s in rows_of)
    text = lines(facts(issues=parse_issues(listed)))
    at = text.index(f"  to triage      #4 {URL}/issues/4")
    assert text[at + 1] == f"                 #3 {URL}/issues/3"
    assert not any(line.startswith("  parked") for line in text)


def test_s041_15_ship_watch_reports_one_chain_cycle_per_loop_through_another_repo(
    ch: ModuleType, ws: ModuleType
) -> None:
    forge = ShowForge(ch)
    forge.issue("o/r#3", body="Depends on x/b#2")
    forge.issue("x/b#2", body="Depends on o/r#3")
    forge.issue("o/r#5", body="Depends on #6")  # a loop wholly in o/r: its triage reads CYCLE
    forge.issue("o/r#6", body="Depends on #5")
    forge.configs = {"o/r": GATED, "x/b": GATED}
    forge.collaborators = {("o/r", "alice")}  # x/b#2's author, trusted by o/r
    starts = triage_lines((3, "BLOCKED"), (5, "CYCLE"), (6, "CYCLE"))
    rows = ws.chain_rows("o/r", starts, None, trusted_only(ch, forge))
    assert [(r.state, r.subject, r.detail) for r in rows] == [("CHAIN_CYCLE", "o/r#3", "o/r#3 -> x/b#2 -> o/r#3")]
    assert rows[0].fix == f"answer which link is wrong and remove it: uv run --no-project python {ws.CHAINS} show o/r#3"
    assert rows[0].json()["agent"] is False
    assert "CHAIN_CYCLE" in ws.ACTION and "CHAIN_CYCLE" not in ws.AGENT
    # A malformed reference in "cycle" is CHAIN_UNREADABLE, naming only its checked part
    bad = {"rows": [{"ref": "o/r#3", "gate": None, "cycle": ["o/r#3", "x/b#2; rm -rf ~", "o/r#3"]}]}
    garbled = ws.chain_rows("o/r", starts, None, lambda cmd: proc(1, json.dumps(bad)))
    assert [(r.state, r.subject) for r in garbled] == [("CHAIN_UNREADABLE", "x/b#2")]
    assert garbled[0].fix is not None and "rm -rf" not in garbled[0].fix
    with pytest.raises(ws.Refused, match="malformed cycle"):
        ws.chain_cycle_rows("o/r", {"rows": [{"ref": "o/r#3", "cycle": "o/r#3"}]})


def test_s041_15_status_and_the_fleet_count_chain_cycle_with_the_chain_rows(fl: ModuleType) -> None:
    fix = "answer which link is wrong and remove it: uv run --no-project python chains.py show o/r#3"
    found = facts(Row("CHAIN_CYCLE", "o/x#3", "o/x#3 -> a/b#2 -> o/x#3", False, fix))
    assert report(found).verdict is Verdict.WAITS
    text = lines(found)
    assert text[3:5] == [
        "  chain          CHAIN_CYCLE o/x#3 https://github.com/o/x/issues/3: o/x#3 -> a/b#2 -> o/x#3",
        f"                 fix: {fix}",
    ]
    cycle = fl.Row("CHAIN_CYCLE", "o/x#3", "o/x#3 -> a/b#2 -> o/x#3")
    assert fl.leads(cycle) and fl.exit_code([fl.RepoReport("o/x", (cycle,), None)]) == 1


def test_s041_16_the_docs_say_the_strict_shape_cycle_and_chain_cycle() -> None:
    rubric = (TRIAGE / "references" / "triage-rubric.md").read_text(encoding="utf-8")
    links = rubric.split("## Links between issues", 1)[1].split("\n## ", 1)[0]
    assert "Depends on[:] <ref>" in links and "` (`, `;`, or ` — `" in links
    assert "Context goes on its own line, never on a Depends on line" in links
    assert "closes a cycle:" in links
    flags = rubric.split("## Flags from `triage_state.py`", 1)[1]
    assert "\n| MALFORMED_DEPENDS | " in flags and "\n| CYCLE | " in flags
    assert "`cycle <loop> waits on owner/repo#N`" in flags
    comments = (TRIAGE / "references" / "comments.md").read_text(encoding="utf-8")
    cycle = comments.split("## A cycle", 1)[1].split("\n## ", 1)[0]
    assert "one option per link of the loop" in cycle and "<!-- shipmill:needs-decision -->" in cycle
    skill = (TRIAGE / "SKILL.md").read_text(encoding="utf-8")
    assert "- **CYCLE:**" in skill and "- **MALFORMED_DEPENDS:**" in skill
    chains = skill.split("\n## Chains", 1)[1].split("\n## ", 1)[0]
    assert "`CYCLE (<loop>)`" in chains and "MALFORMED_DEPENDS line <n>: <the line>" in chains
    assert "closes a cycle:" in chains
    watch = (WATCH / "SKILL.md").read_text(encoding="utf-8")
    assert "\n| CHAIN_CYCLE | " in watch and "| `false` | CHAIN_CYCLE |" in watch
