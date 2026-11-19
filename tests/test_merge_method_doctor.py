"""Spec 072: doctor's merge row and its hooks lines (S-072-9, S-072-10), and the skills and docs
that name [agents] merge (S-072-11). The repo's merge settings come from FakeGitHub, never the
network"""

import re
from pathlib import Path

import pytest

from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, doctor
from shipmill.github import MergeMethods

from .conftest import FakeGitHub, Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/t"\n'
SETTINGS = "Settings > General > Pull Requests"


def configure(repo: Repo, merge: str | None) -> None:
    line = "" if merge is None else f'merge = "{merge}"\n'
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + AGENTS + line)


def merge_rows(repo: Repo, github: FakeGitHub | None) -> list[Check]:
    return [c for c in doctor(repo.root, github) if c.name == "merge"]


# -- S-072-9: the merge row -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("merge", "detail"),
    [
        (None, "squash (default, D-96)"),
        ("squash", "squash ([agents] merge)"),
        ("merge", "merge ([agents] merge)"),
    ],
)
def test_s072_9_the_row_names_the_method_and_where_it_comes_from(repo: Repo, merge: str | None, detail: str) -> None:
    configure(repo, merge)
    assert merge_rows(repo, repo.github) == [Check("PASS", "merge", detail)]


def test_s072_9_merge_where_merge_commits_are_off_warns_naming_the_repo_setting(repo: Repo) -> None:
    configure(repo, "merge")
    repo.github.allowed = MergeMethods(squash=True, merge=False)
    (row,) = merge_rows(repo, repo.github)
    assert row == Check(
        "WARN",
        "merge",
        f"merge ([agents] merge), but the repo doesn't allow merge commits (allow_merge_commit, {SETTINGS}),"
        ' so every merge is refused: allow them, or set [agents] merge = "squash" in .github/shipmill.toml (D-96)',
    )
    repo.github.allowed = MergeMethods(squash=False, merge=True)  # squash off doesn't touch "merge"
    assert merge_rows(repo, repo.github) == [Check("PASS", "merge", "merge ([agents] merge)")]


@pytest.mark.parametrize("merge", [None, "squash"])
def test_s072_9_squash_where_squash_merges_are_off_warns_naming_the_repo_setting(repo: Repo, merge: str | None) -> None:
    configure(repo, merge)
    repo.github.allowed = MergeMethods(squash=False, merge=True)
    (row,) = merge_rows(repo, repo.github)
    assert row.status == "WARN"
    assert "the repo doesn't allow squash merges (allow_squash_merge" in row.detail
    assert 'set [agents] merge = "merge"' in row.detail


@pytest.mark.parametrize("merge", [None, "squash"])
def test_s072_9_squash_where_merge_commits_are_off_warns_for_a_stacks_base(repo: Repo, merge: str | None) -> None:
    configure(repo, merge)
    repo.github.allowed = MergeMethods(squash=True, merge=False)
    (row,) = merge_rows(repo, repo.github)
    assert row.status == "WARN"
    assert "the repo doesn't allow merge commits (allow_merge_commit" in row.detail
    assert "a stack's base lands with a squash and its child is rebased" in row.detail
    repo.github.allowed = MergeMethods(squash=False, merge=False)  # both off: a WARN for each
    assert [c.status for c in merge_rows(repo, repo.github)] == ["WARN", "WARN"]


def test_s072_9_settings_that_cant_be_read_warn_and_never_guess(repo: Repo) -> None:
    configure(repo, "merge")
    repo.github.allowed_error = "HTTP 404: Not Found"
    assert merge_rows(repo, repo.github) == [
        Check(
            "WARN",
            "merge",
            "merge ([agents] merge); can't read the repo's merge settings: gh api -X GET failed: HTTP 404: Not Found",
        )
    ]
    assert merge_rows(repo, None) == [
        Check("WARN", "merge", "merge ([agents] merge); can't read the repo's merge settings: gh isn't installed")
    ]


def test_s072_9_a_repo_without_agents_gets_no_merge_row(repo: Repo) -> None:
    class Unasked(FakeGitHub):
        def merge_methods(self) -> MergeMethods:
            raise AssertionError("no read of the merge settings without [agents]")

    assert merge_rows(repo, Unasked()) == []


# -- S-072-10: the hooks block's merge lines -----------------------------------------------------


def hooks_lines(repo: Repo) -> dict[str, str]:
    rows = [c.detail for c in doctor(repo.root, repo.github) if c.name == "hooks"]
    return {rule: d for d in rows if (rule := d.split(" ", 1)[0]) in {"merge-method", "rebase-merge"}}


@pytest.mark.parametrize("merge", [None, "squash"])
def test_s072_10_under_squash_merge_method_is_on_and_refuses_none(repo: Repo, merge: str | None) -> None:
    configure(repo, merge)
    lines = hooks_lines(repo)
    source = "default" if merge is None else "[agents] merge"
    assert lines["merge-method"] == (
        f"merge-method on: always, [agents] merge is squash ({source}), so it refuses none:"
        " --squash lands a pull request, --merge a stack's base (D-96)"
    )
    assert lines["rebase-merge"].startswith("rebase-merge on: always") and lines["rebase-merge"].endswith("(D-96)")
    assert "(squash)" in lines["rebase-merge"]


def test_s072_10_under_merge_merge_method_refuses_squash(repo: Repo) -> None:
    configure(repo, "merge")
    lines = hooks_lines(repo)
    assert lines["merge-method"] == (
        'merge-method on: always, [agents] merge = "merge", so a squash merge (--squash, merge_method=squash)'
        " is refused (D-96)"
    )
    assert "(merge)" in lines["rebase-merge"] and "D-96" in lines["rebase-merge"]
    assert "D-33" not in " ".join(lines.values())


# -- S-072-11: the skills and docs ---------------------------------------------------------------

LANDING = ROOT / "skills" / "github-pr-triage" / "references" / "landing.md"
SKILL = ROOT / "skills" / "github-pr-triage" / "SKILL.md"
FLOW = ROOT / "docs" / "flow.md"
LANES = ROOT / "docs" / "release-lanes.md"


def merge_style() -> str:
    """landing.md's Merge style section"""
    text = LANDING.read_text(encoding="utf-8")
    found = re.search(r"^## Merge style\n(.*?)(?=^## )", text, re.M | re.S)
    assert found is not None, "landing.md has no Merge style section"
    return found.group(1)


def flow_landing() -> str:
    """docs/flow.md's How a pull request lands section"""
    text = FLOW.read_text(encoding="utf-8")
    found = re.search(r"^### How a pull request lands\n(.*?)(?=^##)", text, re.M | re.S)
    assert found is not None, "docs/flow.md has no How a pull request lands section"
    return found.group(1)


def test_s072_11_the_skills_and_docs_name_the_setting_and_d96_not_d33() -> None:
    for name, text in (
        ("landing.md", merge_style()),
        ("SKILL.md", SKILL.read_text(encoding="utf-8")),
        ("flow.md", flow_landing()),
        ("release-lanes.md", LANES.read_text(encoding="utf-8")),
    ):
        assert "[agents] merge" in text, name
        assert "D-96" in text, name
        assert "D-33" not in text, name
    assert "D-33" not in LANDING.read_text(encoding="utf-8")


def test_s072_11_landing_and_flow_say_a_merge_commit_brings_in_between_commits() -> None:
    for text in (merge_style(), flow_landing()):
        assert "in-between commits" in text
        assert '"fix lint"' in text


def test_s072_11_no_text_swaps_a_method_the_repo_doesnt_allow() -> None:
    """D-33's fallback is gone: no text tells a session to take a merge commit where squash
    merges are off, and a method the repo doesn't allow is reported"""
    for text in (merge_style(), SKILL.read_text(encoding="utf-8"), flow_landing()):
        assert "don't allow a squash merge, use a merge commit" not in text
        assert "allows only squash or rebase merges" not in text
        assert "never swapped" in text or "never falls back" in text
