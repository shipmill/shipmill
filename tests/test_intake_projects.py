"""intake_state.py --projects (spec 106, #1739): a project head's state, its check issue and
parts, and the product's active count under [agents] projects; without the network"""

import datetime as dt
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_intake_outcomes import FAKE_GH, FAKE_UVX, Checkout, ist, via

BOT = "shipmill-app[bot]"
NOW = dt.datetime(2026, 11, 26, 12, tzinfo=dt.UTC)
RECORD = "<!-- shipmill:project-stopped -->\nStopped: the outcome moved to #9.\n<!-- shipmill:agent -->"
CHECK = "## Check\n\nRun the release and see the page.\n"
CLEANUP = (
    CHECK
    + "\n## Cleanup\n\n- [x] drop the flag\n- [ ] delete the old table\n- [ ] remove the cron\n"
    + "\n## Notes\n- [ ] not cleanup\n"
)

__all__ = ["ist"]  # the module fixture, shared with spec 101's tests


def sub(
    number: int, state: str = "OPEN", title: str = "Part", body: str = "", parts: tuple[str, ...] = ()
) -> dict[str, Any]:
    """A sub-issue of a head, with its own sub-issues' states"""
    nodes = [{"number": 900 + i, "state": s} for i, s in enumerate(parts)]
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "subIssues": {"totalCount": len(nodes), "nodes": nodes},
    }


def check(number: int = 50, state: str = "OPEN", body: str = CHECK, parts: tuple[str, ...] = ()) -> dict[str, Any]:
    return sub(number, state, "Check: the release page shows the new plan", body, parts)


def head(
    number: int = 7,
    subs: tuple[dict[str, Any], ...] = (),
    labels: tuple[str, ...] = ("project",),
    state: str = "OPEN",
    reason: str | None = None,
    association: str = "OWNER",
    author: str = "maintainer",
    labelled_by: str | None = None,
    comments: tuple[tuple[str, str], ...] = (),
    closed_at: str | None = None,
) -> dict[str, Any]:
    """A head issue as PROJECTS_QUERY reads it"""
    kind = "Bot" if labelled_by is not None and labelled_by.endswith("[bot]") else "User"
    actor = {"__typename": kind, "login": labelled_by}
    events = [] if labelled_by is None else [{"label": {"name": "project"}, "actor": actor}]
    return {
        "number": number,
        "title": f"Head {number}",
        "body": "",
        "state": state,
        "stateReason": reason,
        "closedAt": closed_at,
        "author": {"login": author},
        "authorAssociation": association,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "timelineItems": {"nodes": events},
        "comments": {"nodes": [{"author": {"login": a}, "body": b} for a, b in comments]},
        "subIssues": {"totalCount": len(subs), "nodes": list(subs)},
    }


def read(ist: ModuleType, node: dict[str, Any]) -> tuple[str, str] | None:
    row = ist.project_row(node, BOT)
    return None if row is None else (row.state, row.note)


# -- S-106-12 -------------------------------------------------------------------------------


def test_s106_12_a_head_with_no_check_issue_or_labelled_held_reads_held(ist: ModuleType) -> None:
    assert read(ist, head()) == ("PROJECT_HELD", "no check issue")
    assert read(ist, head(subs=(sub(8),))) == ("PROJECT_HELD", "no check issue")
    assert read(ist, head(subs=(check(),), labels=("project", "held"))) == ("PROJECT_HELD", "labelled held")
    # a `Check: ` title without a ## Check section is a part, not the check issue
    assert read(ist, head(subs=(sub(8, title="Check: it works", body="no section"),))) == (
        "PROJECT_HELD",
        "no check issue",
    )
    row = ist.project_row(head(), BOT)
    assert (row.holder, row.check, ist.project_json(row)["parts"]) == ("start", None, {"open": 0, "closed": 0})


def test_s106_12_an_open_check_and_an_open_or_no_part_reads_active_or_focus(ist: ModuleType) -> None:
    assert read(ist, head(subs=(check(),))) == ("PROJECT_ACTIVE", "no part filed")
    assert read(ist, head(subs=(check(), sub(8), sub(9, "CLOSED")))) == ("PROJECT_ACTIVE", "1 of 2 parts open")
    # a part under the check issue counts, two levels deep
    assert read(ist, head(subs=(check(parts=("OPEN",)), sub(8, "CLOSED")))) == ("PROJECT_ACTIVE", "1 of 2 parts open")
    focus = ist.project_row(head(subs=(check(), sub(8)), labels=("project", "focus")), BOT)
    assert (focus.state, focus.holder) == ("PROJECT_FOCUS", "maintainer")
    assert ist.project_json(focus) == {
        "kind": "project",
        "number": 7,
        "state": "PROJECT_FOCUS",
        "title": "Head 7",
        "note": "1 of 1 parts open",
        "holder": "maintainer",
        "check": 50,
        "parts": {"open": 1, "closed": 0},
    }
    assert ist.project_row(head(subs=(check(), sub(8))), BOT).holder == "agents"


def test_s106_12_every_part_closed_reads_closing_with_its_cleanup(ist: ModuleType) -> None:
    done = (sub(8, "CLOSED"), sub(9, "CLOSED"))
    assert read(ist, head(subs=(check(), *done))) == ("PROJECT_CLOSING", "no cleanup listed")
    closing = ist.project_row(head(subs=(check(body=CLEANUP, parts=("CLOSED",)), *done)), BOT)
    assert (closing.state, closing.note) == ("PROJECT_CLOSING", "cleanup: delete the old table; remove the cron")
    assert (closing.holder, closing.parts_closed) == ("checker", 3)
    # every check box ticked lists no cleanup
    ticked = CHECK + "\n## Cleanup\n\n- [x] drop the flag\n"
    assert read(ist, head(subs=(check(body=ticked), *done))) == ("PROJECT_CLOSING", "no cleanup listed")


def test_s106_12_a_closed_head_reads_closed_or_stopped_by_the_bots_record(ist: ModuleType) -> None:
    at = "2026-11-20T10:00:00Z"
    assert read(ist, head(state="CLOSED", reason="COMPLETED", closed_at=at)) == (
        "PROJECT_CLOSED",
        "closed as completed",
    )
    stopped = head(state="CLOSED", reason="NOT_PLANNED", closed_at=at, comments=((BOT, RECORD),))
    assert read(ist, stopped) == ("PROJECT_STOPPED", "stopped")
    assert ist.project_row(stopped, BOT).holder is None
    # without the record, or with it by anyone else, a head closed as not planned reads nothing
    assert read(ist, head(state="CLOSED", reason="NOT_PLANNED", closed_at=at)) is None
    assert read(ist, head(state="CLOSED", reason="NOT_PLANNED", closed_at=at, comments=(("someone", RECORD),))) is None


def test_s106_12_a_head_is_a_trusted_authors_or_labelled_by_another(ist: ModuleType) -> None:
    assert read(ist, head(association="NONE", author="drive-by")) is None
    # an issue form's label is the opener's own: still no head
    assert read(ist, head(association="NONE", author="drive-by", labelled_by="drive-by")) is None
    assert read(ist, head(association="NONE", author="drive-by", labelled_by="maintainer")) is not None
    assert read(ist, head(association="NONE", author=BOT)) is not None
    # another bot's label counts for nothing (a workflow an outsider's text can trigger); the --bot-login's does
    assert read(ist, head(association="NONE", author="drive-by", labelled_by="github-actions[bot]")) is None
    assert read(ist, head(association="NONE", author="drive-by", labelled_by=BOT)) is not None


def test_s106_12_a_second_check_issue_is_no_part(ist: ModuleType) -> None:
    second = sub(51, "OPEN", "Check: the docs say so", CHECK)
    assert read(ist, head(subs=(check(), second, sub(8, "CLOSED")))) == ("PROJECT_CLOSING", "no cleanup listed")


def test_s106_12_more_sub_issues_than_read_is_refused(ist: ModuleType) -> None:
    node = head(subs=(check(),))
    node["subIssues"]["totalCount"] = 80
    with pytest.raises(SystemExit) as exited:
        ist.project_row(node, BOT)
    assert exited.value.code == 2


def test_s106_12_fetch_projects_reads_open_heads_and_those_closed_within_30_days(ist: ModuleType) -> None:
    pages = {
        "OPEN": [head(7, (check(),)), head(8, labels=("project",), association="NONE", author="x")],
        "CLOSED": [
            head(9, state="CLOSED", reason="COMPLETED", closed_at="2026-11-20T00:00:00Z"),
            head(10, state="CLOSED", reason="COMPLETED", closed_at="2026-10-01T00:00:00Z"),  # 56 days ago
        ],
    }
    seen: list[dict[str, Any]] = []

    def run(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        seen.append(variables)
        states = "OPEN" if "states: OPEN" in query else "CLOSED"
        assert 'labels: ["project"]' in query
        nodes = pages[states]
        return {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}

    rows = ist.fetch_projects("o/r", BOT, NOW, run)
    assert [(r.number, r.state) for r in rows] == [(7, "PROJECT_ACTIVE"), (9, "PROJECT_CLOSED")]
    assert seen[1]["since"] == "2026-10-27T12:00:00Z" and "since" not in seen[0]


# -- S-106-11 -------------------------------------------------------------------------------


def test_s106_11_an_issue_without_the_project_label_reads_no_row(ist: ModuleType) -> None:
    """a plan item filed before spec 106 carries no label: no project row, whatever its sub-issues"""
    assert read(ist, head(labels=(), subs=(check(), sub(8)))) is None
    assert read(ist, head(labels=("feature",), subs=(check(),))) is None


def test_s106_11_an_accepted_plans_filed_items_are_labelled_project() -> None:
    root = Path(__file__).resolve().parents[1] / "skills" / "product-intake"
    plan = (root / "references" / "plan.md").read_text(encoding="utf-8")
    filing = next(line for line in plan.splitlines() if "issue create" in line and "plan-{plan}-W-{n}" in line)
    assert "--label project" in filing
    assert "filed before spec 106 has no label and reads no project row" in plan
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    step = next(line for line in skill.splitlines() if line.startswith("1. Open its issue from plan.md"))
    assert "labelled `project`" in step


# -- S-106-28 -------------------------------------------------------------------------------


class Gh:
    """shipmill gh --product as a stub: each owner's heads, a repo that fails, and the calls"""

    def __init__(self, ist: ModuleType, heads: dict[str, list[dict[str, Any]]], fail: tuple[str, ...] = ()):
        self.ist, self.heads, self.fail = ist, heads, fail
        self.calls: list[tuple[str, str]] = []

    def graphql(self, via: str, query: str, variables: dict[str, str], step: str) -> dict[str, Any]:
        self.calls.append((via, query))
        found = {}
        for alias, owner, name in re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', query):
            repo = f"{owner}/{name}"
            if repo in self.fail:
                raise self.ist.Unreadable(f"{step}: shipmill gh --product {via} exited 1")
            nodes = self.heads.get(repo, [])
            found[alias] = {"issues": {"totalCount": len(nodes), "nodes": nodes}}
        return found


def active(number: int, focus: bool = False) -> dict[str, Any]:
    labels = ("project", "focus") if focus else ("project",)
    return head(number, (check(), sub(number + 100)), labels=labels)


def test_s106_28_the_product_counts_active_and_focus_heads_one_call_per_owner(ist: ModuleType) -> None:
    product = ist.Product("o/home", ("o/home", "o/api", "p/web"), 3)
    local = [ist.project_row(active(1), BOT), ist.project_row(head(2), BOT)]  # one active, one held
    gh = Gh(
        ist, {"o/api": [active(5, focus=True), head(6)], "p/web": [active(9), head(10, (check(), sub(11, "CLOSED")))]}
    )
    projects = ist.projects_active(product, local, gh, BOT)
    assert (projects.active, projects.room) == (3, 0)  # #1, o/api#5 in focus, p/web#9; held and closing count nothing
    assert [v for v, _ in gh.calls] == ["o/api", "p/web"]  # one call per owner, through the owner's repo
    assert projects.json() == {"limit": 3, "active": 3, "room": 0}
    assert projects.line() == "projects active: 3 of 3 (product o/home)"
    assert ist.Projects("o/home", 2, 5).room == 0  # never below 0
    # an untrusted head of another repo counts nothing
    outsider = head(12, (check(), sub(13)), association="NONE", author="drive-by")
    assert (
        ist.projects_active(
            ist.Product("o/home", ("o/home", "o/api"), 3), [], Gh(ist, {"o/api": [outsider]}), BOT
        ).active
        == 0
    )


def test_s106_28_a_failed_read_exits_2_naming_the_repo(ist: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    product = ist.Product("o/home", ("o/home", "o/api"), 2)
    with pytest.raises(SystemExit) as exited:
        ist.projects_active(product, [], Gh(ist, {}, fail=("o/api",)), BOT)
    assert exited.value.code == 2 and "counting the active projects of o/api" in capsys.readouterr().err


def test_s106_28_without_the_key_nothing_is_read(ist: ModuleType) -> None:
    gh = Gh(ist, {})
    assert ist.projects_active(ist.Product("o/r", ("o/r", "o/api"), None), [], gh, BOT) is None
    assert gh.calls == []


def test_s106_28_a_component_reads_the_limit_from_its_home(ist: ModuleType, tmp_path: Path) -> None:
    config = tmp_path / "shipmill.toml"
    config.write_text('[product]\nhome = "o/home"\n')
    home = '[agents]\napp_id = 1\nprojects = 2\n[product]\nrepos = ["o/r", "o/api"]\n'
    product = ist.product_of("o/r", config, lambda _: home, "projects")
    assert (product.home, product.repos, product.limit) == ("o/home", ("o/r", "o/home", "o/api"), 2)
    # the outcomes limit is read apart: a home setting only projects sets no outcomes limit
    assert ist.product_of("o/r", config, lambda _: home).limit is None


def test_s106_28_a_component_that_sets_projects_is_refused_naming_the_home(
    ist: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "shipmill.toml"
    config.write_text('[agents]\nprojects = 2\n[product]\nhome = "o/home"\n')
    with pytest.raises(SystemExit) as exited:
        ist.product_of("o/r", config, lambda _: None, "projects")
    assert exited.value.code == 2
    assert "[agents] projects is the product's, set in its home o/home's" in capsys.readouterr().err


# -- the run, as a session runs it ----------------------------------------------------------

PROJECT_GH = FAKE_GH.replace(
    'if "labels: [$label]" in query:',
    "if 'labels: [\"project\"]' in query:\n"
    '    repo = {"issues": page(data["heads"]["OPEN" if "states: OPEN" in query else "CLOSED"])}\n'
    'elif "labels: [$label]" in query:',
)
PROJECT_UVX = FAKE_UVX.replace(
    '    found[alias] = {"issues": {"totalCount": data["counts"][repo]}}',
    '    heads = data["heads"].get(repo, [])\n'
    '    found[alias] = {"issues": {"totalCount": len(heads), "nodes": heads}}',
)


class Projects(Checkout):
    """spec 101's checkout, its fake gh and uvx also answering the projects queries"""

    def __init__(self, root: Path, config: str | None, heads: dict[str, Any], uvx: dict[str, Any] | None = None):
        super().__init__(root, config, {"heads": {}, **(uvx or {})})
        gh = json.loads((self.bin / "gh.json").read_text())
        (self.bin / "gh.json").write_text(json.dumps({**gh, "heads": heads}))
        for name, body in (("gh", PROJECT_GH), ("uvx", PROJECT_UVX)):
            (self.bin / name).write_text(f"#!{sys.executable}\n{body}")


def test_s106_12_the_run_prints_a_row_per_head_after_the_other_rows(tmp_path: Path) -> None:
    heads = {"OPEN": [active(7, focus=True), head(8)], "CLOSED": []}
    checkout = Projects(tmp_path, None, heads)
    lines = checkout.run("--projects", "--json")
    assert lines.returncode == 1, lines.stderr  # the opportunity rows' actions; no project row is one
    first, *rows = lines.stdout.splitlines()
    assert first == '{"autonomy": "propose"}'  # no limit, no projects key
    projects = [json.loads(r) for r in rows if json.loads(r).get("kind") == "project"]
    assert [(p["number"], p["state"], p["holder"]) for p in projects] == [
        (7, "PROJECT_FOCUS", "maintainer"),
        (8, "PROJECT_HELD", "start"),
    ]
    assert rows[-2:] == [json.dumps(p, sort_keys=True) for p in projects]
    text = checkout.run("--projects").stdout.splitlines()
    assert text[1].startswith("#11") and text[-1] == "PROJECT_HELD     #8      no check issue  Head 8"
    assert not any("PROJECT_" in line for line in checkout.run().stdout.splitlines())  # without the flag


def test_s106_28_the_run_counts_the_homes_product(tmp_path: Path) -> None:
    config = '[agents]\napp_id = 1\nprojects = 2\n[product]\nrepos = ["o/api"]\n'
    heads = {"OPEN": [active(7)], "CLOSED": []}
    checkout = Projects(tmp_path, config, heads, {"heads": {"o/api": [active(5), head(6)]}})
    lines = checkout.run("--projects", "--json")
    assert json.loads(lines.stdout.splitlines()[0]) == {
        "autonomy": "propose",
        "projects": {"limit": 2, "active": 2, "room": 0},
    }, lines.stderr
    text = checkout.run("--projects")
    assert text.stdout.splitlines()[1] == "projects active: 2 of 2 (product o/r)"
    assert [via(call) for call in checkout.product_calls()] == ["o/api", "o/api"]  # one call a run
    failed = Projects(tmp_path / "f", config, heads, {"heads": {}, "fail": ["o/api"]}).run("--projects")
    assert failed.returncode == 2 and "o/api" in failed.stderr
