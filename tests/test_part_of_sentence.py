"""#1678: a pull request's "Part of #N" links it as covering part of issue N when it starts a
line or a sentence of the body, outside code spans and fences, so #1631's "Stacked on #1625
(spec 094). Part of #1620: ..." links and #1675's "its build #1631 saying Part of #1620" does not"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_parent_check import WAITED, classify, parted, waiting

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_part_of_sentence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("Stacked on #11 (spec 094). Part of #12: it closes on its check", True, id="after a period"),
        pytest.param("Serves the parser! Part of: #12", True, id="after an exclamation mark"),
        pytest.param("Serves the parser! part of #12", False, id="lowercase after a sentence end"),
        pytest.param("Is it done? Part of #12 and #13", True, id="first of several after a question mark"),
        pytest.param("- Kind: fix. Part of #12", True, id="after a bullet's sentence"),
        pytest.param("Run `make`. Part of #12", True, id="after a code span's sentence"),
        pytest.param("Its build #31 saying Part of #12 reads VERIFY_DUE", False, id="mid-sentence"),
        pytest.param("Done. It says Part of #12", False, id="mid-sentence after a sentence end"),
        pytest.param("Done. `Part of #12` on its own", False, id="backticked after a sentence end"),
        pytest.param("Done.\n```\nDone. Part of #12\n```", False, id="fenced"),
        pytest.param("Write it as e.g. Part of #12", False, id="after e.g."),
        pytest.param("Compare i.e. Part of #12, cf. Part of #12, vs. Part of #12", False, id="after i.e. cf. vs."),
        pytest.param("Done. Part of #13 and #12", False, id="not the first ref"),
        pytest.param("Done.Part of #12", False, id="no space after the period"),
    ],
)
def test_1678_part_of_links_at_the_start_of_a_sentence(ts: ModuleType, body: str, expected: bool) -> None:
    assert ts.closes({"title": "x", "body": body}, 12, partial=True) is expected
    assert ts.closes({"title": "x", "body": body}, 12) is False


def merged(number: int, body: str, at: str) -> dict[str, Any]:
    pr = {"number": number, "state": "MERGED", "title": "x", "body": body, "mergedAt": at}
    return {"willCloseTarget": False, "isCrossRepository": False, "source": pr}


def test_1678_1620_s_build_links_and_the_pr_quoting_it_does_not(ts: ModuleType) -> None:
    # #1631 says "Part of #1620" after a sentence; #1675, merged after the check-waiting
    # comment, only quotes it mid-sentence: #1620 stays with the person its comment names
    build = merged(31, "Stacked on #25 (spec 094). Part of #1: the issue has a `## Check`", "2026-09-03T10:00:00Z")
    quote = merged(35, "## Plan\n- Proof: its build #31 saying Part of #1 reads it", "2026-09-07T10:00:00Z")
    assert classify(ts, parted([build, quote], [waiting()])) == (
        "WITH_PERSON",
        f"check waiting on @maria since {WAITED} #31:merged(part)",
    )
    assert classify(ts, parted([build]))[0] == "VERIFY_DUE"
