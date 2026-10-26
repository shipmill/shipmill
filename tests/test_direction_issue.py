"""Spec 034: the direction issue, shipmill's question for a missing docs/product.md: which
issue it is (triage_state.py), the watch keeping it out of the issue rows, triage's rule for
it, and setup creating its label"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
MARKER = "<!-- shipmill-direction -->"
BODY = f"{MARKER}\nWrite the product's direction ...\n"
BOT = "shipmill-o[bot]"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    return load("setup_state", SKILLS / "shipmill-setup" / "scripts" / "setup_state.py")


def author(login: str) -> dict[str, str]:
    """GraphQL's author: a Bot's login comes without "[bot]" """
    if login.endswith("[bot]"):
        return {"__typename": "Bot", "login": login.removesuffix("[bot]")}
    return {"__typename": "User", "login": login}


def issue(
    body: str = BODY,
    labels: tuple[str, ...] = ("shipmill-direction",),
    by: str = "amy",
    association: str = "OWNER",
) -> dict[str, Any]:
    """An open issue as triage_state.py's query returns it"""
    return {
        "number": 12,
        "title": "Write the product's direction (docs/product.md)",
        "body": body,
        "author": author(by),
        "authorAssociation": association,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": []},
        "timelineItems": {"nodes": []},
    }


def rest(number: int, by: str = "amy", association: str = "OWNER", **kw: Any) -> dict[str, Any]:
    """An issue as the REST API lists it: a Bot's login carries "[bot]" """
    found = {
        "number": number,
        "body": BODY,
        "user": {"login": by, "type": "Bot" if by.endswith("[bot]") else "User"},
        "author_association": association,
        "labels": [{"name": "shipmill-direction"}],
    }
    return {**found, **kw}


def triage_line(number: int, state: str) -> str:
    return json.dumps({"number": number, "state": state, "title": "t", "note": ""})


def test_s034_5_the_label_and_marker_are_triage_states_one_definition(ts: ModuleType, ws: ModuleType) -> None:
    assert (ts.DIRECTION_LABEL, ts.DIRECTION_MARKER) == ("shipmill-direction", MARKER)
    assert ws.DIRECTION_LABEL == ts.DIRECTION_LABEL


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_s034_5_a_trusted_authors_labelled_marked_issue_is_a_direction_issue(ts: ModuleType, association: str) -> None:
    assert ts.direction_issue(issue(association=association), None) is True
    assert ts.direction_issue(issue(association=association), BOT) is True


def test_s034_5_the_bot_logins_issue_is_a_direction_issue(ts: ModuleType) -> None:
    assert ts.direction_issue(issue(by=BOT, association="NONE"), BOT) is True
    assert ts.direction_issue(issue(by="Shipmill-O[bot]", association="NONE"), BOT) is True  # logins ignore case
    assert ts.direction_issue(issue(by=BOT, association="NONE"), None) is False  # no --bot-login, no trust
    assert ts.direction_issue(issue(by="other-app[bot]", association="NONE"), BOT) is False


@pytest.mark.parametrize("association", ["CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"])
def test_s034_5_anyone_elses_labelled_marked_issue_is_no_direction_issue(ts: ModuleType, association: str) -> None:
    assert ts.direction_issue(issue(by="mallory", association=association), BOT) is False


@pytest.mark.parametrize(
    "body", [f"{MARKER}\r\nWrite ...\r\n", f"{MARKER}  \nWrite ...\n", MARKER], ids=["crlf", "trailing", "alone"]
)
def test_s034_5_the_marker_is_the_bodys_first_line(ts: ModuleType, body: str) -> None:
    assert ts.direction_issue(issue(body=body), None) is True


@pytest.mark.parametrize(
    "body",
    [
        "Write the product's direction\n",  # no marker
        f"Direction\n{MARKER}\n",  # the marker on line 2
        f"\n{MARKER}\n",  # past a blank first line
        f"  {MARKER}\n",  # indented
        f"> {MARKER}\n",  # quoted
        f"{MARKER} please\n",  # more on its line
        "<!-- shipmill-direction: x -->\n",  # another marker
        "",
    ],
)
def test_s034_5_without_the_marker_first_it_is_any_issue(ts: ModuleType, body: str) -> None:
    assert ts.direction_issue(issue(body=body), None) is False


def test_s034_5_without_the_label_it_is_any_issue(ts: ModuleType) -> None:
    assert ts.direction_issue(issue(labels=()), None) is False
    assert ts.direction_issue(issue(labels=("shipmill-upgrade",)), None) is False


def test_s034_5_with_trusted_only_the_bot_logins_issue_is_trusted_and_an_outsiders_is_not(ts: ModuleType) -> None:
    ours = issue(by=BOT, association="NONE")
    assert ts.gated(ours, BOT, True) is None  # read on as any trusted issue, not UNTRUSTED
    outsider = issue(by="mallory", association="NONE")
    assert ts.gated(outsider, BOT, True) == ("UNTRUSTED", "opened by @mallory (none)")
    assert ts.direction_issue(outsider, BOT) is False


def test_s034_5_the_watch_reads_the_direction_issues_from_the_rest_api(ws: ModuleType) -> None:
    found = [
        rest(12),
        rest(13, by=BOT, association="NONE"),
        rest(14, by="mallory", association="NONE"),  # an outsider's: any issue
        rest(15, body=f"Direction\n{MARKER}\n"),  # the marker not first
        rest(16, labels=[]),  # the label off
        rest(17, pull_request={"url": "x"}),  # a pull request is no issue
        rest(18, body=None),
    ]
    assert ws.direction_numbers(found, BOT) == {12, 13}
    assert ws.direction_numbers(found, None) == {12}


def test_s034_5_the_watch_keeps_direction_issues_out_of_issues_and_issues_open(ws: ModuleType) -> None:
    lines = [triage_line(12, "NEW"), triage_line(13, "BLOCKED"), triage_line(20, "NEW"), triage_line(9, "BLOCKED")]
    triage = "\n".join(lines)
    before = ws.intake("o/r", 1, triage, [], lambda n: [], BOT)
    assert [(r.state, r.detail) for r in before] == [("ISSUES", "NEW #12 #20"), ("ISSUES_OPEN", "BLOCKED #13 #9")]
    rows = ws.intake("o/r", 1, triage, [], lambda n: [], BOT, False, None, None, frozenset(), (), frozenset({12, 13}))
    assert [(r.state, r.detail) for r in rows] == [("ISSUES", "NEW #20"), ("ISSUES_OPEN", "BLOCKED #9")]
    # with only a direction issue to triage, there is no ISSUES row at all
    only = "\n".join(lines[:2])
    rows = ws.intake("o/r", 1, only, [], lambda n: [], BOT, False, None, None, frozenset(), (), frozenset({12, 13}))
    assert rows == []


def test_s034_5_a_direction_issue_waiting_on_its_question_stays_in_needs_decision(ws: ModuleType) -> None:
    # spec 034: while the question waits, the issue is in NEEDS_DECISION, out of ISSUES and ISSUES_OPEN
    triage = "\n".join([triage_line(12, "NEEDS_DECISION"), triage_line(13, "DECIDED")])
    rows = ws.intake("o/r", 1, triage, [], lambda n: [], BOT, False, None, None, frozenset(), (), frozenset({12, 13}))
    assert [(r.state, r.detail) for r in rows] == [("NEEDS_DECISION", "#12")]


def test_s034_5_an_outsiders_labelled_marked_issue_stays_untrusted(ws: ModuleType) -> None:
    # with --trusted-only triage_state.py reads it UNTRUSTED, and it is no direction issue
    directions = ws.direction_numbers([rest(14, by="mallory", association="NONE")], BOT)
    assert directions == frozenset()
    line = triage_line(14, "UNTRUSTED")
    rows = ws.intake("o/r", 0, line, [], lambda n: [], BOT, True, None, None, frozenset(), (), directions)
    assert [(r.state, r.detail, r.json()["agent"]) for r in rows] == [("UNTRUSTED", "#14", False)]


def test_s034_10_triage_posts_no_verdict_on_a_direction_issue() -> None:
    triage = " ".join((SKILLS / "github-issue-triage" / "SKILL.md").read_text(encoding="utf-8").split())
    assert (
        "A direction issue, labelled `shipmill-direction` with `<!-- shipmill-direction -->` as its body's first"
        " line and opened by an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` (spec 034), is shipmill's"
        " question for the product's direction, so triage posts no verdict on it, and when `triage_state.py`"
        " reads it DECIDED, leaves the reply and the `needs-decision` label to github-ship-watch." in triage
    )


@pytest.mark.parametrize(
    "text",
    [
        '[agents]\nprompt = "x"\n',
        '[agents]\nprompt = "x"\nmode = "headless"\n',
        '[agents]\nprompt = "x"\napp_id = 1\nmode = "interactive"\n',
    ],
)
def test_s034_11_setup_wants_the_direction_label_with_agents(ss: ModuleType, tmp_path: Path, text: str) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(text, encoding="utf-8")
    wanted = ss.wanted_labels(tmp_path)
    assert wanted["shipmill-direction"] == ("1d76db", "shipmill's question for the product's direction")
    missing = [name for name in wanted if name in ("needs-decision", "shipmill-direction")]
    row = ss.labels_row(missing, wanted)
    assert (row.state, row.detail) == ("LABELS_MISSING", "needs-decision, shipmill-direction")


@pytest.mark.parametrize("text", [None, "", 'mode = "release"\n', '[lanes.dev]\nmode = "headless"\n'])
def test_s034_11_setup_never_wants_it_without_agents(ss: ModuleType, tmp_path: Path, text: str | None) -> None:
    if text is not None:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "shipmill.toml").write_text(text, encoding="utf-8")
    wanted = ss.wanted_labels(tmp_path)
    assert "shipmill-direction" not in wanted
    assert ("needs-decision" in wanted) is False
