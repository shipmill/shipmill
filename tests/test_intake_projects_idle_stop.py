"""intake_state.py --projects reads an idle project and a stop (spec 106, #1741): PROJECT_IDLE,
PROJECT_STOP_DUE, and a stopped project's reason; without the network"""

import datetime as dt
from pathlib import Path
from types import ModuleType
from typing import Any

from .test_intake_outcomes import ist
from .test_intake_projects import BOT, NOW, check, head, sub, who

__all__ = ["ist"]  # the module fixture, shared with spec 101's tests

QUESTION = (
    "<!-- shipmill:needs-decision -->\n`@maintainer` Decision needed: continue, hold, or stop #7?\n"
    "<!-- shipmill:agent -->"
)
OLD = "2026-11-01T10:00:00Z"  # 25 days before NOW
DAYS_13 = "2026-11-13T13:00:00Z"  # less than 14 days before NOW


def said(author: str, body: str, at: str, association: str = "OWNER") -> dict[str, Any]:
    return {"author": who(author), "authorAssociation": association, "body": body, "createdAt": at}


def tree(updated: str, state: str = "OPEN", labels: tuple[str, ...] = ("project",), parts: int = 1) -> dict[str, Any]:
    """An active head whose whole tree was last updated at `updated`"""
    node = head(7, (check(), *(sub(8 + i) for i in range(parts))), labels=labels, state=state)
    node["createdAt"] = OLD
    for item in node["subIssues"]["nodes"]:
        item["updatedAt"] = updated
        for part in item["subIssues"]["nodes"]:
            part["updatedAt"] = updated
    return node


def action(ist: ModuleType, node: dict[str, Any], maintainers: frozenset[str] = frozenset()) -> tuple[str, str]:
    read = ist.project_row(node, BOT)
    found = ist.project_action(node, read, BOT, NOW, "Triage:", maintainers)
    return found.state, found.note


# -- S-106-17 -------------------------------------------------------------------------------


def test_s106_17_a_tree_with_no_update_for_14_days_reads_idle(ist: ModuleType) -> None:
    assert action(ist, tree(OLD)) == ("PROJECT_IDLE", "no change since 2026-11-01")
    assert action(ist, tree(DAYS_13)) == ("PROJECT_ACTIVE", "1 of 1 parts open")
    focus = tree(OLD, labels=("project", "focus"))
    assert action(ist, focus)[0] == "PROJECT_IDLE"
    closing = tree(OLD)
    closing["subIssues"]["nodes"][1]["state"] = "CLOSED"
    assert action(ist, closing)[0] == "PROJECT_IDLE"
    held = tree(OLD, labels=("project", "held"))
    assert action(ist, held)[0] == "PROJECT_HELD"  # a held head waits for its start, never idle
    row = ist.project_action(tree(OLD), ist.project_row(tree(OLD), BOT), BOT, NOW, "Triage:", frozenset())
    assert (row.holder, row.base, row.counted, "PROJECT_IDLE" in ist.PROJECT_ACTION) == (
        "agent",
        "PROJECT_ACTIVE",
        True,
        True,
    )


def test_s106_17_any_part_or_pull_request_of_the_tree_counts_as_an_update(ist: ModuleType) -> None:
    by_part = tree(OLD)
    by_part["subIssues"]["nodes"][0]["subIssues"]["nodes"] = [{"number": 90, "state": "OPEN", "updatedAt": DAYS_13}]
    assert action(ist, by_part)[0] == "PROJECT_ACTIVE"
    by_pull = tree(OLD)
    by_pull["subIssues"]["nodes"][1]["closedByPullRequestsReferences"] = {"nodes": [{"updatedAt": DAYS_13}]}
    assert action(ist, by_pull)[0] == "PROJECT_ACTIVE"
    by_comment = tree(OLD)
    by_comment["comments"]["nodes"] = [said("maintainer", "Still on it.", DAYS_13)]
    assert action(ist, by_comment)[0] == "PROJECT_ACTIVE"


def test_s106_17_the_bots_question_after_the_last_update_ends_idle(ist: ModuleType) -> None:
    asked = tree(OLD)
    asked["comments"]["nodes"] = [said(BOT, QUESTION, "2026-11-20T10:00:00Z", "NONE")]
    assert action(ist, asked)[0] == "PROJECT_ACTIVE"  # the question waits: no second one
    # the same question by anyone else counts for nothing, and is an update of the tree
    other = tree(OLD)
    other["comments"]["nodes"] = [said("someone", QUESTION, OLD, "NONE")]
    assert action(ist, other)[0] == "PROJECT_IDLE"
    # a question older than the last update is an earlier one
    stale = tree("2026-11-05T10:00:00Z")
    stale["comments"]["nodes"] = [said(BOT, QUESTION, OLD, "NONE")]
    assert action(ist, stale) == ("PROJECT_IDLE", "no change since 2026-11-05")


# -- S-106-18 -------------------------------------------------------------------------------


def test_s106_18_a_trusted_stop_reply_reads_stop_due(ist: ModuleType) -> None:
    stop = tree(DAYS_13)
    stop["comments"]["nodes"] = [said("maintainer", "stop: the outcome moved to #9\nmore words", DAYS_13)]
    assert action(ist, stop) == ("PROJECT_STOP_DUE", "stop: the outcome moved to #9")
    row = ist.project_action(stop, ist.project_row(stop, BOT), BOT, NOW, "Triage:", frozenset())
    assert (row.holder, row.counted, "PROJECT_STOP_DUE" in ist.PROJECT_ACTION) == ("agent", True, True)
    # any state, a held one too
    held = tree(DAYS_13, labels=("project", "held"))
    held["comments"]["nodes"] = [said("maintainer", "Stop: not now", DAYS_13)]
    assert action(ist, held) == ("PROJECT_STOP_DUE", "stop: not now")


def test_s106_18_stop_answering_the_idle_question_reads_stop_due(ist: ModuleType) -> None:
    answered = tree(OLD)
    answered["comments"]["nodes"] = [
        said(BOT, QUESTION, "2026-11-20T10:00:00Z", "NONE"),
        said("maintainer", "stop\n\nThe goal was dropped.", "2026-11-21T10:00:00Z"),
    ]
    assert action(ist, answered) == ("PROJECT_STOP_DUE", "stop: The goal was dropped.")
    # without a question before it, or without a reason, a bare `stop` is no stop
    bare = tree(DAYS_13)
    bare["comments"]["nodes"] = [said("maintainer", "stop\nno question asked", DAYS_13)]
    assert action(ist, bare)[0] == "PROJECT_ACTIVE"
    reasonless = tree(OLD)
    reasonless["comments"]["nodes"] = [
        said(BOT, QUESTION, "2026-11-20T10:00:00Z", "NONE"),
        said("maintainer", "stop", "2026-11-21T10:00:00Z"),
    ]
    assert action(ist, reasonless)[0] == "PROJECT_ACTIVE"
    # a relay of the maintainer's answer is that answer (D-68)
    relayed = tree(OLD)
    relay = "Decision by `@maintainer`, relayed by Claude Code\n\nstop: the release moved\n<!-- shipmill:agent -->"
    relayed["comments"]["nodes"] = [said(BOT, relay, "2026-11-21T10:00:00Z", "NONE")]
    assert action(ist, relayed, frozenset({"maintainer"})) == ("PROJECT_STOP_DUE", "stop: the release moved")


def test_s106_18_an_untrusted_or_older_stop_changes_nothing(ist: ModuleType) -> None:
    outsider = tree(DAYS_13)
    outsider["comments"]["nodes"] = [said("drive-by", "stop: I don't like it", DAYS_13, "NONE")]
    assert action(ist, outsider)[0] == "PROJECT_ACTIVE"
    by_bot = tree(DAYS_13)
    by_bot["comments"]["nodes"] = [said(BOT, "stop: on its own", DAYS_13, "NONE")]
    assert action(ist, by_bot)[0] == "PROJECT_ACTIVE"
    lifted = tree(DAYS_13)
    lifted["comments"]["nodes"] = [
        said("maintainer", "stop: not now", "2026-11-20T10:00:00Z"),
        said("maintainer", "continue after all", "2026-11-21T10:00:00Z"),
    ]
    assert action(ist, lifted)[0] == "PROJECT_ACTIVE"
    # a closed head is past its stop
    closed = tree(DAYS_13, state="CLOSED")
    closed["stateReason"] = "COMPLETED"
    closed["comments"]["nodes"] = [said("maintainer", "stop: late", DAYS_13)]
    assert ist.project_row(closed, BOT).state == "PROJECT_CLOSED"
    assert action(ist, closed)[0] == "PROJECT_CLOSED"


# -- S-106-19, S-106-21 ---------------------------------------------------------------------

SKILL = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "SKILL.md"


def test_s106_21_a_stopped_projects_row_names_its_record_and_reason(ist: ModuleType) -> None:
    record = "<!-- shipmill:project-stopped -->\nThe outcome moved to #9.\n<!-- shipmill:agent -->"
    node = tree(DAYS_13, state="CLOSED")
    node["stateReason"] = "NOT_PLANNED"
    node["comments"]["nodes"] = [said(BOT, record, DAYS_13, "NONE")]
    assert ist.project_row(node, BOT).note == "stopped: The outcome moved to #9."
    text = SKILL.read_text(encoding="utf-8")
    assert "matches a new request against each PROJECT_STOPPED row's outcome as against a DECLINED opportunity" in text
    assert "naming the stop record" in text


def test_s106_19_the_skill_gives_the_stop_step() -> None:
    text = SKILL.read_text(encoding="utf-8")
    step = next(line for line in text.splitlines() if line.startswith("**PROJECT_STOP_DUE: stop the project.**"))
    for words in (
        "as not planned with the comment `Project stopped: <reason>`",
        "closes their open pull requests unmerged",
        "`shipmill revert open`",
        "only for each pull request a `Revert on stop: #<pr>[, #<pr>]` line of the check issue names",
        "sets the status of the project's spec (the approved one its head's body links) to `stopped`",
        "`<!-- shipmill:project-stopped -->`",
    ):
        assert words in step, words
    idle = next(line for line in text.splitlines() if line.startswith("**PROJECT_IDLE: ask"))
    assert "continue, hold, or stop" in idle and "label the head `held`" in idle


def test_s106_17_the_idle_note_dates_the_last_update(ist: ModuleType) -> None:
    assert ist.tree_updated(tree(OLD), BOT) == dt.datetime(2026, 11, 1, 10, tzinfo=dt.UTC)
