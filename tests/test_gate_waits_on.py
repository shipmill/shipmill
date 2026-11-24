"""Spec 089 (S-089-12): a subject left unchanged because it waits on another item names that
item in a comment whose first line is `<!-- shipmill:waits-on owner/repo#N -->`, posted as the
--bot-login; the walk that finds the subject idle hands it again once the named item was
updated after the hand. A marker by anyone else counts for nothing"""

import datetime as dt
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from shipmill.agents import Mode
from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.gate import Action, StateRead, WatchState, state_dir
from shipmill.gitrepo import Git
from shipmill.walk import HANDED, Hand, Handed, Head, Pull, Waited, waited_updates, waits, waits_on

from .test_gate import checkout
from .test_gate_walk import NOW, REPO, Source, cfg, handed, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

SHA = "a" * 40
HEAD = Head(SHA, "SUCCESS")
BEFORE = NOW - dt.timedelta(hours=25)  # a hand past retry_hours (24)
BOT = "shipmill-demo[bot]"
APP = {"__typename": "Bot", "login": "shipmill-demo"}  # the bot as GraphQL spells its login
PERSON = {"__typename": "User", "login": "amy"}
PRS = Finding("PRS_OPEN", REPO, "#3", False, ((3, SHA),), "land")


def seed(git: Git, idle: bool = False) -> None:
    hands = {"PRS_OPEN #3": Hand("s0", BEFORE, HEAD, idle=idle)}  # an interactive gate's: no end
    Handed(hands).save(state_dir(git) / HANDED)


def unchanged() -> dict[int, Pull]:
    return {3: Pull(HEAD, BEFORE - dt.timedelta(hours=1))}


# -- the walk


@pytest.mark.parametrize("idle", [False, True], ids=["past retry", "already idle"])
def test_s089_12_an_idle_subject_whose_waited_item_changed_since_its_hand_is_handed_again(
    checkout: Git, idle: bool
) -> None:
    seed(checkout, idle)
    source = Source({3: [PRS]}, pulls=unchanged(), waits={3: BEFORE + dt.timedelta(hours=2)})
    decision = tick(checkout, source, NOW, cfg())
    assert decision.action is Action.LAUNCH
    assert "waited #3" in source.reads
    assert handed(checkout)["PRS_OPEN #3"]["session"] != "s0"


def test_s089_12_a_subject_whose_waited_item_didnt_change_stays_idle(checkout: Git) -> None:
    seed(checkout)
    source = Source({3: [PRS]}, pulls=unchanged(), waits={3: BEFORE - dt.timedelta(minutes=1)})
    decision = tick(checkout, source, NOW, cfg())
    assert decision.action is Action.UNCHANGED and handed(checkout)["PRS_OPEN #3"]["idle"] is True


def test_s089_12_a_subject_within_retry_reads_no_marker(checkout: Git) -> None:
    Handed({"PRS_OPEN #3": Hand("s0", NOW - dt.timedelta(hours=1), HEAD)}).save(state_dir(checkout) / HANDED)
    source = Source({3: [PRS]}, pulls=unchanged())
    tick(checkout, source, NOW, cfg(Mode.INTERACTIVE))
    assert not any(r.startswith("waited") for r in source.reads)


# -- reading the markers


class GraphQL:
    """Answers the waits-on queries: each subject's comments, and each named item's updatedAt"""

    def __init__(self, comments: Mapping[int, list[dict[str, Any]]], updated: Mapping[str, str | None]) -> None:
        self.comments, self.updated = comments, updated
        self.queries: list[str] = []

    def __call__(self, query: str, variables: Mapping[str, str]) -> dict[str, Any]:
        self.queries.append(query)
        if "comments(last: 50)" in query:
            assert dict(variables) == {"owner": "romamo", "name": "demo"}
            numbers = [int(n) for n in re.findall(r"i(\d+): issueOrPullRequest", query)]
            repo = {f"i{n}": {"comments": {"nodes": self.comments.get(n, [])}} for n in numbers}
            return {"data": {"repository": repo}}
        found = re.findall(r'(w\d+): resource\(url: "https://github\.com/([^/"]+/[^/"]+)/issues/(\d+)"\)', query)
        data: dict[str, Any] = {}
        for alias, repo, number in found:
            at = self.updated.get(f"{repo}#{number}")
            data[alias] = None if at is None else {"updatedAt": at}
        return {"data": data}


def marker(named: str, rest: str = "\nOn hold: waits on the answer there.") -> str:
    return f"<!-- shipmill:waits-on {named} -->{rest}"


def test_s089_12_the_newest_marker_by_the_bot_names_the_waited_item() -> None:
    comments = {
        3: [
            {"author": APP, "body": marker("romamo/demo#7")},
            {"author": APP, "body": marker("other/lib#12")},  # the newest by the bot wins
            {"author": PERSON, "body": marker("romamo/demo#9")},  # anyone else's counts for nothing
            {"author": APP, "body": "Still waiting.\n" + marker("romamo/demo#10", "")},  # not its first line
        ],
        4: [{"author": PERSON, "body": marker("romamo/demo#7")}],
        5: [{"author": {"__typename": "User", "login": BOT}, "body": marker("romamo/demo#8")}],  # REST's spelling
    }
    found = waits_on(REPO, [3, 4, 5], BOT, GraphQL(comments, {}))
    assert found == {3: Waited("other/lib", 12), 5: Waited("romamo/demo", 8)}


def test_s089_12_the_waited_items_are_read_across_repos_and_a_gone_one_wakes_nothing() -> None:
    graphql = GraphQL({}, {"romamo/demo#7": "2026-11-23T06:40:00Z", "other/lib#12": None})
    found = waited_updates([Waited("romamo/demo", 7), Waited("other/lib", 12)], graphql)
    assert found == {Waited("romamo/demo", 7): dt.datetime(2026, 11, 23, 6, 40, tzinfo=dt.UTC)}
    assert len(graphql.queries) == 1


def test_s089_12_a_subject_waiting_on_an_answer_elsewhere_wakes_once_it_comes() -> None:
    # #1441 waited on the answer on #1253; the answer came 2026-11-23 06:40, after the hand of 2026-11-20
    comments = {1441: [{"author": APP, "body": marker("shipmill/shipmill#1253")}]}
    graphql = GraphQL(comments, {"shipmill/shipmill#1253": "2026-11-23T06:40:00Z"})
    found = waits("romamo/demo", [1441], BOT, graphql)
    assert found == {1441: dt.datetime(2026, 11, 23, 6, 40, tzinfo=dt.UTC)}
    assert waits("romamo/demo", [1441], "someone-else[bot]", graphql) == {}


def test_s089_12_a_gate_without_an_apps_bot_reads_no_marker(checkout: Git) -> None:
    def gh(cmd: list[str], workspace: Path) -> str:
        raise AssertionError("no bot: no marker counts, so nothing is read")

    assert WatchState(REPO, checkout.root, StateRead(), state_dir(checkout), NOW, gh).waited([3]) == {}


def test_s089_12_a_marker_naming_an_item_the_token_cant_read_wakes_nothing_and_fails_no_tick(checkout: Git) -> None:
    # gh api graphql exits 1 on any errors entry, as run_command raises: GitHub answers a
    # repository() or issueOrPullRequest() it can't resolve with a NOT_FOUND error, a resource() with null alone
    comments = [{"author": APP, "body": marker("other/private#12")}]

    def gh(cmd: list[str], workspace: Path) -> str:
        query = cmd[cmd.index("-f") + 1]
        if "comments(last: 50)" in query:
            return json.dumps({"data": {"repository": {"i3": {"comments": {"nodes": comments}}}}})
        if "repository(owner:" in query:
            raise ReleaseError("gh api graphql failed: Could not resolve to a Repository named 'other/private'.")
        return json.dumps({"data": {"w0": None}})

    read = StateRead(bot_login=BOT)
    assert WatchState(REPO, checkout.root, read, state_dir(checkout), NOW, gh).waited([3]) == {}
