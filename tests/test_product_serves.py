"""Spec 071: a component goal's optional `  serves: G-n[, G-n ...]` line naming the goals of its
product's home direction it serves, read by `shipmill product check|show|ids` and written by
`shipmill product serves`"""

import json
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.product import DIRECTION, Serves, check, read

from .test_direction_edit import repo

COMPONENT = '[product]\nhome = "acme/product"\n'
HOME = '[agents]\nprompt = "/t"\napp_id = 1234\n\n[product]\nrepos = ["acme/api"]\n'
CONFIG = Path(".github/shipmill.toml")

SERVED = """\
# Acme API

## Mission

The API partners build on.

## Users

- U-1: A partner's developer

## Goals

- G-1: Partners integrate in a day
  measure: lead_time_p90 < 1d
  serves: G-2, G-4
- G-2: Partners can page every list
  serves: G-1
- G-3: The API documents itself

## Non-goals

- N-1: A GraphQL API

## Quality bar

- Q-1: Every endpoint is tested
"""
PLAIN = SERVED.replace("  serves: G-2, G-4\n", "").replace("  serves: G-1\n", "")


def write(root: Path, text: str, config: str | None = COMPONENT, path: Path = DIRECTION) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if config is not None:
        (root / CONFIG).parent.mkdir(parents=True, exist_ok=True)
        (root / CONFIG).write_text(config, encoding="utf-8")
    return root


def run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), "product", *args])


def test_s071_1_check_accepts_serves_lines_under_the_item_or_the_measure_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, SERVED)
    assert check(root) == ()
    assert run(root, "check", "--local") == 0  # without it the ids are checked against the home's (S-071-3)
    assert capsys.readouterr().out == f"{DIRECTION}: well formed, 6 items\n"
    goals = read(root).goals
    assert [g.serves for g in goals] == [Serves.parse("G-2, G-4"), Serves.parse("G-1"), None]
    assert goals[0].measure is not None and goals[0].measure.text == "lead_time_p90 < 1d"


def test_s071_1_check_accepts_serves_lines_in_a_goals_section_moved_to_docs_product(tmp_path: Path) -> None:
    goals = SERVED[SERVED.index("## Goals") : SERVED.index("## Non-goals")]
    root = write(tmp_path / "moved", SERVED.replace(goals, "## Goals\n\nSee [Goals](product/goals.md).\n\n"))
    write(root, goals, None, Path("docs/product/goals.md"))
    assert check(root) == ()
    assert read(root) == read(write(tmp_path / "inline", SERVED))


G1 = "- G-1: Partners integrate in a day\n  measure: lead_time_p90 < 1d\n  serves: G-2, G-4\n"
REFUSED = [
    pytest.param(
        SERVED.replace("- N-1: A GraphQL API\n", "- N-1: A GraphQL API\n  serves: G-1\n"),
        23,
        "a serves line sits only under a goal; `## Non-goals` holds none",
        id="under a non-goal",
    ),
    pytest.param(
        SERVED.replace("- U-1: A partner's developer\n", "- U-1: A partner's developer\n  serves: G-1\n"),
        10,
        "a serves line sits only under a goal; `## Users` holds none",
        id="outside Goals",
    ),
    pytest.param(
        SERVED.replace("  serves: G-1\n", "  serves: G-1\n  serves: G-3\n"),
        18,
        "a second serves line under G-2; a goal carries at most one",
        id="a second one",
    ),
    pytest.param(
        SERVED.replace("  serves: G-1\n", "   serves: G-1\n"),
        17,
        "a serves line is `  serves: G-n[, G-n ...]`, indented by two spaces; got `   serves: G-1`",
        id="three spaces",
    ),
    pytest.param(
        SERVED.replace("  serves: G-1\n", "serves: G-1\n"),
        17,
        "a serves line is `  serves: G-n[, G-n ...]`, indented by two spaces; got `serves: G-1`",
        id="no indent",
    ),
    pytest.param(
        SERVED.replace("  serves: G-1\n", "  serves: N-1\n"),
        17,
        "a serves line names goal ids, `G-n` with n from 1, a comma and one space between; got 'N-1'",
        id="a non-goal id",
    ),
    pytest.param(
        SERVED.replace("  serves: G-1\n", "  serves: G-1,G-2\n"),
        17,
        "a serves line names goal ids, `G-n` with n from 1, a comma and one space between; got 'G-1,G-2'",
        id="no space after the comma",
    ),
    pytest.param(
        SERVED.replace("  serves: G-2, G-4\n", "  serves: G-2, G-4, G-2\n"),
        15,
        "a serves line names G-2 twice; it names each goal once",
        id="an id twice",
    ),
    pytest.param(
        SERVED.replace("  serves: G-1\n", "\n  serves: G-1\n"),
        18,
        "a serves line sits right under its goal's item line or its measure line; this one is after a blank line",
        id="after a blank line",
    ),
    pytest.param(
        SERVED.replace(G1, "- G-1: Partners integrate in a day\n  serves: G-2, G-4\n  measure: lead_time_p90 < 1d\n"),
        15,
        "a measure line sits right under its goal's item line, above G-1's serves line",
        id="above the measure line",
    ),
]


@pytest.mark.parametrize(("text", "line", "rule"), REFUSED)
@pytest.mark.parametrize("local", [[], ["--local"]])
def test_s071_1_check_refuses_a_misplaced_or_malformed_serves_line_naming_file_line_and_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, line: int, rule: str, local: list[str]
) -> None:
    root = write(tmp_path, text)
    assert [str(p) for p in check(root)] == [f"{DIRECTION}:{line}: {rule}"]
    assert run(root, "check", *local) == 1
    assert capsys.readouterr().out == f"{DIRECTION}:{line}: {rule}\n"


@pytest.mark.parametrize(
    ("config", "why"),
    [
        pytest.param(None, ".github/shipmill.toml sets no [product] home, so this repo is in no product", id="no file"),
        pytest.param(
            '[agents]\nprompt = "/t"\n',
            ".github/shipmill.toml sets no [product] home, so this repo is in no product",
            id="no [product]",
        ),
        pytest.param(
            "[product]\nstandalone = true\n",
            ".github/shipmill.toml sets no [product] home, so this repo is in no product",
            id="standalone",
        ),
        pytest.param(
            HOME,
            "this repo is the product's home ([product] repos in .github/shipmill.toml), which serves no product "
            "above it",
            id="the home",
        ),
    ],
)
@pytest.mark.parametrize("local", [[], ["--local"]])
def test_s071_2_check_refuses_any_serves_line_outside_a_component(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str | None, why: str, local: list[str]
) -> None:
    root = write(tmp_path, SERVED, config)
    rule = f"a serves line names the product goals a component's goal serves; {why}; delete the line"
    assert run(root, "check", *local) == 1
    assert capsys.readouterr().out == f"{DIRECTION}:15: {rule}\n{DIRECTION}:17: {rule}\n"
    with pytest.raises(ReleaseError, match="is not well formed"):  # show refuses what check refuses
        run(root, "show")
    plain = write(tmp_path / "plain", PLAIN, config)  # without a serves line the config isn't read
    assert check(plain) == ()


def test_s071_2_a_direction_without_serves_lines_never_reads_the_config(tmp_path: Path) -> None:
    root = write(tmp_path, PLAIN, "[product\nnot toml")
    assert check(root) == ()
    with pytest.raises(ReleaseError):
        check(write(tmp_path / "served", SERVED, "[product\nnot toml"))


def test_s071_9_show_json_gives_each_goal_a_serves_list_and_ids_lists_only_this_repo_s(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, SERVED)  # --local: the product's part is S-071-5's
    assert run(root, "show", "--local", "--json", "--section", "goals") == 0
    goals = json.loads(capsys.readouterr().out)["goals"]
    assert [(g["id"], g["serves"]) for g in goals] == [("G-1", ["G-2", "G-4"]), ("G-2", ["G-1"]), ("G-3", [])]
    assert run(root, "show", "--local", "--json") == 0
    whole = json.loads(capsys.readouterr().out)
    assert all("serves" not in item for key in ("users", "non_goals", "quality") for item in whole[key])
    assert run(root, "show", "--local", "--section", "goals") == 0  # the text form prints the line as the file has it
    assert capsys.readouterr().out == SERVED[SERVED.index("## Goals") : SERVED.index("\n## Non-goals")]
    assert run(root, "ids") == 0
    assert capsys.readouterr().out.splitlines() == [
        "U-1: A partner's developer",
        "G-1: Partners integrate in a day",
        "G-2: Partners can page every list",
        "G-3: The API documents itself",
        "N-1: A GraphQL API",
        "Q-1: Every endpoint is tested",
    ]


def lines_of(root: Path) -> list[str]:
    return (root / DIRECTION).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("args", "expected", "printed"),
    [
        pytest.param(
            ["G-3", "G-5"],
            SERVED.replace("- G-3: The API documents itself\n", "- G-3: The API documents itself\n  serves: G-5\n"),
            "  serves: G-5",
            id="under the item line",
        ),
        pytest.param(
            ["G-1", "G-7", "G-2"],
            SERVED.replace("  serves: G-2, G-4\n", "  serves: G-7, G-2\n"),
            "  serves: G-7, G-2",
            id="replaced under the measure line",
        ),
        pytest.param(
            ["G-2", "G-3"],
            SERVED.replace("  serves: G-1\n", "  serves: G-3\n"),
            "  serves: G-3",
            id="replaced under the item line",
        ),
        pytest.param(
            ["G-1", "--clear"], SERVED.replace("  serves: G-2, G-4\n", ""), "  serves: G-2, G-4", id="cleared"
        ),
        pytest.param(["G-3", "--clear"], SERVED, "G-3 has no serves line; nothing written", id="nothing to clear"),
    ],
)
def test_s071_10_serves_writes_replaces_or_clears_only_the_goal_s_serves_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], expected: str, printed: str
) -> None:
    root = write(tmp_path, SERVED)
    assert run(root, "serves", *args) == 0
    assert capsys.readouterr().out == f"{printed}\n"
    assert (root / DIRECTION).read_text(encoding="utf-8") == expected
    assert check(root) == ()


def test_s071_10_serves_writes_under_the_measure_line_of_a_goal_without_one(tmp_path: Path) -> None:
    root = write(tmp_path, PLAIN)
    assert run(root, "serves", "G-1", "G-2") == 0
    assert lines_of(root)[12:15] == [
        "- G-1: Partners integrate in a day",
        "  measure: lead_time_p90 < 1d",
        "  serves: G-2",
    ]


def test_s071_10_serves_writes_in_the_file_a_moved_goals_section_points_to(tmp_path: Path) -> None:
    goals = PLAIN[PLAIN.index("## Goals") : PLAIN.index("## Non-goals")]
    moved = PLAIN.replace(goals, "## Goals\n\nSee [Goals](product/goals.md).\n\n")
    root = write(tmp_path, moved)
    write(root, goals, None, Path("docs/product/goals.md"))
    assert run(root, "serves", "G-3", "G-1") == 0
    assert (root / "docs/product/goals.md").read_text(encoding="utf-8") == goals.replace(
        "itself\n", "itself\n  serves: G-1\n"
    )
    assert (root / DIRECTION).read_text(encoding="utf-8") == moved


@pytest.mark.parametrize(
    ("text", "config", "args"),
    [
        pytest.param(SERVED.replace("  serves: G-1\n", "  serves: G-1, G-1\n"), COMPONENT, ["G-3", "G-2"], id="broken"),
        pytest.param(SERVED, None, ["G-1", "--clear"], id="serves outside a component, cleared"),
        pytest.param(SERVED, HOME, ["G-3", "G-2"], id="serves in the home"),
        pytest.param(PLAIN, None, ["G-3", "G-2"], id="a new one outside a component"),
        pytest.param(PLAIN, HOME, ["G-3", "G-2"], id="a new one in the home"),
        pytest.param(SERVED, COMPONENT, ["N-1", "G-2"], id="not a goal"),
        pytest.param(SERVED, COMPONENT, ["G-3", "N-2"], id="not a goal id"),
        pytest.param(SERVED, COMPONENT, ["G-3", "G-2", "G-2"], id="an id twice"),
        pytest.param(SERVED, COMPONENT, ["G-9", "G-2"], id="no such goal"),
    ],
)
def test_s071_10_serves_exits_2_without_writing_on_a_file_check_refuses(
    tmp_path: Path, text: str, config: str | None, args: list[str]
) -> None:
    root = write(tmp_path, text, config)
    before = (root / DIRECTION).read_bytes()
    with pytest.raises(ReleaseError):
        run(root, "serves", *args)
    assert (root / DIRECTION).read_bytes() == before


@pytest.mark.parametrize("args", [["G-3"], ["G-3", "G-2", "--clear"]])
def test_s071_10_serves_takes_goal_ids_or_clear_never_both_nor_neither(tmp_path: Path, args: list[str]) -> None:
    root = write(tmp_path, SERVED)
    with pytest.raises(SystemExit) as stopped:
        run(root, "serves", *args)
    assert stopped.value.code == 2
    assert (root / DIRECTION).read_text(encoding="utf-8") == SERVED


def test_s071_10_retire_removes_a_goal_s_serves_line_and_add_edit_measure_keep_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, {"docs/product.md": SERVED, ".github/shipmill.toml": COMPONENT})
    assert run(root, "retire", "G-1") == 0  # its measure line and its serves line go with it
    assert run(root, "retire", "G-2") == 0  # its serves line, right under its item line
    assert (root / DIRECTION).read_text(encoding="utf-8") == SERVED.replace(
        G1 + "- G-2: Partners can page every list\n  serves: G-1\n", ""
    )
    root = repo(tmp_path / "kept", {"docs/product.md": SERVED, ".github/shipmill.toml": COMPONENT})
    assert run(root, "add", "goals", "Partners see their usage") == 0
    assert run(root, "edit", "G-2", "Partners can page and filter every list") == 0
    assert run(root, "measure", "G-2", "lead_time_median < 2d") == 0
    assert run(root, "measure", "G-1", "lead_time_p90 < 2d") == 0
    capsys.readouterr()
    assert check(root) == ()
    assert (root / DIRECTION).read_text(encoding="utf-8") == SERVED.replace(
        "lead_time_p90 < 1d", "lead_time_p90 < 2d"
    ).replace(
        "- G-2: Partners can page every list\n  serves: G-1\n- G-3: The API documents itself\n",
        "- G-2: Partners can page and filter every list\n  measure: lead_time_median < 2d\n  serves: G-1\n"
        "- G-3: The API documents itself\n- G-4: Partners see their usage\n",
    )
    assert run(root, "measure", "G-2", "--clear") == 0
    assert lines_of(root)[15:17] == ["- G-2: Partners can page and filter every list", "  serves: G-1"]
