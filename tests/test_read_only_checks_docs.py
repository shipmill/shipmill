"""#1852, D-116: a project's check runs by reading alone, a check whose only form is a write
asks the maintainer at once, and a check that didn't run is never closed at decided"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "skills" / "product-intake"
TRIAGE = ROOT / "skills" / "github-issue-triage"
OPTIONS = ('"leave it open: I check it and close it by hand"', '"close it unchecked"')


def flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def entry(log: str, number: int) -> str:
    """One D-n entry of the decisions log, its heading to the next"""
    found = re.search(rf"^## D-{number}: .*?(?=^## |\Z)", log, re.MULTILINE | re.DOTALL)
    assert found is not None, number
    return " ".join(found.group(0).split())


def test_d116_records_the_rule() -> None:
    d116 = entry((ROOT / "docs" / "decisions.md").read_text(encoding="utf-8"), 116)
    assert "A project's check runs by reading alone" in d116
    assert "Refines spec 042's check rules" in d116
    assert "existing issues and pull requests that already show the behaviour" in d116
    assert "the released package's test that reproduces the project's repro" in d116
    assert "A check whose only form is a write" in d116 and "at once" in d116
    assert "never closes a check that didn't run at a decided comment, whatever the zone's level" in d116
    assert "Supersedes" not in d116
    for path in (
        "skills/product-intake/SKILL.md",
        "skills/product-intake/references/plan.md",
        "skills/github-issue-triage/references/triage-rubric.md",
        "skills/github-issue-triage/references/needs-decision.md",
        "docs/specs/042-parent-check.md",
    ):
        assert path in d116, path


def test_d116_product_intake_writes_the_check_to_run_by_reading() -> None:
    skill = (INTAKE / "SKILL.md").read_text(encoding="utf-8")
    step = next(line for line in skill.splitlines() if line.startswith("**PROJECT_START_DUE: start the project"))
    assert "Write the check so it runs by reading alone (D-116)" in step
    assert "existing issues and pull requests that already show the behaviour" in step
    assert "the released package's test that reproduces the project's repro" in step
    assert "A check whose only form is a write says so in its `## Check`" in step
    assert "asks the maintainer on the check issue at once" in step
    for option in OPTIONS:
        assert option in step, option
    assert "never closed at a `decided` comment, whatever the zone's level" in step

    plan = flat(INTAKE / "references" / "plan.md")
    assert "a person other than its builder can run, and it runs by reading alone (spec 042, D-116)" in plan
    assert "the released package's test that reproduces the project's repro" in plan
    assert "**Never a write:** a check never opens an issue, adds a label, opens a pull request, or deploys" in plan
    assert "**A check whose only form is a write** says so in its `## Check`" in plan
    assert "**Never closed at `decided`:** a check that didn't run is closed only on the maintainer's" in plan


def test_d116_triage_never_closes_an_unrun_check_at_decided() -> None:
    rubric = flat(TRIAGE / "references" / "triage-rubric.md")
    check = rubric.split("## A parent's check", 1)[1].split("## Flags from", 1)[0]
    rule = check.split("**Never closed at `decided`.**", 1)[1].split("- **", 1)[0]
    assert "A check that didn't run is never closed at a `decided` comment, whatever the zone's level" in rule
    assert '"close it unchecked" answer closes it (D-116)' in rule
    assert "A project's check issue (spec 106) is written to run by reading alone" in rule
    assert "one whose only form is a write says so, and the session asks at once" in rule

    asking = flat(TRIAGE / "references" / "needs-decision.md")
    rule = asking.split("**A check that didn't run is never decided.**", 1)[1].split("- **", 1)[0]
    assert "a project's check whose only form is a write among them" in rule
    assert "is asked whatever the zone's level, never closed at a decided comment" in rule
    assert '"close it unchecked" answer closes it' in rule and "D-116" in rule
