"""Spec 041, #714: a strict Depends on line, and MALFORMED_DEPENDS for one outside it"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_chains import Forge, link
from .test_triage_human import person, run_script
from .test_triage_state import first_page, forward, open_issue

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = ("acme", "home")
TRIAGED = {"body": "Triage: implement, a build issue of S-041", "createdAt": "2026-09-01T10:00:00Z"}
FENCE = "`" * 3
# The three lines of #680, each read on main as a hold on every reference in it
PROSE_LINES = [
    "Depends on: D1 for the type names (decisions D1–D5: acme/home#32)",
    "Depends on: acme/api#129 deployed; D1 (decisions D1–D5: acme/home#32)",
    "Depends on: the classifier deployed and decision D4 on #32",
]


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_chain_integrity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def triaged(body: str, number: int = 7) -> dict[str, Any]:
    item = open_issue(number, [TRIAGED])
    item["body"] = body
    item["blockedBy"] = forward([])
    item["subIssues"] = forward([])
    return item


def refs(ts: ModuleType, body: str) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = ts.dependency_refs({"body": body}, REPO)
    return found


def classify(ts: ModuleType, item: dict[str, Any], states: dict[tuple[str, str, int], str]) -> tuple[str, str]:
    verdict: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", states, None, REPO)
    return verdict


def test_s041_1_a_strict_line_holds_on_every_reference(ts: ModuleType) -> None:
    three = [("acme", "api", 3), ("acme", "home", 1), ("acme", "home", 2)]
    assert refs(ts, "Depends on #1, #2 and acme/api#3\n") == three
    assert refs(ts, "Depends on: #1 #2") == [("acme", "home", 1), ("acme", "home", 2)]
    assert refs(ts, "- depends on #1, and #2") == [("acme", "home", 1), ("acme", "home", 2)]
    urls = "Depends on https://github.com/o/r/issues/5 and https://github.com/o/r/pull/6"
    assert refs(ts, urls) == [("o", "r", 5), ("o", "r", 6)]
    placeholders = {"body": "Depends on #{B1}, acme/api#{B2} and #4\n"}
    assert ts.unfilled_dependencies(placeholders) == ["B1", "B2"]
    for body in ("Depends on #1, #2 and acme/api#3", "Depends on: #1 #2", urls, placeholders["body"]):
        assert ts.malformed_dependencies({"body": body}) == []


def test_s041_2_a_note_after_the_references_holds_nothing(ts: ModuleType) -> None:
    assert refs(ts, "Depends on acme/api#129 (deployed)") == [("acme", "api", 129)]
    assert refs(ts, "Depends on #5 (decided in #9)") == [("acme", "home", 5)]
    assert refs(ts, "Depends on #5; see #9 for the decision") == [("acme", "home", 5)]
    assert refs(ts, "Depends on #5, #6 — #9 holds the decision") == [("acme", "home", 5), ("acme", "home", 6)]
    for body in ("Depends on acme/api#129 (deployed)", "Depends on #5; see #9", "Depends on #5 — see #9"):
        assert ts.malformed_dependencies({"body": body}) == []
    # A placeholder in a note is no dependency either
    assert ts.unfilled_dependencies({"body": "Depends on #5 (split names it #{B1})"}) == []


@pytest.mark.parametrize("line", PROSE_LINES)
def test_s041_3_a_line_of_680_reads_malformed_depends(ts: ModuleType, line: str) -> None:
    body = f"Build the reader.\n\n{line}\n"
    item = triaged(body)
    state, note = classify(ts, item, {})
    assert state == "MALFORMED_DEPENDS"
    assert note.startswith(f"line 3: {line}")
    assert "MALFORMED_DEPENDS" in ts.ACTION
    # It still holds on every reference the line names, as before, so nothing starts early
    assert ("acme", "home", 32) in refs(ts, body)
    if "acme/api#129" in line:
        assert refs(ts, body) == [("acme", "api", 129), ("acme", "home", 32)]
    # Untriaged, the same body reads NEW
    untriaged = triaged(body)
    untriaged["comments"]["nodes"] = []
    assert classify(ts, untriaged, {})[0] == "NEW"


def test_s041_3_the_script_exits_1_on_malformed_depends(tmp_path: Path) -> None:
    item = triaged(f"Build the reader.\n\n{PROSE_LINES[1]}\n")
    proc = run_script(tmp_path, first_page([item]))
    assert proc.returncode == 1, proc.stderr
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["state"] for r in rows] == ["MALFORMED_DEPENDS"]
    assert rows[0]["note"].startswith(f"line 3: {PROSE_LINES[1]} | ")


def test_s041_4_prose_and_fenced_lines_hold_nothing(ts: ModuleType) -> None:
    prose = "Depends on the parser landing first\n"
    assert refs(ts, prose) == [] and ts.malformed_dependencies({"body": prose}) == []
    assert classify(ts, triaged(prose), {})[0] == "NEEDS_PR"
    for fence in (FENCE, "~~~"):
        body = f"An example:\n\n{fence}md\nDepends on #7\nDepends on: the classifier and #32\n{fence}\n"
        assert refs(ts, body) == []
        assert ts.malformed_dependencies({"body": body}) == []
        assert ts.unfilled_dependencies({"body": f"{fence}\nDepends on #{{B1}}\n{fence}\n"}) == []
        assert classify(ts, triaged(body), {})[0] == "NEEDS_PR"
    # A line after the fence closes is read again, and its number counts the fenced lines
    after = f"{FENCE}\nDepends on #7\n{FENCE}\nDepends on #8 deployed\n"
    assert refs(ts, after) == [("acme", "home", 8)]
    assert ts.malformed_dependencies({"body": after}) == ["line 4: Depends on #8 deployed"]


def test_s041_5_malformed_depends_comes_after_unfilled_and_before_the_holds(ts: ModuleType) -> None:
    malformed = "Depends on #3 deployed\n"
    # UNFILLED first
    assert classify(ts, triaged("Depends on #{B1}\n" + malformed), {})[0] == "UNFILLED"
    # Before SPEC_REFUSED, BLOCKED, and UNBLOCKED, whatever its holds' states
    # (a refused pull request holds only when named after the triage comment: a hold comment)
    on_hold = {"body": "On hold: waits on #3", "createdAt": "2026-09-02T10:00:00Z"}
    for hold, usual in (("CLOSED_UNMERGED", "SPEC_REFUSED"), ("OPEN", "BLOCKED"), ("CLOSED", "UNBLOCKED")):
        states = {("acme", "home", 3): hold}
        strict, loose = triaged("Depends on #3\n"), triaged(malformed)
        for item in (strict, loose):
            item["comments"]["nodes"].append(on_hold)
        assert classify(ts, strict, states)[0] == usual
        state, note = classify(ts, loose, states)
        assert (state, note) == ("MALFORMED_DEPENDS", f"line 1: Depends on #3 deployed | acme/home#3:{hold.lower()}")
    # A person's item with a malformed line and no open hold: never HANDOFF_DUE
    item = person(body="Reload the server.\n\nDepends on #3 once deployed\n")
    closed = {("acme", "home", 3): "CLOSED"}
    verdict = ts.classify_open(item, "Triage:", "postponed", closed, None, REPO, "bot[bot]", {})
    assert verdict == ("MALFORMED_DEPENDS", "line 3: Depends on #3 once deployed | acme/home#3:closed")
    fixed = person(body="Reload the server.\n\nDepends on #3 (once deployed)\n")
    assert ts.classify_open(fixed, "Triage:", "postponed", closed, None, REPO, "bot[bot]", {})[0] == "HANDOFF_DUE"


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    scripts = SCRIPT.parent
    sys.path.insert(0, str(scripts))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("chains_integrity", scripts / "chains.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


def test_s041_6_link_appends_a_line_for_a_reference_only_in_a_note(
    ch: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = Forge(ch)
    a = forge.add("o/r#7", "Depends on #5 (see #4)\n")
    b = forge.add("o/r#4")
    forge.add("o/r#5")
    forge.blocked.add((a, b))  # the relation is there: only the line is missing
    assert link(ch, forge, "o/r#7", "--blocked-by", "o/r#4") == 0
    assert forge.body("o/r#7") == "Depends on #5 (see #4)\nDepends on o/r#4"
    assert "added to o/r#7: Depends on o/r#4" in capsys.readouterr().out

    # A strict line naming it: already linked, nothing written
    forge = Forge(ch)
    a = forge.add("o/r#7", "Depends on #5 and #4 (both deployed)\n")
    b = forge.add("o/r#4")
    forge.blocked.add((a, b))
    assert link(ch, forge, "o/r#7", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == []
    assert capsys.readouterr().out.strip() == "already linked"
