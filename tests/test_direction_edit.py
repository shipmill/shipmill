"""#404, spec 024: agents edit the structured parts of docs/product.md and REVIEW.md only
through commands, which hand out ids the file's git history never held, write one line, and
leave every other line byte for byte as it was"""

import difflib
import subprocess
from pathlib import Path

import pytest

from shipmill import product, review
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.lineedit import Document, LineText

from .test_product import GOALS, MOVED, WELL_FORMED, write

DIRECTION = "docs/product.md"


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True
    )


def repo(root: Path, files: dict[str, str]) -> Path:
    """A git checkout whose first commit holds the files"""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    commit(root, files, "first")
    return root


def commit(root: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), *args])


def read(root: Path, name: str) -> bytes:
    return (root / name).read_bytes()


def diff(old: bytes, new: bytes) -> tuple[list[bytes], list[bytes]]:
    """The lines old had that new lacks, and those new adds, line endings included; every other
    line is the same bytes in the same order"""
    a, b = old.splitlines(keepends=True), new.splitlines(keepends=True)
    removed: list[bytes] = []
    added: list[bytes] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            removed += a[i1:i2]
            added += b[j1:j2]
    return removed, added


REVIEW = """\
# Review

## Passes

Bugs first.

## Important

- I-1: A change to the planner has a test per lane
- I-3: No network call in tests

## Nits

cap: 3

- Wording

## Protected areas

- `src/shipmill/land.py`: it pushes tags
"""


# S-024-15: the next id is one above any the file's history held


def test_s024_15_product_add_skips_an_id_retired_in_an_earlier_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, {DIRECTION: WELL_FORMED.replace("- G-3: Buyers can track a widget\n", "")})
    commit(root, {DIRECTION: WELL_FORMED}, "add G-3")
    commit(root, {DIRECTION: WELL_FORMED.replace("- G-3: Buyers can track a widget\n", "")}, "retire G-3")
    assert [str(i.id) for i in product.read(root).goals] == ["G-1"]
    assert run(root, "product", "add", "goals", "Widgets ship worldwide") == 0
    assert capsys.readouterr().out == "- G-4: Widgets ship worldwide\n"
    assert "- G-1: Widgets reach buyers in a day\n- G-4: Widgets ship worldwide\n" in (root / DIRECTION).read_text()
    assert product.check(root) == ()


def test_s024_15_product_add_reads_the_history_of_a_moved_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, {DIRECTION: MOVED, "docs/product/goals.md": GOALS + "- G-7: Retired later\n"})
    commit(root, {"docs/product/goals.md": GOALS}, "retire G-7")
    assert run(root, "product", "add", "goals", "A new goal") == 0
    assert capsys.readouterr().out == "- G-8: A new goal\n"


def test_s024_15_each_prefix_counts_its_own_ids_and_a_repo_without_commits_counts_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write(tmp_path, WELL_FORMED)
    git(root, "init", "-q", "-b", "main")
    for section, line in (
        ("users", "- U-2: x"),
        ("goals", "- G-4: x"),
        ("non-goals", "- N-1: x"),
        ("quality", "- Q-2: x"),
    ):
        assert run(root, "product", "add", section, "x") == 0
        assert capsys.readouterr().out == f"{line}\n"
    assert product.check(root) == ()


def test_s024_15_review_add_rule_skips_an_id_retired_in_an_earlier_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, {"REVIEW.md": REVIEW.replace("- I-3: No network call in tests\n", "- I-5: Gone\n")})
    commit(root, {"REVIEW.md": REVIEW}, "retire I-5, add I-3")
    assert run(root, "review", "add-rule", "Every script stays Python 3.10") == 0
    assert capsys.readouterr().out == "- I-6: Every script stays Python 3.10\n"
    assert (
        "- I-3: No network call in tests\n- I-6: Every script stays Python 3.10\n" in (root / "REVIEW.md").read_text()
    )
    assert review.check(root) == []


def test_s024_15_a_subdirectory_review_counts_only_its_own_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, {"REVIEW.md": REVIEW, "skills/REVIEW.md": "## Important\n\n- I-2: A skill names its spec\n"})
    commit(root, {"skills/REVIEW.md": "## Important\n\n- I-1: A skill's commands run as shipmill\n"}, "rewrite")
    assert run(root, "review", "add-rule", "--dir", "skills", "Scripts have no dependencies") == 0
    assert capsys.readouterr().out == "- I-3: Scripts have no dependencies\n"


# S-024-16: other lines unchanged, a missing section in its fixed place, a moved section's file,
# and exit 2 without writing on a file check refuses


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("final", [True, False], ids=["final newline", "no final newline"])
def test_s024_16_product_edits_leave_every_other_line_byte_for_byte(tmp_path: Path, eol: str, final: bool) -> None:
    text = WELL_FORMED.replace("\n", eol)
    if not final:
        text = text.removesuffix(eol)
    root = repo(tmp_path, {DIRECTION: text})
    end = eol.encode()
    before = read(root, DIRECTION)
    product.add(root, product.Section.USERS, LineText("A widget seller"))
    assert diff(before, before := read(root, DIRECTION)) == ([], [b"- U-2: A widget seller" + end])
    product.add(root, product.Section.QUALITY, LineText("Every widget is boxed"))  # after the file's last line
    after = read(root, DIRECTION)
    q1, q2 = b"- Q-1: Every widget is tested", b"- Q-2: Every widget is boxed"
    if final:
        assert diff(before, after) == ([], [q2 + end])
    else:  # the old last line gains the line ending it lacked, and the new last line goes without
        assert diff(before, after) == ([q1], [q1 + end, q2])
    assert after.endswith(end) is final
    before = after
    product.edit(root, product.ItemId.parse("G-3"), LineText("Buyers can track every widget"))
    assert diff(before, before := read(root, DIRECTION)) == (
        [b"- G-3: Buyers can track a widget" + end],
        [b"- G-3: Buyers can track every widget" + end],
    )
    product.retire(root, product.ItemId.parse("U-2"))
    assert diff(before, read(root, DIRECTION)) == ([b"- U-2: A widget seller" + end], [])
    assert product.check(root) == ()


def test_s024_16_product_add_writes_into_an_empty_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = repo(tmp_path, {DIRECTION: WELL_FORMED})
    assert run(root, "product", "add", "non-goals", "Widgets for pets") == 0
    assert capsys.readouterr().out == "- N-1: Widgets for pets\n"
    assert (root / DIRECTION).read_text() == WELL_FORMED.replace(
        "## Non-goals\n\n", "## Non-goals\n\n- N-1: Widgets for pets\n\n"
    )
    assert product.check(root) == ()


def test_s024_16_product_edits_change_the_file_a_moved_section_points_to(tmp_path: Path) -> None:
    root = repo(tmp_path, {DIRECTION: MOVED, "docs/product/goals.md": GOALS})
    edited = product.add(root, product.Section.GOALS, LineText("Widgets ship worldwide"))
    assert (edited.path, edited.line) == (Path("docs/product/goals.md"), 5)
    assert read(root, DIRECTION) == MOVED.encode()
    assert (root / "docs/product/goals.md").read_text() == GOALS + "- G-4: Widgets ship worldwide\n"
    product.edit(root, product.ItemId.parse("G-1"), LineText("Widgets reach buyers in an hour"))
    product.retire(root, product.ItemId.parse("G-3"))
    assert (root / "docs/product/goals.md").read_text() == (
        "## Goals\n\n- G-1: Widgets reach buyers in an hour\n- G-4: Widgets ship worldwide\n"
    )
    assert read(root, DIRECTION) == MOVED.encode()
    assert product.check(root) == ()


@pytest.mark.parametrize(
    "argv",
    [
        ["product", "add", "goals", "x"],
        ["product", "edit", "G-1", "x"],
        ["product", "retire", "G-1"],
    ],
)
def test_s024_16_product_edits_exit_2_without_writing_on_a_direction_check_refuses(
    tmp_path: Path, argv: list[str]
) -> None:
    broken = WELL_FORMED.replace("- G-3:", "- G-1:")
    root = repo(tmp_path, {DIRECTION: broken})
    with pytest.raises(ReleaseError, match=r"doesn't pass `.*product check`, so nothing was written(.|\n)*G-1 again"):
        run(root, *argv)
    assert read(root, DIRECTION) == broken.encode()


@pytest.mark.parametrize(
    "argv",
    [
        ["review", "add-rule", "x"],
        ["review", "protect", "docs/**", "--why", "x"],
        ["review", "set-cap", "2"],
        ["review", "retire", "I-1"],
    ],
)
def test_s024_16_review_edits_exit_2_without_writing_on_a_file_check_refuses(tmp_path: Path, argv: list[str]) -> None:
    broken = REVIEW.replace("cap: 3\n", "cap: 3\ncap: 4\n")
    root = repo(tmp_path, {"REVIEW.md": broken})
    with pytest.raises(ReleaseError, match=r"REVIEW.md doesn't pass `.*review check`, so nothing was written"):
        run(root, *argv)
    assert read(root, "REVIEW.md") == broken.encode()


def test_s024_16_review_edits_leave_every_other_line_byte_for_byte(tmp_path: Path) -> None:
    text = REVIEW.replace("\n", "\r\n")
    root = repo(tmp_path, {"REVIEW.md": text})
    file = review.review_file(root, None)
    before = read(root, "REVIEW.md")
    assert review.add_rule(root, file, LineText("Rule")).text == "- I-4: Rule"
    assert diff(before, before := read(root, "REVIEW.md")) == ([], [b"- I-4: Rule\r\n"])
    review.protect(root, file, review.Glob("skills/**"), LineText("agents run them"))
    assert diff(before, before := read(root, "REVIEW.md")) == ([], [b"- `skills/**`: agents run them\r\n"])
    review.set_cap(root, file, 1)
    assert diff(before, before := read(root, "REVIEW.md")) == ([b"cap: 3\r\n"], [b"cap: 1\r\n"])
    assert review.retire(root, file, "I-1").text == "- I-1: A change to the planner has a test per lane"
    assert diff(before, before := read(root, "REVIEW.md")) == (
        [b"- I-1: A change to the planner has a test per lane\r\n"],
        [],
    )
    review.retire(root, file, "src/shipmill/land.py")
    assert diff(before, read(root, "REVIEW.md")) == ([b"- `src/shipmill/land.py`: it pushes tags\r\n"], [])
    assert review.check(root) == []


@pytest.mark.parametrize(
    ("text", "argv", "expected"),
    [
        pytest.param(
            REVIEW.replace("## Nits\n\ncap: 3\n\n- Wording\n\n", ""),
            ["set-cap", "2"],
            REVIEW.replace("## Nits\n\ncap: 3\n\n- Wording\n\n", "## Nits\n\ncap: 2\n\n"),
            id="Nits between Important and Protected areas",
        ),
        pytest.param(
            REVIEW.replace(
                "## Important\n\n- I-1: A change to the planner has a test per lane\n"
                "- I-3: No network call in tests\n\n",
                "",
            ),
            ["add-rule", "Rule"],
            REVIEW.replace(
                "## Important\n\n- I-1: A change to the planner has a test per lane\n"
                "- I-3: No network call in tests\n\n",
                "## Important\n\n- I-1: Rule\n\n",
            ),
            id="Important before Nits",
        ),
        pytest.param(
            REVIEW.replace("\n## Protected areas\n\n- `src/shipmill/land.py`: it pushes tags\n", ""),
            ["protect", "docs/**", "--why", "the docs"],
            REVIEW.replace("- `src/shipmill/land.py`: it pushes tags", "- `docs/**`: the docs"),
            id="Protected areas after Nits, at the end",
        ),
        pytest.param(
            "# Review\n\n## Passes\n\nBugs first.\n",
            ["protect", "docs/**", "--why", "the docs"],
            "# Review\n\n## Passes\n\nBugs first.\n\n## Protected areas\n\n- `docs/**`: the docs\n",
            id="no structured section: at the end",
        ),
        pytest.param(
            "## Important\n\n- I-1: x\n\n## Free\n\ntext\n",
            ["set-cap", "4"],
            "## Important\n\n- I-1: x\n\n## Nits\n\ncap: 4\n\n## Free\n\ntext\n",
            id="right after the earlier section, before a free one",
        ),
        pytest.param(
            REVIEW.replace("cap: 3\n\n", ""),
            ["set-cap", "2"],
            REVIEW.replace("cap: 3\n", "cap: 2\n"),
            id="a cap line at the top of Nits",
        ),
        pytest.param(
            REVIEW.replace("- `src/shipmill/land.py`: it pushes tags\n", ""),
            ["protect", "docs/**", "--why", "the docs"],
            REVIEW.replace("- `src/shipmill/land.py`: it pushes tags", "- `docs/**`: the docs"),
            id="into an empty section",
        ),
    ],
)
def test_s024_16_review_edits_write_a_missing_section_in_its_fixed_place(
    tmp_path: Path, text: str, argv: list[str], expected: str
) -> None:
    root = repo(tmp_path, {"REVIEW.md": text})
    assert run(root, "review", *argv) == 0
    assert (root / "REVIEW.md").read_text() == expected
    assert review.check(root) == []


def test_s024_16_review_without_a_file_creates_it_holding_only_the_section(tmp_path: Path) -> None:
    root = repo(tmp_path, {"skills/x.md": "x\n"})
    assert run(root, "review", "add-rule", "Rule") == 0
    assert (root / "REVIEW.md").read_text() == "## Important\n\n- I-1: Rule\n"
    with pytest.raises(ReleaseError, match="no skills/REVIEW.md"):
        run(root, "review", "retire", "--dir", "skills", "I-1")
    assert not (root / "skills/REVIEW.md").exists()


def test_s024_16_unknown_items_and_bad_text_exit_2_without_writing(tmp_path: Path) -> None:
    root = repo(tmp_path, {DIRECTION: WELL_FORMED, "REVIEW.md": REVIEW})
    for argv, message in (
        (["product", "edit", "G-2", "x"], "no G-2 in docs/product.md"),
        (["product", "retire", "U-1"], "U-1 is the only item of `## Users`"),
        (["product", "add", "goals", " padded"], "the text is one line"),
        (["product", "add", "goals", "two\nlines"], "the text is one line"),
        (["product", "edit", "X-1", "x"], "an item id is U-n, G-n, N-n, or Q-n"),
        (["review", "retire", "I-2"], "no I-2 in REVIEW.md's Important"),
        (["review", "retire", "docs/**"], "no docs/\\*\\* in REVIEW.md's Protected areas"),
        (["review", "protect", "a`b", "--why", "x"], "a protected glob is"),
        (["review", "set-cap", "-1"], "a whole number from 0"),
        (["review", "add-rule", "--dir", "../x", "x"], "--dir is a directory in the repository"),
        (["review", "add-rule", "--dir", "nowhere", "x"], "--dir nowhere: no such directory"),
    ):
        with pytest.raises(ReleaseError, match=message):
            run(root, *argv)
    assert read(root, DIRECTION) == WELL_FORMED.encode()
    assert read(root, "REVIEW.md") == REVIEW.encode()
    with pytest.raises(SystemExit) as exc:
        run(root, "product", "add", "mission", "x")
    assert exc.value.code == 2


# S-024-17: protect refuses a listed glob; --dir creates a REVIEW.md with only the touched section


def test_s024_17_protect_refuses_a_glob_already_listed(tmp_path: Path) -> None:
    root = repo(tmp_path, {"REVIEW.md": REVIEW})
    with pytest.raises(ReleaseError, match=r"`src/shipmill/land\.py` is already in REVIEW\.md's Protected areas"):
        run(root, "review", "protect", "src/shipmill/land.py", "--why", "again")
    assert read(root, "REVIEW.md") == REVIEW.encode()


def test_s024_17_dir_creates_a_subdirectory_review_holding_only_the_touched_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, {"REVIEW.md": REVIEW, "skills/x.md": "x\n"})
    assert run(root, "review", "protect", "--dir", "skills", "github-pr-triage/**", "--why", "it merges") == 0
    assert capsys.readouterr().out == "- `github-pr-triage/**`: it merges\n"
    assert (root / "skills/REVIEW.md").read_text() == "## Protected areas\n\n- `github-pr-triage/**`: it merges\n"
    assert read(root, "REVIEW.md") == REVIEW.encode()
    with pytest.raises(ReleaseError, match="already in skills/REVIEW.md's Protected areas"):
        run(root, "review", "protect", "--dir", "skills", "github-pr-triage/**", "--why", "again")
    other = repo(tmp_path / "other", {"src/x.py": ""})
    assert run(other, "review", "set-cap", "--dir", "src", "2") == 0
    assert (other / "src/REVIEW.md").read_text() == "## Nits\n\ncap: 2\n"
    assert review.check(root) == [] and review.check(other) == []


def test_s024_15_a_shallow_clone_is_refused_rather_than_reusing_a_retired_id(tmp_path: Path) -> None:
    origin = repo(tmp_path / "origin", {"REVIEW.md": "## Important\n\n- I-1: a\n- I-2: b\n"})
    commit(origin, {"REVIEW.md": "## Important\n\n- I-1: a\n"}, "retire I-2")
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow))
    before = read(shallow, "REVIEW.md")
    with pytest.raises(ReleaseError, match="shallow clone"):
        run(shallow, "review", "add-rule", "new")
    assert read(shallow, "REVIEW.md") == before


def test_s024_16_protect_refuses_a_glob_spanning_lines(tmp_path: Path) -> None:
    root = repo(tmp_path, {"REVIEW.md": REVIEW})
    with pytest.raises(ReleaseError, match="path pattern on one line"):
        run(root, "review", "protect", "docs\n## Important\n- I-x", "--why", "w")
    assert read(root, "REVIEW.md") == REVIEW.encode()


def test_s024_17_a_review_symlinked_out_of_the_repo_is_never_written_through(tmp_path: Path) -> None:
    root = repo(tmp_path / "repo", {"skills/x.md": "x\n"})
    outside = tmp_path / "outside.md"
    (root / "REVIEW.md").symlink_to(outside)  # dangling: the target doesn't exist yet
    with pytest.raises(ReleaseError, match="outside the repository"):
        run(root, "review", "add-rule", "x")
    assert not outside.exists()


def test_line_text_and_documents_refuse_what_they_cannot_write(tmp_path: Path) -> None:
    for bad in ("", " x", "x ", "a\nb", "a\rb"):
        with pytest.raises(ReleaseError, match="the text is one line"):
            LineText(bad)
    path = tmp_path / "f.md"
    path.write_bytes(b"\xff\n")
    with pytest.raises(ReleaseError, match="not UTF-8 text"):
        Document.read(path)
