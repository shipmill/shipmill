"""Spec 025: `shipmill evals check` validates the eval suite without a model"""

import os
import re
import subprocess
from pathlib import Path

import pytest

from shipmill import evals
from shipmill.cli import main
from shipmill.errors import ReleaseError

ROOT = Path(__file__).resolve().parents[1]
SKILL = "github-issue-triage"
CASE = f"{SKILL}/feature-maintainer-filed"

PROMPT = f"""---
name: feature-maintainer-filed
tags: [{SKILL}, smoke]
runs: 3
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill]
---

Triage shipmill/shipmill#380.
"""

CASE_YAML = """schema_version: "1.1"
name: feature-maintainer-filed
context:
  scaffold_script: scaffold.sh
graders:
  - name: verdict
    type: regex
    pattern: 'Triage: \\*\\*feature\\*\\*\\.'  # the verdict's first line
    target: {source: file, path: .eval/gh.jsonl}
  - name: substance
    type: llm
    criteria: |
      PASS if the comment names the maintainer as the filer.
      FAIL otherwise.
"""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _manifest(commit: str, **fields: str) -> str:
    values = {"path": CASE, "skill": SKILL, "kind": "verdict", "source": "shipmill/shipmill#380", "commit": commit}
    values |= fields
    return "[[case]]\n" + "".join(f'{k} = "{v}"\n' for k, v in values.items())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit, a skill, and a well-formed one-case suite"""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, f"skills/{SKILL}/SKILL.md", "---\nname: triage\n---\n")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    _write(root, f"evals/{CASE}/prompt.md", PROMPT)
    _write(root, f"evals/{CASE}/case.yaml", CASE_YAML)
    _write(root, "evals/cases.toml", _manifest(_sha(root)))
    return root


def _sha(root: Path) -> str:
    return _git(root, "rev-parse", "--short", "HEAD").strip()


def _check(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    code = main(["evals", "check", "--repo", str(root)])
    return code, capsys.readouterr().out.splitlines()


def _fails(root: Path, capsys: pytest.CaptureFixture[str], rule: str) -> None:
    code, lines = _check(root, capsys)
    assert code == 1
    assert len(lines) == 1, lines
    assert lines[0].startswith(f"evals/{CASE}: "), lines
    assert re.search(rule, lines[0]), lines[0]


def test_s025_1_well_formed_suite_exits_0(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _check(repo, capsys) == (0, ["evals/cases.toml: well formed, 1 cases"])


def test_s025_1_graders_in_files_and_block_lists_are_read(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # the runner's other layout: tags as a block list, graders as graders/*.md, no case.yaml
    (repo / f"evals/{CASE}/case.yaml").unlink()
    _write(repo, f"evals/{CASE}/prompt.md", f"---\ntags:\n  - {SKILL}\n---\n\nTriage it.\n")
    _write(repo, f"evals/{CASE}/graders/fired.md", "---\ntype: tool_used\ntool: Skill\nmin: 1\n---\n")
    assert _check(repo, capsys)[0] == 0


def test_s025_1_no_evals_directory_is_an_empty_suite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _check(tmp_path, capsys) == (0, ["no case under evals/: nothing to check"])


def _shared_tools(root: Path) -> None:
    """evals/ as the gh stub's build leaves it (S-025-3 to S-025-6): tools, no case yet"""
    _write(root, "evals/bin/gh", "#!/usr/bin/env python3\n")
    _write(root, "evals/graders/no-miss.yaml", "name: no-miss\ntype: regex\n")
    _write(root, "evals/scaffold.sh", "#!/bin/sh\n")


def test_s025_1_shared_tools_without_cases_are_an_empty_suite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _shared_tools(tmp_path)
    assert _check(tmp_path, capsys) == (0, ["no case under evals/: nothing to check"])


def test_s025_1_a_case_without_the_manifest_still_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _shared_tools(tmp_path)
    _write(tmp_path, f"evals/{CASE}/prompt.md", PROMPT)
    code, lines = _check(tmp_path, capsys)
    assert code == 1
    assert lines == [
        "evals/cases.toml: missing; it lists every case under evals/",
        f"evals/{CASE}: a case directory not listed in evals/cases.toml",
    ]


def test_s025_1_a_graders_directory_is_never_a_case(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _shared_tools(repo)
    _write(repo, "evals/graders/shared/prompt.md", PROMPT)
    _write(repo, f"evals/{SKILL}/graders/shared/prompt.md", PROMPT)
    assert _check(repo, capsys)[0] == 0


def test_s025_1_case_directory_missing_from_manifest(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{SKILL}/unlisted/prompt.md", PROMPT)
    code, lines = _check(repo, capsys)
    assert code == 1
    assert lines == [f"evals/{SKILL}/unlisted: a case directory not listed in evals/cases.toml"]


def test_s025_1_manifest_entry_without_directory(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = (repo / "evals/cases.toml").read_text() + _manifest(_sha(repo), path=f"{SKILL}/gone")
    _write(repo, "evals/cases.toml", text)
    code, lines = _check(repo, capsys)
    assert code == 1
    assert lines == [
        f"evals/{SKILL}/gone: listed in evals/cases.toml, but no directory there holds a prompt.md or a case.yaml"
    ]


def test_s025_1_skill_not_under_skills(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), skill="no-such-skill"))
    code, lines = _check(repo, capsys)
    assert code == 1
    # the tags then don't name it either: each rule a line
    assert lines == [
        f"evals/{CASE}: skill 'no-such-skill' is not a directory under skills/",
        f"evals/{CASE}: tags ['{SKILL}', 'smoke'] do not name the skill 'no-such-skill'",
    ]


def test_s025_1_tags_not_naming_the_skill(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{CASE}/prompt.md", PROMPT.replace(f"[{SKILL}, smoke]", "[smoke]"))
    _fails(repo, capsys, rf"tags \['smoke'\] do not name the skill '{SKILL}'")


def test_s025_1_tags_from_case_yaml_when_prompt_has_none(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{CASE}/prompt.md", PROMPT.replace(f"tags: [{SKILL}, smoke]\n", ""))
    _write(repo, f"evals/{CASE}/case.yaml", CASE_YAML.replace("context:", f"tags: [{SKILL}]\ncontext:"))
    assert _check(repo, capsys)[0] == 0


@pytest.mark.parametrize("source", ["shipmill#380", "shipmill/shipmill#0", "docs/specs/025-agent-evals.md", "#380"])
def test_s025_1_malformed_source(repo: Path, capsys: pytest.CaptureFixture[str], source: str) -> None:
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), source=source))
    _fails(repo, capsys, rf"source '{re.escape(source)}' is neither owner/repo#N nor the path of a file")


def test_s025_1_postmortem_source(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, "docs/postmortems/2026-10-01-merge.md", "# Postmortem\n")
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), source="docs/postmortems/2026-10-01-merge.md"))
    assert _check(repo, capsys)[0] == 0
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), source="docs/postmortems/missing.md"))
    _fails(repo, capsys, "source 'docs/postmortems/missing.md' is neither")


def test_s025_1_unknown_kind(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), kind="opinion"))
    _fails(repo, capsys, "kind 'opinion' is not one of verdict, decision, finding, fix")


@pytest.mark.parametrize("commit", ["0123abc", "deadbeef" * 5, "main", "HEAD"])  # a branch moves: a sha only
def test_s025_1_commit_that_does_not_resolve(repo: Path, capsys: pytest.CaptureFixture[str], commit: str) -> None:
    _write(repo, "evals/cases.toml", _manifest(commit))
    _fails(repo, capsys, rf"commit '{commit}' does not resolve to a commit in this repository")


def test_s025_1_no_deterministic_grader(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    only_llm = (
        CASE_YAML.split("  - name: verdict")[0] + "  - name: substance" + CASE_YAML.split("  - name: substance")[1]
    )
    _write(repo, f"evals/{CASE}/case.yaml", only_llm)
    _fails(repo, capsys, r"no deterministic grader \(file_exists, regex, tool_order, tool_used\)")
    for kind in ("decision", "fix"):
        _write(repo, "evals/cases.toml", _manifest(_sha(repo), kind=kind))
        _fails(repo, capsys, "no deterministic grader")
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), kind="finding"))  # a judge alone may grade a finding
    assert _check(repo, capsys)[0] == 0


def test_s025_1_no_grader_at_all(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / f"evals/{CASE}/case.yaml").unlink()
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), kind="finding"))
    _fails(repo, capsys, r"no grader, in graders/\*\.md or in case\.yaml")


def test_s025_1_max_turns_above_40(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{CASE}/prompt.md", PROMPT.replace("max_turns: 40", "max_turns: 41"))
    _fails(repo, capsys, "max_turns is 41, above the ceiling of 40")


def test_s025_1_timeout_seconds_above_900(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{CASE}/prompt.md", PROMPT.replace("timeout_seconds: 900", "timeout_seconds: 901"))
    _fails(repo, capsys, "timeout_seconds is 901, above the ceiling of 900")


def test_s025_1_limits_from_case_yaml_execution(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{CASE}/prompt.md", PROMPT.replace("max_turns: 40\n", ""))
    _write(repo, f"evals/{CASE}/case.yaml", CASE_YAML + "execution:\n  max_turns: 200\n")
    _fails(repo, capsys, "max_turns is 200, above the ceiling of 40")


def test_s025_1_without_limits_the_runner_defaults_pass(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = PROMPT.replace("max_turns: 40\n", "").replace("timeout_seconds: 900\n", "")
    _write(repo, f"evals/{CASE}/prompt.md", text)
    assert _check(repo, capsys)[0] == 0


@pytest.mark.parametrize(
    ("file", "text", "rule"),
    [
        ("prompt.md", "---\nmax_turns: many\n---\n", "max_turns is a whole number from 1; got 'many'"),
        ("prompt.md", "---\ntags: [a\n---\n", r"prompt\.md: line 1: a flow list closes with \]"),
        ("prompt.md", "---\nname: x\n", "prompt.md: the frontmatter has no closing ---"),
        ("prompt.md", "---\njust text\n---\n", "prompt.md: line 1: not a `key: value` line"),
        ("prompt.md", "---\nname: a\nname: b\n---\n", "prompt.md: line 2: name is set twice"),
        ("case.yaml", "graders:\n  - name: x\n    type: script\n", "case.yaml: grader 1: type is one of"),
        ("case.yaml", "graders: regex\n", "case.yaml: graders is a list of graders"),
        ("graders/x.md", "---\nweight: 2\n---\n", "graders/x.md: type is one of .*; got None"),
    ],
)
def test_s025_1_unreadable_case_file_names_the_rule(
    repo: Path, capsys: pytest.CaptureFixture[str], file: str, text: str, rule: str
) -> None:
    _write(repo, f"evals/{CASE}/{file}", text)
    _fails(repo, capsys, rule)


def test_s025_1_a_grader_that_is_not_a_regular_file_is_refused_unread(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # a FIFO or a symlink to /dev/zero would block or never end a read: refused, never opened
    (repo / f"evals/{CASE}/graders").mkdir()
    os.mkfifo(repo / f"evals/{CASE}/graders/pipe.md")
    _fails(repo, capsys, r"graders/pipe\.md is not a regular file")
    (repo / f"evals/{CASE}/graders/pipe.md").unlink()
    (repo / f"evals/{CASE}/graders/zero.md").symlink_to("/dev/zero")
    _fails(repo, capsys, r"graders/zero\.md is not a regular file")


def test_s025_1_a_commit_that_is_not_a_sha_never_reaches_git(repo: Path) -> None:
    asked: list[str] = []

    def resolves(sha: str) -> bool:
        asked.append(sha)
        return True

    for commit in ("--output=/tmp/x", "-c", "HEAD"):
        _write(repo, "evals/cases.toml", _manifest(commit))
        report = evals.check(repo, resolves)
        assert report is not None
        assert [v.rule for v in report.violations] == [
            f"commit {commit!r} does not resolve to a commit in this repository (a 7 to 40 digit sha)"
        ]
    assert asked == []


def test_s025_1_violations_name_each_case(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, f"evals/{SKILL}/second/prompt.md", PROMPT.replace("max_turns: 40", "max_turns: 50"))
    _write(repo, f"evals/{SKILL}/second/case.yaml", CASE_YAML)
    text = (repo / "evals/cases.toml").read_text() + _manifest(_sha(repo), path=f"{SKILL}/second", kind="nope")
    _write(repo, "evals/cases.toml", text)
    code, lines = _check(repo, capsys)
    assert code == 1
    assert lines == [
        f"evals/{SKILL}/second: kind 'nope' is not one of verdict, decision, finding, fix",
        f"evals/{SKILL}/second: max_turns is 50, above the ceiling of 40",
    ]


def test_s025_1_results_mocks_and_bin_are_not_cases(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, "evals/results/2026/case/prompt.md", PROMPT)
    _write(repo, "evals/mocks/tracker/prompt.md", PROMPT)
    _write(repo, "evals/bin/gh", "#!/usr/bin/env python3\n")
    _write(repo, f"evals/{CASE}/fixture/nested/prompt.md", PROMPT)  # inside a case: the case's own
    assert _check(repo, capsys)[0] == 0


def test_s025_1_missing_manifest_names_it(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "evals/cases.toml").unlink()
    code, lines = _check(repo, capsys)
    assert code == 1
    assert lines == [
        "evals/cases.toml: missing; it lists every case under evals/",
        f"evals/{CASE}: a case directory not listed in evals/cases.toml",
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[[case]\n", "is not valid TOML"),
        ('title = "x"\n', r"holds only \[\[case\]\] entries; got title"),
        ('[[case]]\npath = "a/b"\n', "has exactly the keys path, skill, kind, source, commit; missing skill"),
        (_manifest("abc1234", extra="1"), "unknown extra"),
        (_manifest("abc1234").replace('kind = "verdict"', "kind = 3"), "kind is a non-empty string; got 3"),
        (_manifest("abc1234", path="../escape"), "path is relative to evals/"),
        (_manifest("abc1234", path="/abs/x"), "path is relative to evals/"),
        (_manifest("abc1234") * 2, "is listed twice"),
    ],
)
def test_malformed_manifest_exits_2(repo: Path, text: str, message: str) -> None:
    _write(repo, "evals/cases.toml", text)
    with pytest.raises(ReleaseError, match=message):
        main(["evals", "check", "--repo", str(repo)])


def test_s025_1_this_repository_suite_is_well_formed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["evals", "check", "--repo", str(ROOT)]) == 0


def test_s025_2_ci_runs_evals_check_on_every_pull_request() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    on = text[text.index("\non:\n") : text.index("\npermissions:")]
    assert re.search(r"^  pull_request:\s*$", on, re.MULTILINE), "CI runs on every pull request, unfiltered"
    assert "paths" not in on and "branches-ignore" not in on
    assert re.search(r"^\s+run: uv run shipmill evals check$", text, re.MULTILINE)
    # the check resolves each case's commit, so the checkout holds the whole history
    assert re.search(r"^\s+fetch-depth: 0\b", text, re.MULTILINE)


def _suite(repo: Path, kinds: dict[str, int]) -> None:
    """Replace the suite with well-formed cases, so many of each kind"""
    manifest = ""
    for kind, count in kinds.items():
        for n in range(count):
            path = f"{SKILL}/{kind}-{n}"
            _write(repo, f"evals/{path}/prompt.md", PROMPT)
            _write(repo, f"evals/{path}/case.yaml", CASE_YAML)
            manifest += _manifest(_sha(repo), path=path, kind=kind)
    (repo / f"evals/{CASE}/prompt.md").unlink()
    (repo / f"evals/{CASE}/case.yaml").unlink()
    _write(repo, "evals/cases.toml", manifest)


def _gate(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    code = main(["evals", "check", "--gate", "--repo", str(root)])
    return code, capsys.readouterr().out.splitlines()


def test_s025_16_gate_names_the_kinds_short_of_the_first_suite(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _suite(repo, {"verdict": 8, "decision": 2, "fix": 5})
    assert _gate(repo, capsys) == (
        1,
        [
            "evals/cases.toml: well formed, 15 cases",
            "gate off: short of the first suite's counts, decision: 2 of 4, finding: 0 of 4",
        ],
    )


def test_s025_16_gate_is_on_at_the_first_suite_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _suite(repo, {"verdict": 8, "decision": 4, "finding": 4, "fix": 4})
    assert _gate(repo, capsys) == (
        0,
        ["evals/cases.toml: well formed, 20 cases", "gate on: 8 verdict, 4 decision, 4 finding, 4 fix cases at least"],
    )


def test_s025_16_gate_off_without_a_suite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, lines = _gate(tmp_path, capsys)
    assert code == 1
    assert lines[-1] == (
        "gate off: short of the first suite's counts, verdict: 0 of 8, decision: 0 of 4, finding: 0 of 4, fix: 0 of 4"
    )


def test_s025_16_gate_reports_violations_before_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, "evals/cases.toml", _manifest(_sha(repo), kind="nope"))
    code, lines = _gate(repo, capsys)
    assert code == 1
    assert lines == [f"evals/{CASE}: kind 'nope' is not one of verdict, decision, finding, fix"]


def test_s025_16_check_without_gate_ignores_the_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _check(repo, capsys) == (0, ["evals/cases.toml: well formed, 1 cases"])
