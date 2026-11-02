"""S-052-12: docs/release-lanes.md says how shipmill retires a config key now that a refused
key stops only its feature (spec 052, D-64)"""

import re
from pathlib import Path

from shipmill.refused import CATALOGUE

ROOT = Path(__file__).parent.parent
LANES = ROOT / "docs" / "release-lanes.md"


def flat(path: Path) -> str:
    """The file's text with its line breaks as spaces, so a phrase across a wrapped line matches"""
    return " ".join(path.read_text(encoding="utf-8").split())


def retired() -> str:
    """The Retired keys passage, up to the next heading"""
    text = LANES.read_text(encoding="utf-8")
    found = re.search(r"^### Retired keys\n(.*?)^#", text, re.MULTILINE | re.DOTALL)
    assert found is not None, "docs/release-lanes.md has no Retired keys section"
    return " ".join(found.group(1).split())


def test_s052_12_a_refused_key_turns_off_only_its_feature() -> None:
    assert "A refused key turns off only its feature" in retired()


def test_s052_12_refusing_a_key_is_the_maintainers_decision_under_d63_no_sooner_than_14_days() -> None:
    text = retired()
    assert "Refusing a deprecated key is the maintainer's decision under D-63" in text
    assert "no sooner than 14 days after the release that deprecated it (D-64)" in text


def test_s052_12_a_refusal_is_an_entry_in_refused_py() -> None:
    text = retired()
    assert "The refusal is an entry in `src/shipmill/refused.py`" in text
    for refusal in CATALOGUE:  # the table lists the catalogue as it is
        assert f"| `{refusal.table} {refusal.key}` | {refusal.spec} |" in text


def test_s052_12_no_passage_still_says_a_refused_key_exits_2() -> None:
    text = flat(LANES)
    assert "with exit 2, and `doctor` fails its policy check" not in text
    assert "whatever its value, exits 2" not in text
