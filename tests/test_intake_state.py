"""The product-intake skill's state script (#69), without gh or the network"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "intake_state.py"


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def issue(
    number: int,
    *comments: str,
    labels: tuple[str, ...] = (),
    body: str = "",
    thumbs: int = 0,
    state: str = "OPEN",
    reason: str | None = None,
    closed_at: str | None = None,
    commented_at: str = "2026-10-01T10:00:00Z",
) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "url": f"https://github.com/o/r/issues/{number}",
        "state": state,
        "stateReason": reason,
        "closedAt": closed_at,
        "body": body,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "reactions": {"totalCount": thumbs},
        "comments": {
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
            "nodes": [said(c, commented_at) for c in comments],
        },
    }


def said(
    body: str, at: str, association: str = "MEMBER", login: str = "maintainer", kind: str = "User"
) -> dict[str, Any]:
    """A comment as GitHub returns it; by a member unless the test says otherwise"""
    return {
        "body": body,
        "createdAt": at,
        "author": {"__typename": kind, "login": login},
        "authorAssociation": association,
    }


def opportunity(number: int, members: str, *comments: str, **kwargs: Any) -> dict[str, Any]:
    body = f"## Problem\n\nSlow.\n\n## Evidence\n\n{members}\n\n## Success\n\nFast, unlike #999.\n"
    labels = ("opportunity", *kwargs.pop("labels", ()))
    return issue(number, *comments, body=body, labels=labels, **kwargs)


def discussion(number: int, *, closed: bool = False, category: str = "Ideas", thumbs: int = 0) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Discussion {number}",
        "url": f"https://github.com/o/r/discussions/{number}",
        "closed": closed,
        "category": {"name": category},
        "reactions": {"totalCount": thumbs},
    }


class Fake:
    """GitHub, answering each query from fixtures; records the queries it was asked"""

    def __init__(
        self,
        opened: list[dict[str, Any]],
        opportunities: list[dict[str, Any]],
        discussions: list[dict[str, Any]] | None = None,
        closed_thumbs: dict[int, int] | None = None,
    ) -> None:
        self.opened = opened
        self.opportunities = opportunities
        self.discussions = discussions
        self.closed_thumbs = closed_thumbs or {}
        self.asked: list[str] = []

    @staticmethod
    def page(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.asked.append(query)
        if "labels: [$label]" in query:
            repo: dict[str, Any] = {"issues": self.page(self.opportunities)}
        elif "issues(states: OPEN" in query:
            repo = {"hasDiscussionsEnabled": self.discussions is not None, "issues": self.page(self.opened)}
        elif "discussions(" in query:
            repo = {"discussions": self.page(self.discussions or [])}
        elif "issueOrPullRequest" in query:
            numbers = [int(n) for n in re.findall(r"m(\d+):", query)]
            repo = {f"m{n}": {"reactions": {"totalCount": self.closed_thumbs.get(n, 0)}} for n in numbers}
        else:
            raise AssertionError(f"unexpected query: {query}")
        return {"data": {"repository": repo}}


def states(ist: ModuleType, fake: Fake, **kwargs: Any) -> dict[int, tuple[str, str]]:
    options: dict[str, Any] = {
        "label": "opportunity",
        "accepted": "planned",
        "marker": "Triage:",
        "skip": set(ist.SKIP_LABELS),
        "categories": None,
        "autonomy": "propose",
        **kwargs,
    }
    intake = ist.fetch("o/r", run=fake, **options)
    return {r.number: (r.state, r.note) for r in ist.rows(intake)}


def test_evidence_reads_only_the_evidence_section_of_this_repo(ist: ModuleType) -> None:
    body = (
        "Fixes nothing, see #1.\n\n## Evidence\n\n- #12 (+1 3)\n- o/r#13\n- other/repo#14\n"
        "- https://github.com/O/R/discussions/15\n- https://github.com/o/r/issues/16#issuecomment-1\n"
        "- https://github.com/x/y/issues/17\n\n## Success\n\n- #18\n"
    )
    assert ist.evidence(body, "o", "r") == {12, 13, 15, 16}
    assert ist.evidence("", "o", "r") == set()


def test_the_verdict_is_the_first_bold_word_of_a_triage_comment(ist: ModuleType) -> None:
    assert ist.verdict("Triage: **implement**, phase 3", "Triage:") == "implement"
    assert ist.verdict("  Triage: **postponed to 1.1**. A feature later", "Triage:") == "postponed to 1.1"
    assert ist.verdict("Triage: clarify which flag", "Triage:") == "clarify"
    assert ist.verdict("Thanks!", "Triage:") is None


def test_feedback_is_what_triage_left_to_intake(ist: ModuleType) -> None:
    fake = Fake(
        [
            issue(1),  # untriaged
            issue(2, "Triage: **implement**"),  # a bug or a contract change: triage's
            issue(3, "Triage: **feature**. Spec in #9"),  # already in the spec gate
            issue(4, "Triage: **postponed to 1.1**"),  # postponed: triage's (spec 074)
            issue(5, labels=("bug",)),
            issue(6, "Triage: **won't fix**"),
            issue(7, "Triage: **implement**", "Triage: **needs a decision**"),  # the newest verdict counts
        ],
        [],
    )
    found = states(ist, fake)
    assert {n for n, (s, _) in found.items() if s == "NEW_FEEDBACK"} == {1, 7}


def test_1628_a_postponed_issue_or_a_persons_item_is_never_feedback(ist: ModuleType) -> None:
    """#1628: triage_state.py reads an issue labelled postponed with a trusted triage comment
    as POSTPONED, whatever that comment says, and one labelled human or role:<name> as a
    person's item, so intake must not read either as a request to group. Labelled postponed
    with no trusted triage comment, triage reads it NEW (#1766), and so it is feedback"""
    handed = triage_template("Opportunity")
    fake = Fake(
        [
            issue(1),  # an ordinary request: still feedback
            issue(2, labels=("postponed",)),  # postponed with no Triage: comment: NEW in triage (#1766)
            issue(3, labels=("role:maintainer", "postponed")),
            issue(4, labels=("human",)),
            issue(5, labels=("role:infra",)),
            issue(6, labels=("Role:Infra",)),  # triage compares these case-insensitively
            issue(7, labels=("Human",)),
            issue(8, handed, labels=("postponed",)),  # the label outweighs a hand-off, as in triage
            issue(9, labels=("enhancement",)),  # any other label leaves it feedback
        ],
        [],
    )
    found = states(ist, fake)
    assert {n for n, (s, _) in found.items() if s == "NEW_FEEDBACK"} == {1, 2, 9}


def test_1774_a_filed_plan_item_or_a_project_head_is_never_feedback(ist: ModuleType) -> None:
    """#1774: intake files an accepted plan's items with the plan-item marker as their first
    line and the project label; a trusted, untriaged item is the maintainer's accepted work,
    not a request to group, while an outsider's copy of the marker changes nothing (D-16)"""
    marker = "<!-- shipmill:plan-item #12 W-1 -->"

    def by(number: int, association: str, login: str, kind: str = "User", **kwargs: Any) -> dict[str, Any]:
        found = issue(number, **kwargs)
        found["author"] = {"__typename": kind, "login": login}
        found["authorAssociation"] = association
        return found

    fake = Fake(
        [
            by(1, "NONE", "shipmill-o", "Bot", body=f"{marker}\n\nDo W-1."),  # the --bot-login's item
            by(2, "MEMBER", "maintainer", body=f"{marker}\nDo W-1."),  # a member's item
            by(3, "OWNER", "owner", body="The plan", labels=("project",)),  # a project head
            by(4, "NONE", "mallory", body=f"{marker}\n\nPlease build this."),  # an outsider's copy
            by(5, "MEMBER", "maintainer", body=f"Context first\n{marker}"),  # the marker only counts first
            by(6, "NONE", "someone-else", "Bot", body=f"{marker}\n"),  # another bot is no --bot-login
            by(7, "CONTRIBUTOR", "mallory", body="A request"),
        ],
        [],
    )
    found = states(ist, fake, bot_login="shipmill-o[bot]")
    assert {n for n, (s, _) in found.items() if s == "NEW_FEEDBACK"} == {4, 5, 6, 7}
    assert "project" in ist.SKIP_LABELS


def test_s074_1_a_postponed_issue_is_feedback_again_only_after_a_newer_opportunity(ist: ModuleType) -> None:
    """proves: S-074-1"""
    postponed = triage_template("Postpone")
    assert ist.verdict(postponed, "Triage:").startswith("postponed")
    handed = triage_template("Opportunity")
    reopened = issue(2)
    reopened["comments"]["nodes"] = [said(postponed, "2026-10-01T10:00:00Z"), said(handed, "2026-10-05T10:00:00Z")]
    stale = issue(3)
    stale["comments"]["nodes"] = [
        said(handed, "2026-10-01T10:00:00Z"),
        said("Triage: **postponed**: it serves no goal of the direction.", "2026-10-05T10:00:00Z"),
    ]
    fake = Fake([issue(1, postponed), reopened, stale, issue(4, "Triage: **postponed to 1.1**")], [])
    assert states(ist, fake) == {2: ("NEW_FEEDBACK", "issue")}


def json_lines(ist: ModuleType, fake: Fake, bot_login: str | None = None) -> dict[int, dict[str, Any]]:
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(ist.SKIP_LABELS),
        categories=None,
        autonomy="propose",
        bot_login=bot_login,
        run=fake,
    )
    return {r.number: ist.json_row(r) for r in ist.rows(intake)}


def test_1374_only_a_trusted_triage_comment_hides_or_hands_over_a_request(ist: ModuleType) -> None:
    """A `Triage:` comment counts from an OWNER, MEMBER, or COLLABORATOR or the --bot-login
    (D-16); anyone else's reads as absent, the trusted one before it still counting"""
    handed = triage_template("Opportunity")
    early, late = "2026-10-01T10:00:00Z", "2026-10-05T10:00:00Z"
    cases = {
        1: [said("Triage: **postponed**", early, "NONE", "mallory")],  # a stranger's postpone hides nothing
        2: [said("Triage: **postponed**", early), said(handed, late, "NONE", "mallory")],  # nor undoes a member's
        3: [said(handed, early, "CONTRIBUTOR", "mallory")],  # a stranger's hand-off marks nothing handed
        4: [said("Triage: **postponed**", early, "NONE", "shipmill-o", "Bot")],  # the --bot-login's counts
        5: [said("Triage: **postponed**", early, "OWNER", "owner"), said(handed, late, "NONE", "shipmill-o", "Bot")],
        6: [said("Triage: **postponed**", early, "NONE", "other-app", "Bot")],  # another App is no one
        7: [said(handed, late, "COLLABORATOR", "carol")],
    }
    opened = []
    for number, comments in cases.items():
        request = issue(number)
        request["comments"]["nodes"] = comments
        opened.append(request)

    found = json_lines(ist, Fake(opened, []), bot_login="shipmill-o[bot]")
    assert {n for n, line in found.items() if line["state"] == "NEW_FEEDBACK"} == {1, 3, 5, 6, 7}
    assert {n: found[n]["handed"] for n in (1, 3, 5, 6, 7)} == {1: None, 3: None, 5: late, 6: None, 7: late}

    # without --bot-login the App is anyone: its postpone on 4 hides nothing, and its hand-off
    # on 5 leaves the owner's postpone before it standing
    found = json_lines(ist, Fake(opened, []))
    assert {n for n, line in found.items() if line["state"] == "NEW_FEEDBACK"} == {1, 3, 4, 6, 7}


class Paging(Fake):
    """Fake, with one older page of comments behind every issue's newest 50"""

    def __init__(self, opened: list[dict[str, Any]], older: list[dict[str, Any]]) -> None:
        super().__init__(opened, [])
        self.older = older

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "before: $cursor" not in query:
            return super().__call__(query, variables)
        self.asked.append(query)
        page = {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": self.older}
        return {"data": {"repository": {"issue": {"comments": page}}}}


def test_1374_paging_back_reads_past_a_strangers_triage_comment(ist: ModuleType) -> None:
    """A stranger's newest `Triage:` comment doesn't stop the paging: the member's older
    postpone, on the page before, still counts, read with its author"""
    request = issue(1)
    request["comments"] = {
        "pageInfo": {"hasPreviousPage": True, "startCursor": "c1"},
        "nodes": [said("Triage: **opportunity**", "2026-10-05T10:00:00Z", "NONE", "mallory")],
    }
    fake = Paging([request], [said("Triage: **postponed**", "2026-10-01T10:00:00Z")])
    assert json_lines(ist, fake) == {}
    older = [q for q in fake.asked if "before: $cursor" in q]
    assert len(older) == 1 and "authorAssociation" in older[0] and "author { __typename login }" in older[0]
    assert all("authorAssociation" in q for q in fake.asked if "issues(" in q)


def test_1384_only_a_trusted_triage_comment_hands_off_an_accepted_opportunity(ist: ModuleType) -> None:
    """A stranger's `Triage: **feature**` leaves an accepted opportunity ACCEPTED; a member's or
    the --bot-login's hands it off"""
    early, late = "2026-10-01T10:00:00Z", "2026-10-05T10:00:00Z"
    feature = "Triage: **feature**. On hold: o/r#40"
    cases = {
        10: said(feature, late, "NONE", "mallory"),
        11: said(feature, late, "CONTRIBUTOR", "mallory"),
        12: said(feature, late),
        13: said(feature, late, "NONE", "shipmill-o", "Bot"),
    }
    opps = []
    for number, newest in cases.items():
        opp = opportunity(number, f"- #{number - 9}", labels=("planned",))
        opp["comments"]["nodes"] = [said("Triage: **opportunity**", early, "NONE", "shipmill-o", "Bot"), newest]
        opps.append(opp)
    found = states(ist, Fake([], opps), bot_login="shipmill-o[bot]")
    assert {n: found[n][0] for n in cases} == {10: "ACCEPTED", 11: "ACCEPTED", 12: "HANDED_OFF", 13: "HANDED_OFF"}
    assert found[12][1] == "triage: feature"


def test_1384_a_decline_reason_skips_only_a_trusted_triage_comment(ist: ModuleType) -> None:
    """A trusted `Triage:` comment is never the reason; a stranger's is an ordinary comment"""
    closed, before = "2026-10-02T10:00:00Z", "2026-10-02T09:59:58Z"
    reason = said("Out of scope (D-6).", "2026-10-02T09:59:59Z")
    cases = {
        10: said("Triage: **opportunity**", before),
        11: said("Triage: **opportunity**", before, "NONE", "shipmill-o", "Bot"),
        12: said("Triage: **reopen** this", before, "NONE", "mallory"),
    }
    opps = []
    for number, first in cases.items():
        opp = opportunity(number, f"- #{number - 9}", state="CLOSED", reason="NOT_PLANNED", closed_at=closed)
        opp["comments"]["nodes"] = [first, reason]
        opps.append(opp)
    found = states(ist, Fake([], opps), bot_login="shipmill-o[bot]")
    assert found[10] == found[11] == ("DECLINED", "Out of scope (D-6).")
    assert found[12] == ("DECLINED", "Triage: **reopen** this")


def test_1384_only_a_trusted_triage_comment_serves_a_goal(ist: ModuleType) -> None:
    """A stranger's `Triage: ... Serves: G-n` serves nothing, so the goal's plan stays due"""
    goals = [ist.Goal("G-1", "Releases go out on their own")]
    served = "Triage: **feature**. Serves: G-1."

    def rows_for(comment: dict[str, Any], bot_login: str | None) -> dict[str, str]:
        request = issue(1)
        request["comments"]["nodes"] = [comment]
        found = ist.plan_rows(
            goals,
            open_issues=[request],
            opportunities=[],
            plan_issues=[],
            pulls=[],
            specs=[],
            marker="Triage:",
            bot_login=bot_login,
            wip=None,
            room=lambda limit: 1,
        )
        return {r.goal: r.note for r in found}

    at = "2026-10-01T10:00:00Z"
    assert rows_for(said(served, at, "NONE", "mallory"), "shipmill-o[bot]") == {"G-1": "no-work"}
    assert rows_for(said(served, at, "CONTRIBUTOR", "mallory"), None) == {"G-1": "no-work"}
    assert rows_for(said(served, at, "NONE", "shipmill-o", "Bot"), None) == {"G-1": "no-work"}
    assert rows_for(said(served, at), None) == {}
    assert rows_for(said(served, at, "NONE", "shipmill-o", "Bot"), "shipmill-o[bot]") == {}


def test_s074_2_feedback_and_accepted_lines_carry_author_association_and_handed(ist: ModuleType) -> None:
    """proves: S-074-2"""
    handed = triage_template("Opportunity")
    untriaged = issue(1)
    untriaged["author"] = {"__typename": "User", "login": "alice"}
    untriaged["authorAssociation"] = "NONE"
    over = issue(2)
    over["author"] = {"__typename": "Bot", "login": "shipmill-o"}
    over["authorAssociation"] = "CONTRIBUTOR"
    over["comments"]["nodes"] = [
        said("Triage: **clarify** which flag", "2026-10-01T10:00:00Z"),
        said(handed, "2026-10-03T10:00:00Z"),
        said("Thanks, any news?", "2026-10-04T10:00:00Z", "NONE", "alice"),
    ]
    clarify = issue(3, "Triage: **clarify** which flag")
    ghost = issue(4)
    ghost["author"] = None
    accepted = opportunity(10, "- #9", "Triage: **opportunity**", labels=("planned",))
    accepted["author"] = {"__typename": "User", "login": "owner"}
    accepted["authorAssociation"] = "OWNER"
    waiting = opportunity(11, "- #8", "Triage: **opportunity**")
    talk = discussion(20)
    talk["author"] = {"__typename": "User", "login": "bob"}
    fake = Fake([untriaged, over, clarify, ghost], [accepted, waiting], discussions=[talk])
    found = json_lines(ist, fake)

    assert found[1]["state"] == "NEW_FEEDBACK"
    assert (found[1]["author"], found[1]["association"], found[1]["handed"]) == ("alice", "NONE", None)
    assert (found[2]["author"], found[2]["association"]) == ("shipmill-o[bot]", "CONTRIBUTOR")
    assert found[2]["handed"] == "2026-10-03T10:00:00Z"  # the hand-off's createdAt, not a later reply's
    assert found[3]["handed"] is None  # the newest verdict isn't a hand-off
    assert found[4]["author"] is None  # GitHub returned no opener
    assert found[20]["kind"] == "discussion" and found[20]["state"] == "NEW_FEEDBACK"
    assert (found[20]["author"], found[20]["association"], found[20]["handed"]) == ("bob", None, None)
    assert found[10]["state"] == "ACCEPTED"
    assert (found[10]["author"], found[10]["association"], found[10]["handed"]) == ("owner", "OWNER", None)
    assert found[11]["state"] == "OPPORTUNITY_OPEN"
    assert not {"author", "association", "handed"} & set(found[11])  # other lines keep their keys


def test_an_opportunity_groups_its_members_instead_of_a_second_one(ist: ModuleType) -> None:
    fake = Fake(
        [issue(1, thumbs=2), issue(2, thumbs=1), issue(3)],
        [opportunity(10, "- #1\n- #2\n- #4", thumbs=1)],
        closed_thumbs={4: 5},
    )
    found = states(ist, fake)
    assert found == {10: ("OPPORTUNITY_OPEN", ""), 3: ("NEW_FEEDBACK", "issue")}
    intake = ist.fetch(
        "o/r",
        label="opportunity",
        accepted="planned",
        marker="Triage:",
        skip=set(),
        categories=None,
        autonomy="propose",
        run=fake,
    )
    (row,) = [r for r in ist.rows(intake) if r.number == 10]
    assert row.members == [1, 2, 4] and row.thumbs == 1 + 2 + 1 + 5  # its own, and each member's, closed too


def test_a_request_in_two_live_opportunities_overlaps(ist: ModuleType) -> None:
    fake = Fake(
        [issue(1)],
        [
            opportunity(10, "- #1"),
            opportunity(11, "- #1", labels=("planned",)),
            opportunity(12, "- #1", state="CLOSED", reason="DUPLICATE", closed_at="2026-10-02T10:00:00Z"),
        ],
    )
    found = states(ist, fake)
    assert found[1] == ("OVERLAP", "#10:opportunity_open, #11:accepted")
    assert found[12] == ("MERGED", "closed as a duplicate")


def test_the_maintainers_call_sets_each_opportunity_state(ist: ModuleType) -> None:
    closed = "2026-10-02T10:00:00Z"
    fake = Fake(
        [],
        [
            opportunity(10, "- #1", "Triage: **opportunity**, waiting for the maintainer"),
            opportunity(11, "- #2", "Triage: **opportunity**", labels=("planned",)),
            opportunity(
                12, "- #3", "Triage: **opportunity**", "Triage: **feature**. On hold: o/r#40", labels=("planned",)
            ),
            opportunity(
                13,
                "- #4",
                "Triage: **opportunity**",
                "Out of scope: shipmill stays GitHub-only (D-6).\nMore detail.",
                state="CLOSED",
                reason="NOT_PLANNED",
                closed_at=closed,
                commented_at="2026-10-02T09:59:58Z",
            ),
            opportunity(14, "- #5", "Triage: **opportunity**", state="CLOSED", reason="NOT_PLANNED", closed_at=closed),
            opportunity(15, "- #6", state="CLOSED", reason="COMPLETED", closed_at=closed),
        ],
    )
    found = states(ist, fake)
    assert found[10] == ("OPPORTUNITY_OPEN", "")
    assert found[11] == ("ACCEPTED", "hand it to triage's spec gate")
    assert found[12] == ("HANDED_OFF", "triage: feature")
    assert found[13] == ("DECLINED", "Out of scope: shipmill stays GitHub-only (D-6).")
    assert found[14] == ("NO_REASON", "closed as not planned with no comment")
    assert found[15] == ("DONE", "")


def test_an_old_comment_is_not_a_decline_reason(ist: ModuleType) -> None:
    old = opportunity(
        13,
        "- #4",
        "I want this",
        state="CLOSED",
        reason="NOT_PLANNED",
        closed_at="2026-10-05T10:00:00Z",
        commented_at="2026-10-01T10:00:00Z",
    )
    assert states(ist, Fake([], [old]))[13][0] == "NO_REASON"


def test_a_later_reply_does_not_replace_the_decline_reason(ist: ModuleType) -> None:
    declined = opportunity(13, "- #4", state="CLOSED", reason="NOT_PLANNED", closed_at="2026-10-02T10:00:00Z")
    declined["comments"]["nodes"] = [
        {"body": "Out of scope (D-6).", "createdAt": "2026-10-02T09:59:58Z"},
        {"body": "Triage: **opportunity**", "createdAt": "2026-10-03T10:00:00Z"},
        {"body": "Please reconsider, we need this", "createdAt": "2026-10-04T10:00:00Z"},
    ]
    assert states(ist, Fake([], [declined]))[13] == ("DECLINED", "Out of scope (D-6).")


def test_a_roadmap_tracking_issue_is_not_feedback(ist: ModuleType) -> None:
    """The default skip labels include roadmap (#26 read as NEW_FEEDBACK); --skip-label adds to them"""
    fake = Fake([issue(1, labels=("roadmap",)), issue(2, labels=("epic",)), issue(3)], [])
    assert states(ist, fake) == {2: ("NEW_FEEDBACK", "issue"), 3: ("NEW_FEEDBACK", "issue")}
    skip = ist.skip_labels(["epic"])
    assert skip == {*ist.SKIP_LABELS, "epic"}
    assert states(ist, fake, skip=skip) == {3: ("NEW_FEEDBACK", "issue")}


def test_a_declined_groups_members_are_never_proposed_again(ist: ModuleType) -> None:
    """A new request the skill links into the declined opportunity's evidence reads as declined"""
    fake = Fake(
        [issue(1), issue(2)],
        [
            opportunity(
                13,
                "- #1\n- #2",
                "No: out of scope.",
                state="CLOSED",
                reason="NOT_PLANNED",
                closed_at="2026-10-01T10:00:00Z",
            )
        ],
    )
    assert states(ist, fake) == {13: ("DECLINED", "No: out of scope.")}


def test_discussions_count_when_enabled_outside_announcements(ist: ModuleType) -> None:
    fake = Fake(
        [],
        [opportunity(10, "- https://github.com/o/r/discussions/21")],
        discussions=[
            discussion(20, thumbs=4),
            discussion(21),
            discussion(22, closed=True),
            discussion(23, category="Announcements"),
        ],
    )
    assert states(ist, fake) == {10: ("OPPORTUNITY_OPEN", ""), 20: ("NEW_FEEDBACK", "discussion")}
    assert states(ist, fake, categories={"Announcements"}) == {
        10: ("OPPORTUNITY_OPEN", ""),
        23: ("NEW_FEEDBACK", "discussion"),
    }


def test_no_discussions_query_when_they_are_off(ist: ModuleType) -> None:
    fake = Fake([issue(1)], [])
    states(ist, fake)
    assert not any("discussions(" in q for q in fake.asked)


def test_more_than_100_labels_is_refused(ist: ModuleType) -> None:
    capped = issue(1)
    capped["labels"]["pageInfo"]["hasNextPage"] = True
    with pytest.raises(SystemExit) as caught:
        states(ist, Fake([capped], []))
    assert caught.value.code == 2


def test_intake_autonomy_defaults_to_propose_and_never_acts(ist: ModuleType, tmp_path: Path) -> None:
    config = tmp_path / "shipmill.toml"
    assert ist.intake_autonomy(None) == "propose"
    config.write_text('name = "x"\n[autonomy]\nrelease = "act"\ndeploy.production = "act"\n')
    assert ist.intake_autonomy(config) == "propose"
    config.write_text('[autonomy]\nintake = "observe"  # report only\n')
    assert ist.intake_autonomy(config) == "observe"
    for bad in ('"act"', '"auto"', "1"):
        config.write_text(f"[autonomy]\nintake = {bad}\n")
        with pytest.raises(SystemExit):
            ist.intake_autonomy(config)


def test_the_310_reader_reads_plain_lines_and_refuses_the_rest(ist: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "shipmill.toml"
    text = "[lanes.dev]\nintake = \"no\"\n[autonomy]\nintake = 'observe'\nwip = 3\non = true\n[roadmap]\nwip = 4\n"
    assert ist.config_values_310(text, path, "autonomy", ("intake", "wip", "on")) == {
        "intake": "observe",
        "wip": 3,
        "on": True,
    }
    assert ist.config_values_310(text, path, "roadmap", ("wip", "cadence")) == {"wip": 4}
    for unreadable in ('autonomy.intake = "observe"\n', '[autonomy]\nintake = ["observe"]\n'):
        with pytest.raises(SystemExit):
            ist.config_values_310(unreadable, path, "autonomy", ("intake",))


COMMENTS = SCRIPT.parents[2] / "github-issue-triage" / "references" / "comments.md"


def triage_template(section: str, index: int = 0) -> str:
    """The ``index``-th markdown template under a ``## section`` heading of triage's comments.md"""
    text = COMMENTS.read_text(encoding="utf-8").split(f"\n## {section}\n", 1)[1].split("\n## ", 1)[0]
    return text.split("```markdown\n")[index + 1].split("\n```", 1)[0]


def test_a_request_triage_hands_over_is_feedback_until_an_opportunity_lists_it(ist: ModuleType) -> None:
    handed = triage_template("Opportunity")
    assert ist.verdict(handed, "Triage:") == "opportunity"
    covered = triage_template("Feature", 1)  # an accepted opportunity covers it: triage's
    fake = Fake([issue(1, handed), issue(2, handed), issue(3, covered)], [opportunity(10, "- #2")])
    found = states(ist, fake)
    assert found[1][0] == "NEW_FEEDBACK"  # handed over, not yet grouped
    assert found[10][0] == "OPPORTUNITY_OPEN"
    assert 2 not in found  # grouped: a member of #10, no row of its own
    assert 3 not in found  # not feedback: triage builds it under the accepted opportunity


def test_s106_29_a_project_check_issue_is_no_feedback(ist: ModuleType) -> None:
    """#1802: a sub-issue titled `Check: ` with a `## Check` section is its parent's closing
    check (spec 042, spec 106), never a request to group; without a parent it still is one"""
    check = {**issue(1, body="## Check\n\nRun it.\n"), "title": "Check: it works", "parent": {"number": 7}}
    orphan = {**issue(2, body="## Check\n\nRun it.\n"), "title": "Check: it works", "parent": None}
    untitled = {**issue(3, body="## Check\n\nRun it.\n"), "parent": {"number": 7}}
    found = states(ist, Fake([check, orphan, untitled], []))
    assert 1 not in found
    assert found[2][0] == "NEW_FEEDBACK"
    assert found[3][0] == "NEW_FEEDBACK"
    assert "parent { number }" in ist.ISSUE_FIELDS
