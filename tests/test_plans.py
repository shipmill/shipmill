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


MEASURED = DIRECTION.replace("own\n", "own\n  measure: issue_to_release_p90 < 2d\n")
NOT_A_GOAL = "not a `- G-<n>: <text>` item"


def test_check_skips_a_goals_measure_line(plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # #749: a goal's measure line (spec 027) under its item line holds no id and is skipped
    (root / "docs" / "product.md").write_text(MEASURED, encoding="utf-8")
    assert plans.goal_ids(root) == frozenset({"G-3", "G-6"})
    assert check(plans, root, PLAN, capsys) == (0, "")


def test_check_skips_a_measure_line_in_a_moved_goals_section(
    plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "docs" / "product.md").write_text(
        "# Example\n\n## Mission\n\nShip it.\n\n## Goals\n\nSee [Goals](product/goals.md).\n", encoding="utf-8"
    )
    (root / "docs" / "product").mkdir()
    (root / "docs" / "product" / "goals.md").write_text(
        "## Goals\n\n- G-3: Releases\n  measure: change_failure_rate <= 5%\n", encoding="utf-8"
    )
    assert check(plans, root, PLAN, capsys) == (0, "")


def test_s071_11_check_reads_goals_that_carry_serves_lines_as_without_them(
    plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = DIRECTION.replace("own\n", "own\n  serves: G-2, G-4\n").replace(
        "a goal\n", "a goal\n  measure: issue_to_release_p90 < 2d\n  serves: G-1\n"
    )
    (root / "docs" / "product.md").write_text(served, encoding="utf-8")
    assert plans.goal_ids(root) == frozenset({"G-3", "G-6"})
    assert check(plans, root, PLAN, capsys) == (0, "")
    (root / "docs" / "product.md").write_text(DIRECTION.replace("own\n", "own\n\n  serves: G-2\n"), encoding="utf-8")
    with pytest.raises(SystemExit):  # a serves line after a blank line still stops it
        check(plans, root, PLAN, capsys)


STRAY = [
    ("prose under a goal", MEASURED.replace("  measure:", "And more:"), f"docs/product.md:10: {NOT_A_GOAL}"),
    ("unindented measure", MEASURED.replace("  measure:", "measure:"), f"docs/product.md:10: {NOT_A_GOAL}"),
    ("other indented key", MEASURED.replace("  measure:", "  target:"), f"docs/product.md:10: {NOT_A_GOAL}"),
    (
        "measure after a blank line",
        MEASURED.replace("\n  measure:", "\n\n  measure:"),
        f"docs/product.md:11: {NOT_A_GOAL}",
    ),
    (
        "second measure line",
        MEASURED.replace("< 2d\n", "< 2d\n  measure: change_failure_rate <= 5%\n"),
        f"docs/product.md:11: {NOT_A_GOAL}",
    ),
    (
        "measure outside Goals",
        MEASURED.replace("## Goals", "## Users\n\n- U-1: A maintainer\n  measure: x < 1\n\n## Goals"),
        "docs/product.md:10: not a `- U-<n>: <text>` item",
    ),
]


@pytest.mark.parametrize(("case", "direction", "error"), STRAY, ids=[c[0] for c in STRAY])
def test_check_still_refuses_a_stray_direction_line(
    plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str], case: str, direction: str, error: str
) -> None:
    (root / "docs" / "product.md").write_text(direction, encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        check(plans, root, PLAN, capsys)
    assert stopped.value.code == 2, case
    assert error in capsys.readouterr().err


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


# -- the plan a goal's next plan follows (spec 097, #1712)

FOLLOWING = PLAN.replace("Measure: none yet\n", "Measure: none yet\nFollows: #752\n")


def test_s097_8_one_follows_line_after_measure_passes(
    plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check(plans, root, FOLLOWING, capsys) == (0, "")
    assert check(plans, root, PLAN, capsys) == (0, "")  # none: a goal's first plan, or one before spec 097
    later = FOLLOWING.replace("Follows: #752\n", "\nFollows: #752\n")  # a blank line between is fine
    assert check(plans, root, later, capsys) == (0, "")
    plan, _ = plans.parse(FOLLOWING, frozenset({"G-3"}))
    assert plan.follows == 752 and [i.id for i in plan.items] == ["W-1", "W-2", "W-3", "W-4"]
    assert plans.parse(PLAN, frozenset({"G-3"}))[0].follows is None


@pytest.mark.parametrize(
    ("name", "body", "line", "rule"),
    [
        ("no #", FOLLOWING.replace("#752", "752"), 8, "a Follows line is `Follows: #<n>`"),
        ("a repo", FOLLOWING.replace("#752", "o/r#752"), 8, "a Follows line is `Follows: #<n>`"),
        ("two plans", FOLLOWING.replace("#752", "#752, #800"), 8, "a Follows line is `Follows: #<n>`"),
        ("words", FOLLOWING.replace("#752", "#752 (the last one)"), 8, "a Follows line is `Follows: #<n>`"),
        ("before Measure", PLAN.replace("Trigger:", "Follows: #752\nTrigger:"), 6, "comes after the Goal section's"),
        ("second", FOLLOWING.replace("#752\n", "#752\nFollows: #753\n"), 9, "a second `Follows: #<n>` line"),
        ("in Order", PLAN.replace("then the feature", "then the feature\nFollows: #752\n"), 19, "belongs in the Goal"),
        ("in Notes", PLAN + "Follows: #752\n", 27, "belongs in the Goal section"),
    ],
)
def test_s097_8_any_other_follows_line_exits_2_naming_it(
    plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str], name: str, body: str, line: int, rule: str
) -> None:
    code, err = check(plans, root, body, capsys)
    assert code == 2, name
    assert f"plan.md:{line}: " in err and rule in err, err


# -- the Goal section's lines for the goal's kind (spec 105, #1731)

KINDS = DIRECTION + (
    "- G-4: The maintainer sees what waits on them. Check: `queue --fleet` lists it all. By: 2026-12-31\n"
    "- G-5: Held: agents keep to the direction. Threshold: every pull request names a goal. Source: the plan check\n"
    "  measure: issue_to_release_p90 < 2d\n"
    "- G-7: A release goal. Check: 0.7.0 is out. By: v0.7.0\n"
)
GOAL_PLAN = PLAN.replace("goal=G-3", "goal=G-4").replace(
    "Measure: none yet\n", "Check: `queue --fleet` lists it all\nBy: 2026-12-31\n"
)
MEASURE_PLAN = PLAN.replace("goal=G-3", "goal=G-5").replace(
    "Measure: none yet\n",
    "Threshold: every pull request names a goal\nSource: the plan check\nMeasure: issue_to_release_p90 < 2d\n",
)


@pytest.fixture
def kinded(root: Path) -> Path:
    (root / "docs" / "product.md").write_text(KINDS, encoding="utf-8")
    return root


def test_s105_9_check_reads_each_goals_kind_from_the_direction(plans: ModuleType, kinded: Path) -> None:
    assert plans.goal_kinds(kinded) == {"G-3": None, "G-6": None, "G-4": "goal", "G-5": "measure", "G-7": "goal"}
    assert plans.goal_ids(kinded) == frozenset({"G-3", "G-4", "G-5", "G-6", "G-7"})


def test_s105_9_check_reads_this_repositorys_direction(plans: ModuleType) -> None:
    kinds = plans.goal_kinds(SCRIPT.parents[3])
    assert kinds["G-1"] == "measure" and kinds["G-3"] == "goal"


def test_s105_9_check_passes_a_plan_for_each_kind(
    plans: ModuleType, kinded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check(plans, kinded, GOAL_PLAN, capsys) == (0, "")
    release = GOAL_PLAN.replace("goal=G-4", "goal=G-7").replace("By: 2026-12-31", "By: v0.7.0")
    assert check(plans, kinded, release, capsys) == (0, "")
    assert check(plans, kinded, MEASURE_PLAN, capsys) == (0, "")
    assert check(plans, kinded, PLAN, capsys) == (0, "")  # kind none: `Measure:` alone, as before
    # spec 097's Follows line comes after the last of the kind's lines
    following = GOAL_PLAN.replace("By: 2026-12-31\n", "By: 2026-12-31\nFollows: #752\n")
    assert check(plans, kinded, following, capsys) == (0, "")
    measured = MEASURE_PLAN.replace("< 2d\n", "< 2d\nFollows: #752\n")
    assert check(plans, kinded, measured, capsys) == (0, "")
    # without the direction (`items` reads a plan as written), the lines show the kind
    plan, problems = plans.parse(following, None)
    assert problems == [] and plan.follows == 752


GOAL_SECTION_REFUSED = [
    (
        "goal without Check",
        GOAL_PLAN.replace("Check: `queue --fleet` lists it all\n", ""),
        8,
        "no `Check: <check>` line",
    ),
    ("goal without By", GOAL_PLAN.replace("By: 2026-12-31\n", ""), 8, "no `By: <horizon>` line"),
    (
        "goal with Measure",
        GOAL_PLAN.replace("By: 2026-12-31\n", "By: 2026-12-31\nMeasure: none\n"),
        9,
        "`Measure:` line",
    ),
    ("goal with Source", GOAL_PLAN.replace("By: 2026-12-31\n", "By: 2026-12-31\nSource: x\n"), 9, "`Source:` line"),
    ("goal By twice", GOAL_PLAN.replace("By: 2026-12-31\n", "By: 2026-12-31\nBy: 0.7.0\n"), 9, "a second `By:` line"),
    ("goal Check twice", GOAL_PLAN.replace("Check:", "Check: twice\nCheck:"), 8, "a second `Check:` line"),
    ("goal bad horizon", GOAL_PLAN.replace("By: 2026-12-31", "By: Q4"), 8, "a By line's horizon is a date"),
    ("goal no calendar date", GOAL_PLAN.replace("By: 2026-12-31", "By: 2026-13-01"), 8, "got `2026-13-01`"),
    ("goal empty Check", GOAL_PLAN.replace("Check: `queue --fleet` lists it all", "Check:"), 7, "`Check: <check>`"),
    (
        "goal By before Check",
        GOAL_PLAN.replace("Check: `queue --fleet` lists it all\nBy: 2026-12-31\n", "By: 2026-12-31\nCheck: c\n"),
        8,
        "`Check:` comes before `By:`",
    ),
    (
        "goal before Trigger",
        GOAL_PLAN.replace("Trigger: no-work\n", "").replace("By: 2026-12-31\n", "By: 2026-12-31\nTrigger: no-work\n"),
        6,
        "comes after the Goal section's `Trigger:` line",
    ),
    (
        "goal Follows before By",
        GOAL_PLAN.replace("By: 2026-12-31\n", "Follows: #752\nBy: 2026-12-31\n"),
        8,
        "comes after the Goal section's `By:` line",
    ),
    (
        "measure without Threshold",
        MEASURE_PLAN.replace("Threshold: every pull request names a goal\n", ""),
        9,
        "no `Threshold: <threshold>` line",
    ),
    ("measure without Source", MEASURE_PLAN.replace("Source: the plan check\n", ""), 9, "no `Source: <source>` line"),
    ("measure without Measure", MEASURE_PLAN.replace("Measure: issue_to_release_p90 < 2d\n", ""), 9, "no `Measure:"),
    (
        "measure with Check",
        MEASURE_PLAN.replace("Trigger: no-work\n", "Trigger: no-work\nCheck: c\n"),
        7,
        "`Check:` line",
    ),
    ("measure with By", MEASURE_PLAN.replace("< 2d\n", "< 2d\nBy: 2026-12-31\n"), 10, "`By:` line"),
    (
        "measure Source twice",
        MEASURE_PLAN.replace("Source: the plan check\n", "Source: a\nSource: b\n"),
        9,
        "a second `Source:`",
    ),
    (
        "measure Measure first",
        MEASURE_PLAN.replace("Measure: issue_to_release_p90 < 2d\n", "").replace(
            "Trigger: no-work\n", "Trigger: no-work\nMeasure: none\n"
        ),
        8,
        "`Threshold:` comes before `Measure:`",
    ),
    ("none with Check", PLAN.replace("Measure: none yet\n", "Measure: none yet\nCheck: c\n"), 8, "`Check:` line"),
    (
        "none with Threshold",
        PLAN.replace("Measure: none yet\n", "Threshold: t\nMeasure: none yet\n"),
        7,
        "`Threshold:` line",
    ),
    (
        "none without Measure",
        PLAN.replace("Measure: none yet\n", ""),
        7,
        "no `Measure: <the measure line, or none>` line",
    ),
    (
        "none Measure twice",
        PLAN.replace("Measure: none yet\n", "Measure: none yet\nMeasure: none\n"),
        8,
        "a second `Measure:`",
    ),
]


@pytest.mark.parametrize(
    ("case", "body", "line", "rule"), GOAL_SECTION_REFUSED, ids=[c[0] for c in GOAL_SECTION_REFUSED]
)
def test_s105_9_check_refuses_a_goal_section_line_naming_it(
    plans: ModuleType,
    kinded: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    body: str,
    line: int,
    rule: str,
) -> None:
    code, err = check(plans, kinded, body, capsys)
    assert code == 2, case
    assert any(f"plan.md:{line}: " in shown and rule in shown for shown in err.splitlines()), err


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("Ship. Check: c", "`. Check: ` with no `. By: ` after it"),
        ("Ship. By: 2026-12-31", "`. By: ` with no `. Check: ` before it"),
        ("Ship. Check: c. By: 2026-12-31.", "a horizon is a date"),
        ("Held: x. Source: s", "`Held: ` with no `. Threshold: `"),
        ("Held: x. Threshold: t. Source: s. Check: c. By: 0.7.0", "both a goal's labels and a measure's"),
        (". Check: c. By: 0.7.0", "its outcome is empty"),
    ],
)
def test_s105_9_check_stops_on_a_malformed_goal_in_the_direction(
    plans: ModuleType, root: Path, capsys: pytest.CaptureFixture[str], text: str, rule: str
) -> None:
    (root / "docs" / "product.md").write_text(DIRECTION.replace("Releases go out on their own", text), encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        check(plans, root, PLAN, capsys)
    assert stopped.value.code == 2
    err = capsys.readouterr().err
    assert "docs/product.md:9: G-3: " in err and rule in err and "run `shipmill product check`" in err, err
