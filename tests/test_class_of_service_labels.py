"""Spec 070: setup wants the class-of-service labels with [agents], product intake's accept
step names them, and the spec gate's split never puts one on a build issue"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "shipmill-setup" / "scripts" / "setup_state.py"
OPPORTUNITY = ROOT / "skills" / "product-intake" / "references" / "opportunity.md"
SPEC_GATE = ROOT / "skills" / "github-issue-triage" / "references" / "spec-gate.md"
CLASSES = ("expedite", "fixed-date")


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def config(root: Path, text: str) -> None:
    path = root / ".github" / "shipmill.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.mark.parametrize("agents", ['[agents]\nprompt = "x"\nmode = "headless"\n', '[agents]\nprompt = "x"\n'])
def test_s070_14_labels_missing_names_expedite_and_fixed_date_with_agents(
    ss: ModuleType, tmp_path: Path, agents: str
) -> None:
    config(tmp_path, agents)
    wanted = ss.wanted_labels(tmp_path)
    have = {name for name in wanted if name not in CLASSES}  # every other label exists
    missing = [name for name in wanted if name not in have]  # as setup_state.py's main reads it
    row = ss.labels_row(missing, wanted)
    assert (row.state, row.detail) == ("LABELS_MISSING", "expedite, fixed-date")
    assert "expedite, fixed-date," in ss.labels_row([], wanted).detail  # LABELS_OK names them once they exist
    ran: list[list[str]] = []

    def gh(cmd: list[str]) -> str:
        ran.append(cmd)
        return ""

    ss.create_labels("me/demo", wanted, missing, ["gh"], gh)
    assert [cmd[3] for cmd in ran] == ["expedite", "fixed-date"]  # --fix creates them
    assert all(cmd[cmd.index("--description") + 1].startswith("Class of service: ") for cmd in ran)


@pytest.mark.parametrize("text", ["", 'mode = "release"\n'])
def test_s070_14_no_agents_wants_no_class_label(ss: ModuleType, tmp_path: Path, text: str) -> None:
    config(tmp_path, text)
    wanted = ss.wanted_labels(tmp_path)
    assert not set(CLASSES) & set(wanted)
    assert "expedite" not in ss.labels_row([], wanted).detail


def test_s070_15_the_opportunity_comment_names_the_classes_beside_planned() -> None:
    text = OPPORTUNITY.read_text(encoding="utf-8")
    section = text.split("## Intake's triage line on the opportunity", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```markdown\n(.*?)```", section, re.S)
    assert len(blocks) == 2
    for block in blocks:  # the accept question, with and without a goal served
        accept = block.index("`planned`")
        assert all(block.index(f"`{label}`") > accept for label in CLASSES), block
    served = flat(blocks[0])
    assert "accept with `planned` and add `expedite`, or `fixed-date` with a due date on the milestone it is in" in (
        served
    )
    prose = flat(section)
    assert "only a label a person adds counts, so never add `expedite` or `fixed-date` yourself" in prose
    assert "never copy one onto a build issue" in prose


def test_s070_15_the_spec_gate_files_build_issues_with_no_class_label() -> None:
    split = SPEC_GATE.read_text(encoding="utf-8").split("### Split it into build issues", 1)[1].split("\n### ", 1)[0]
    step = flat(split.split("2. **File them in order.**", 1)[1].split("\n3. ", 1)[0])
    assert "File a build issue with no class label, `expedite` or `fixed-date`, even when the feature issue" in step
    assert "never copy it onto them" in step
    specs = (ROOT / "skills" / "github-issue-triage" / "scripts" / "specs.py").read_text(encoding="utf-8")
    assert not any(label in specs for label in CLASSES)  # split prints no label for a build issue
