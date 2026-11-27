"""#1766: the postponed label reads POSTPONED (or REVISIT) only once a trusted `Triage:` comment
gives its reason (D-16); labelled with none, the issue reads NEW so a session triages it, and
product intake reads the label the same way"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_intake_state import Fake, states
from .test_intake_state import issue as request
from .test_parent_check import part, parted

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
INTAKE = ROOT / "skills" / "product-intake" / "scripts" / "intake_state.py"
REPO = ("o", "r")
BOT = "shipmill-gate[bot]"
UNTRIAGED = "postponed label without a triage comment"
POSTPONE = "Triage: **postpone**. Not before the parser lands."
STABLE_AT = "2026-09-10T10:00:00Z"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_postponed_needs_reason", TRIAGE)


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    return load("intake_state_postponed_needs_reason", INTAKE)


def said(body: str, at: str, login: str, association: str, bot: bool = False) -> dict[str, Any]:
    author = {"__typename": "Bot" if bot else "User", "login": login}
    return {"body": body, "createdAt": at, "author": author, "authorAssociation": association}


def labelled(*comments: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": 7,
        "body": "",
        "labels": {"nodes": [{"name": "postponed"}]},
        "comments": {"nodes": list(comments)},
        "timelineItems": {"nodes": []},
    }


def classify(ts: ModuleType, item: dict[str, Any], stable: Any = None) -> tuple[str, str]:
    found: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", {}, stable, REPO, BOT, {})
    return found


def test_1766_a_postponed_label_without_a_triage_comment_reads_new(ts: ModuleType) -> None:
    assert classify(ts, labelled()) == ("NEW", UNTRIAGED)
    chatter = said("Any news on this?", "2026-09-01T10:00:00Z", "ana", "OWNER")
    assert classify(ts, labelled(chatter)) == ("NEW", UNTRIAGED)


def test_1766_an_untrusted_triage_comment_gives_the_label_no_reason(ts: ModuleType) -> None:
    for comment in (
        said(POSTPONE, "2026-09-01T10:00:00Z", "mallory", "NONE"),
        said(POSTPONE, "2026-09-01T10:00:00Z", "carl", "CONTRIBUTOR"),
        said(POSTPONE, "2026-09-01T10:00:00Z", "other-app", "NONE", bot=True),  # another App is no one
    ):
        assert classify(ts, labelled(comment)) == ("NEW", UNTRIAGED), comment
    stable = ts.latest_stable([{"name": "v1.2.0", "target": {"tagger": {"date": STABLE_AT}}}])
    old = said(POSTPONE, "2026-09-01T10:00:00Z", "mallory", "NONE")
    assert classify(ts, labelled(old), stable) == ("NEW", UNTRIAGED)  # nor reads REVISIT


def test_1766_a_trusted_triage_comment_reads_postponed_and_revisit_as_before(ts: ModuleType) -> None:
    stable = ts.latest_stable([{"name": "v1.2.0", "target": {"tagger": {"date": STABLE_AT}}}])
    for login, association, bot in (
        ("ana", "OWNER", False),
        ("ben", "MEMBER", False),
        ("cat", "COLLABORATOR", False),
        ("shipmill-gate", "NONE", True),  # the --bot-login's
    ):
        early = said(POSTPONE, "2026-09-01T10:00:00Z", login, association, bot)
        late = said(POSTPONE, "2026-09-20T10:00:00Z", login, association, bot)
        assert classify(ts, labelled(early)) == ("POSTPONED", ""), login
        assert classify(ts, labelled(early), stable) == ("REVISIT", "postponed before v1.2.0"), login
        assert classify(ts, labelled(late), stable) == ("POSTPONED", ""), login


def test_1766_a_postpone_split_still_reads_postponed(ts: ModuleType) -> None:
    # Part of #1 merged, the rest postponed: its triage comment is the --bot-login's
    held = parted([part(21)], labels=("postponed",))
    assert ts.classify_open(held, "Triage:", "postponed", {}, None, REPO, BOT, {})[0] == "POSTPONED"
    # with no trusted triage comment the label says nothing: it reads as unlabelled, by its check
    held["comments"]["nodes"] = []
    assert ts.classify_open(held, "Triage:", "postponed", {}, None, REPO, BOT, {})[0] == "VERIFY_DUE"


def test_1766_intake_reads_the_label_as_triage_does(ist: ModuleType) -> None:
    bare = request(1, labels=("postponed",))  # triage reads NEW: a request like any untriaged one
    stranger = request(2, labels=("postponed",))
    stranger["comments"]["nodes"] = [said(POSTPONE, "2026-10-01T10:00:00Z", "mallory", "NONE")]
    member = request(3, POSTPONE, labels=("postponed",))  # triage reads POSTPONED: triage's
    handed = request(4, "Triage: **opportunity**. Grouped", labels=("postponed",))  # trusted: triage's
    fake = Fake([bare, stranger, member, handed], [])
    found = states(ist, fake)
    assert {n for n, (s, _) in found.items() if s == "NEW_FEEDBACK"} == {1, 2}
