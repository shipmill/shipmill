"""The product-intake skill's plan grammar and items (spec 028), without gh or the network"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "plans.py"

DIRECTION = """# Example

## Mission

Ship it.

## Goals

- G-3: Releases go out on their own
- G-6: Agents propose the work that reaches a goal
"""

PLAN = """<!-- shipmill:plan goal=G-3 rev=1 -->
## Goal

G-3: Releases go out on their own

Trigger: no-work
Measure: none yet

## Work

- W-1 existing: #212
- W-2 feature: A release cut on every green batch
- W-3 fix: The lane stalls on a flaky job (after W-2)
- W-4 feature: Notices name the release (after W-1, W-3)

## Order

The existing issue first, then the feature the fix builds on.

## Milestone

none

## Notes

Left out: dates (D-32).
"""


@pytest.fixture(scope="module")
def plans() -> ModuleType:
    spec = importlib.util.spec_from_file_location("plans", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "product.md").write_text(DIRECTION, encoding="utf-8")
    return tmp_path


def check(plans: ModuleType, root: Path, body: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    file = root / "plan.md"
    file.write_text(body, encoding="utf-8")
    code = plans.main(["check", str(file), "--root", str(root)])
    return code, capsys.readouterr().err


def test_s028_6_a_well_formed_plan_passes(plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check(plans, root, PLAN, capsys) == (0, "")
    without_notes = PLAN.split("## Notes")[0].replace("none\n", "Release 1.0\n")
    assert check(plans, root, without_notes, capsys) == (0, "")


def test_s028_6_a_plan_parses_into_its_items(plans: ModuleType) -> None:
    plan, problems = plans.parse(PLAN, frozenset({"G-3"}))
    assert problems == []
    assert (plan.goal, plan.rev, plan.milestone) == ("G-3", 1, None)
    assert [(i.id, i.kind, i.text, i.after) for i in plan.items] == [
        ("W-1", "existing", "#212", ()),
        ("W-2", "feature", "A release cut on every green batch", ()),
        ("W-3", "fix", "The lane stalls on a flaky job", ("W-2",)),
        ("W-4", "feature", "Notices name the release", ("W-1", "W-3")),
    ]


NO_ITEMS = """<!-- shipmill:plan goal=G-3 rev=1 -->
## Goal

G-3: Releases go out on their own

## Work

## Order

Nothing to do.

## Milestone

none
"""

REFUSED = [
    ("no marker", PLAN.replace("<!-- shipmill:plan goal=G-3 rev=1 -->\n", ""), 1, "the first line is the marker"),
    ("malformed marker", PLAN.replace("rev=1", "rev=0"), 1, "the first line is the marker"),
    ("marker not first", "\n" + PLAN, 1, "the first line is the marker"),
    ("unlisted goal", PLAN.replace("goal=G-3", "goal=G-9"), 1, "names G-9, which docs/product.md doesn't list"),
    ("missing heading", PLAN.replace("## Order\n", ""), 19, "no `## Order` before `## Milestone`"),
    ("missing last heading", PLAN.split("## Milestone")[0], 19, "no `## Milestone` section"),
    ("extra heading", PLAN.replace("## Notes", "## Risks"), 24, "`## Risks` is not a plan heading"),
    ("level-one heading", PLAN.replace("## Notes", "# Notes"), 24, "`# Notes` is not a plan heading"),
    ("second heading", PLAN + "\n## Order\n\nAgain.\n", 28, "a second `## Order`"),
    (
        "out of order",
        PLAN.replace("## Order\n\nThe existing issue first, then the feature the fix builds on.\n\n", "").replace(
            "## Notes", "## Order\n\nLate.\n\n## Notes"
        ),
        20,
        "`## Order` is out of order",
    ),
    ("text before Goal", PLAN.replace("-->\n", "-->\nHello\n"), 2, "nothing but the marker comes before"),
    ("no items", NO_ITEMS, 7, "Work holds at least one item"),
    ("item form", PLAN.replace("- W-2 feature:", "- W-2 idea:"), 12, "a Work line is an item"),
    (
        "item without text",
        PLAN.replace("- W-2 feature: A release cut on every green batch", "- W-2 feature:"),
        12,
        "a Work line is an item",
    ),
    (
        "prose in Work",
        PLAN.replace("- W-1 existing: #212\n", "- W-1 existing: #212\nAnd more.\n"),
        12,
        "a Work line is an item",
    ),
    ("duplicate id", PLAN.replace("- W-2 feature:", "- W-1 feature:"), 12, "W-1 is a duplicate item id"),
    ("out of sequence", PLAN.replace("- W-1 existing: #212", "- W-5 existing: #212"), 11, "W-5 is out of sequence"),
    (
        "existing prose",
        PLAN.replace("- W-1 existing: #212", "- W-1 existing: the release issue"),
        11,
        "its text is one issue reference",
    ),
    (
        "existing two refs",
        PLAN.replace("- W-1 existing: #212", "- W-1 existing: #212 #213"),
        11,
        "its text is one issue reference",
    ),
    (
        "after a later item",
        PLAN.replace("(after W-2)", "(after W-4)"),
        13,
        "W-3 comes after W-4, which isn't an item before it",
    ),
    (
        "after itself",
        PLAN.replace("(after W-2)", "(after W-3)"),
        13,
        "W-3 comes after W-3, which isn't an item before it",
    ),
    ("after malformed", PLAN.replace("(after W-2)", "(after 2)"), 13, "`(after ...)` names earlier items"),
    (
        "milestone two lines",
        PLAN.replace("## Milestone\n\nnone\n", "## Milestone\n\nnone\nRelease 1.0\n"),
        23,
        "Milestone holds one line",
    ),
    ("milestone empty", PLAN.replace("## Milestone\n\nnone\n", "## Milestone\n\n"), 21, "Milestone holds one line"),
]


@pytest.mark.parametrize(("case", "body", "line", "rule"), REFUSED, ids=[c[0] for c in REFUSED])
def test_s028_6_check_refuses_naming_the_line_and_rule(
    plans: ModuleType,
    root: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    body: str,
    line: int,
    rule: str,
) -> None:
    code, err = check(plans, root, body, capsys)
    assert code == 2, case
    assert any(f"plan.md:{line}: " in shown and rule in shown for shown in err.splitlines()), err


def test_check_reads_a_moved_goals_section(plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (root / "docs" / "product.md").write_text(
        "# Example\n\n## Mission\n\nShip it.\n\n## Goals\n\nSee [Goals](product/goals.md).\n", encoding="utf-8"
    )
    (root / "docs" / "product").mkdir()
    (root / "docs" / "product" / "goals.md").write_text("## Goals\n\n- G-3: Releases\n", encoding="utf-8")
    assert check(plans, root, PLAN, capsys) == (0, "")


def test_check_without_a_direction_stops(plans: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = tmp_path / "plan.md"
    file.write_text(PLAN, encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        plans.main(["check", str(file), "--root", str(tmp_path)])
    assert stopped.value.code == 2
    assert "no docs/product.md" in capsys.readouterr().err


def issue_node(
    number: int, body: str, *, association: str = "NONE", bot: bool = True, repo: str = "o/r"
) -> dict[str, Any]:
    author = {"__typename": "Bot", "login": "shipmill"} if bot else {"__typename": "User", "login": "someone"}
    return {
        "number": number,
        "body": body,
        "author": author,
        "authorAssociation": association,
        "repository": {"nameWithOwner": repo},
    }


class Fake:
    """GitHub answering the one items query; records each call"""

    def __init__(self, body: str, subs: list[dict[str, Any]], found: list[dict[str, Any]]) -> None:
        self.body, self.subs, self.found = body, subs, found
        self.calls: list[dict[str, Any]] = []

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(variables)
        return {
            "data": {
                "repository": {
                    "issue": {
                        "number": variables["number"],
                        "body": self.body,
                        "subIssues": {"pageInfo": {"hasNextPage": False}, "nodes": self.subs},
                    }
                },
                "search": {"issueCount": len(self.found), "nodes": self.found},
            }
        }


def test_s028_7_items_lists_each_item_and_its_filed_issue(
    plans: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake(
        PLAN,
        subs=[issue_node(301, "<!-- shipmill:plan-item #300 W-2 -->\nA release cut ...")],
        found=[
            issue_node(301, "<!-- shipmill:plan-item #300 W-2 -->\nA release cut ..."),
            issue_node(305, "<!-- shipmill:plan-item #300 W-3 -->\nThe lane ...", association="OWNER", bot=False),
            issue_node(304, "<!-- shipmill:plan-item #300 W-3 -->\nThe lane ..."),
            issue_node(306, "<!-- shipmill:plan-item #30 W-4 -->\nAnother plan's item"),
            issue_node(307, "Quoted: <!-- shipmill:plan-item #300 W-4 -->"),
        ],
    )
    assert plans.main(["items", "o/r#300", "--bot-login", "shipmill[bot]", "--json"], run=fake) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows == [
        {"id": "W-1", "kind": "existing", "text": "#212", "after": [], "issue": None},
        {"id": "W-2", "kind": "feature", "text": "A release cut on every green batch", "after": [], "issue": 301},
        {"id": "W-3", "kind": "fix", "text": "The lane stalls on a flaky job", "after": ["W-2"], "issue": 304},
        {"id": "W-4", "kind": "feature", "text": "Notices name the release", "after": ["W-1", "W-3"], "issue": None},
    ]
    assert len(fake.calls) == 1
    assert fake.calls[0]["search"] == 'repo:o/r is:issue in:body "shipmill:plan-item #300"'


def test_s028_7_items_reads_a_marker_only_from_a_trusted_author_of_this_repo(plans: ModuleType) -> None:
    marker = "<!-- shipmill:plan-item #300 W-2 -->\nx"
    fake = Fake(
        PLAN,
        subs=[],
        found=[
            issue_node(310, marker, bot=False),  # an outsider (D-29)
            issue_node(311, marker, repo="o/other"),  # another repository
        ],
    )
    found = {item.id: issue for item, issue in plans.plan_items("o/r#300", "shipmill[bot]", fake)}
    assert found["W-2"] is None
    without_login = {
        item.id: issue for item, issue in plans.plan_items("o/r#300", None, Fake(PLAN, [issue_node(312, marker)], []))
    }
    assert without_login["W-2"] is None  # the App's issue counts only with --bot-login
    trusted = Fake(PLAN, [], [issue_node(313, marker, association="MEMBER", bot=False)])
    assert {i.id: n for i, n in plans.plan_items("o/r#300", None, trusted)}["W-2"] == 313


def test_items_text_output(plans: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert plans.main(["items", "o/r#300"], run=Fake(PLAN, [], [])) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["W-1", "existing", "none", "#212"]
    assert out[2].endswith("(after W-2)")


def test_items_on_a_malformed_plan_stops(plans: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        plans.main(["items", "o/r#300", "--json"], run=Fake(PLAN.replace("- W-2 feature:", "- W-1 feature:"), [], []))
    assert stopped.value.code == 2
    assert "o/r#300:12: W-1 is a duplicate item id" in capsys.readouterr().err


class Paged(Fake):
    """GitHub answering with more sub-issues or marker matches than one page holds"""

    def __init__(self, more_subs: bool, count: int) -> None:
        super().__init__(PLAN, [], [])
        self.more_subs, self.count = more_subs, count

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = super().__call__(query, variables)
        response["data"]["repository"]["issue"]["subIssues"]["pageInfo"]["hasNextPage"] = self.more_subs
        response["data"]["search"]["issueCount"] = self.count
        return response


@pytest.mark.parametrize(("more_subs", "count"), [(True, 0), (False, 101)], ids=["sub-issues", "search"])
def test_s028_7_items_past_one_page_stops_rather_than_truncating(
    plans: ModuleType, capsys: pytest.CaptureFixture[str], more_subs: bool, count: int
) -> None:
    with pytest.raises(SystemExit) as stopped:
        plans.main(["items", "o/r#300", "--json"], run=Paged(more_subs, count))
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "more than 100 sub-issues or marker matches" in captured.err


def test_items_on_a_missing_issue_or_graphql_errors_stops(
    plans: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {"data": {"repository": {"issue": None}, "search": {"issueCount": 0, "nodes": []}}}

    def errors(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {"data": None, "errors": [{"message": "Could not resolve to a Repository"}]}

    for run, shown in ((missing, "no issue o/r#300"), (errors, "Could not resolve to a Repository")):
        with pytest.raises(SystemExit) as stopped:
            plans.main(["items", "o/r#300"], run=run)
        assert stopped.value.code == 2
        assert shown in capsys.readouterr().err


def test_items_names_a_plan_as_owner_repo_number(plans: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        plans.main(["items", "#300"], run=Fake(PLAN, [], []))
    assert stopped.value.code == 2
    assert "owner/repo#N" in capsys.readouterr().err
