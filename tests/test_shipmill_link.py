"""Spec 041, amended by #1645: one `shipmill link` command for holds between issues and pull
requests, a pull request's Depends on line, and the gate, queue, status, chains, and triage
reading the same links"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill import link as linking
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.item_status import Holder, Kind, Ref, explain
from shipmill.queue import items
from shipmill.status import Issue, Pull, Row, parked

from .test_chain_integrity import triaged
from .test_chains import Forge, link
from .test_chains import ch as ch  # noqa: F401  (the fixture)
from .test_status_comment_readers import AGENT, BOT, HOLDS, by_bot, day, issue, said
from .test_status_comment_readers import ts as ts  # noqa: F401  (the fixture)
from .test_status_comment_readers import ws as ws  # noqa: F401  (the fixture)
from .test_status_item import NONE
from .test_status_picture import REPO, facts
from .test_triage_state import backward, comment, first_page

ROOT = Path(__file__).resolve().parents[1]


def unlink(ch: ModuleType, forge: Forge, *argv: str) -> int:
    result: int = ch.main(["unlink", *argv], run=forge, write=forge, edit=forge.edit, comment=forge.comment)
    return result


# -- S-041-17: shipmill link and unlink run chains.py from the checkout ------------------------


def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "https://github.com/o/r.git"], check=True)
    return root


def test_s041_17_link_and_unlink_run_chains_py_with_whole_references(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path)
    ran: list[tuple[list[str], Path]] = []

    def chains(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        ran.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, 0, "added to o/r#5: Depends on x/y#4\n", "")

    assert main(["--repo", str(root), "link", "#5", "--blocked-by", "x/y#4"], chains=chains) == 0
    assert main(["--repo", str(root), "link", "#5", "--child", "#6", "--product", "--no-text"], chains=chains) == 0
    assert main(["--repo", str(root), "unlink", "o/r#5", "--blocked-by", "#4"], chains=chains) == 0
    script = str(ROOT / "skills" / "github-issue-triage" / "scripts" / "chains.py")
    assert [cmd[1:] for cmd, _ in ran] == [
        [script, "link", "o/r#5", "--blocked-by", "x/y#4"],
        [script, "link", "o/r#5", "--child", "o/r#6", "--product", "--no-text"],
        [script, "unlink", "o/r#5", "--blocked-by", "o/r#4"],
    ]
    assert all(cwd == root.resolve() for _, cwd in ran)  # its writes follow the checkout's config
    assert capsys.readouterr().out.count("added to o/r#5") == 3


def test_s041_17_its_output_and_exit_code_pass_through(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = checkout(tmp_path)

    def refused(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 2, "", "error: no issue o/r#404\n")

    assert main(["--repo", str(root), "link", "#5", "--blocked-by", "#404"], chains=refused) == 2
    assert capsys.readouterr().err == "error: no issue o/r#404\n"


@pytest.mark.parametrize("given", ["nope", "o/r5", "#0", "o/r#", "#5 x"])
def test_s041_17_a_malformed_reference_is_refused_before_anything_runs(given: str) -> None:
    with pytest.raises(ReleaseError, match="is no reference"):
        linking.LinkRef.parse(given, "o/r")
    with pytest.raises(ReleaseError, match="no GitHub origin"):
        linking.LinkRef.parse("#5", None)


def test_s041_17_link_runs_the_real_chains_py(tmp_path: Path) -> None:
    """The bundled chains.py takes what link passes it: a self-link is refused, naming it"""
    root = checkout(tmp_path)
    request = linking.LinkRequest(False, linking.LinkRef("o/r", 5), linking.LinkRef("o/r", 5), False)
    proc = linking.run_chains(request.command("python3", linking.chains_script()), root)
    assert proc.returncode == 2
    assert "o/r#5 can't be linked to itself" in proc.stderr


# -- S-041-18: a pull request that waits ---------------------------------------------------------


def test_s041_18_link_on_a_pull_request_writes_its_line_alone_and_again_nothing(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    forge.add("o/r#115", "Adds the thing.\n", kind="PullRequest")
    forge.add("x/y#116")
    assert link(ch, forge, "o/r#115", "--blocked-by", "x/y#116") == 0
    assert forge.body("o/r#115") == "Adds the thing.\n\nDepends on x/y#116"
    assert forge.writes() == ["PATCH"]  # no native relation for a pull request
    assert capsys.readouterr().out.strip() == "added to o/r#115: Depends on x/y#116"
    assert link(ch, forge, "o/r#115", "--blocked-by", "x/y#116") == 0
    assert forge.writes() == ["PATCH"]
    assert capsys.readouterr().out.strip() == "already linked"


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["o/r#115", "--blocked-by", "o/r#4", "--no-text"], "o/r#115 is a pull request: its link is a Depends on line"),
        (["o/r#4", "--blocked-by", "o/r#115"], "o/r#115 is a pull request"),
        (["o/r#115", "--child", "o/r#4"], "o/r#115 is a pull request"),
        (["o/r#4", "--child", "o/r#115"], "o/r#115 is a pull request"),
    ],
)
def test_s041_18_a_pull_request_takes_no_relation(
    ch: ModuleType, capsys: pytest.CaptureFixture[str], argv: list[str], named: str
) -> None:
    forge = Forge(ch)
    forge.add("o/r#115", "Body", kind="PullRequest")
    forge.add("o/r#4", "Issue")
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, *argv)
    assert exit_.value.code == 2
    assert named in capsys.readouterr().err
    assert forge.writes() == []


# -- S-041-19: unlink ----------------------------------------------------------------------------


def test_s041_19_unlink_removes_both_forms_and_again_nothing(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    a = forge.add("o/r#5", "Build it.\r\n\r\nDepends on o/r#4\r\nMore text.\r\n")
    b = forge.add("o/r#4")
    forge.blocked.add((a, b))
    assert unlink(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == ["removeBlockedBy", "PATCH", "comment"]
    assert forge.blocked == set()
    assert forge.body("o/r#5") == "Build it.\r\n\r\nMore text.\r\n"  # the line and its break, the rest as it was
    out = capsys.readouterr().out
    assert "unlinked: o/r#5 is no longer blocked by o/r#4" in out
    assert "removed from o/r#5: Depends on o/r#4" in out
    assert unlink(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == ["removeBlockedBy", "PATCH", "comment"]  # nothing more
    assert capsys.readouterr().out.strip() == "not linked"


def test_s041_19_unlink_keeps_a_lines_other_references_and_its_note(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    forge.add("o/r#5", "- Depends on: #3, https://github.com/o/r/issues/4 and x/y#9 (all deployed)\nDepends on #4")
    forge.add("o/r#4")
    assert unlink(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.body("o/r#5") == "- Depends on: #3, x/y#9 (all deployed)"
    assert forge.writes() == ["PATCH", "comment"]


def test_s041_19_unlink_of_a_child_and_of_a_pull_request(ch: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    forge = Forge(ch)
    p = forge.add("o/r#1", "Depends on o/r#2")
    c = forge.add("o/r#2")
    forge.parents[c] = p
    assert unlink(ch, forge, "o/r#1", "--child", "o/r#2") == 0
    assert forge.parents == {} and forge.body("o/r#1") == ""
    assert forge.writes() == ["removeSubIssue", "PATCH", "comment"]

    forge = Forge(ch)
    forge.add("o/r#115", "Adds it.\n\nDepends on x/y#116", kind="PullRequest")
    forge.add("x/y#116")
    assert unlink(ch, forge, "o/r#115", "--blocked-by", "x/y#116") == 0
    assert forge.body("o/r#115") == "Adds it.\n"
    assert forge.writes() == ["PATCH", "comment"]


def test_s041_19_unlinks_comment_takes_the_hold_up_so_triage_asks_no_link_again(
    ch: ModuleType, ts: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The review's case: a hold line beside its link, then the link removed (an unlink, or a
    cycle's answer): the agent's newest word is unlink's comment, which names no hold"""
    forge = Forge(ch)
    a = forge.add("o/r#7", "Depends on o/r#12")
    b = forge.add("o/r#12")
    forge.blocked.add((a, b))
    assert unlink(ch, forge, "o/r#7", "--blocked-by", "o/r#12") == 0
    [(ref, note)] = forge.comments
    assert ref == "o/r#7" and note.startswith("Unlinked from o/r#12: it no longer holds this item")
    assert ts.hold_refs({"number": 7, "comments": {"nodes": [{"body": note}]}}, ("o", "r")) == {}
    hold_line = by_bot(HOLD, day(2))
    before = issue(hold_line)
    assert unlinked(ts, before, HOLDS)[0] == "HOLD_UNLINKED"  # without unlink's comment it asks again
    after = issue(hold_line, by_bot(note, day(3)))
    assert unlinked(ts, after, HOLDS)[0] == "BLOCKED"


def test_s041_19_a_refused_relation_with_nothing_to_remove_posts_nothing(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The third review's case: a forge without issue dependencies, and no line naming it"""
    forge = Forge(ch)
    forge.refuse_read = "Issue dependencies are not enabled"
    forge.add("o/r#7", "Build it.")
    forge.add("o/r#12")
    for _ in range(2):
        assert unlink(ch, forge, "o/r#7", "--blocked-by", "o/r#12") == 0
        assert capsys.readouterr().out.splitlines() == ["text only: Issue dependencies are not enabled", "not linked"]
    assert forge.writes() == [] and forge.comments == []


def test_s041_19_a_malformed_line_naming_it_is_refused_before_any_write(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    a = forge.add("o/r#5", "Depends on: the classifier deployed and #4\n")
    b = forge.add("o/r#4")
    forge.blocked.add((a, b))
    with pytest.raises(SystemExit) as exit_:
        unlink(ch, forge, "o/r#5", "--blocked-by", "o/r#4")
    assert exit_.value.code == 2
    assert "line 1 of o/r#5's body is malformed" in capsys.readouterr().err
    assert forge.writes() == []


# -- S-041-20: chains.py show reads a pull request's lines ----------------------------------------


def test_s041_20_show_reads_an_open_pull_requests_depends_on_lines_as_holds(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    forge.add("o/r#3", "Depends on o/r#115")  # an issue held on the pull request
    forge.add("o/r#115", "Depends on x/y#116 and x/y#117", kind="PullRequest")
    forge.add("x/y#116")
    forge.add("x/y#117", state="CLOSED")
    ch.main(["show", "o/r#3", "--json"], run=forge, contents=lambda repo: None)
    rows = {r["ref"]: r for r in json.loads(capsys.readouterr().out)["rows"]}
    pull = rows["o/r#115"]
    assert pull["state"] == "OPEN"
    assert pull["holds"] == ["x/y#116"] and pull["waits_on"] == ["x/y#116", "x/y#117"]
    assert pull["waiting_for"] == "items"
    assert "x/y#116" in rows  # the walk follows its lines

    # with --trusted-only, an untrusted author's lines hold nothing
    forge.issues[("o", "r", 115)]["author"] = "mallory"
    original = forge.item

    def item(found: dict[str, str], native: bool) -> dict[str, Any]:
        node = original(found, native)
        if found["ref"] == "o/r#115":
            node |= {"author": {"__typename": "User", "login": "mallory"}, "authorAssociation": "NONE"}
        return node

    forge.item = item  # type: ignore[method-assign]
    ch.main(["show", "o/r#3", "--json", "--trusted-only"], run=forge, contents=lambda repo: None, standing=no_one)
    rows = {r["ref"]: r for r in json.loads(capsys.readouterr().out)["rows"]}
    assert rows["o/r#115"]["holds"] == [] and rows["o/r#115"]["waits_on"] == []
    assert "x/y#116" not in rows


def no_one(repo: str, user: str) -> bool:
    return False


# -- S-041-21: the gate never hands a pull request that waits to land -----------------------------


def pr(number: int, body: str = "", draft: bool = False, author: str = "amy") -> dict[str, Any]:
    return {
        "number": number,
        "isDraft": draft,
        "isCrossRepository": False,
        "labels": [],
        "headRefOid": "a" * 40,
        "assignees": [],
        "author": {"login": author},
        "body": body,
    }


def no_comments(number: int) -> list[Any]:
    return []


def test_s041_21_a_pull_request_whose_line_names_an_open_item_is_parked_not_handed(ws: ModuleType) -> None:
    asked: list[set[Any]] = []

    def states(refs: set[Any]) -> dict[Any, str]:
        asked.append(set(refs))
        return {("x", "y", 116): "OPEN", ("o", "r", 9): "MERGED"}

    prs = [pr(115, "Depends on x/y#116, #9 and #7\nDepends on X/Y#116"), pr(120, "Depends on #9"), pr(121)]
    rows = {r.state: r.detail for r in ws.intake("o/r", 0, "", prs, no_comments, BOT, hold_states=states)}
    assert rows["PRS_OPEN"] == "#120 #121"  # every item #120 names closed
    assert rows["PRS_PARKED"] == "WAITS_ON #115 (o/r#7 x/y#116)"  # #7's state unread: it holds
    assert asked == [{("x", "y", 116), ("o", "r", 9), ("o", "r", 7)}]  # one read for every pull request


def test_s041_21_after_with_person_and_to_merge_and_an_agents_draft_is_held(ws: ModuleType) -> None:
    def states(refs: set[Any]) -> dict[Any, str]:
        return dict.fromkeys(refs, "OPEN")

    prs = [pr(115, "Depends on #116"), pr(130, "Depends on #116", draft=True, author="app/shipmill-o")]
    rows = {r.state: r.detail for r in ws.intake("o/r", 0, "", prs, no_comments, BOT, hold_states=states)}
    assert "PRS_OPEN" not in rows and "AGENT_DRAFT" not in rows
    assert rows["AGENT_DRAFT_HELD"] == "#130 (o/r#116)"
    assert rows["PRS_PARKED"] == "WAITS_ON #115 (o/r#116)"
    found = parked([Row("PRS_PARKED", REPO, "WITH_PERSON #4 (@a); TO_MERGE #12; WAITS_ON #115 (o/r#116)", False)])
    assert found.people == [(4, "@a")] and found.merge == [12] and found.waits == [(115, ("o/r#116",))]
    for bad in ("WAITS_ON #115", "WAITS_ON #115 (o/r#116); TO_MERGE #12", "WAITS_ON #1 (x)"):
        with pytest.raises(ReleaseError, match="unreadable"):
            parked([Row("PRS_PARKED", REPO, bad, False)])


def test_s041_21_the_gates_change_check_reads_each_pull_requests_body() -> None:
    from shipmill import walk

    assert " body " in walk.CONNECTIONS["pulls"][1]
    text = (ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py").read_text(encoding="utf-8")
    assert 'PR_FIELDS = "number,isDraft,isCrossRepository,labels,headRefOid,assignees,author,body"' in text


# -- S-041-22: status --item and queue hold it by its target --------------------------------------


def test_s041_22_status_and_queue_hold_a_pull_request_by_what_it_waits_on() -> None:
    found = facts(
        Row("PRS_PARKED", REPO, f"WAITS_ON #115 (x/y#116) #117 ({REPO}#3)", False),
        pulls=[Pull(115, False, "CLEAN", "main"), Pull(117, False, "CLEAN", "main")],
        issues=[Issue(3, "NEEDS_DECISION")],
    )
    explained = explain(found, Ref("115", 115, Kind.PULL), lambda _: NONE, None)
    assert explained.bucket == "parked"
    held = [c for c in explained.conditions if c.reason.startswith("waits on")]
    assert [(c.reason, c.clears, c.holder) for c in held] == [
        ("waits on x/y#116 (open)", "x/y#116 closing or merging", Holder.ELSEWHERE)
    ]
    records = items(found, lambda _: NONE, None, start=[115, 117])
    assert records[115].holder is Holder.ELSEWHERE and records[115].waits_on == ("x/y#116",)
    # one waiting on an open issue of the repo counts with it, as a BLOCKED issue does
    assert records[117].waits_on == (f"{REPO}#3",)
    assert (records[117].holder, records[117].via) == (Holder.MAINTAINER, 3)
    # and what waits on #3 names it, in queue's blocks as in --item's
    every = items(found, lambda _: NONE, None)
    assert [(str(w.ref), w.bucket) for w in every[3].blocks] == [(f"{REPO}#117", "parked")]


# -- S-041-23: HOLD_UNLINKED ---------------------------------------------------------------------

HOLD = "Triage: **implement**\n\nOn hold: waits on #12."


def unlinked(
    ts: ModuleType, item: dict[str, Any], states: dict[Any, str], issues: Any = None, home: str | None = None
) -> tuple[str, str]:
    """As triage_state.py's main reads an open issue, the holds GitHub gave as issues passed on"""
    known = frozenset(states) if issues is None else issues
    found: tuple[str, str] = ts.classify_open(
        item, "Triage:", "postponed", states, None, ("o", "r"), BOT, issues=known, home=home
    )
    return found


def test_s041_23_an_agents_hold_comment_with_no_link_reads_hold_unlinked(ts: ModuleType) -> None:
    held = issue(by_bot("Triage: **implement**\n\nOn hold: waits on #12 and o/r#13.", day(2)))
    assert unlinked(ts, held, HOLDS) == ("HOLD_UNLINKED", "unlinked o/r#12 unlinked o/r#13 | o/r#12:open o/r#13:open")
    assert "HOLD_UNLINKED" in ts.ACTION

    # a Depends on line or a native relation records it: as before
    assert unlinked(ts, issue(by_bot(HOLD, day(2)), body="Depends on #12"), HOLDS)[0] == "BLOCKED"
    node = {"number": 12, "state": "OPEN", "stateReason": None, "repository": {"nameWithOwner": "o/r"}}
    assert unlinked(ts, issue(by_bot(HOLD, day(2)), blockedBy={"nodes": [node]}), HOLDS)[0] == "BLOCKED"

    # a pull request takes no link from an issue (S-017-9): a hold on one stays its comment
    assert unlinked(ts, issue(by_bot(HOLD, day(2))), HOLDS, issues=frozenset())[0] == "BLOCKED"

    # a person's hold comment is theirs to word; a closed hold holds nothing
    person = issue(by_bot("Triage: **implement**", day(2)), said("On hold: waits on #12.", day(3), "amy", "OWNER"))
    assert unlinked(ts, person, HOLDS)[0] == "BLOCKED"
    assert unlinked(ts, issue(by_bot(HOLD, day(2))), {("o", "r", 12): "CLOSED"})[0] != "HOLD_UNLINKED"

    # only the agent's newest word counts: a later comment, such as the one after an unlink or a
    # cycle's answer, takes the hold up, and a question's options name no hold
    later = by_bot("Unlinked: #12 holds nothing now.", day(3))
    assert unlinked(ts, issue(by_bot(HOLD, day(2)), later), HOLDS)[0] == "BLOCKED"
    asked = "<!-- shipmill:needs-decision -->\n@amy Decision needed: which link?\n\n1. o/r#7 waits on #12"
    question = by_bot(asked, day(3))
    assert unlinked(ts, issue(by_bot("Triage: **implement**", day(2)), question), HOLDS)[0] != "HOLD_UNLINKED"

    # in a component, another repo's item takes no link there (S-038-11): its hold stays a comment
    other = {("x", "home", 12): "OPEN"}
    elsewhere = issue(by_bot("Triage: **implement**\n\nOn hold: waits on x/home#12.", day(2)))
    assert unlinked(ts, elsewhere, other, home="x/home")[0] == "BLOCKED"
    assert unlinked(ts, elsewhere, other)[0] == "HOLD_UNLINKED"

    # read after MALFORMED_DEPENDS
    malformed = issue(by_bot(HOLD, day(2)), body="Depends on the thing and #13")
    assert unlinked(ts, malformed, HOLDS)[0] == "MALFORMED_DEPENDS"


STATES_GH = """#!{python}
import json, os, sys
query = next(a[len("query="):] for a in sys.argv[1:] if a.startswith("query="))
fake = json.loads(open(os.environ["FAKE_GH_DATA"]).read())
if "r0: repository" in query:  # the holds' states: #12 an issue, #20 a pull request
    kinds = {{"12": "Issue", "20": "PullRequest"}}
    found = {{}}
    for i, number in enumerate(sorted(kinds)):
        found["r" + str(i)] = {{"issueOrPullRequest": {{"__typename": kinds[number], "state": "OPEN"}}}}
    print(json.dumps({{"data": found}}))
else:
    print(json.dumps({{"data": {{"repository": fake["comments" if "issue(number" in query else "first"]}}}}))
"""


def test_s041_23_the_script_reads_hold_unlinked_for_an_issue_and_not_a_pull_request(tmp_path: Path) -> None:
    item = triaged("Build the reader.")
    hold = f"On hold: waits on #12. It waits on #20 too.\n\n{AGENT}"
    item["comments"]["nodes"].append(comment(hold, "2026-09-03T10:00:00Z"))
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(STATES_GH.format(python=sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({"first": first_page([item]), "comments": {"issue": {"comments": backward([])}}}))
    env = {"PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]), "FAKE_GH_DATA": str(data)}
    script = ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
    cmd = [sys.executable, str(script), "o/r", "--json", "--bot-login", BOT]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    assert proc.returncode == 1, proc.stderr
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [(r["state"], r["note"]) for r in rows] == [("HOLD_UNLINKED", "unlinked o/r#12 | o/r#12:open o/r#20:open")]


def test_s041_23_the_watch_status_and_gate_count_it_as_a_triage_action(ws: ModuleType) -> None:
    from shipmill import status, walk

    assert "HOLD_UNLINKED" in ws.TRIAGE_ACTION
    assert any("HOLD_UNLINKED" in states for name, states in status.ISSUE_LINES if name == "to triage")
    assert any("HOLD_UNLINKED" in str(states) for states in walk.TIERS.values())


# -- S-041-24: the docs ---------------------------------------------------------------------------


def test_s041_24_the_skills_record_a_hold_with_shipmill_link() -> None:
    def doc(*parts: str) -> str:
        return ROOT.joinpath("skills", *parts).read_text(encoding="utf-8")

    assert "`shipmill link #N --blocked-by #R`" in doc("github-issue-resolve", "SKILL.md")
    triage = doc("github-issue-triage", "SKILL.md")
    assert "`shipmill link <owner/repo#N> --blocked-by <owner/repo#M>`" in triage and "shipmill unlink" in triage
    assert "**HOLD_UNLINKED:**" in triage
    rubric = doc("github-issue-triage", "references", "triage-rubric.md")
    assert "A hold is recorded only as a link" in rubric and "| HOLD_UNLINKED |" in rubric
    assert "shipmill link #<pr> --blocked-by" in doc("github-pr-triage", "SKILL.md")
    assert "WAITS_ON #N (owner/repo#M)" in doc("github-ship-watch", "SKILL.md")
