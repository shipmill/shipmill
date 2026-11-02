"""Spec 051, Doctor and the docs: the setup skill, docs/flow.md, and README.md name the three
authoring modes, [agents] author, shipmill app-login, each person's opt-in, and who the decider is"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [("skills", "shipmill-setup", "SKILL.md"), ("docs", "flow.md"), ("README.md",)]


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("doc", DOCS)
def test_s051_16_the_docs_name_the_modes_the_key_app_login_the_opt_in_and_the_decider(doc: tuple[str, ...]) -> None:
    text = folded(*doc)
    lower = text.lower()
    for mode in ("autonomous", "assisted", "operator"):
        assert f"**{mode}**" in lower, mode
    assert '`[agents] author = "app"`' in text
    assert '`[agents] author = "decider"`' in text
    assert "`shipmill app-login`" in text
    assert "each person opts in by running `shipmill app-login` themselves" in lower
    assert "the decider is who assigned or approved the work, never an outside author" in lower


def test_s051_16_the_setup_skill_reads_credit_as_deprecated_for_author() -> None:
    text = folded("skills", "shipmill-setup", "SKILL.md")
    assert '`[agents] credit` is deprecated (spec 051): write `[agents] author = "app"` instead' in text
