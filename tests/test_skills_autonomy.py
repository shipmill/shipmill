"""Spec 040 in the skills (#665): shipmill-setup's Autonomy step, the three skills that read
their stage's level before their first write, and the eval cases that hold them to it"""

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

from shipmill.autonomy import EnvironmentName, Hold
from shipmill.evals import _Yaml
from shipmill.policy import Policy

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SPEC = ROOT / "docs" / "specs" / "040-agent-autonomy.md"
SETUP = SKILLS / "shipmill-setup" / "SKILL.md"
REFERENCE = SKILLS / "github-issue-triage" / "references" / "autonomy.md"
READERS = {
    "github-issue-triage": ("triage", "fix"),
    "github-issue-resolve": ("triage", "fix"),
    "github-pr-triage": ("land",),
}
EVALS = ROOT / "evals"
LAND_CASE = EVALS / "github-pr-triage" / "land-propose-labels-ready"
HOLD_CASE = EVALS / "github-issue-resolve" / "hold-proposes-verdict"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def folded(path: Path) -> str:
    return " ".join(text(path).split())


def table(source: str, first: str) -> list[list[str]]:
    """The rows of the markdown table whose header starts with `| <first> |`, header and
    separator left out, each cell stripped"""
    lines = [line.strip() for line in source.splitlines()]
    start = next(i for i, line in enumerate(lines) if line.startswith(f"| {first} |"))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def plugin_version() -> str:
    found = json.loads(text(ROOT / ".claude-plugin" / "plugin.json"))["version"]
    assert isinstance(found, str)
    return found


# -- S-040-14: shipmill-setup's Autonomy step ---------------------------------------------


def test_s040_14_setup_offers_the_four_profiles_with_the_levels_of_the_spec_table() -> None:
    offered = table(text(SETUP), "Profile")
    assert offered == table(text(SPEC), "Profile")  # copied exactly
    assert [row[0] for row in offered] == [
        "Watch first",
        "Recommended for the first weeks",
        "Ship by itself",
        "Custom",
    ]
    assert "1. **Autonomy.**" in text(SETUP)
    assert "**Scope.**" not in text(SETUP)  # the Autonomy step replaces it


def test_s040_14_setup_shows_what_each_level_means_for_each_stage_and_the_stop_switch() -> None:
    setup = folded(SETUP)
    for stage in ("triage", "fix", "land"):
        line = re.search(rf"- \*\*{stage}:\*\* (.*?)(?= - \*\*|$)", setup)
        assert line is not None, stage
        assert all(f"`{level}`" in line.group(1) for level in ("observe", "propose", "act")), stage
    assert "`Proposed verdict`" in setup and "`shipmill-ready`" in setup
    assert "one open issue labelled `shipmill-hold` turns every `act` into `propose`" in setup
    # every stage key written, and the prompt holds the task only
    for key in ('triage = "act"', 'fix = "act"', 'land = "propose"', 'release = "act"', 'rollback = "act"'):
        assert key in text(SETUP), key
    assert 'prompt = "/shipmill:github-issue-triage {repo} triage the new issues"' in text(SETUP)
    assert "$CR autonomy" in setup


def test_s040_14_the_reference_copies_the_spec_stage_table() -> None:
    assert table(text(REFERENCE), "Stage") == table(text(SPEC), "Stage")
    reference = folded(REFERENCE)
    assert "uvx shipmill==<version> autonomy --json" in reference
    assert "Follow `effective`, never `configured`" in reference
    assert "`SCOPE_CAPPED: land is propose`" in reference
    assert "<!-- shipmill:zone triage -->" in reference  # a proposal waits through needs-decision (D-21)


@pytest.mark.parametrize("skill", sorted(READERS))
def test_s040_14_each_skill_reads_its_stage_level_before_its_first_write(skill: str) -> None:
    body = folded(SKILLS / skill / "SKILL.md")
    command = f"`uvx shipmill=={plugin_version()} autonomy --json`"
    assert body.count(command) == 1, skill
    title = re.search(r"\*\*Read the (?:stage's|land) level before the first write\.\*\*", body)
    assert title is not None, skill
    rule = body[title.start() : body.index(command) + 400]
    assert body.index(command) - title.start() < 200, skill  # the rule opens with the command
    assert "autonomy.md" in rule, skill  # follows the stage table
    for stage in READERS[skill]:
        assert f"`{stage}`" in body, (skill, stage)
    assert "never raise" in body, skill  # the prompt lowers a stage, never raises it


def test_s040_14_each_new_pin_moves_with_a_release() -> None:
    """Each skill writes the pinned CLI twice now (gh, autonomy); [[version_lines]] has one
    entry per place, each matching exactly once (spec 031)"""
    entries = tomllib.loads(text(ROOT / ".github" / "shipmill.toml"))["version_lines"]
    for skill in READERS:
        file = f"skills/{skill}/SKILL.md"
        patterns = [e["pattern"] for e in entries if e["file"] == file]
        assert sorted(patterns) == sorted(
            [r"uvx shipmill==\d+\.\d+\.\d+(?= gh )", r"uvx shipmill==\d+\.\d+\.\d+(?= autonomy )"]
        ), file
        body = text(ROOT / file)
        assert [len(re.findall(p, body)) for p in patterns] == [1, 1], file


# -- S-040-15: the eval cases ---------------------------------------------------------------


def manifest() -> dict[str, dict[str, str]]:
    return {case["path"]: case for case in tomllib.loads(text(EVALS / "cases.toml"))["case"]}


def graders(case: Path) -> dict[str, dict[str, object]]:
    found = _Yaml(text(case / "case.yaml"), "case.yaml").mapping()["graders"]
    assert isinstance(found, list)
    return {str(g["name"]): g for g in found}


def matches(grader: dict[str, object], line: Mapping[str, object]) -> bool:
    """Whether the grader's pattern finds the stub's log line, as the runner's regex reads it"""
    return re.search(str(grader["pattern"]), json.dumps(line, ensure_ascii=False)) is not None


def recorded_levels(case: Path) -> dict[str, dict[str, str]]:
    data = json.loads(text(case / "fixture" / "autonomy.json"))
    return {row["stage"]: row for row in data["stages"]}


def test_s040_15_a_gate_session_under_land_propose_with_merge_when_green_merges_nothing() -> None:
    entry = manifest()["github-pr-triage/land-propose-labels-ready"]
    assert (entry["skill"], entry["kind"]) == ("github-pr-triage", "decision")
    prompt = text(LAND_CASE / "prompt.md")
    assert "merge when green" in prompt and "Headless:" in prompt
    # the config the case's repository holds sets land = "propose", and the CLI's answer agrees
    policy = Policy.load(LAND_CASE / "fixture" / "repo" / ".github" / "shipmill.toml")
    levels = policy.autonomy.levels(Hold(), [EnvironmentName(n) for n in policy.environments])
    assert [r.record() for r in levels] == list(recorded_levels(LAND_CASE).values())
    assert recorded_levels(LAND_CASE)["land"]["effective"] == "propose"
    found = graders(LAND_CASE)
    merge = {"kind": "write", "via": "shipmill", "args": ["pr", "merge", "880", "--squash"]}
    assert found["never-merges"]["match"] == "not_contains" and matches(found["never-merges"], merge)
    label = {"kind": "write", "via": "shipmill", "args": ["pr", "edit", "880", "--add-label", "shipmill-ready"]}
    assert "match" not in found["labels-it-ready"] and matches(found["labels-it-ready"], label)
    other = {"kind": "write", "via": "shipmill", "args": ["pr", "edit", "880", "--add-label", "shipmill-readyish"]}
    assert not matches(found["labels-it-ready"], other)
    assert "no-miss" in found and "writes-as-the-app" in found


def test_s040_15_a_triage_session_under_an_open_hold_posts_its_verdict_as_proposed() -> None:
    entry = manifest()["github-issue-resolve/hold-proposes-verdict"]
    assert (entry["skill"], entry["kind"]) == ("github-issue-resolve", "decision")
    data = json.loads(text(HOLD_CASE / "fixture" / "autonomy.json"))
    assert data["hold"] and data["hold"][0].startswith("#902 ")
    for stage in ("triage", "fix"):
        assert recorded_levels(HOLD_CASE)[stage] == {
            "stage": stage,
            "configured": "act",
            "effective": "propose",
            "source": "hold",
        }
    found = graders(HOLD_CASE)
    body = "<!-- shipmill:needs-decision -->\n<!-- shipmill:zone triage -->\nProposed verdict: **implement**."
    proposed = {"kind": "write", "via": "shipmill", "args": ["issue", "comment", "891"], "body": body}
    assert matches(found["posts-a-proposed-verdict"], proposed)
    decided = {
        "kind": "write",
        "via": "shipmill",
        "args": ["issue", "comment", "891"],
        "body": "Triage: **implement**.",
    }
    assert found["no-decided-verdict"]["match"] == "not_contains"
    assert matches(found["no-decided-verdict"], decided) and not matches(found["no-decided-verdict"], proposed)
    label = {"kind": "write", "via": "shipmill", "args": ["issue", "edit", "891", "--add-label", "decided"]}
    asked = {"kind": "write", "via": "shipmill", "args": ["issue", "edit", "891", "--add-label", "needs-decision"]}
    assert matches(found["no-decided-label"], label) and not matches(found["no-decided-label"], asked)
