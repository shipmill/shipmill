"""Spec 056, #1104: the skills a session follows name the land window: github-pr-triage's QUEUED
verdict and LAND_DUE, github-ship-watch's LAND_DUE and LAND_QUEUED rows, and shipmill-setup's
[land.window]"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def doc(*parts: str) -> str:
    return SKILLS.joinpath(*parts).read_text(encoding="utf-8")


def test_s056_14_the_skills_name_the_queued_verdict_the_rows_and_the_section() -> None:
    triage = doc("github-pr-triage", "SKILL.md")
    landing = doc("github-pr-triage", "references", "landing.md")
    for text in (triage, landing):
        assert "QUEUED" in text
        assert "exit 10" in text
        assert "LAND_DUE" in text
        assert "queued_label" in text
    # the gate's table row says what exit 10 answers
    gate_row = next(line for line in triage.splitlines() if line.startswith("| `pr_gate.py"))
    assert "exit 10 QUEUED" in gate_row

    watch = doc("github-ship-watch", "SKILL.md")
    for state in ("LAND_DUE", "LAND_QUEUED"):
        assert re.search(rf"^\| {state} \| ", watch, re.MULTILINE), state
    due = next(line for line in watch.splitlines() if line.startswith("| LAND_DUE |"))
    assert "/shipmill:github-pr-triage <repo>" in due
    assert "An action (exit 1)" in due

    setup = doc("shipmill-setup", "SKILL.md")
    assert "### Land window" in setup
    window = setup.split("### Land window", 1)[1].split("\n### ", 1)[0]
    assert "[land.window]" in window
    assert "hours" in window
    assert "[agents] prompt" in window
    assert "queued_label" in window
