"""Spec 036, #639: triage_state.py's --role flags and role:<name> items, without gh or the network"""

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_triage_human import BOT, REPO, SCRIPT, closed_by_hand, handoff, node, person, run_script, said
from .test_triage_state import first_page, forward

MAINTAINER = {"maintainer": (("maria",), ())}


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state_roles", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def classify(
    ts: ModuleType,
    item: dict[str, Any],
    roles: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] | None = None,
    states: dict[tuple[str, str, int], str] | None = None,
) -> tuple[str, str]:
    verdict: tuple[str, str] = ts.classify_open(
        item, "Triage:", "postponed", states or {}, None, REPO, BOT, {}, roles=roles
    )
    return verdict


def fresh(tmp_path: Path, name: str) -> Path:
    """A directory of its own for one run of the script, so two runs don't share the fakes"""
    path = tmp_path / name
    path.mkdir()
    return path


def rows(stdout: str) -> dict[int, dict[str, Any]]:
    found = (json.loads(line) for line in stdout.splitlines())
    return {r["number"]: r for r in found if "number" in r}


@pytest.mark.parametrize(
    "flags",
    [
        ["--role", "Maintainer=maria"],  # a name outside [a-z0-9][a-z0-9-]{0,44}
        ["--role", "-x=maria", "--role", "maintainer=maria"],
        ["--role", "maintainer"],  # no "="
        ["--role", "maintainer=maria,bad login"],  # a filler that is neither login nor team
        ["--role", "maintainer=maria-"],
        ["--role", "maintainer=hubot[bot]"],
        ["--role", "maintainer=@org"],  # a team without its slug
        ["--role", "maintainer=maria,"],  # an empty filler
        ["--role", "maintainer="],  # an empty filler list
        ["--role", "maintainer=maria", "--role", "maintainer=bo"],  # a name given twice
        ["--role", "infra=maria"],  # no maintainer
    ],
)
def test_s036_6_a_malformed_or_incomplete_role_set_exits_2_naming_role(tmp_path: Path, flags: list[str]) -> None:
    proc = run_script(tmp_path, first_page([person()]), *flags)
    assert proc.returncode == 2
    assert "--role" in proc.stderr
    assert proc.stdout == ""


def test_s036_6_a_well_formed_role_set_parses(ts: ModuleType) -> None:
    roles = ts.parse_roles(["maintainer=maria", "infra=maria,hu-bot", "legal=@example-org/legal"])
    assert roles == {
        "maintainer": (("maria",), ()),
        "infra": (("maria", "hu-bot"), ()),
        "legal": ((), ("@example-org/legal",)),
    }


@pytest.mark.parametrize("label", ["role:infra", "Role:Infra", "human"])
def test_s036_7_a_role_item_is_a_person_s_item_exactly_as_a_human_one(ts: ModuleType, label: str) -> None:
    # Triaged from the start, its holds apply, it reads no PR state
    assert classify(ts, person(labels=(label,))) == ("HANDOFF_DUE", "for @ana")
    held = person(labels=(label,), blocked_by=[node("o/r#3")])
    assert classify(ts, held) == ("BLOCKED", "o/r#3:open(native)")
    with_pr = person(labels=(label,))
    with_pr["timelineItems"] = forward([{"willCloseTarget": True, "source": {"number": 8, "state": "OPEN"}}])
    assert classify(ts, with_pr)[0] == "HANDOFF_DUE"
    assert classify(ts, person([handoff()], labels=(label,)))[0] == "WITH_PERSON"
    done = person([handoff(), said("done", "2026-09-06T10:00:00Z", by="ana", bot=False)], labels=(label,))
    assert classify(ts, done) == ("VERIFY_DUE", "done reported by @ana")
    # Closed by hand with a ## Check, it owes a check, never a SUSPECT_CLOSE
    closed = closed_by_hand(labels=(label,))
    assert ts.classify_closed(closed, "release-blocker", "incident", BOT)[0] == "VERIFY_CLOSED"


def test_s036_7_wip_counts_no_role_item(tmp_path: Path) -> None:
    waiting = person([handoff()], labels=("role:infra",))
    waiting["timelineItems"] = forward([{"willCloseTarget": True, "source": {"number": 8, "state": "OPEN"}}])
    proc = run_script(tmp_path, first_page([waiting]), "--wip", "1")
    assert proc.returncode == 0, proc.stderr
    last = json.loads(proc.stdout.splitlines()[-1])
    assert last == {"in_progress": 0, "ready": [], "room": 1, "wip": 1}


def test_s036_8_an_unassigned_role_item_reads_assign_due_even_while_held(ts: ModuleType) -> None:
    roles = {"maintainer": (("a",), ()), "infra": (("a", "b"), ())}
    free = person(people=(), labels=("role:infra",))
    assert classify(ts, free, roles) == ("ASSIGN_DUE", "assign @a @b (role:infra)")
    held = person(people=(), labels=("role:infra",), blocked_by=[node("o/r#3")])
    assert classify(ts, held, roles) == ("ASSIGN_DUE", "assign @a @b (role:infra)")
    assert "ASSIGN_DUE" in ts.ACTION


def test_s036_8_the_script_exits_1_with_an_assign_list(tmp_path: Path) -> None:
    item = person(people=(), labels=("role:infra",))
    proc = run_script(tmp_path, first_page([item]), "--role", "maintainer=a", "--role", "infra=a")
    assert proc.returncode == 1, proc.stderr
    row = rows(proc.stdout)[7]
    assert (row["state"], row["note"], row["assign"]) == ("ASSIGN_DUE", "assign @a (role:infra)", ["a"])


def test_s036_8_assign_due_comes_after_the_decision_and_milestone_states(tmp_path: Path) -> None:
    parked = person(people=(), labels=("role:infra", "needs-decision"))
    parked["number"] = 8
    proc = run_script(tmp_path, first_page([parked]), "--role", "maintainer=a")
    assert rows(proc.stdout)[8]["state"] == "NEEDS_DECISION"


def test_s036_9_an_unassigned_human_item_is_assigned_to_the_maintainer(ts: ModuleType) -> None:
    roles = {"maintainer": (("maria", "bo"), ())}
    assert classify(ts, person(people=()), roles) == ("ASSIGN_DUE", "assign @maria @bo (role:maintainer)")


def test_s036_9_an_assigned_human_item_reads_as_before(ts: ModuleType) -> None:
    for item in (person(), person([handoff()]), person(blocked_by=[node("o/r#3")])):
        assert classify(ts, item, MAINTAINER) == classify(ts, item)


def test_s036_9_an_assigned_human_item_s_script_line_keeps_its_state_and_note(tmp_path: Path) -> None:
    before = rows(run_script(fresh(tmp_path, "a"), first_page([person()])).stdout)[7]
    after = rows(run_script(fresh(tmp_path, "b"), first_page([person()]), "--role", "maintainer=maria").stdout)[7]
    assert (after["state"], after["note"]) == (before["state"], before["note"]) == ("HANDOFF_DUE", "for @ana")


def test_s036_10_an_undefined_role_falls_back_to_the_maintainer(ts: ModuleType) -> None:
    roles = {"maintainer": (("maria",), ())}
    item = person(people=(), labels=("role:dns",))
    assert classify(ts, item, roles) == ("ASSIGN_DUE", "assign @maria (role:dns); role:dns undefined")
    # A name outside the pattern is undefined too
    odd = person(people=(), labels=("role:dns_ops",))
    assert classify(ts, odd, roles)[1] == "assign @maria (role:dns_ops); role:dns_ops undefined"


def test_s036_10_two_role_labels_resolve_to_the_union_of_their_fillers(ts: ModuleType) -> None:
    roles = {
        "maintainer": (("maria",), ()),
        "infra": (("ana", "Hubot"), ()),
        "legal": (("hubot",), ("@example-org/legal",)),
    }
    item = person(people=(), labels=("role:infra", "role:legal"))
    assert classify(ts, item, roles) == ("ASSIGN_DUE", "assign @ana @Hubot (role:infra role:legal)")
    assigned = person(labels=("role:infra", "role:legal"))
    assert classify(ts, assigned, roles) == ("HANDOFF_DUE", "for @ana @example-org/legal")


def test_s036_11_a_team_only_role_is_never_assigned_and_its_team_is_handed_off(ts: ModuleType) -> None:
    roles = {"maintainer": (("maria",), ()), "legal": ((), ("@example-org/legal",))}
    held = person(people=(), labels=("role:legal",), blocked_by=[node("o/r#3")])
    assert classify(ts, held, roles) == ("BLOCKED", "o/r#3:open(native)")
    free = person(people=(), labels=("role:legal",))
    assert classify(ts, free, roles) == ("HANDOFF_DUE", "for @example-org/legal")
    waiting = person([handoff()], people=(), labels=("role:legal",))
    assert classify(ts, waiting, roles) == ("WITH_PERSON", "with @example-org/legal since 2026-09-05T10:00:00Z")


def test_s036_11_the_script_carries_the_teams_list(tmp_path: Path) -> None:
    flags = ("--role", "maintainer=maria", "--role", "legal=@example-org/legal")
    due = person(people=(), labels=("role:legal",))
    proc = run_script(fresh(tmp_path, "a"), first_page([due]), *flags)
    assert proc.returncode == 1, proc.stderr
    row = rows(proc.stdout)[7]
    assert (row["state"], row["note"]) == ("HANDOFF_DUE", "for @example-org/legal")
    assert (row["assignees"], row["teams"]) == ([], ["@example-org/legal"])
    waiting = person([handoff()], people=(), labels=("role:legal",))
    proc = run_script(fresh(tmp_path, "b"), first_page([waiting]), *flags)
    assert proc.returncode == 0, proc.stderr
    row = rows(proc.stdout)[7]
    assert (row["state"], row["assignees"], row["teams"]) == ("WITH_PERSON", [], ["@example-org/legal"])


@pytest.mark.parametrize(
    ("label", "note"),
    [("human", "labelled human, no assignee"), ("role:infra", "labelled role:infra, no assignee")],
)
def test_s036_12_without_role_flags_an_unassigned_item_reads_no_assignee(ts: ModuleType, label: str, note: str) -> None:
    assert classify(ts, person(people=(), labels=(label,))) == ("NO_ASSIGNEE", note)


def test_s036_12_with_role_flags_no_item_reads_no_assignee(tmp_path: Path) -> None:
    items = []
    for number, labels in enumerate((("human",), ("role:infra",), ("role:legal",), ("role:dns", "human")), 1):
        item = person(people=(), labels=labels)
        item["number"] = number
        items.append(item)
    flags = ("--role", "maintainer=maria", "--role", "infra=ana", "--role", "legal=@example-org/legal")
    proc = run_script(tmp_path, first_page(items), *flags)
    states = {n: r["state"] for n, r in rows(proc.stdout).items()}
    assert states == {1: "ASSIGN_DUE", 2: "ASSIGN_DUE", 3: "HANDOFF_DUE", 4: "ASSIGN_DUE"}, proc.stderr
