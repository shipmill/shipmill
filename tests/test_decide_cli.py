"""Spec 030: `shipmill decide levels` and `shipmill decide classify`"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill.classify import RepoPath
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.github import FileChange, GhCli, PullChange

from .conftest import POLICY, Repo

CONFIG = CONFIG_PATH.as_posix()
BASE = "b" * 40
HEAD = "h" * 40
FRAGMENTS = POLICY.replace("[changelog]\n", '[changelog]\nfragments = "changelog.d"\n')
LOG = """\
# Decisions

## D-1: Settings live in one file

- Decided: 2026-10-01, in o/demo#1
- Rule: every setting lives in .github/shipmill.toml
- Why: one place to read
- Applies to: .github/shipmill.toml, src/shipmill/config.py
- Enforced by: review

## D-2: The direction is the maintainer's

- Decided: 2026-10-02, in o/demo#2
- Rule: only the maintainer edits docs/product.md
- Why: others plan against it
- Applies to: docs/product.md, docs/product/
- Enforced by: review
- Superseded by: D-3

## D-3: The direction is the maintainer's, docs/product/ too

- Decided: 2026-10-03, in o/demo#3
- Rule: only the maintainer edits docs/product.md and docs/product/
- Why: others plan against it
- Applies to: docs/product.md, docs/product/
- Enforced by: review
- Supersedes: D-2
"""
REVIEW = """\
# Review

## Protected areas

- `src/release/**`: a release users install
"""


@dataclass
class FakePulls:
    """A pull request as GhCli.pull_change and text_at read it, with no network"""

    files: tuple[FileChange, ...] = ()
    texts: dict[tuple[str, str], str] = field(default_factory=dict)
    reads: list[tuple[str, str]] = field(default_factory=list)

    def pull_change(self, number: int) -> PullChange:
        return PullChange(number, BASE, HEAD, self.files)

    def text_at(self, sha: str, path: str) -> str:
        self.reads.append((sha, path))
        return self.texts[(sha, path)]


def commit(repo: Repo, config: str = POLICY, **files: str) -> None:
    """Commit the config and files on main, push, and point origin/HEAD at it"""
    repo.write(CONFIG, config)
    for path, text in files.items():
        repo.write(path, text)
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "--allow-empty", "-m", "base")
    repo.git.run("push", "-q", "origin", "main")
    repo.git.run("remote", "set-head", "origin", "main")


def run(repo: Repo, capsys: pytest.CaptureFixture[str], *args: str, pulls: FakePulls | None = None) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "decide", *args, "--json"], pulls=pulls or FakePulls()) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def zones_of(found: dict[str, Any]) -> dict[str, str]:
    return {z["zone"]: z["level"] for z in found["zones"]}


def patch(*added: str, removed: tuple[str, ...] = (), start: int = 1) -> str:
    lines = [f"@@ -{start},{len(removed)} +{start},{len(added)} @@", *(f"-{r}" for r in removed)]
    return "\n".join(lines + [f"+{a}" for a in added])


# -- levels -----------------------------------------------------------------------------------


def test_s030_5_levels_json_names_every_zone_with_its_level_floor_and_source(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    config = POLICY + (
        '\n[autonomy]\nrelease = "propose"\nrollback = "observe"\nupgrade = "act"\n'
        '\n[decisions]\nveto_hours = 48\ncontract-addition = "act"\ndirection = "ask"\n'
    )
    commit(repo, config)
    found = run(repo, capsys, "levels")
    assert found["veto_hours"] == 48
    rows = {r["zone"]: r for r in found["zones"]}
    assert list(rows) == [
        "direction", "decision-policy", "scope", "rule-departure", "contract-change", "contract-addition",
        "security", "protected", "interpretation", "triage-verdict", "implementation", "unknown",
        "release", "breaking-release", "deploy", "rollback", "intake", "upgrade",
    ]  # fmt: skip
    assert all(set(r) == {"zone", "level", "floor", "source"} for r in found["zones"])
    assert rows["direction"] == {"zone": "direction", "level": "ask", "floor": "ask", "source": "config"}
    assert rows["contract-addition"] == {"zone": "contract-addition", "level": "act", "floor": None, "source": "config"}
    assert rows["scope"] == {"zone": "scope", "level": "ask", "floor": "ask", "source": "default"}
    assert rows["security"]["floor"] == "notify"
    assert rows["decision-policy"] == {"zone": "decision-policy", "level": "never", "floor": "never", "source": "fixed"}
    assert rows["breaking-release"]["source"] == "fixed"
    assert rows["breaking-release"]["level"] == "ask"
    assert (rows["release"]["level"], rows["release"]["source"]) == ("ask", "autonomy")  # propose
    assert (rows["rollback"]["level"], rows["rollback"]["source"]) == (None, "autonomy")  # observe
    assert (rows["upgrade"]["level"], rows["upgrade"]["source"]) == ("act", "autonomy")  # act
    assert (rows["deploy"]["level"], rows["deploy"]["source"]) == ("act", "autonomy")  # D-7: unlisted acts
    assert (rows["intake"]["level"], rows["intake"]["source"]) == ("ask", "autonomy")  # propose by default


def test_s030_5_levels_read_the_working_tree_or_the_ref(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    repo.write(CONFIG, POLICY + '\n[decisions]\ntriage-verdict = "ask"\n')  # not committed
    tree = {r["zone"]: r for r in run(repo, capsys, "levels")["zones"]}
    assert (tree["triage-verdict"]["level"], tree["triage-verdict"]["source"]) == ("ask", "config")
    at_ref = {r["zone"]: r for r in run(repo, capsys, "levels", "--ref", "origin/HEAD")["zones"]}
    assert (at_ref["triage-verdict"]["level"], at_ref["triage-verdict"]["source"]) == ("notify", "default")
    assert run(repo, capsys, "levels")["veto_hours"] == 24


def test_s030_5_the_deploy_row_shows_its_most_held_back_environment(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    environments = (
        '\n[environments.staging]\nlane = "rc"\nworkflow = "deploy.yml"\n'
        '\n[environments.production]\nlane = "stable"\nworkflow = "deploy.yml"\n'
        '\n[autonomy.deploy]\nstaging = "act"\nproduction = "propose"\n'
    )
    commit(repo, POLICY + environments)
    rows = {r["zone"]: r for r in run(repo, capsys, "levels")["zones"]}
    assert rows["deploy"]["level"] == "ask"


def test_s030_5_levels_text_form(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    assert main(["--repo", str(repo.root), "decide", "levels"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "veto_hours: 24"
    assert out[1].split() == ["direction", "never", "floor", "ask", "default"]
    assert len(out) == 1 + 18


# -- classify --files -------------------------------------------------------------------------


def test_s030_6_classify_files_detects_direction_and_security_and_nothing_for_code(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    for path in ("docs/product.md", "docs/product/goals.md"):
        found = run(repo, capsys, "classify", "--files", path)
        assert zones_of(found) == {"direction": "never"}
        assert found["level"] == "never"
    found = run(repo, capsys, "classify", "--files", ".github/workflows/ci.yml")
    assert zones_of(found) == {"security": "ask"}
    assert found["level"] == "ask"
    found = run(repo, capsys, "classify", "--files", "src/x.py")
    assert found == {"level": None, "zones": [], "candidates": []}


def test_s030_6_the_strictest_level_wins_and_each_zone_has_its_reason(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    found = run(repo, capsys, "classify", "--files", "./.github/workflows/ci.yml", "docs/product.md")
    assert found["level"] == "never"
    assert [z["zone"] for z in found["zones"]] == ["direction", "security"]  # the zone table's order
    assert all(z["reason"] for z in found["zones"])


def test_s030_6_paths_alone_count_the_config_as_both_of_its_zones(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    assert zones_of(run(repo, capsys, "classify", "--files", CONFIG)) == {"decision-policy": "never", "security": "ask"}


def test_s030_6_classify_text_form(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    assert main(["--repo", str(repo.root), "decide", "classify", "--files", "src/x.py"]) == 0
    assert capsys.readouterr().out == "level: none, no zone detected\n"
    assert main(["--repo", str(repo.root), "decide", "classify", "--files", "docs/product.md"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "level: never"
    assert out[1].startswith("zone: direction at never: docs/product.md edits")


def test_s030_6_a_path_outside_the_repo_is_refused() -> None:
    for bad in ("/etc/passwd", "../x.py", "", "a//b"):
        with pytest.raises(ReleaseError):
            RepoPath.given(bad)


# -- classify --pr ----------------------------------------------------------------------------


def config_change(before: str, after: str) -> FakePulls:
    return FakePulls(
        (FileChange(CONFIG, "modified", patch("x")),),
        {(BASE, CONFIG): before, (HEAD, CONFIG): after},
    )


def test_s030_7_a_changed_key_under_decisions_is_decision_policy(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    pulls = config_change(POLICY, POLICY + '\n[decisions]\ntriage-verdict = "ask"\n')
    found = run(repo, capsys, "classify", "--pr", "7", pulls=pulls)
    assert zones_of(found) == {"decision-policy": "never"}
    assert found["level"] == "never"


def test_s030_7_another_section_of_the_config_is_security_and_not_decision_policy(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    decisions = '\n[decisions]\ntriage-verdict = "ask"\n'
    pulls = config_change(POLICY + decisions, POLICY.replace('name = "demo"', 'name = "other"') + decisions)
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=pulls)) == {"security": "ask"}


def test_s030_7_a_comment_in_decisions_is_neither(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    before = POLICY + '\n[decisions]\ntriage-verdict = "ask"\n'
    after = POLICY + '\n[decisions]\n# the maintainer wants to see each verdict\ntriage-verdict = "ask"  # for now\n'
    found = run(repo, capsys, "classify", "--pr", "7", pulls=config_change(before, after))
    assert found == {"level": None, "zones": [], "candidates": []}


def test_s030_7_an_added_or_unparseable_config_counts_as_both(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    added = FakePulls((FileChange(CONFIG, "added", patch("x")),), {(HEAD, CONFIG): POLICY + "\n[decisions]\n"})
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=added)) == {"security": "ask"}  # empty table
    broken = config_change(POLICY, POLICY + "\n[decisions\n")
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=broken)) == {
        "decision-policy": "never",
        "security": "ask",
    }


def test_s030_8_a_spec_whose_status_line_becomes_approved_is_scope(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    spec = "docs/specs/031-x.md"
    approved = FakePulls(
        (FileChange(spec, "modified", patch("status: approved", removed=("status: draft",), start=3)),)
    )
    found = run(repo, capsys, "classify", "--pr", "8", pulls=approved)
    assert zones_of(found) == {"scope": "ask"}
    assert found["zones"][0]["reason"] == f"{spec}'s status line becomes approved"
    new = FakePulls((FileChange(spec, "added", patch("# S-031: X", "", "status: approved")),))
    assert zones_of(run(repo, capsys, "classify", "--pr", "8", pulls=new)) == {"scope": "ask"}
    still = FakePulls((FileChange(spec, "modified", patch("status: approved", removed=("status: approved",))),))
    assert zones_of(run(repo, capsys, "classify", "--pr", "8", pulls=still)) == {}
    draft = FakePulls((FileChange(spec, "added", patch("status: draft")),))
    assert zones_of(run(repo, capsys, "classify", "--pr", "8", pulls=draft)) == {}


def test_s030_8_a_changelog_line_under_a_major_heading_is_contract_change(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    head = "# Changelog\n\n## [Unreleased]\n\n### Breaking\n\n- Drop --old (#9)\n\n### Added\n\n- A flag (#9)\n"
    breaking = FakePulls(
        (FileChange("CHANGELOG.md", "modified", patch("### Breaking", "", "- Drop --old (#9)", "", start=5)),),
        {(HEAD, "CHANGELOG.md"): head},
    )
    found = run(repo, capsys, "classify", "--pr", "9", pulls=breaking)
    assert zones_of(found) == {"contract-change": "ask"}
    assert found["zones"][0]["reason"] == "CHANGELOG.md:7 adds an entry under ### Breaking, a [bump] major heading"
    added = FakePulls(
        (FileChange("CHANGELOG.md", "modified", patch("- A flag (#9)", start=11)),),
        {(HEAD, "CHANGELOG.md"): head},
    )
    assert zones_of(run(repo, capsys, "classify", "--pr", "9", pulls=added)) == {}


def test_s030_8_a_fragment_under_a_major_heading_is_contract_change(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, FRAGMENTS)
    fragment = "changelog.d/9-drop-old.md"
    text = "### Breaking\n\n- Drop --old (#9)\n"
    pulls = FakePulls((FileChange(fragment, "added", patch(*text.splitlines())),), {(HEAD, fragment): text})
    assert zones_of(run(repo, capsys, "classify", "--pr", "9", pulls=pulls)) == {"contract-change": "ask"}
    minor = "### Added\n\n- A flag (#9)\n"
    pulls = FakePulls((FileChange(fragment, "added", patch(*minor.splitlines())),), {(HEAD, fragment): minor})
    assert zones_of(run(repo, capsys, "classify", "--pr", "9", pulls=pulls)) == {}


def test_s030_8_a_path_a_base_review_glob_covers_is_protected(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, **{"REVIEW.md": REVIEW, "skills/REVIEW.md": "## Protected areas\n\n- `scripts/*.py`: the gate\n"})
    pulls = FakePulls(
        (
            FileChange("src/release/land.py", "modified", patch("x")),
            FileChange("skills/scripts/gate.py", "modified", patch("x")),
            FileChange("src/other.py", "modified", patch("x")),
        )
    )
    found = run(repo, capsys, "classify", "--pr", "10", pulls=pulls)
    assert zones_of(found) == {"protected": "ask"}
    reason = found["zones"][0]["reason"]
    assert "src/release/land.py matches `src/release/**` (REVIEW.md): a release users install" in reason
    assert "skills/scripts/gate.py matches `scripts/*.py` (skills/REVIEW.md): the gate" in reason
    assert "src/other.py" not in reason


def test_s030_8_a_review_glob_only_the_pull_request_adds_protects_nothing(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    repo.write("REVIEW.md", REVIEW)  # in the working tree only, as a pull request's would be
    pulls = FakePulls((FileChange("src/release/land.py", "modified", patch("x")),))
    assert zones_of(run(repo, capsys, "classify", "--pr", "10", pulls=pulls)) == {}


def test_s030_9_the_levels_come_from_the_ref_never_from_the_change(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    relaxed = POLICY + '\n[decisions]\ndirection = "ask"\n'
    repo.write(CONFIG, relaxed)  # the pull request's checkout sets it
    pulls = FakePulls(
        (
            FileChange(CONFIG, "modified", patch('direction = "ask"')),
            FileChange("docs/product.md", "modified", patch("- G-9: more")),
        ),
        {(BASE, CONFIG): POLICY, (HEAD, CONFIG): relaxed},
    )
    found = run(repo, capsys, "classify", "--pr", "11", pulls=pulls)
    assert zones_of(found) == {"direction": "never", "decision-policy": "never"}
    assert zones_of(run(repo, capsys, "classify", "--files", "docs/product.md")) == {"direction": "never"}
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "-m", "relax")
    branch = repo.git.sha()
    # --ref names the base explicitly; at a ref that holds the relaxed config, it is what counts
    relaxed_base = run(repo, capsys, "classify", "--ref", branch, "--files", "docs/product.md")
    assert zones_of(relaxed_base) == {"direction": "ask"}
    assert zones_of(run(repo, capsys, "classify", "--files", "docs/product.md")) == {"direction": "never"}


def test_s030_9_a_ref_the_checkout_lacks_exits_2(repo: Repo) -> None:
    commit(repo)
    with pytest.raises(ReleaseError, match="nope is not in"):
        main(["--repo", str(repo.root), "decide", "classify", "--ref", "nope", "--files", "src/x.py"])


def test_s030_10_candidates_list_active_decisions_covering_a_changed_path_and_never_as_zones(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, **{"docs/decisions.md": LOG})
    pulls = FakePulls(
        (
            FileChange("src/shipmill/config.py", "modified", patch("x")),
            FileChange("docs/product/goals.md", "renamed", patch("x"), previous="docs/goals.md"),
        )
    )
    found = run(repo, capsys, "classify", "--pr", "12", pulls=pulls)
    assert found["candidates"] == [
        {"decision": "D-1", "title": "Settings live in one file"},
        {"decision": "D-3", "title": "The direction is the maintainer's, docs/product/ too"},
    ]  # D-2 is superseded
    assert zones_of(found) == {"direction": "never"}
    assert not any(z["zone"].startswith("D-") or z["zone"] == "rule-departure" for z in found["zones"])
    code = run(repo, capsys, "classify", "--pr", "12", pulls=FakePulls((FileChange("src/x.py", "modified", "x"),)))
    assert code == {"level": None, "zones": [], "candidates": []}


def test_s030_10_without_a_log_there_are_no_candidates(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    assert run(repo, capsys, "classify", "--files", CONFIG)["candidates"] == []


def test_s030_8_gh_reads_the_merge_base_the_head_and_every_file_with_its_patch(tmp_path: Path) -> None:
    """GhCli.pull_change and text_at, against a gh that answers from a script"""
    merge_base = "a" * 40
    pull = json.dumps({"head": {"sha": HEAD}, "base": {"sha": "t" * 40}})
    files = (
        json.dumps(
            {"filename": "docs/specs/031-x.md", "status": "modified", "patch": "@@ -3 +3 @@\n+status: approved"}
        ),
        json.dumps({"filename": "docs/product/goals.md", "status": "renamed", "previous_filename": "docs/goals.md"}),
    )
    script = tmp_path / "gh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{tmp_path / "args"}"\n'
        'case "$*" in\n'
        f"  *compare/*) echo {merge_base} ;;\n"
        f"  *pulls/5/files*) printf '%s\\n' '{files[0]}' '{files[1]}' ;;\n"
        f"  *pulls/5) echo '{pull}' ;;\n"
        "  *contents/*) printf 'status: approved\\n' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    hub = GhCli(tmp_path, gh=str(script))
    change = hub.pull_change(5)
    assert (change.number, change.base, change.head) == (5, merge_base, HEAD)
    assert change.files == (
        FileChange("docs/specs/031-x.md", "modified", "@@ -3 +3 @@\n+status: approved"),
        FileChange("docs/product/goals.md", "renamed", None, "docs/goals.md"),
    )
    assert change.files[1].paths == ("docs/product/goals.md", "docs/goals.md")
    assert hub.text_at(HEAD, "docs/specs/031 x.md") == "status: approved\n"
    calls = (tmp_path / "args").read_text(encoding="utf-8").splitlines()
    assert calls[1] == f"api repos/{{owner}}/{{repo}}/compare/{'t' * 40}...{HEAD} --jq .merge_base_commit.sha"
    assert calls[2] == "api --paginate repos/{owner}/{repo}/pulls/5/files?per_page=100 --jq .[]"
    assert calls[3].endswith(f"contents/docs/specs/031%20x.md?ref={HEAD}")


def test_s030_8_a_missing_diff_for_a_file_a_rule_reads_exits_2(repo: Repo) -> None:
    commit(repo)
    pulls = FakePulls((FileChange("docs/specs/031-x.md", "modified", None),))
    with pytest.raises(ReleaseError, match="no diff for docs/specs/031-x.md"):
        main(["--repo", str(repo.root), "decide", "classify", "--pr", "13"], pulls=pulls)
