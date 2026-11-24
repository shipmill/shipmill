"""Spec 086, #1529: chains.py impact, stalled, and path, three read-only views of show's one
walk"""

import base64
import importlib.util
import json
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

from .test_chain_impact import NOW, SCRIPTS
from .test_chain_impact import Forge as ImpactForge
from .test_chains_show import GATED


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("chains_views", SCRIPTS / "chains.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


OLD = "2026-03-01T00:00:00Z"  # 9 days before NOW
RECENT = "2026-03-08T00:00:00Z"  # 2 days
MID = "2026-03-06T00:00:00Z"  # 4 days


class Forge(ImpactForge):
    """The fake forge, answering too the list queries the views page through: a repo's open
    issues and open milestones, and a milestone's open issues, 100 a page"""

    def __init__(self, ch: ModuleType) -> None:
        super().__init__(ch)
        self.milestones: dict[str, list[tuple[int, str, str]]] = {}  # repo: (number, title, state)
        self.listed: list[tuple[str, str | None]] = []  # (which list, the cursor asked)

    def page(self, nodes: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
        start = int(cursor) if cursor else 0
        more = start + 100 < len(nodes)
        return {
            "pageInfo": {"hasNextPage": more, "endCursor": str(start + 100) if more else None},
            "nodes": nodes[start : start + 100],
        }

    def open_in(self, repo: str, milestone: str | None = None) -> list[dict[str, Any]]:
        found = [
            item
            for item in self.items.values()
            if item["type"] == "Issue"
            and item["state"] == "OPEN"
            and item["repo"].lower() == repo.lower()
            and (milestone is None or item.get("milestone") == milestone)
        ]
        return [{"number": item["number"]} for item in sorted(found, key=lambda item: item["number"])]

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert "mutation" not in query
        repo = f"{variables.get('owner')}/{variables.get('name')}"
        cursor = variables.get("cursor")
        if query == self.ch.OPEN_ISSUES:
            self.listed.append(("issues", cursor))
            return {"data": {"repository": {"issues": self.page(self.open_in(repo), cursor)}}}
        if query == self.ch.OPEN_MILESTONES:
            self.listed.append(("milestones", cursor))
            nodes = [{"number": n, "title": t} for n, t, s in self.milestones.get(repo, []) if s == "OPEN"]
            return {"data": {"repository": {"milestones": self.page(nodes, cursor)}}}
        if query == self.ch.MILESTONE_ISSUES:
            self.listed.append(("milestone", cursor))
            title = next(t for n, t, _ in self.milestones[repo] if n == variables["number"])
            issues = self.page(self.open_in(repo, title), cursor)
            return {"data": {"repository": {"milestone": {"issues": issues}}}}
        return super().__call__(query, variables)


@pytest.fixture
def forge(ch: ModuleType) -> Forge:
    return Forge(ch)


def run(ch: ModuleType, forge: Forge, *argv: str) -> int:
    code: int = ch.main(list(argv), run=forge, contents=forge.config, standing=forge.standing, now=NOW)
    return code


def chain(forge: Forge) -> None:
    """o/r#1 holds 3 (2 directly), o/r#2 holds 1, o/r#5 holds 1 (1 directly), o/r#9 holds 2
    (2 directly), and o/r#3, o/r#4, o/r#6, o/r#7, o/r#8 hold nothing"""
    forge.issue("o/r#1", updated=OLD, milestone="v1")
    forge.issue("o/r#2", body="Depends on o/r#1", milestone="v1", updated=RECENT)
    forge.issue("o/r#3", body="Depends on o/r#2", milestone="v2")
    forge.issue("o/r#4", body="Depends on o/r#1")
    forge.issue("o/r#5", updated=MID, labels=["role:infra"])
    forge.issue("o/r#6", body="Depends on o/r#5")
    forge.issue("o/r#9", updated=OLD)
    forge.issue("o/r#7", body="Depends on o/r#9")
    forge.issue("o/r#8", body="Depends on o/r#9")
    forge.configs = {"o/r": GATED}


def test_s086_4_impact_prints_only_what_holds_most_held_first_then_held_direct_then_the_reference(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    chain(forge)
    starts = ["o/r#3", "o/r#4", "o/r#6", "o/r#7", "o/r#8"]
    assert run(ch, forge, "impact", *starts) == 0
    assert capsys.readouterr().out.splitlines() == [
        "o/r#1 holds 3 (2 directly), waits for agent, idle 9d milestones: o/r v1, o/r v2  title of o/r#1",
        "o/r#9 holds 2 (2 directly), waits for agent, idle 9d  title of o/r#9",
        "o/r#2 holds 1 (1 directly), waits for items, idle 2d milestones: o/r v2  title of o/r#2",
        "o/r#5 holds 1 (1 directly), waits for person, idle 4d  title of o/r#5",
    ]
    assert run(ch, forge, "impact", *starts, "--json") == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert [row["ref"] for row in rows] == ["o/r#1", "o/r#9", "o/r#2", "o/r#5"]
    assert rows[0]["held"] == 3 and rows[0]["held_direct"] == 2 and rows[0]["state"] == "READY"
    assert set(rows[0]) >= {"ref", "title", "state", "holds", "waiting_for", "idle_days", "milestones"}


def test_s086_4_impact_orders_a_tie_by_the_reference_numerically_and_prints_nothing_with_no_weight(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#10")
    forge.issue("o/r#9")
    forge.issue("o/r#11", body="Depends on o/r#10\nDepends on o/r#9")
    forge.issue("o/r#12")
    forge.configs = {"o/r": GATED}
    assert run(ch, forge, "impact", "o/r#11") == 0
    assert [line.split()[0] for line in capsys.readouterr().out.splitlines()] == ["o/r#9", "o/r#10"]
    assert run(ch, forge, "impact", "o/r#12") == 0
    assert capsys.readouterr().out == ""
    assert run(ch, forge, "impact", "o/r#12", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"rows": []}


def test_s086_4_repo_reads_every_open_issue_past_the_first_page_as_a_start(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    # 150 open issues; the only link is on the second page: o/r#140 waits on o/r#130
    for n in range(1, 151):
        forge.issue(f"o/r#{n}", body="Depends on o/r#130" if n == 140 else "")
    forge.issue("o/r#151", state="CLOSED", reason="COMPLETED", body="Depends on o/r#130")
    forge.configs = {"o/r": GATED}
    assert run(ch, forge, "impact", "--repo", "o/r") == 0
    assert capsys.readouterr().out.splitlines() == [
        "o/r#130 holds 1 (1 directly), waits for agent, idle 68d  title of o/r#130"
    ]
    assert forge.listed == [("issues", None), ("issues", "100")]
    asked = {ref for refs in forge.asked for ref in refs}
    assert {f"o/r#{n}" for n in range(1, 151)} <= asked and "o/r#151" not in asked


def test_s086_4_repo_adds_its_issues_beside_a_reference_and_trusts_as_an_origin(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1")
    forge.issue("o/r#2", body="Depends on o/r#1")
    forge.issue("p/q#1", author=("bob", "OWNER"), body="Depends on o/r#2")
    forge.configs = {"o/r": GATED, "p/q": GATED}
    assert run(ch, forge, "impact", "p/q#1", "--repo", "o/r", "--trusted-only") == 0
    assert [line.split()[:3] for line in capsys.readouterr().out.splitlines()] == [
        ["o/r#1", "holds", "2"],
        ["o/r#2", "holds", "1"],
    ]


def stalled_chain(forge: Forge) -> None:
    """Heads: o/r#1 (agent, 9 days, holds 2), o/r#9 (agent, 9 days, holds 3), o/r#5 (person,
    4 days, holds 1). o/r#2 waits on items and is idle 9 days; o/r#20 and o/r#21 are a cycle
    idle 9 days that o/r#22 waits on; o/r#30 holds nothing, idle 9 days"""
    forge.issue("o/r#1", updated=OLD)
    forge.issue("o/r#2", body="Depends on o/r#1", updated=OLD)
    forge.issue("o/r#3", body="Depends on o/r#2")
    forge.issue("o/r#5", updated=MID, labels=["role:infra"])
    forge.issue("o/r#6", body="Depends on o/r#5")
    forge.issue("o/r#9", updated=OLD)
    forge.issue("o/r#7", body="Depends on o/r#9")
    forge.issue("o/r#8", body="Depends on o/r#9")
    forge.issue("o/r#10", body="Depends on o/r#9")
    forge.issue("o/r#20", body="Depends on o/r#21", updated=OLD)
    forge.issue("o/r#21", body="Depends on o/r#20", updated=OLD)
    forge.issue("o/r#22", body="Depends on o/r#20")
    forge.issue("o/r#30", updated=OLD)
    forge.configs = {"o/r": GATED}


def test_s086_5_stalled_prints_heads_idle_7_days_or_more_never_items_or_a_cycle_and_exits_1(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    stalled_chain(forge)
    assert run(ch, forge, "stalled", "--repo", "o/r") == 1
    assert capsys.readouterr().out.splitlines() == [
        "o/r#9 holds 3 (3 directly), waits for agent, idle 9d  title of o/r#9",
        "o/r#1 holds 2 (1 directly), waits for agent, idle 9d  title of o/r#1",
    ]
    assert run(ch, forge, "stalled", "--repo", "o/r", "--days", "3", "--json") == 1
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert [(row["ref"], row["waiting_for"]) for row in rows] == [
        ("o/r#9", "agent"),
        ("o/r#1", "agent"),
        ("o/r#5", "person"),
    ]


def test_s086_5_stalled_orders_by_held_then_the_longest_idle(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", updated="2026-03-02T00:00:00Z")  # 8 days
    forge.issue("o/r#2", updated=OLD)  # 9 days
    forge.issue("o/r#3", body="Depends on o/r#1\nDepends on o/r#2")
    forge.configs = {"o/r": GATED}
    assert run(ch, forge, "stalled", "o/r#3") == 1
    assert [line.split()[0] for line in capsys.readouterr().out.splitlines()] == ["o/r#2", "o/r#1"]


def test_s086_5_stalled_exits_0_without_a_row_and_2_on_days_below_1(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.issue("o/r#1", updated=RECENT)
    forge.issue("o/r#2", body="Depends on o/r#1")
    forge.configs = {"o/r": GATED}
    assert run(ch, forge, "stalled", "o/r#2") == 0
    assert capsys.readouterr().out == ""
    assert run(ch, forge, "stalled", "o/r#2", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"rows": []}
    with pytest.raises(SystemExit) as exited:
        run(ch, forge, "stalled", "o/r#2", "--days", "0")
    assert exited.value.code == 2
    assert "--days must be 1 or more" in capsys.readouterr().err
    assert forge.asked == [["o/r#2"], ["o/r#1"]] * 2  # --days 0 read nothing


def path_chain(forge: Forge) -> None:
    """Milestone v1 (number 3) of o/r holds o/r#1 and o/r#2, and o/r#8 closed. o/r#1 waits on
    o/r#4 (agent) and x/y#5 (maintainer); o/r#2 waits on o/r#4 and o/r#6 (decision), which
    waits on o/r#4 too, and on closed o/r#7. o/r#9 waits on o/r#1, outside the milestone"""
    forge.milestones = {"o/r": [(2, "v1.0", "OPEN"), (3, "v1", "OPEN"), (4, "v2", "CLOSED")]}
    forge.issue("o/r#1", milestone="v1", body="Depends on o/r#4\nDepends on x/y#5", blocking=["o/r#9"])
    forge.issue("o/r#2", milestone="v1", body="Depends on o/r#4\nDepends on o/r#6")
    forge.issue("o/r#8", milestone="v1", state="CLOSED", reason="COMPLETED", body="Depends on o/r#4")
    forge.issue("o/r#4", updated=OLD)
    forge.issue("x/y#5", labels=["role:maintainer"])
    forge.issue("o/r#6", labels=["needs-decision"], body="Depends on o/r#4\nDepends on o/r#7")
    forge.issue("o/r#7", state="CLOSED", reason="COMPLETED")
    forge.issue("o/r#9", blocked_by=["o/r#1"], milestone="v2")
    forge.configs = {"o/r": GATED, "x/y": GATED}


def test_s086_6_path_lists_the_milestone_and_what_it_waits_on_once_decision_and_maintainer_first(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    path_chain(forge)
    assert run(ch, forge, "path", "--repo", "o/r", "--milestone", "v1") == 0
    assert capsys.readouterr().out.splitlines() == [
        "o/r#6 waits for decision, holds 1 in the path, idle 68d  title of o/r#6",
        "x/y#5 waits for maintainer, holds 1 in the path, idle 68d  title of x/y#5",
        "o/r#4 waits for agent, holds 3 in the path, idle 9d  title of o/r#4",
        "o/r#1 waits for items, holds 0 in the path, idle 68d  title of o/r#1",
        "o/r#2 waits for items, holds 0 in the path, idle 68d  title of o/r#2",
    ]
    assert run(ch, forge, "path", "--repo", "o/r", "--milestone", "v1", "--json") == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["milestone"] == "v1"
    assert [(row["ref"], row["held_in_path"], row["held"]) for row in printed["rows"]] == [
        ("o/r#6", 1, 1),
        ("x/y#5", 1, 2),  # o/r#9, outside the path, counts in held alone
        ("o/r#4", 3, 4),
        ("o/r#1", 0, 1),
        ("o/r#2", 0, 0),
    ]


def test_s086_6_an_unknown_milestone_exits_2_naming_it(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    path_chain(forge)
    for title in ("v2", "V1", "nope"):  # closed, another case, none: an exact open title only
        with pytest.raises(SystemExit) as exited:
            run(ch, forge, "path", "--repo", "o/r", "--milestone", title)
        assert exited.value.code == 2
        assert capsys.readouterr().err == f'error: no open milestone "{title}" in o/r\n'


def test_s086_6_a_milestone_with_nothing_open_says_so_and_exits_0(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.milestones = {"o/r": [(5, "v3", "OPEN")]}
    forge.issue("o/r#1", milestone="v3", state="CLOSED", reason="COMPLETED")
    assert run(ch, forge, "path", "--repo", "o/r", "--milestone", "v3") == 0
    assert capsys.readouterr().out == "milestone v3: nothing open\n"
    assert forge.asked == []


def test_s086_6_path_pages_the_milestones_and_the_milestones_issues(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.milestones = {"o/r": [(n, f"m{n}", "OPEN") for n in range(1, 121)]}
    for n in range(1, 131):
        forge.issue(f"o/r#{n}", milestone="m120")
    forge.configs = {"o/r": GATED}
    assert run(ch, forge, "path", "--repo", "o/r", "--milestone", "m120", "--json") == 0
    assert len(json.loads(capsys.readouterr().out)["rows"]) == 130
    assert forge.listed == [("milestones", None), ("milestones", "100"), ("milestone", None), ("milestone", "100")]


@pytest.mark.parametrize(
    "argv",
    [
        ["path", "--milestone", "v1"],
        ["path", "--repo", "o/r", "--repo", "p/q", "--milestone", "v1"],
        ["path", "o/r#1", "--repo", "o/r", "--milestone", "v1"],
        ["impact"],
        ["stalled"],
        ["impact", "--repo", "not-a-repo"],
    ],
)
def test_s086_6_the_views_refuse_their_misuse_with_exit_2(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        run(ch, forge, *argv)
    assert exited.value.code == 2
    assert forge.asked == [] and forge.listed == []


def gh_fake(forge: Forge, commands: list[list[str]]) -> Any:
    """A fake gh command line: GraphQL through the forge, the contents API and the
    collaborator check through REST reads; every command recorded"""

    def execute(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        assert cmd[:2] == ["gh", "api"]
        if cmd[2] == "graphql":
            variables: dict[str, Any] = {}
            query = ""
            for flag, value in zip(cmd[3::2], cmd[4::2], strict=True):
                name, _, text = value.partition("=")
                if name == "query":
                    query = text
                else:
                    variables[name] = int(text) if flag == "-F" else text
            response = forge(query, variables)
            return subprocess.CompletedProcess(cmd, 1 if response.get("errors") else 0, json.dumps(response), "")
        if cmd[2].endswith("/contents/.github/shipmill.toml"):
            content = base64.b64encode(GATED.encode()).decode()
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"encoding": "base64", "content": content}), "")
        assert "/collaborators/" in cmd[2]
        return subprocess.CompletedProcess(cmd, 1, "", "gh: Not Found (HTTP 404)")

    return execute


@pytest.mark.parametrize(
    "argv",
    [
        ["impact", "--repo", "o/r", "--trusted-only"],
        ["stalled", "--repo", "o/r", "--days", "1", "--trusted-only"],
        ["path", "--repo", "o/r", "--milestone", "v1", "--trusted-only"],
    ],
)
def test_s086_7_the_views_make_only_reads_through_gh(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    path_chain(forge)
    forge.issue("o/r#10", author=("mallory", "NONE"), body="Depends on o/r#4", milestone="v1")
    forge.issue("o/r#11", author=("carol", "NONE"), body="Depends on p/q#1")
    forge.issue("p/q#1", author=("dave", "OWNER"))
    commands: list[list[str]] = []
    execute = gh_fake(forge, commands)

    def contents(repo: str) -> str | None:
        found: str | None = ch.gh_contents(repo, execute)
        return found

    def standing(repo: str, user: str) -> bool:
        found: bool = ch.gh_collaborator(repo, user, execute)
        return found

    runner = ch.gh_runner(["gh"], execute)
    ch.main(argv, run=runner, contents=contents, standing=standing, now=NOW)
    capsys.readouterr()
    assert commands, "the view read through gh"
    for cmd in commands:
        assert cmd[:2] == ["gh", "api"]
        assert not {"-X", "--method", "-i", "--input"} & set(cmd), cmd  # REST GET only
        if cmd[2] == "graphql":
            query = next(arg for arg in cmd if arg.startswith("query="))
            assert query.removeprefix("query=").lstrip().startswith("query"), cmd
            assert "mutation" not in query
    assert any(cmd[2].endswith("/contents/.github/shipmill.toml") for cmd in commands)
