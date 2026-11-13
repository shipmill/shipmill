"""Spec 065, #1087: a component's triage reads a hold on its product's other repos with the read
token (`shipmill gh --product`), and the skills say how a component reads them, without the
network: a fake gh and a fake uvx on PATH"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_triage_state import comment, first_page, forward, open_issue
from .test_triage_upstream import COORDINATOR, HOME, REPO, TRIAGE, load

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

FAKE_GH = """#!{python}
import os
print(open(os.environ["FAKE_GH_DATA"]).read())
"""
# `uvx shipmill==<v> --repo <top> gh --product <repo> api graphql -f query=...`: logs its
# arguments, then answers each alias of the query from the plan's nodes, or exits as it says
FAKE_UVX = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_UVX_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
plan = json.load(open(os.environ["FAKE_UVX_PLAN"]))
if plan.get("exit"):
    sys.stderr.write(plan.get("stderr", ""))
    sys.exit(plan["exit"])
query = next(a for a in args if a.startswith("query="))
found = re.findall(
    r'(r\\d+): repository\\(owner: "([^"]+)", name: "([^"]+)"\\) \\{{ issueOrPullRequest\\(number: (\\d+)\\)', query
)
data = {{}}
for alias, owner, name, number in found:
    node = plan["nodes"].get(owner + "/" + name + "#" + number)
    data[alias] = {{"issueOrPullRequest": node}} if node else None
print(json.dumps({{"data": data}}))
"""


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_product_reads", TRIAGE)


def issue_node(state: str = "OPEN", reason: str | None = None) -> dict[str, Any]:
    closed = None if state == "OPEN" else "2026-11-10T10:00:00Z"
    return {"__typename": "Issue", "state": state, "stateReason": reason, "closedAt": closed}


def held(*refs: str, number: int = 7) -> dict[str, Any]:
    """o/r#7, triaged implement, its body's Depends on line naming refs"""
    item = open_issue(number, [comment("Triage: implement")])
    item["body"] = f"Depends on {', '.join(refs)}\n"
    item["blockedBy"] = forward([])
    item["subIssues"] = forward([])
    return item


def run(
    tmp_path: Path, nodes: list[dict[str, Any]], plan: dict[str, Any], *args: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """triage_state.py o/r over a fake gh, which reads no hold's state (as for a repo the
    session's token 404s), and a fake uvx that answers as plan says; the uvx calls it logged"""
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    for tool, text in (("gh", FAKE_GH), ("uvx", FAKE_UVX)):
        path = fakes / tool
        path.write_text(text.format(python=sys.executable), encoding="utf-8")
        path.chmod(0o700)
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({"data": {"repository": first_page(nodes)}}), encoding="utf-8")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({"nodes": {}, **plan}), encoding="utf-8")
    log = tmp_path / "uvx.log"
    log.unlink(missing_ok=True)
    env = {
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(data),
        "FAKE_UVX_PLAN": str(plan_file),
        "FAKE_UVX_LOG": str(log),
    }
    cmd = [sys.executable, str(TRIAGE), "o/r", "--json", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, cwd=tmp_path)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls


def rows(proc: subprocess.CompletedProcess[str]) -> list[tuple[int, str, str]]:
    return [(r["number"], r["state"], r["note"]) for r in map(json.loads, proc.stdout.splitlines())]


def product(call: list[str]) -> str:
    return call[call.index("--product") + 1]


# -- S-065-8 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("node", "state", "shown"),
    [
        (issue_node(), "BLOCKED", "open"),
        (issue_node("CLOSED", "COMPLETED"), "UNBLOCKED", "closed"),
        (issue_node("CLOSED", "NOT_PLANNED"), "UNBLOCKED", "not_planned"),
    ],
)
def test_s065_8_a_hold_on_the_home_is_read_with_the_read_token(
    tmp_path: Path, node: dict[str, Any], state: str, shown: str
) -> None:
    proc, calls = run(tmp_path, [held(f"{HOME}#11")], {"nodes": {f"{HOME}#11": node}}, "--home", HOME)
    assert proc.returncode == (1 if state == "UNBLOCKED" else 0), proc.stderr
    # read, so no D-60 note: it reads as any hold does
    assert rows(proc) == [(7, state, f"{HOME}#11:{shown}")]
    [call] = calls
    assert call[0].startswith("shipmill==")
    assert call[1:3] == ["--repo", str(tmp_path.resolve())]
    assert call[3:8] == ["gh", "--product", HOME, "api", "graphql"]


def test_s065_8_one_call_per_owner(tmp_path: Path) -> None:
    refs = ("acme/api#4", f"{HOME}#11", "other/lib#9", "other/web#2")
    nodes = {ref: issue_node("CLOSED", "COMPLETED") for ref in refs}
    proc, calls = run(tmp_path, [held(*refs)], {"nodes": nodes}, "--home", HOME)
    assert proc.returncode == 1, proc.stderr
    assert rows(proc) == [(7, "UNBLOCKED", " ".join(f"{ref}:closed" for ref in sorted(refs)))]
    # the home's owner through the home; another owner through its first repo among the holds
    assert sorted(product(call) for call in calls) == [HOME, "other/lib"]
    queries = {product(call): call[-1] for call in calls}
    assert '"api"' in queries[HOME] and '"product"' in queries[HOME] and '"lib"' not in queries[HOME]
    assert '"lib"' in queries["other/lib"] and '"web"' in queries["other/lib"]


def test_s065_8_a_hold_in_its_own_repo_is_read_by_plain_gh_alone(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, [held("#3")], {"nodes": {"o/r#3": issue_node()}}, "--home", HOME)
    assert proc.returncode == 0, proc.stderr
    assert rows(proc) == [(7, "BLOCKED", "o/r#3:unknown")]
    assert calls == []


def test_s065_8_a_partial_answer_reads_the_nodes_that_came_back(ts: ModuleType) -> None:
    refs = [("acme", "api", 4), ("acme", "product", 11)]
    answer: dict[str, Any] = {
        "data": {"r0": None, "r1": {"issueOrPullRequest": issue_node("CLOSED", "NOT_PLANNED")}},
        "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a Repository"}],
    }
    seen: list[list[str]] = []

    def execute(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, json.dumps(answer), "")

    states, closes = ts.product_states(refs, HOME, ["shipmill", "gh"], execute)
    assert states == {refs[0]: "UNKNOWN", refs[1]: "NOT_PLANNED"}
    assert closes == {refs[1]: "2026-11-10T10:00:00Z"}
    assert [cmd[:4] for cmd in seen] == [["shipmill", "gh", "--product", HOME]]


# -- S-065-9 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan",
    [
        {"exit": 2, "stderr": "error: D-84: acme/product's [product] repos doesn't list o/r\n"},
        {"nodes": {}},  # GitHub answered, with no node for the hold
    ],
)
def test_s065_9_a_failed_read_reads_unknown_with_d60s_note(tmp_path: Path, plan: dict[str, Any]) -> None:
    proc, calls = run(tmp_path, [held(f"{HOME}#11")], plan, "--home", HOME)
    assert proc.returncode == 0, proc.stderr  # BLOCKED is no action, as before
    assert rows(proc) == [(7, "BLOCKED", f"{HOME}#11:unknown | {COORDINATOR}")]
    assert len(calls) == 1
    if plan.get("exit"):
        assert "note: shipmill gh --product acme/product exited 2: error: D-84" in proc.stderr


def test_s065_9_an_unread_hold_elsewhere_counts_as_open_without_the_note(tmp_path: Path) -> None:
    plan = {"exit": 2, "stderr": "error: D-84: other/lib is outside the product\n"}
    proc, calls = run(tmp_path, [held("other/lib#9")], plan, "--home", HOME)
    assert proc.returncode == 0, proc.stderr
    assert rows(proc) == [(7, "BLOCKED", "other/lib#9:unknown")]
    assert [product(call) for call in calls] == ["other/lib"]


def test_s065_9_a_shipmill_gh_that_prints_no_graphql_answer_is_a_failed_read(ts: ModuleType) -> None:
    def execute(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "not json", "boom")

    ref = ("acme", "product", 11)
    assert ts.product_states([ref], HOME, ["shipmill", "gh"], execute) == ({}, {})


# -- S-065-10 ------------------------------------------------------------------------------


@pytest.mark.parametrize("home", [None, "o/r", "O/R"])
def test_s065_10_no_shipmill_gh_without_a_component_home(tmp_path: Path, home: str | None) -> None:
    items = [held(f"{HOME}#11"), held("other/lib#9", number=8), held("#3", number=9)]
    # any `shipmill gh` call fails: it is logged, and exits 99
    fails = {"exit": 99, "stderr": "no call expected\n"}
    proc, calls = run(tmp_path, items, fails, *(("--home", home) if home else ()))
    assert calls == []
    assert proc.returncode == 0, proc.stderr
    assert "shipmill gh" not in proc.stderr
    # the states and notes as before spec 065: unread holds read unknown, and no D-60 note in the home
    assert rows(proc) == [
        (9, "BLOCKED", "o/r#3:unknown"),
        (8, "BLOCKED", "other/lib#9:unknown"),
        (7, "BLOCKED", f"{HOME}#11:unknown"),
    ]


def test_s065_10_product_reads_is_empty_without_a_component_home(ts: ModuleType) -> None:
    unread = {("acme", "product", 11): "UNKNOWN", ("o", "r", 3): "UNKNOWN", ("other", "lib", 9): "OPEN"}
    assert ts.product_reads(unread, REPO, None) == []
    assert ts.product_reads(unread, REPO, "O/r") == []
    # in a component: only another repo's hold that plain gh read no state for
    assert ts.product_reads(unread, REPO, HOME) == [("acme", "product", 11)]


# -- S-065-11 ------------------------------------------------------------------------------


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def test_s065_11_resolve_says_how_a_component_reads_its_product() -> None:
    resolve = flat(SKILLS / "github-issue-resolve" / "SKILL.md")
    [part] = [p for p in resolve.split("**")[1:] if p.startswith("In a component, read the product's other repos")]
    rest = resolve.split("**In a component, read the product's other repos", 1)[1].split("**Mentions", 1)[0]
    assert "D-84" in part
    assert "`shipmill gh --product <its repo>" in rest
    assert "writes nothing there" in rest
    assert "follows an item there only when that repo's trust rule (D-16) trusts its author" in rest
    assert "writes no substitute" in rest
    assert "needs-decision protocol" in rest and "naming the reference it couldn't read" in rest
    # the pinned `uvx shipmill==X gh ` stays once in the file, for its [[version_lines]] pattern
    assert len(re.findall(r"uvx shipmill==\d+\.\d+\.\d+(?= gh )", resolve)) == 1


def test_s065_11_the_rubric_and_triage_skill_name_the_read_token() -> None:
    rubric = (SKILLS / "github-issue-triage" / "references" / "triage-rubric.md").read_text(encoding="utf-8")
    [row] = [line for line in rubric.splitlines() if line.startswith("| BLOCKED |") and "D-60" in line]
    assert "D-60's note" in row and "marks only a hold on a home item the read token couldn't read" in row
    triage = flat(SKILLS / "github-issue-triage" / "SKILL.md")
    assert "D-84" in triage
    assert "`shipmill gh --product <their repo>`" in triage and "writes only its own (D-84)" in triage


def test_d60s_reason_no_longer_says_a_component_cant_read_the_home() -> None:
    """D-84 refines D-60: a component reads the home through the read token, so the coordinator's
    filing order rests on a hold the read token may still not read, not on one it never can"""
    for path in (
        SKILLS / "github-issue-triage" / "SKILL.md",
        SKILLS / "github-issue-triage" / "references" / "spec-gate.md",
    ):
        text = flat(path)
        assert "session can't read the home" not in text, path
        assert "the read token (D-84)" in text, path
