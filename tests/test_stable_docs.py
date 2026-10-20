"""Spec 029's docs: no stable release described as a soaked rc (S-029-13)"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
LANES = ROOT / "docs" / "release-lanes.md"
DOCS = (
    LANES,
    ROOT / "README.md",
    ROOT / "site" / "index.html",
    ROOT / "skills" / "shipmill-setup" / "SKILL.md",
    ROOT / "skills" / "github-issue-triage" / "references" / "triage-rubric.md",
)
# the wording that made a stable release a soaked rc; a soak on something observed, such as
# [environments] bake_minutes, and the name min_soak_days stay legitimate (D-39)
SOAKED = re.compile(
    r"\bsoaked\b|\bsoaks\b|release candidate or soak|real users already ran|min_soak_days = \d",
    re.IGNORECASE,
)


def flat(path: Path) -> str:
    """The file's text with its line breaks as spaces, so a phrase across a wrapped line matches"""
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_s029_13_no_stable_release_is_described_as_a_soaked_rc(path: Path) -> None:
    assert SOAKED.findall(flat(path)) == []


def test_s029_13_release_lanes_documents_the_breaking_hold_promote_from_and_the_deprecation() -> None:
    text = flat(LANES)
    # the breaking hold
    assert "a breaking change waits for the maintainer" in text.lower()
    assert "gh workflow run release.yml -f lane=stable -f dry-run=false" in text
    # promote_from = "rc" with no age requirement
    assert 'promote_from = "rc"' in text and "whatever its age" in text
    # the deprecation, and the upgrade that migrates
    assert "`min_soak_days` was deprecated in 0.53.0" in text
    # and the refusal that followed, not a "next minor" that already shipped (S-029-9)
    assert "later releases refuse a `[lanes.stable]` that sets it, with exit 2" in text
    assert "next minor release refuses" not in text
    assert "shipmill upgrade --apply stable-every-batch" in text
