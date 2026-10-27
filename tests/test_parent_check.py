"""Spec 042, #717: a parent with a ## Check reads VERIFY_DUE, CHECK_FAILED, and, closed
before its check ran, VERIFY_CLOSED, without gh or the network"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_chains_e2e import World
from .test_triage_human import by, node, person, run_script, said
from .test_triage_state import FakeGitHub, backward, first_page, forward, open_issue

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = ("o", "r")
BOT = "shipmill-gate[bot]"
CHECK = "Serve the new field.\n\n## Check\n\n`curl -s https://api.acme.example/v1/item/1` has `colour`\n"
FAILED = "<!-- shipmill:check-failed -->"
VERIFIED = "<!-- shipmill:verified -->"
TRIAGED = said("Triage: **implement**, a feature issue of S-042", "2026-09-01T10:00:00Z")
CLOSED_2, CLOSED_3 = "2026-09-03T10:00:00Z", "2026-09-04T10:00:00Z"


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_parent_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parent(
    children: list[dict[str, Any]],
    comments: list[dict[str, Any]] | None = None,
    body: str = CHECK,
    labels: tuple[str, ...] = (),
) -> dict[str, Any]:
    item = open_issue(1, [TRIAGED, *(comments or [])], labels=labels)
    item["body"] = body
    item["author"] = {"__typename": "User", "login": "maria"}
    item["authorAssociation"] = "OWNER"
    item["assignees"] = {"nodes": []}
    item["blockedBy"] = forward([])
    item["subIssues"] = forward(children)
    return item


def both_closed() -> list[dict[str, Any]]:
    return [node("o/r#2", "CLOSED", CLOSED_2), node("o/r#3", "CLOSED", CLOSED_3)]


def classify(ts: ModuleType, item: dict[str, Any]) -> tuple[str, str]:
    verdict: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", {}, None, REPO, BOT, {})
    return verdict


def test_s042_1_a_parent_with_a_check_whose_children_closed_reads_verify_due(ts: ModuleType, tmp_path: Path) -> None:
    state, note = classify(ts, parent(both_closed()))
    assert state == "VERIFY_DUE"
    assert note == "children 2/2 closed o/r#2:closed(child) o/r#3:closed(child): run its ## Check"
    assert "VERIFY_DUE" in ts.ACTION
    proc = run_script(tmp_path, first_page([parent(both_closed())]))
    assert proc.returncode == 1, proc.stderr
    assert [json.loads(line)["state"] for line in proc.stdout.splitlines()] == ["VERIFY_DUE"]


def test_s042_2_without_a_check_it_reads_as_before_and_an_open_child_blocks(ts: ModuleType) -> None:
    plain = parent(both_closed(), body="Serve the new field.\n")
    assert classify(ts, plain) == ("UNBLOCKED", "children 2/2 closed o/r#2:closed(child) o/r#3:closed(child)")
    for body in (CHECK, "Serve the new field.\n"):
        held = parent([node("o/r#2", "CLOSED", CLOSED_2), node("o/r#3")], body=body)
        assert classify(ts, held) == ("BLOCKED", "children 1/2 closed o/r#2:closed(child) o/r#3:open(child)")


def test_s042_3_a_trusted_check_failed_comment_after_the_newest_close_reads_check_failed(
    ts: ModuleType, tmp_path: Path
) -> None:
    after = "2026-09-05T10:00:00Z"
    for comment in (
        said(f"{FAILED}\nThe check returned no `colour`.", after),  # the --bot-login
        said(f"{FAILED}\nStill missing.", after, **by("maria", "MEMBER")),
    ):
        state, note = classify(ts, parent(both_closed(), [comment]))
        assert state == "CHECK_FAILED"
        assert note == f"check failed {after} children 2/2 closed o/r#2:closed(child) o/r#3:closed(child)"
    assert "CHECK_FAILED" in ts.ACTION
    # By anyone else, before the newest close, or not as the first line, it changes nothing
    for comment in (
        said(f"{FAILED}\nI think it failed.", after, **by("someone", "CONTRIBUTOR")),
        said(f"{FAILED}\nFailed before #3 closed.", "2026-09-03T12:00:00Z"),
        said(f"The marker {FAILED} quoted mid-comment.", after),
    ):
        assert classify(ts, parent(both_closed(), [comment]))[0] == "VERIFY_DUE"
    failed = parent(both_closed(), [said(f"{FAILED}\nNo `colour`.", after)])
    proc = run_script(tmp_path, first_page([failed]))
    assert proc.returncode == 1, proc.stderr
    assert [json.loads(line)["state"] for line in proc.stdout.splitlines()] == ["CHECK_FAILED"]


def test_s042_4_a_fix_child_blocks_it_and_its_close_makes_it_verify_due_again(ts: ModuleType) -> None:
    comment = said(f"{FAILED}\nNo `colour`.", "2026-09-05T10:00:00Z")
    fix = node("o/r#4")
    assert classify(ts, parent([*both_closed(), fix], [comment]))[0] == "BLOCKED"
    fixed = node("o/r#4", "CLOSED", "2026-09-06T10:00:00Z")
    state, note = classify(ts, parent([*both_closed(), fixed], [comment]))
    assert state == "VERIFY_DUE" and note.startswith("children 3/3 closed ")


def test_s042_5_a_person_s_item_and_an_upstream_parent_keep_their_states(ts: ModuleType) -> None:
    failed = said(f"{FAILED}\nNo `colour`.", "2026-09-05T10:00:00Z")
    for labels in (("human",), ("role:infra",)):
        item = person([failed], body=CHECK, labels=labels)
        item["subIssues"] = forward(both_closed())
        assert classify(ts, item)[0] == "HANDOFF_DUE"  # its children closed: the person's turn (spec 017)
        handed = person(
            [said("<!-- shipmill:handoff -->\n@ana, your turn", "2026-09-06T10:00:00Z")], body=CHECK, labels=labels
        )
        handed["subIssues"] = forward(both_closed())
        handed["comments"]["nodes"].append(said("done", "2026-09-07T10:00:00Z", **by("ana")))
        assert classify(ts, handed) == ("VERIFY_DUE", "done reported by @ana")
    upstream = parent(both_closed(), [failed], labels=("upstream",))
    assert ts.gated(upstream, BOT, False) == ("UPSTREAM", "no coordinator: waits for the maintainer")


def closed_parent(
    closer: dict[str, Any] | None,
    actor: tuple[str, bool] = ("shipmill-gate", True),
    comments: list[dict[str, Any]] | None = None,
    body: str = CHECK,
    children: int = 2,
    labels: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A parent closed as completed at 2026-09-07T10:00:00Z"""
    who, bot = actor
    return {
        "number": 1,
        "title": "Serve the new field",
        "stateReason": "COMPLETED",
        "body": body,
        "subIssues": {"totalCount": children},
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "refs": forward([]),
        "timelineItems": {
            "nodes": [
                {
                    "createdAt": "2026-09-07T10:00:00Z",
                    "actor": {"__typename": "Bot" if bot else "User", "login": who},
                    "closer": closer,
                }
            ]
        },
        "comments": backward(comments or []),
    }


PR = {"__typename": "PullRequest", "number": 12, "merged": True}
COMMIT = {"__typename": "Commit", "abbreviatedOid": "abc1234", "message": "Serve colour, see fixes #1 later"}


def closed(ts: ModuleType, item: dict[str, Any]) -> tuple[str, str] | None:
    verdict: tuple[str, str] | None = ts.classify_closed(item, "release-blocker", "incident", BOT)
    return verdict


def test_s042_6_a_parent_closed_before_its_check_ran_reads_verify_closed(ts: ModuleType) -> None:
    assert closed(ts, closed_parent(PR, ("maria", False))) == ("VERIFY_CLOSED", "closed by #12: run its ## Check")
    # A commit naming it only mid-line would read SUSPECT_CLOSE: a parent with a check never does
    assert closed(ts, closed_parent(COMMIT, ("maria", False))) == (
        "VERIFY_CLOSED",
        "closed by commit abc1234: run its ## Check",
    )
    assert closed(ts, closed_parent(None)) == ("VERIFY_CLOSED", "closed by @shipmill-gate[bot]: run its ## Check")
    # A trusted verified comment after the close: nothing. An outsider's, or one before, never counts
    for who in ({}, by("maria", "OWNER")):
        done = closed_parent(
            PR, comments=[said(f"{VERIFIED}\nThe check returned `colour`.", "2026-09-08T10:00:00Z", **who)]
        )
        assert closed(ts, done) is None
    for comment in (
        said(f"{VERIFIED}\nLooks fine to me.", "2026-09-08T10:00:00Z", **by("someone", "NONE")),
        said(f"{VERIFIED}\nVerified the earlier close.", "2026-09-06T10:00:00Z"),
    ):
        assert closed(ts, closed_parent(PR, comments=[comment]))[0] == "VERIFY_CLOSED"  # type: ignore[index]
    # Closed by hand by a trusted person other than the --bot-login: as before this spec
    by_hand = closed_parent(None, ("maria", False))
    assert closed(ts, by_hand) == ("SUSPECT_CLOSE", "closed as completed by hand, and no merged PR mentions it")
    # No check, no sub-issue, a person's item, or an upstream report: as before
    assert closed(ts, closed_parent(PR, body="Serve the new field.\n")) is None
    assert closed(ts, closed_parent(None, children=0))[0] == "SUSPECT_CLOSE"  # type: ignore[index]
    assert closed(ts, closed_parent(None, labels=("upstream",))) is None
    assert closed(ts, closed_parent(PR, ("maria", False), labels=("human",))) == (
        "VERIFY_CLOSED",
        "closed by @maria: run its ## Check",
    )


def test_s042_6_only_the_native_query_asks_a_closed_issue_for_sub_issues(ts: ModuleType) -> None:
    closed_part = ts.QUERY.split("closed: issues", 1)[1]
    assert "subIssues(first: 1) { totalCount }" in closed_part
    assert "subIssues" not in ts.TEXT_QUERY


def test_s042_6_fetch_reads_a_closed_parent_s_comments_back_to_its_close(ts: ModuleType) -> None:
    item = closed_parent(PR)  # the first query's comments(last: 5), here none
    after = said(f"{VERIFIED}\nThe check returned `colour`.", "2026-09-08T10:00:00Z")
    gh = FakeGitHub(
        ts,
        {
            ("QUERY", None, None): first_page([], closed_nodes=[item]),
            ("COMMENTS_PAGE", 1, None): {"issue": {"comments": backward([after])}},
        },
    )
    fetched = ts.fetch("o/r", 20, run=gh)["closed"]["nodes"][0]
    assert ("COMMENTS_PAGE", 1, None) in gh.calls
    assert closed(ts, fetched) is None


# S-042-12: the parent's whole life over one scripted forge, through the real triage_state.py


class ParentWorld(World):
    """test_chains_e2e's forge with sub-issues: chains.py link --child records them, and
    triage_state.py's queries return them, open and closed"""

    def __init__(self, tmp: Path, ch: ModuleType) -> None:
        super().__init__(tmp, ch)
        self.children: dict[str, list[str]] = {}

    def open_node(self, ticket: Any) -> dict[str, Any]:
        found = super().open_node(ticket)
        found["subIssues"]["nodes"] = [self.native(r) for r in self.children.get(ticket.ref, [])]
        return found

    def closed_node(self, ticket: Any) -> dict[str, Any]:
        return {**super().closed_node(ticket), "subIssues": {"totalCount": len(self.children.get(ticket.ref, []))}}

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if query == self.ch.PARENT:
            child = self.ids[variables["id"]]
            mine = next((p for p, kids in self.children.items() if child in kids), None)
            return {"data": {"node": {"parent": {"id": self.tickets[mine].id} if mine else None}}}
        if query == self.ch.ADD_SUB_ISSUE:
            self.children.setdefault(self.ids[variables["issue"]], []).append(self.ids[variables["sub"]])
            return {"data": {"addSubIssue": {"issue": {"id": variables["issue"]}}}}
        return super().__call__(query, variables)


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    scripts = SCRIPT.parent
    sys.path.insert(0, str(scripts))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("chains_parent_check", scripts / "chains.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


def test_s042_12_a_parent_closes_on_its_check_over_a_scripted_forge(tmp_path: Path, ch: ModuleType) -> None:
    world = ParentWorld(tmp_path, ch)
    feature, reader, api, fix = "acme/app#1", "acme/app#2", "acme/app#3", "acme/app#4"
    world.open(feature, "Serve the new field", body=CHECK)
    world.open(reader, "Read colour from the payload")
    world.open(api, "Serve colour on the API")
    for ref in (feature, reader, api):
        world.comment(ref, "Triage: **implement**.", "shipmill-gate", bot=True)
    for child in (reader, api):
        assert world.chains("link", feature, "--child", child)[0] == 0
    gate = "shipmill-gate"

    def row(ref: str) -> tuple[int, tuple[str, str] | None]:
        code, rows = world.triage("acme/app")
        return code, rows.get(ref)

    assert row(feature)[1] == ("BLOCKED", f"children 0/2 closed {reader}:open(child) {api}:open(child)")

    # Both children merge: the parent's check is due, not its close
    world.close(reader, gate, bot=True, pr=10)
    world.close(api, gate, bot=True, pr=11)
    code, verdict = row(feature)
    assert code == 1
    assert verdict == (
        "VERIFY_DUE",
        f"children 2/2 closed {reader}:closed(child) {api}:closed(child): run its ## Check",
    )

    # The check fails: the session says so, and the parent reads CHECK_FAILED
    world.comment(feature, f"{FAILED}\nThe API returned no `colour`; it must.", gate, bot=True)
    code, verdict = row(feature)
    assert code == 1 and verdict is not None and verdict[0] == "CHECK_FAILED"

    # The fix is filed as a new child: BLOCKED on it, then VERIFY_DUE again once it closes
    world.open(fix, "Serialise colour in the API's item view")
    world.comment(fix, "Triage: **implement**. The fix the parent's check asked for.", gate, bot=True)
    assert world.chains("link", feature, "--child", fix)[0] == 0
    assert row(feature)[1] == (
        "BLOCKED",
        f"children 2/3 closed {reader}:closed(child) {api}:closed(child) {fix}:open(child)",
    )
    world.close(fix, gate, bot=True, pr=12)
    assert row(feature)[1] is not None and row(feature)[1][0] == "VERIFY_DUE"  # type: ignore[index]

    # The check holds: the session closes the parent, then posts its verified comment
    world.close(feature, gate, bot=True)
    assert row(feature) == (1, ("VERIFY_CLOSED", "closed by @shipmill-gate[bot]: run its ## Check"))
    world.comment(feature, f"{VERIFIED}\nThe API returned `colour`. Children: #2, #3, #4 merged.", gate, bot=True)
    assert world.triage("acme/app") == (0, {})
