"""Spec 024: docs/product.md, the product's direction, and `shipmill product check|show|ids`"""

import json
import shutil
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.product import DIRECTION, ItemId, Prefix, Problem, Section, check, read

ROOT = Path(__file__).resolve().parents[1]

WELL_FORMED = """\
# Acme

## Mission

Acme ships widgets.

It ships them fast.

## Users

- U-1: A widget buyer

## Goals

- G-1: Widgets reach buyers in a day
- G-3: Buyers can track a widget

## Non-goals

## Quality bar

- Q-1: Every widget is tested
"""


def write(root: Path, text: str, path: Path = DIRECTION) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return root


def problems(root: Path) -> list[str]:
    return [str(p) for p in check(root)]


def run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), "product", *args])


def test_s024_1_the_repos_own_direction_is_well_formed(capsys: pytest.CaptureFixture[str]) -> None:
    assert check(ROOT) == ()
    assert run(ROOT, "check") == 0
    assert capsys.readouterr().out.startswith(f"{DIRECTION}: well formed")


def test_s024_1_a_synthetic_direction_is_well_formed_with_gaps_and_an_empty_non_goals(tmp_path: Path) -> None:
    direction = read(write(tmp_path, WELL_FORMED))
    assert direction.name == "Acme"
    assert direction.mission == "Acme ships widgets.\n\nIt ships them fast."
    assert [str(i.id) for i in direction.goals] == ["G-1", "G-3"]
    assert direction.non_goals == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            WELL_FORMED.replace("## Users\n\n- U-1: A widget buyer\n\n", ""),
            ["docs/product.md:9: missing `## Users`"],
            id="missing heading",
        ),
        pytest.param(
            WELL_FORMED.replace("## Non-goals\n", "## Risks\n\n- R-1: x\n\n## Non-goals\n"),
            ["docs/product.md:18: `## Risks` is not a direction heading"],
            id="extra heading",
        ),
        pytest.param(
            WELL_FORMED + "\n### Notes\n",
            ["docs/product.md:24: `### Notes`: the direction has only its five level-two headings"],
            id="extra level-three heading",
        ),
        pytest.param(
            WELL_FORMED + "\n# Again\n",
            ["docs/product.md:24: a second level-one heading"],
            id="second level-one heading",
        ),
        pytest.param(
            WELL_FORMED.replace("## Goals\n\n- G-1: Widgets reach buyers in a day\n", "").replace(
                "- G-3: Buyers can track a widget\n\n", ""
            )
            + "\n## Goals\n\n- G-1: x\n",
            ["docs/product.md:19: `## Goals` comes after `## Quality bar`"],
            id="out of order",
        ),
        pytest.param(
            WELL_FORMED + "\n## Users\n\n- U-2: y\n",
            ["docs/product.md:24: `## Users` again; it is already on line 9"],
            id="duplicate heading",
        ),
        pytest.param(
            "Intro\n\n" + WELL_FORMED,
            ["docs/product.md:1: the file starts with a level-one heading"],
            id="text before the name",
        ),
        pytest.param(
            WELL_FORMED.replace("# Acme\n\n", "# Acme\n\nIntro\n\n"),
            ["docs/product.md:3: text before `## Mission`"],
            id="text before Mission",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-3: Buyers", "- G-3 Buyers"),
            ["docs/product.md:16: not an item of the form `- G-<n>: <text>`: `- G-3 Buyers can track a widget`"],
            id="malformed item",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-3: Buyers can track a widget", "- G-3: Buyers can track\n  a widget"),
            ["docs/product.md:17: not an item of the form `- G-<n>: <text>`: `  a widget`"],
            id="wrapped item",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-3:", "- G-03:"),
            ["docs/product.md:16: not an item of the form"],
            id="leading zero",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-3:", "- G-0:"),
            ["docs/product.md:16: not an item of the form"],
            id="id from zero",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-3:", "- N-3:"),
            ["docs/product.md:16: `## Goals` holds G-n items; got N-3"],
            id="wrong prefix",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-3:", "- G-1:"),
            ["docs/product.md:16: G-1 again; it is already on docs/product.md:15"],
            id="duplicate id",
        ),
        pytest.param(
            WELL_FORMED.replace("- U-1: A widget buyer\n", ""),
            ["docs/product.md:9: `## Users` holds no item; it needs at least one"],
            id="empty users",
        ),
        pytest.param(
            WELL_FORMED.replace("- G-1: Widgets reach buyers in a day\n- G-3: Buyers can track a widget\n", ""),
            ["docs/product.md:13: `## Goals` holds no item; it needs at least one"],
            id="empty goals",
        ),
        pytest.param(
            WELL_FORMED.replace("- Q-1: Every widget is tested\n", ""),
            ["docs/product.md:20: `## Quality bar` holds no item; it needs at least one"],
            id="empty quality bar",
        ),
        pytest.param(
            WELL_FORMED.replace("Acme ships widgets.\n\nIt ships them fast.\n", ""),
            ["docs/product.md:3: `## Mission` holds no text"],
            id="empty mission",
        ),
    ],
)
def test_s024_1_check_exits_1_naming_the_file_line_and_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, expected: list[str]
) -> None:
    root = write(tmp_path, text)
    found = problems(root)
    assert len(found) == len(expected), found
    for line, prefix in zip(found, expected, strict=True):
        assert line.startswith(prefix), found
    assert run(root, "check") == 1
    assert capsys.readouterr().out.splitlines() == found


def test_s024_1_check_names_every_broken_rule_at_once(tmp_path: Path) -> None:
    text = WELL_FORMED.replace("- U-1:", "- G-1:").replace("- G-3:", "- G-1:")
    assert problems(write(tmp_path, text)) == [
        "docs/product.md:11: `## Users` holds U-n items; got G-1",
        "docs/product.md:16: G-1 again; it is already on docs/product.md:15",
    ]


def test_s024_1_a_missing_direction_fails_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, "check") == 1
    assert "docs/product.md:1: no such file" in capsys.readouterr().out


def test_s024_1_show_and_ids_refuse_a_broken_direction(tmp_path: Path) -> None:
    root = write(tmp_path, WELL_FORMED.replace("- G-3:", "- G-1:"))
    for action in ("show", "ids"):
        with pytest.raises(ReleaseError, match=r"docs/product.md:16: G-1 again"):
            run(root, action)


def test_s024_1_repo_may_follow_the_action(tmp_path: Path) -> None:
    root = write(tmp_path, WELL_FORMED.replace("- G-3:", "- G-1:"))
    assert main(["product", "check", "--repo", str(root)]) == 1


def test_s024_1_bad_cli_input_exits_2(tmp_path: Path) -> None:
    root = write(tmp_path, WELL_FORMED)
    for argv in (["show", "--section", "risks"], ["lint"], ["ids", "--json"]):
        with pytest.raises(SystemExit) as exc:
            run(root, *argv)
        assert exc.value.code == 2


def test_s024_2_show_json_prints_name_mission_and_items(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write(tmp_path, WELL_FORMED), "show", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {
        "name": "Acme",
        "mission": "Acme ships widgets.\n\nIt ships them fast.",
        "users": [{"id": "U-1", "text": "A widget buyer"}],
        "goals": [
            {"id": "G-1", "text": "Widgets reach buyers in a day", "measure": None},
            {"id": "G-3", "text": "Buyers can track a widget", "measure": None},
        ],
        "non_goals": [],
        "quality": [{"id": "Q-1", "text": "Every widget is tested"}],
    }


def test_s024_2_section_prints_only_that_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = write(tmp_path, WELL_FORMED)
    assert run(root, "show", "--section", "goals", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {
        "goals": [
            {"id": "G-1", "text": "Widgets reach buyers in a day", "measure": None},
            {"id": "G-3", "text": "Buyers can track a widget", "measure": None},
        ]
    }
    assert run(root, "show", "--section", "quality", "--section", "non-goals", "--json") == 0
    assert list(json.loads(capsys.readouterr().out)) == ["non_goals", "quality"]
    assert run(root, "show", "--section", "goals") == 0
    assert capsys.readouterr().out == (
        "## Goals\n\n- G-1: Widgets reach buyers in a day\n- G-3: Buyers can track a widget\n"
    )
    assert run(root, "show", "--section", "mission") == 0
    assert capsys.readouterr().out == "## Mission\n\nAcme ships widgets.\n\nIt ships them fast.\n"


def test_s024_2_show_as_text_round_trips_the_direction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write(tmp_path, WELL_FORMED), "show") == 0
    assert capsys.readouterr().out == WELL_FORMED


def test_s024_2_the_repos_own_direction_shows_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ROOT, "show", "--json") == 0
    record = json.loads(capsys.readouterr().out)
    assert record["name"] == "shipmill"
    assert list(record) == ["name", "mission", "users", "goals", "non_goals", "quality"]
    assert record["goals"][0]["id"] == "G-1"


MOVED = WELL_FORMED.replace(
    "- G-1: Widgets reach buyers in a day\n- G-3: Buyers can track a widget\n", "See [Goals](product/goals.md).\n"
)
GOALS = "## Goals\n\n- G-1: Widgets reach buyers in a day\n- G-3: Buyers can track a widget\n"


def moved(root: Path, goals: str | None = GOALS, text: str = MOVED) -> Path:
    write(root, text)
    if goals is not None:
        write(root, goals, Path("docs/product/goals.md"))
    return root


def test_s024_3_a_moved_section_is_read_by_check_show_and_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = moved(tmp_path)
    assert run(root, "check") == 0
    capsys.readouterr()
    assert run(root, "show", "--section", "goals", "--json") == 0
    assert [g["id"] for g in json.loads(capsys.readouterr().out)["goals"]] == ["G-1", "G-3"]
    assert run(root, "show") == 0
    assert capsys.readouterr().out == WELL_FORMED
    assert run(root, "ids") == 0
    assert "G-3: Buyers can track a widget" in capsys.readouterr().out.splitlines()


def test_s024_3_a_moved_mission_keeps_its_paragraphs(tmp_path: Path) -> None:
    text = WELL_FORMED.replace("Acme ships widgets.\n\nIt ships them fast.\n", "See [Mission](product/mission.md).\n")
    root = write(tmp_path, text)
    write(root, "## Mission\n\nAcme ships widgets.\n\nIt ships them fast.\n", Path("docs/product/mission.md"))
    assert read(root).mission == "Acme ships widgets.\n\nIt ships them fast."


@pytest.mark.parametrize(
    ("goals", "text", "expected"),
    [
        pytest.param(
            None,
            MOVED,
            "docs/product.md:15: `## Goals` moved to docs/product/goals.md, which doesn't exist",
            id="missing",
        ),
        pytest.param(
            GOALS.replace("## Goals", "## Non-goals"),
            MOVED,
            "docs/product/goals.md:1: a file `## Goals` moved to starts with it; got `## Non-goals`",
            id="different heading",
        ),
        pytest.param(
            "- G-1: x\n", MOVED, "docs/product/goals.md:1: a file `## Goals` moved to starts with it", id="no heading"
        ),
        pytest.param("", MOVED, "docs/product/goals.md:1: the file is empty", id="empty file"),
        pytest.param(
            GOALS + "\n## Non-goals\n",
            MOVED,
            "docs/product/goals.md:6: `## Non-goals`: a moved section's file holds only its own heading",
            id="second heading",
        ),
        pytest.param(
            GOALS.replace("- G-3:", "- Q-3:"),
            MOVED,
            "docs/product/goals.md:4: `## Goals` holds G-n items; got Q-3",
            id="wrong prefix in the moved file",
        ),
        pytest.param(
            "## Goals\n",
            MOVED,
            "docs/product/goals.md:1: `## Goals` holds no item; it needs at least one",
            id="empty moved section",
        ),
        pytest.param(
            GOALS,
            MOVED.replace("See [Goals](product/goals.md).\n", "See [Goals](product/goals.md).\n- G-4: more\n"),
            "docs/product.md:15: a moved section holds only its `See [...]` line",
            id="something beside the link",
        ),
        pytest.param(
            GOALS,
            MOVED.replace("(product/goals.md)", "(../goals.md)"),
            "docs/product.md:15: a moved section's line is `See [Goals](product/<file>.md).`",
            id="link outside docs/product",
        ),
        pytest.param(
            GOALS,
            MOVED.replace("See [Goals]", "See [Users]"),
            "docs/product.md:15: the link names `Users`; under `## Goals` it names it",
            id="link names another section",
        ),
        pytest.param(
            GOALS.replace("- G-3:", "- G-1:"),
            MOVED,
            "docs/product/goals.md:4: G-1 again; it is already on docs/product/goals.md:3",
            id="duplicate id in the moved file",
        ),
    ],
)
def test_s024_3_check_fails_a_broken_moved_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], goals: str | None, text: str, expected: str
) -> None:
    root = moved(tmp_path, goals, text)
    found = problems(root)
    assert len(found) == 1 and found[0].startswith(expected), found
    assert run(root, "check") == 1
    assert capsys.readouterr().out.splitlines() == found


def test_s024_3_a_moved_section_never_reads_a_file_out_of_docs_product(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A symlinked goals.md, or docs/product/ itself, pointing outside: refused, the target never quoted"""
    secret = tmp_path / "outside" / "goals.md"
    write(tmp_path / "outside", "TOKEN=secret\n", Path("goals.md"))
    root = moved(tmp_path / "repo", None)
    (root / "docs/product").mkdir()
    (root / "docs/product/goals.md").symlink_to(secret)
    assert problems(root) == [
        "docs/product.md:15: docs/product/goals.md is a symlink out of docs/product/; a moved section is a file there"
    ]
    assert run(root, "check") == 1
    assert "secret" not in capsys.readouterr().out
    (root / "docs/product/goals.md").unlink()
    (root / "docs/product").rmdir()
    (root / "docs/product").symlink_to(secret.parent)
    assert len(problems(root)) == 1 and "a symlink out of docs/product/" in problems(root)[0]


def test_s024_1_check_never_reads_a_direction_symlinked_out_of_the_repo(tmp_path: Path) -> None:
    write(tmp_path / "outside", WELL_FORMED, Path("product.md"))
    (tmp_path / "repo/docs").mkdir(parents=True)
    (tmp_path / "repo" / DIRECTION).symlink_to(tmp_path / "outside/product.md")
    assert problems(tmp_path / "repo") == [
        "docs/product.md:1: a symlink out of docs/; the direction is a file in the repo"
    ]


def test_s024_3_the_repos_own_direction_still_passes_with_a_section_moved(tmp_path: Path) -> None:
    """The real docs/product.md as a fixture, its Goals moved to their own file"""
    shutil.copy(ROOT / DIRECTION, write(tmp_path, "") / DIRECTION)
    lines = (tmp_path / DIRECTION).read_text(encoding="utf-8").splitlines(keepends=True)
    start = lines.index("## Goals\n")
    end = lines.index("## Non-goals\n")
    write(tmp_path, "".join(lines[start:end]), Path("docs/product/goals.md"))
    write(tmp_path, "".join([*lines[: start + 1], "\nSee [Goals](product/goals.md).\n\n", *lines[end:]]))
    assert check(tmp_path) == ()
    assert read(tmp_path) == read(ROOT)


def test_s024_4_ids_lists_every_id_with_its_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(moved(tmp_path), "ids") == 0
    assert capsys.readouterr().out.splitlines() == [
        "U-1: A widget buyer",
        "G-1: Widgets reach buyers in a day",
        "G-3: Buyers can track a widget",
        "Q-1: Every widget is tested",
    ]


def test_s024_4_ids_of_the_repos_own_direction(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(ROOT, "ids") == 0
    ids = [line.split(":", 1)[0] for line in capsys.readouterr().out.splitlines()]
    assert ids[0] == "U-1" and "G-7" in ids and "N-5" in ids and "Q-6" in ids
    assert len(ids) == len(set(ids))


def test_an_item_id_is_a_value_object() -> None:
    assert ItemId.parse("G-3") == ItemId(Prefix.GOAL, 3)
    assert str(ItemId(Prefix.QUALITY, 12)) == "Q-12"
    for bad in ("G3", "G-0", "X-1", "g-1", "G-01", " G-1"):
        with pytest.raises(ReleaseError, match="an item id is U-n, G-n, N-n, or Q-n"):
            ItemId.parse(bad)
    with pytest.raises(ReleaseError, match="starts at 1"):
        ItemId(Prefix.GOAL, 0)


def test_a_section_is_named_by_its_option() -> None:
    assert Section.named("non-goals") is Section.NON_GOALS
    with pytest.raises(ReleaseError, match="one of mission, users, goals, non-goals, quality"):
        Section.named("Goals")


def test_a_problem_reads_file_line_rule() -> None:
    assert str(Problem(DIRECTION, 4, "a rule")) == "docs/product.md:4: a rule"
