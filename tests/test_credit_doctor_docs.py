"""Spec 049, Doctor and the docs: doctor's credit row, and the setup skill and docs/flow.md
naming [agents] credit, its default, and what its trailer means"""

from pathlib import Path

import pytest

from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, doctor

from .conftest import Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/t"\n'


def configure(repo: Repo, text: str) -> None:
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + text)


def credit_rows(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github) if c.name == "credit"]


DEPRECATED = (
    '; [agents] credit is deprecated (spec 051): set [agents] author = "app" instead, the same as credit = '
    '"decider", or, for a repo that wants no trailer, leave both unset'
)


def test_s049_11_doctor_says_decider_with_spec_049_when_credit_is_on(repo: Repo) -> None:
    # spec 051 deprecates credit: the row keeps spec 049's reading and WARNs (S-051-4)
    configure(repo, AGENTS + 'credit = "decider"\n')
    assert credit_rows(repo) == [
        Check("WARN", "credit", "decider, a merge names who decided it in Co-authored-by (spec 049)" + DEPRECATED)
    ]


def test_s049_11_doctor_says_off_when_credit_is_off(repo: Repo) -> None:
    configure(repo, AGENTS + 'credit = "off"\n')
    assert credit_rows(repo) == [Check("WARN", "credit", "off" + DEPRECATED)]  # S-051-4: set, so deprecated


def test_s049_11_doctor_says_off_when_credit_is_unset(repo: Repo) -> None:
    configure(repo, AGENTS)
    assert credit_rows(repo) == [Check("PASS", "credit", "off")]


def test_s049_11_no_credit_row_without_agents(repo: Repo) -> None:
    assert credit_rows(repo) == []  # D-9: no line for a section the config doesn't have


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("doc", [("skills", "shipmill-setup", "SKILL.md"), ("docs", "flow.md")])
def test_s049_12_the_docs_name_the_key_its_default_and_what_the_trailer_means(doc: tuple[str, ...]) -> None:
    text = folded(*doc)
    assert '`[agents] credit = "decider"`' in text
    assert 'The default is `"off"`' in text
    assert "the trailer means the person decided the change, not that they wrote it" in text.lower()
