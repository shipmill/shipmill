"""#403, spec 024: REVIEW.md's structured sections are checked and merged without a model,
and its free sections pass through"""

import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.review import DEFAULT_CAP, Glob, Malformed, RuleId, check, parse, show

ROOT_REVIEW = """\
# Review

## Passes

Bugs first, then security, then compliance with the spec.

## Important

- I-1: A change to the release planner has a test for each lane it touches
- I-3: No network call in tests

## Nits

cap: 3

- Wording in comments

## Protected areas

- `src/shipmill/land.py`: it pushes tags and releases
"""

SKILLS_REVIEW = """\
## Important

- I-1: A skill's commands run as `shipmill <command>`
- I-2: A skill names the spec it implements

## Nits

cap: 2

## Protected areas

- `skills/github-pr-triage/scripts/pr_gate.py`: it merges
"""

CODE_REVIEW_ONLY = """\
Review this repo as a senior maintainer would.

# Guidance

## What to look for

- Correctness, then security
- Anything **odd**

```markdown
## Important

this is an example inside a fence, not a section
```

### Deeper heading

Whatever text.
"""


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _problems(text: str) -> list[str]:
    return [str(p) for p in parse(text, PurePosixPath("REVIEW.md"))[1]]


def test_s024_13_well_formed_with_free_sections_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "REVIEW.md", ROOT_REVIEW)
    _write(root, "skills/REVIEW.md", SKILLS_REVIEW)
    _write(root, "docs/REVIEW.md", CODE_REVIEW_ONLY)
    assert main(["--repo", str(root), "review", "check"]) == 0
    assert capsys.readouterr().out == ""


def test_s024_13_repo_without_review_md_passes(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "README.md", "# demo\n")
    assert check(root) == []
    assert main(["review", "check", "--repo", str(root)]) == 0


def test_s024_13_code_review_only_file_passes() -> None:
    assert _problems(CODE_REVIEW_ONLY) == []


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("## Important\n\n- A rule without an id\n", "REVIEW.md:3: an Important item is one line `- I-n: <rule>`"),
        ("## Important\n\n- I-0: zero\n", "REVIEW.md:3: an Important id is I-n with n from 1"),
        ("## Important\n\n- I-x: letters\n", "REVIEW.md:3: an Important id is I-n with n from 1"),
        ("## Important\n\nplain text\n", "REVIEW.md:3: an Important item is one line"),
        ("## Important\n\n- I-1: one\n- I-1: again\n", "REVIEW.md:4: I-1 is already used on line 3"),
        ("## Nits\n\ncap 3\n", "REVIEW.md:3: Nits holds `- <nit>` items and at most one `cap: N` line"),
        ("## Nits\n\ncap: -1\n", "REVIEW.md:3: the Nits cap is a whole number, as `cap: 5`; got '-1'"),
        ("## Nits\n\ncap: 3\ncap: 4\n", "REVIEW.md:4: a second `cap:` line; Nits holds at most one, on line 3"),
        ("## Nits\n\ncap: three\n", "REVIEW.md:3: the Nits cap is a whole number, as `cap: 5`; got 'three'"),
        ("## Nits\n\ncap: 3\nsome prose\n", "REVIEW.md:4: Nits holds `- <nit>` items and at most one `cap: N` line"),
        ("## Protected areas\n\n- src/land.py: no backticks\n", "REVIEW.md:3: a Protected areas item is one line"),
        ("## Protected areas\n\n- `src/land.py`\n", "REVIEW.md:3: a Protected areas item is one line"),
        ("## Protected areas\n\n- ``: empty\n", "REVIEW.md:3: a protected glob is a non-empty path pattern"),
        ("## Protected areas\n\n- `a`: one\n- `a`: two\n", "REVIEW.md:4: `a` is already listed on line 3"),
        ("## Important\n\n- I-1: one\n\n## Important\n\n- I-2: two\n", "REVIEW.md:5: a second ## Important section"),
    ],
)
def test_s024_13_malformed_line_names_file_line_and_rule(section: str, expected: str) -> None:
    problems = _problems(section)
    assert len(problems) == 1
    assert problems[0].startswith(expected)


def test_s024_13_check_exits_1_naming_subdirectory_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "REVIEW.md", ROOT_REVIEW)
    _write(root, "skills/REVIEW.md", "## Important\n\n- I-1: ok\n- I-1: reused\n\n## Nits\n\ncap: 2\ncap: 1\n")
    assert main(["--repo", str(root), "review", "check"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "skills/REVIEW.md:4: I-1 is already used on line 3; ids are unique",
        "skills/REVIEW.md:9: a second `cap:` line; Nits holds at most one, on line 8",
    ]


def test_check_skips_ignored_review_md(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, ".gitignore", "vendor/\n")
    _write(root, "vendor/REVIEW.md", "## Important\n\nbroken\n")
    assert check(root) == []


def test_s024_13_nits_without_cap_line_is_well_formed_and_caps_at_five() -> None:
    rubric, problems = parse("## Nits\n\n- Wording\n", PurePosixPath("REVIEW.md"))
    assert problems == ()
    assert rubric.cap is None
    assert rubric.to_json()["cap"] == DEFAULT_CAP == 5


def test_without_nits_section_the_cap_is_five() -> None:
    rubric, problems = parse("## Important\n\n- I-1: one\n", PurePosixPath("REVIEW.md"))
    assert problems == ()
    assert rubric.cap is None
    assert rubric.to_json()["cap"] == DEFAULT_CAP == 5


def test_s024_14_show_merges_root_and_directories_of_the_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "REVIEW.md", ROOT_REVIEW)
    _write(root, "skills/REVIEW.md", SKILLS_REVIEW)
    _write(root, "skills/github-pr-triage/REVIEW.md", "## Passes\n\nRead the gate twice.\n")
    _write(root, "src/REVIEW.md", "## Nits\n\ncap: 1\n")  # not on the paths below: left out
    path = "skills/github-pr-triage/scripts/pr_gate.py"
    assert main(["--repo", str(root), "review", "show", "--path", path, "--path", "README.md", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "important": [
            {
                "id": "I-1",
                "text": "A change to the release planner has a test for each lane it touches",
                "file": "REVIEW.md",
            },
            {"id": "I-3", "text": "No network call in tests", "file": "REVIEW.md"},
            {"id": "skills/I-1", "text": "A skill's commands run as `shipmill <command>`", "file": "skills/REVIEW.md"},
            {"id": "skills/I-2", "text": "A skill names the spec it implements", "file": "skills/REVIEW.md"},
        ],
        "cap": 2,
        "protected": [
            {"glob": "src/shipmill/land.py", "why": "it pushes tags and releases", "file": "REVIEW.md"},
            {"glob": "skills/github-pr-triage/scripts/pr_gate.py", "why": "it merges", "file": "skills/REVIEW.md"},
        ],
        "free": [
            {"heading": "Review", "text": "", "file": "REVIEW.md"},
            {
                "heading": "Passes",
                "text": "Bugs first, then security, then compliance with the spec.",
                "file": "REVIEW.md",
            },
            {"heading": "Passes", "text": "Read the gate twice.", "file": "skills/github-pr-triage/REVIEW.md"},
        ],
    }


def test_s024_14_show_without_paths_is_the_root_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "REVIEW.md", ROOT_REVIEW)
    _write(root, "skills/REVIEW.md", SKILLS_REVIEW)
    assert main(["review", "show", "--repo", str(root)]) == 0
    out = capsys.readouterr().out
    assert "- I-1: A change to the release planner" in out
    assert "cap: 3" in out
    assert "- `src/shipmill/land.py`: it pushes tags and releases (REVIEW.md)" in out
    assert "## Passes (REVIEW.md)" in out
    assert "skills/" not in out


def test_s024_14_show_free_text_before_first_heading(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "docs/REVIEW.md", CODE_REVIEW_ONLY)
    rubric = show(root, ["docs/guide.md"]).to_json()
    assert rubric["important"] == [] and rubric["protected"] == [] and rubric["cap"] == 5
    assert rubric["free"][0] == {
        "heading": None,
        "text": "Review this repo as a senior maintainer would.",
        "file": "docs/REVIEW.md",
    }
    passed = rubric["free"][2]["text"]
    assert "## Important" in passed and "### Deeper heading" in passed


def test_show_refuses_malformed_and_outside_paths(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    _write(root, "REVIEW.md", "## Nits\n\ncap: 2\ncap: 3\n")
    with pytest.raises(Malformed, match="REVIEW.md:4: a second `cap:` line"):
        show(root, [])
    _write(root, "REVIEW.md", ROOT_REVIEW)
    with pytest.raises(ReleaseError, match="relative to its root"):
        show(root, ["../elsewhere.py"])
    with pytest.raises(ReleaseError, match="outside the repository"):
        show(root, [str(tmp_path / "elsewhere.py")])


def test_value_objects_validate() -> None:
    assert str(RuleId.parse("I-12")) == "I-12"
    with pytest.raises(ReleaseError):
        RuleId.parse("I-01")
    with pytest.raises(ReleaseError):
        Glob("a`b")
