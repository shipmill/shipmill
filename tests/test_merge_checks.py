import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill.autonomy import Autonomy
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.landing import Classic, RulesReader, Unreadable
from shipmill.merge_checks import (
    Command,
    Kind,
    Reading,
    Report,
    Required,
    classify,
    coverage,
    parts,
    read,
    report,
    required_contexts,
)
from shipmill.workflows import Step, events, jobs, steps

from .conftest import POLICY, FakeGitHub, Repo

ROOT = Path(__file__).parent.parent


def _read(text: str, root: Path, job: int = 0) -> Reading:
    return read(text, jobs(text)[job], root)


def _kinds(text: str, root: Path) -> dict[str, Kind]:
    return {c.text: c.kind for c in _read(text, root).commands}


def _kind(part: str) -> Kind:
    (command,) = classify(part, lambda: None)
    return command.kind


WORKFLOW = """\
name: CI
on: [pull_request]
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6 # pinned
        with:
          run: not a step's run
      - run: uv sync --locked && uv run pytest -q
      - name: Lint
        run: |
          # the linters
          uv run ruff check src; uv run ruff format --check src

          git diff | tee diff.txt || true
      - run: >
          uv run mypy
          src tests
      - run: "uv build"
"""


def test_s080_3_a_jobs_commands_are_the_parts_of_its_run_steps(tmp_path: Path) -> None:
    # proves: S-080-3
    reading = _read(WORKFLOW, tmp_path)
    assert [c.text for c in reading.commands] == [
        "uv sync --locked",
        "uv run pytest -q",
        "uv run ruff check src",
        "uv run ruff format --check src",
        "git diff",
        "tee diff.txt",
        "true",
        "uv run mypy src tests",
        "uv build",
    ]
    assert reading.actions == ("actions/checkout", "astral-sh/setup-uv")


def test_s080_3_a_uses_step_gives_the_check_no_kind(tmp_path: Path) -> None:
    # proves: S-080-3
    text = """\
jobs:
  lint:
    steps:
      - uses: actions/checkout@v4
      - uses: golangci/golangci-lint-action@v6
"""
    reading = _read(text, tmp_path)
    assert reading.commands == ()
    assert reading.actions == ("actions/checkout", "golangci/golangci-lint-action")
    assert str(coverage(reading.commands)) == "unknown"


def test_s080_3_steps_in_a_sequence_at_the_keys_indent_and_a_job_calling_a_workflow() -> None:
    text = """\
defaults:
  run:
    working-directory: web
jobs:
  build:
    steps:
    - run: npm test
    - run: npm run lint
      working-directory: app
  call:
    uses: ./.github/workflows/ci.yml
"""
    build, call = jobs(text)
    assert steps(text, build) == (Step("npm test", None, "web"), Step("npm run lint", None, "app"))
    assert steps(text, call) == ()


def test_s080_3_a_matrix_jobs_steps(tmp_path: Path) -> None:
    # proves: S-080-3
    text = """\
jobs:
  test:
    strategy:
      matrix:
        python: ["3.12", "3.13"]
        include:
          - run: not a step
    steps:
      - run: uv run --python ${{ matrix.python }} pytest
      - run: ${{ matrix.command }}
"""
    assert _kinds(text, tmp_path) == {
        "uv run --python ${{ matrix.python }} pytest": Kind.TESTS,
        "${{ matrix.command }}": Kind.UNKNOWN,
    }


def test_s080_3_parts_split_outside_quotes_and_skip_comments_and_heredocs() -> None:
    script = """\
echo "a && b; c | d" && pytest -q  # fast
x=$(git diff | wc -l)
uv run pytest \\
  -n auto
python3 - <<'EOF'
import os; os.exit(1)
EOF
if ruff check .; then
  mypy src
fi
read -r a b <<<"$pair"
pytest
"""
    assert parts(script) == [
        'echo "a && b; c | d"',
        "pytest -q",
        "x=$(git diff | wc -l)",
        "uv run pytest -n auto",
        "python3 - <<'EOF'",
        "if ruff check .",
        "then",
        "mypy src",
        "fi",
        'read -r a b <<<"$pair"',
        "pytest",
    ]


def test_s080_3_shell_keywords_alone_are_no_command(tmp_path: Path) -> None:
    text = "jobs:\n  t:\n    steps:\n      - run: |\n          if ruff check .; then\n"
    text += "            mypy src\n          fi\n"
    assert _kinds(text, tmp_path) == {"if ruff check .": Kind.UNKNOWN, "mypy src": Kind.TYPE_CHECK}


@pytest.mark.parametrize("part", ["if pytest", "elif ruff check .", "while mypy src", "until pytest", "! pytest"])
def test_s080_6_a_command_whose_failure_fails_no_step_is_unknown(part: str) -> None:
    # proves: S-080-6
    # a condition's or a negated command's exit never fails the step, so it proves nothing
    assert classify(part, lambda: None) == [Command(part, Kind.UNKNOWN)]


@pytest.mark.parametrize(
    ("part", "kind"),
    [
        ("uv run --locked pytest -q", Kind.TESTS),
        ("python -m pytest", Kind.TESTS),
        ("uv run mypy", Kind.TYPE_CHECK),
        ("npx eslint .", Kind.LINT),
        ("uv run lint-imports", Kind.IMPORT_BOUNDARIES),
        ("uv build", Kind.BUILD),
        ("CI=1 FORCE_COLOR=0 uv run --with pytest-xdist pytest -n auto", Kind.TESTS),
        ("timeout 600 uv run -- pytest", Kind.TESTS),
        ("sudo -u ci time -p go test ./...", Kind.TESTS),
        ("uv run python -m build", Kind.BUILD),
        ("python3 -m mypy src", Kind.TYPE_CHECK),
        ("poetry run ruff check", Kind.LINT),
        ("pnpm exec tsc --noEmit", Kind.TYPE_CHECK),
        ("bundle exec rspec", Kind.TESTS),
        ("./gradlew check", Kind.TESTS),
        ("./mvnw -B verify", Kind.TESTS),
        ("cargo clippy -- -D warnings", Kind.LINT),
        ("uvx tach check", Kind.IMPORT_BOUNDARIES),
        ("docker build -t app .", Kind.BUILD),
    ],
)
def test_s080_4_a_part_is_looked_up_past_assignments_and_wrappers(part: str, kind: Kind) -> None:
    # proves: S-080-4
    assert _kind(part) is kind


def test_s080_4_a_jobs_parts_in_a_workflow(tmp_path: Path) -> None:
    # proves: S-080-4
    assert _kinds(WORKFLOW, tmp_path) == {
        "uv sync --locked": Kind.UNKNOWN,
        "uv run pytest -q": Kind.TESTS,
        "uv run ruff check src": Kind.LINT,
        "uv run ruff format --check src": Kind.LINT,
        "git diff": Kind.UNKNOWN,
        "tee diff.txt": Kind.UNKNOWN,
        "true": Kind.UNKNOWN,
        "uv run mypy src tests": Kind.TYPE_CHECK,
        "uv build": Kind.BUILD,
    }


def _package(where: Path, scripts: dict[str, str]) -> None:
    where.mkdir(parents=True, exist_ok=True)
    (where / "package.json").write_text(json.dumps({"name": "app", "scripts": scripts}), encoding="utf-8")


def test_s080_5_npm_test_and_pnpm_run_take_the_scripts_kind(tmp_path: Path) -> None:
    # proves: S-080-5
    _package(tmp_path / "web", {"test": "vitest run", "lint": "eslint . && tsc --noEmit"})
    text = """\
jobs:
  web:
    steps:
      - run: npm ci && npm test
        working-directory: web
      - run: pnpm run lint
        working-directory: ./web
"""
    assert _kinds(text, tmp_path) == {
        "npm ci": Kind.UNKNOWN,
        "npm test: vitest run": Kind.TESTS,
        "pnpm run lint: eslint .": Kind.LINT,
        "pnpm run lint: tsc --noEmit": Kind.TYPE_CHECK,
    }


def test_s080_5_the_job_defaults_working_directory_holds_the_package(tmp_path: Path) -> None:
    # proves: S-080-5
    _package(tmp_path / "web", {"test": "jest"})
    text = "jobs:\n  web:\n    defaults:\n      run:\n        working-directory: web\n"
    text += "    steps:\n      - run: yarn test\n"
    assert _kinds(text, tmp_path) == {"yarn test: jest": Kind.TESTS}


@pytest.mark.parametrize(
    ("scripts", "run"),
    [
        (None, "npm test"),  # no package.json
        ({"lint": "eslint ."}, "npm test"),  # no such script
        ({"test": "npm run unit", "unit": "jest"}, "npm test"),  # a script that runs another
        ({"check": "pnpm test", "test": "vitest"}, "pnpm run check"),
    ],
)
def test_s080_5_a_missing_package_or_script_or_a_nested_script_is_unknown(
    tmp_path: Path, scripts: dict[str, str] | None, run: str
) -> None:
    # proves: S-080-5
    if scripts is not None:
        _package(tmp_path, scripts)
    text = f"jobs:\n  web:\n    steps:\n      - run: {run}\n"
    commands = _read(text, tmp_path).commands
    assert {c.kind for c in commands} == {Kind.UNKNOWN}
    assert str(coverage(commands)) == "unknown"


def test_s080_5_an_expression_working_directory_is_unknown(tmp_path: Path) -> None:
    # proves: S-080-5
    _package(tmp_path, {"test": "jest"})
    text = "jobs:\n  web:\n    steps:\n      - run: npm test\n        working-directory: ${{ matrix.dir }}\n"
    assert _kinds(text, tmp_path) == {"npm test": Kind.UNKNOWN}


def test_s080_5_a_package_json_that_isnt_json_fails_naming_it(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{", encoding="utf-8")
    text = "jobs:\n  web:\n    steps:\n      - run: npm test\n"
    with pytest.raises(ReleaseError, match="package.json is not JSON"):
        _read(text, tmp_path)


def test_s080_5_package_json_is_read_only_for_a_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{", encoding="utf-8")
    text = "jobs:\n  t:\n    steps:\n      - run: pytest\n"
    assert _kinds(text, tmp_path) == {"pytest": Kind.TESTS}


@pytest.mark.parametrize(
    "part",
    [
        "make test",
        "./scripts/check.sh",
        "tox",
        "nox -s tests",
        "just check",
        "build",  # the build module only after python -m
        "python scripts/test.py",
        "${{ matrix.command }}",
        'echo "unclosed',
        "mvn clean verify",  # the first argument names no kind
    ],
)
def test_s080_6_a_program_the_table_doesnt_hold_is_unknown_by_its_text(part: str) -> None:
    # proves: S-080-6
    assert classify(part, lambda: None) == [Command(part, Kind.UNKNOWN)]


def test_s080_7_a_checks_kinds(tmp_path: Path) -> None:
    # proves: S-080-7
    proving = coverage(_read(WORKFLOW, tmp_path).commands)
    assert proving.kinds == (Kind.TESTS, Kind.TYPE_CHECK, Kind.LINT)
    assert proving.proves
    assert str(proving) == "tests, type check, lint"

    built = coverage([Command("uv build", Kind.BUILD), Command("make", Kind.UNKNOWN)])
    assert not built.proves
    assert str(built) == "build only"

    nothing = coverage([Command("make test", Kind.UNKNOWN)])
    assert not nothing.proves
    assert str(nothing) == "unknown"
    assert str(coverage([])) == "unknown"

    boundaries = coverage([Command("lint-imports", Kind.IMPORT_BOUNDARIES), Command("uv build", Kind.BUILD)])
    assert str(boundaries) == "import boundaries"


def test_s080_7_this_repos_ci_check_proves() -> None:
    # proves: S-080-7
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    (job,) = jobs(text)
    reading = read(text, job, ROOT)
    assert str(coverage(reading.commands)) == "tests, type check, lint"
    assert "uv run --no-project python skills/github-issue-triage/scripts/specs.py check" in {
        c.text for c in reading.commands if c.kind is Kind.UNKNOWN
    }
    assert reading.actions[:2] == ("actions/checkout", "astral-sh/setup-uv")


# --- The reading of what gates a merge (S-080-1, 2, 8 to 14, 16) ---------------------------------


@dataclass
class FakeRules:
    """A RulesReader over fixed answers, recording each read; a ReleaseError value is raised"""

    rules: list[dict[str, Any]] | ReleaseError = field(default_factory=list)
    sets: dict[int, dict[str, Any]] = field(default_factory=dict)
    classic: Classic | ReleaseError = field(default_factory=lambda: Classic(True, None))
    reads: list[str] = field(default_factory=list)

    def branch_rules(self, repo: str, branch: str) -> Sequence[Mapping[str, Any]]:
        self.reads.append(f"rules {repo} {branch}")
        if isinstance(self.rules, ReleaseError):
            raise self.rules
        return self.rules

    def ruleset(self, repo: str, ruleset_id: int) -> Mapping[str, Any]:
        self.reads.append(f"ruleset {ruleset_id}")
        return self.sets[ruleset_id]

    def rulesets(self, repo: str) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("merge-checks reads no ruleset list")

    def protection(self, repo: str, branch: str) -> Classic:
        self.reads.append(f"protection {branch}")
        if isinstance(self.classic, ReleaseError):
            raise self.classic
        return self.classic


def checks_rule(ruleset_id: int, *contexts: str) -> dict[str, Any]:
    return {
        "type": "required_status_checks",
        "ruleset_id": ruleset_id,
        "parameters": {"required_status_checks": [{"context": c} for c in contexts]},
    }


def classic(contexts: Sequence[str] = (), checks: Sequence[str] = ()) -> Classic:
    status = {"contexts": list(contexts), "checks": [{"context": c, "app_id": 15368} for c in checks]}
    return Classic(True, {"required_status_checks": status})


SLUG = "o/demo"
CI = """\
name: CI
on:
  pull_request:
    branches: [main]
  push:
jobs:
  checks:
    name: "Checks"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run pytest -q && uv run mypy
  test:
    strategy:
      matrix:
        python: ["3.13", "3.14"]
    steps:
      - run: uv run --python ${{ matrix.python }} pytest
  build:
    steps:
      - run: uv build
  named:
    name: lint ${{ matrix.os }}
    steps:
      - run: uv run ruff check .
  call:
    uses: ./.github/workflows/reusable.yml
  remote:
    uses: o/other/.github/workflows/ci.yml@v1
"""
REUSABLE = """\
on: workflow_call
jobs:
  lint:
    name: Lint
    steps:
      - run: npx eslint .
"""
PUSH_ONLY = """\
on: [push]
jobs:
  deploy:
    steps:
      - run: pytest
"""


def _workflows(root: Path, **files: str) -> None:
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / f"{name}.yml").write_text(text, encoding="utf-8")


def _report(root: Path, reader: FakeRules | None, land: Autonomy = Autonomy.ACT, repo: str | None = SLUG) -> Report:
    return report(root, repo, "main", land, reader)


def test_s080_1_required_contexts_name_their_rulesets_and_classic_protection() -> None:
    # proves: S-080-1
    reader = FakeRules(
        rules=[checks_rule(7, "checks", "both"), {"type": "deletion", "ruleset_id": 8}, checks_rule(9, "org")],
        sets={7: {"name": "main"}, 9: {"name": "org rules"}},
        classic=classic(contexts=["both", "classic"], checks=["app check"]),
    )
    found = required_contexts(reader, SLUG, "main")
    assert found.unread == ()
    assert found.required == (
        Required("checks", ('ruleset "main"',)),
        Required("both", ('ruleset "main"', "classic protection")),
        Required("org", ('ruleset "org rules"',)),
        Required("classic", ("classic protection",)),
        Required("app check", ("classic protection",)),
    )
    assert reader.reads.count("ruleset 7") == 1  # each ruleset's name read once
    assert "ruleset 8" not in reader.reads  # a ruleset with no status check rule isn't read


def test_s080_1_the_command_lists_a_context_once_with_both_sources(tmp_path: Path) -> None:
    # proves: S-080-1
    _workflows(tmp_path, ci=CI)
    reader = FakeRules(rules=[checks_rule(7, "Checks")], sets={7: {"name": "main"}}, classic=classic(["Checks"]))
    lines = _report(tmp_path, reader).lines()
    assert lines[0] == (
        "PASS",
        '`Checks` (ruleset "main", classic protection): ci.yml job Checks: tests (uv run pytest -q), type check'
        " (uv run mypy); actions not read: actions/checkout",
    )
    assert len(lines) == 2


def test_s080_2_contexts_match_jobs_by_name_matrix_and_local_reusable_workflow(tmp_path: Path) -> None:
    # proves: S-080-2
    _workflows(tmp_path, ci=CI, reusable=REUSABLE, push=PUSH_ONLY)
    contexts = ["Checks", "test (3.14)", "build", "call / Lint", "deploy", "lint ubuntu", "remote / x", "test"]
    reader = FakeRules(rules=[checks_rule(1, *contexts)], sets={1: {"name": "main"}})
    found = _report(tmp_path, reader)
    matched = {c.required.context: [str(j) for j in c.jobs] for c in found.checks}
    assert matched == {
        "Checks": ["ci.yml job Checks"],
        "test (3.14)": ["ci.yml job test"],
        "build": ["ci.yml job build"],
        "call / Lint": ["reusable.yml job call / Lint"],
        "deploy": [],  # its workflow runs on push alone
        "lint ubuntu": [],  # a name holding an expression
        "remote / x": [],  # a remote reusable workflow
        "test": [],  # a matrix job reports `test (<values>)`
    }
    unknown = [line for _, line in found.lines() if line.startswith("`deploy`")]
    assert unknown == [
        '`deploy` (ruleset "main"): unknown: no job in .github/workflows reports it by a name its text tells'
    ]
    assert {c.required.context: str(c.coverage) for c in found.checks}["call / Lint"] == "lint"


@pytest.mark.parametrize(
    ("on", "names"),
    [
        ("on: pull_request", {"pull_request"}),
        ("on: [push, pull_request_target]  # both", {"push", "pull_request_target"}),
        ("on:\n  - push\n  - merge_group", {"push", "merge_group"}),
        ("'on':\n  pull_request:\n    types: [opened]\n  push:", {"pull_request", "push"}),
        ("name: x", set()),
    ],
)
def test_s080_2_the_events_a_workflow_runs_on(on: str, names: set[str]) -> None:
    # proves: S-080-2
    assert events(f"{on}\njobs:\n  a:\n    steps: []\n") == frozenset(names)


def test_s080_2_merge_group_workflows_report(tmp_path: Path) -> None:
    # proves: S-080-2
    _workflows(tmp_path, queue="on: merge_group\njobs:\n  q:\n    steps:\n      - run: pytest\n")
    reader = FakeRules(rules=[checks_rule(1, "q")], sets={1: {"name": "main"}})
    (check,) = _report(tmp_path, reader).checks
    assert [str(j) for j in check.jobs] == ["queue.yml job q"]


def test_s080_8_act_warns_when_no_check_is_required(tmp_path: Path) -> None:
    # proves: S-080-8
    _workflows(tmp_path, ci=CI, reusable=REUSABLE)
    assert _report(tmp_path, FakeRules()).lines() == [
        (
            "WARN",
            "no status check is required on main, so a pull request can merge on whichever checks reported: require"
            ' one that runs tests, a type check, or a lint, or set [autonomy] land = "propose"; these jobs run on'
            " pull requests and prove something: ci.yml job Checks (tests, type check), ci.yml job test (tests),"
            " reusable.yml job call / Lint (lint)",
        )
    ]


def test_s080_8_act_warns_when_no_required_check_proves(tmp_path: Path) -> None:
    # proves: S-080-8
    _workflows(tmp_path, ci=CI)
    reader = FakeRules(rules=[checks_rule(1, "build", "codecov")], sets={1: {"name": "main"}})
    status, detail = _report(tmp_path, reader).lines()[-1]
    assert status == "WARN"
    assert detail == (
        "main requires 2 checks and none runs tests, a type check, a lint, or an import-boundary check (`build` build"
        " only, `codecov` unknown): require one that runs tests, a type check, or a lint, or set [autonomy] land ="
        ' "propose"; these jobs run on pull requests and prove something: ci.yml job Checks (tests, type check),'
        " ci.yml job test (tests)"
    )


def test_s080_8_act_passes_when_a_required_check_proves(tmp_path: Path) -> None:
    # proves: S-080-8
    _workflows(tmp_path, ci=CI)
    reader = FakeRules(rules=[checks_rule(1, "build", "Checks")], sets={1: {"name": "main"}})
    assert _report(tmp_path, reader).lines()[-1] == (
        "PASS",
        "main requires 2 checks; 1 proves (tests, type check); land is act",
    )


@pytest.mark.parametrize("land", [Autonomy.OBSERVE, Autonomy.PROPOSE])
def test_s080_9_observe_and_propose_pass_on_the_same_reading(tmp_path: Path, land: Autonomy) -> None:
    # proves: S-080-9
    _workflows(tmp_path, ci=CI)
    assert _report(tmp_path, FakeRules(), land).lines() == [("PASS", f"main requires no status check; land is {land}")]
    reader = FakeRules(rules=[checks_rule(1, "build")], sets={1: {"name": "main"}})
    assert _report(tmp_path, reader, land).lines()[-1] == (
        "PASS",
        f"main requires 1 check; none proves (`build` build only); land is {land}",
    )


def test_s080_12_a_checks_line_names_at_most_5_commands_per_kind(tmp_path: Path) -> None:
    # proves: S-080-12
    lints = " && ".join(f"ruff check d{n}" for n in range(7))
    unknowns = " && ".join(f"make t{n}" for n in range(6))
    _workflows(tmp_path, ci=f"on: pull_request\njobs:\n  c:\n    steps:\n      - run: {lints} && {unknowns}\n")
    reader = FakeRules(rules=[checks_rule(1, "c")], sets={1: {"name": "main"}})
    line = _report(tmp_path, reader).lines()[0][1]
    assert line == (
        '`c` (ruleset "main"): ci.yml job c: lint (ruff check d0, ruff check d1, ruff check d2, ruff check d3, ruff'
        " check d4, and 2 more); unknown: make t0, make t1, make t2, make t3, make t4, and 1 more"
    )


@pytest.mark.parametrize("land", list(Autonomy))
def test_s080_13_a_read_that_fails_warns_at_every_level_and_keeps_the_rest(tmp_path: Path, land: Autonomy) -> None:
    # proves: S-080-13
    _workflows(tmp_path, ci=CI)
    reader = FakeRules(
        rules=[checks_rule(1, "Checks")],
        sets={1: {"name": "main"}},
        classic=Unreadable("GET repos/o/demo/branches/main/protection answered 404: Not Found"),
    )
    lines = _report(tmp_path, reader, land).lines()
    assert lines[0][1].startswith('`Checks` (ruleset "main"): ci.yml job Checks: tests')
    assert lines[-1] == (
        "WARN",
        "can't read main's classic protection: GET repos/o/demo/branches/main/protection answered 404: Not Found;"
        f" the checks stay unjudged; main requires 1 check; 1 proves (tests, type check); land is {land}",
    )
    forbidden = FakeRules(rules=Unreadable("GET repos/o/demo/rules/branches/main answered 403: Forbidden"))
    status, detail = _report(tmp_path, forbidden, land).lines()[-1]
    assert status == "WARN"
    assert detail.startswith("can't read main's rulesets: GET repos/o/demo/rules/branches/main answered 403")


@pytest.mark.parametrize(
    ("reader", "repo", "said"),
    [
        (None, SLUG, "can't read the required checks: gh isn't installed"),
        (FakeRules(), None, "can't read the required checks: this checkout's origin isn't a GitHub repository"),
    ],
)
def test_s080_13_no_gh_or_no_github_origin_warns(
    tmp_path: Path, reader: FakeRules | None, repo: str | None, said: str
) -> None:
    # proves: S-080-13
    for land in Autonomy:
        assert _report(tmp_path, reader, land, repo).lines() == [
            ("WARN", f"{said}; the checks stay unjudged; main requires no status check; land is {land}")
        ]
    assert reader is None or reader.reads == []


def test_s080_6_steps_that_fail_no_job_give_their_parts_no_kind(tmp_path: Path) -> None:
    # a failing part fails no job under continue-on-error, or in a shell other than bash or sh
    text = """\
defaults:
  run:
    shell: pwsh
jobs:
  t:
    steps:
      - run: pytest
        continue-on-error: true
      - run: pytest -x
        continue-on-error: ${{ matrix.experimental }}
      - run: mypy
      - run: ruff check
        shell: bash
      - run: pyright
        shell: sh -e {0}
      - run: eslint .
        continue-on-error: false
        shell: bash
"""
    assert _kinds(text, tmp_path) == {
        "pytest": Kind.UNKNOWN,
        "pytest -x": Kind.UNKNOWN,
        "mypy": Kind.UNKNOWN,  # the workflow's default shell is pwsh
        "ruff check": Kind.LINT,
        "pyright": Kind.TYPE_CHECK,
        "eslint .": Kind.LINT,
    }


# --- The command ---------------------------------------------------------------------------------


def _github_origin(repo: Repo) -> None:
    repo.git.run("remote", "set-url", "origin", f"https://github.com/{SLUG}.git")


def _commit_ci(repo: Repo, config: str | None = None) -> None:
    repo.write(".github/workflows/ci.yml", CI)
    if config is not None:
        repo.write(repo.policy_file, config)
    repo.git.run("add", "-A")
    repo.git.run("commit", "-qm", "ci")


def _run(repo: Repo, *argv: str, reader: FakeRules, github: FakeGitHub | None = None) -> int:
    return main(["merge-checks", "--repo", str(repo.root), *argv], github=github, rules_reader=reader)


def test_s080_10_without_land_the_configured_level_counts_even_under_a_hold(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    # proves: S-080-10
    _github_origin(repo)
    _commit_ci(repo, POLICY + '\n[autonomy]\nland = "act"\n')
    held = FakeGitHub()
    held.holds = ["88 hold everything"]
    assert _run(repo, reader=FakeRules(), github=held) == 0
    assert capsys.readouterr().out.startswith("WARN merge-checks: no status check is required on main")
    assert held.labels_read == []  # the hold isn't read
    _commit_ci(repo, POLICY)
    assert _run(repo, reader=FakeRules()) == 0
    assert capsys.readouterr().out == "PASS merge-checks: main requires no status check; land is propose\n"


def test_s080_9_the_configured_observe_passes_without_land(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    # proves: S-080-9
    _github_origin(repo)
    _commit_ci(repo, POLICY + '\n[autonomy]\nland = "observe"\n')
    assert _run(repo, reader=FakeRules()) == 0
    assert capsys.readouterr().out == "PASS merge-checks: main requires no status check; land is observe\n"


def test_s080_11_json_prints_one_object(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    # proves: S-080-11
    _github_origin(repo)
    _commit_ci(repo)
    reader = FakeRules(rules=[checks_rule(1, "Checks", "codecov")], sets={1: {"name": "main"}})
    assert _run(repo, "--land", "act", "--json", reader=reader) == 0
    record = json.loads(capsys.readouterr().out)
    assert set(record) >= {"branch", "land", "status", "summary", "required", "unrequired"}
    assert (record["branch"], record["land"], record["status"]) == ("main", "act", "PASS")
    assert record["summary"] == "main requires 2 checks; 1 proves (tests, type check); land is act"
    checks, codecov = record["required"]
    assert checks["context"] == "Checks"
    assert checks["sources"] == ['ruleset "main"']
    assert checks["kinds"] == ["tests", "type check"]
    (job,) = checks["jobs"]
    assert (job["workflow"], job["job"]) == ("ci.yml", "Checks")
    assert job["commands"] == [
        {"text": "uv run pytest -q", "kind": "tests"},
        {"text": "uv run mypy", "kind": "type check"},
    ]
    assert (codecov["jobs"], codecov["kinds"], codecov["reads"]) == ([], [], "unknown")
    assert record["unrequired"] == [{"workflow": "ci.yml", "job": "test", "kinds": ["tests"]}]


def test_s080_13_the_command_exits_0_on_a_read_that_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    # proves: S-080-13
    _commit_ci(repo)  # the fixture's origin is a local path, not a GitHub repository
    assert _run(repo, "--land", "act", reader=FakeRules()) == 0
    assert capsys.readouterr().out == (
        "WARN merge-checks: can't read the required checks: this checkout's origin isn't a GitHub repository; the"
        " checks stay unjudged; main requires no status check; land is act\n"
    )


def test_s080_14_a_land_that_isnt_a_level_exits_2_naming_the_levels(repo: Repo) -> None:
    # proves: S-080-14
    with pytest.raises(ReleaseError, match="--land 'merge' isn't a level: use one of observe, propose, act"):
        _run(repo, "--land", "merge", reader=FakeRules())


def test_s080_14_runs_without_agents_and_exits_2_on_a_config_that_doesnt_load(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    # proves: S-080-14
    _github_origin(repo)
    _commit_ci(repo)
    assert "[agents]" not in repo.read(repo.policy_file)
    assert _run(repo, "--land", "propose", reader=FakeRules()) == 0
    assert capsys.readouterr().out.startswith("PASS merge-checks:")
    repo.write(repo.policy_file, POLICY + "\n[autonomy]\nland = 3\n")
    with pytest.raises(ReleaseError):
        _run(repo, reader=FakeRules())


def test_s080_16_the_reader_only_reads_and_a_run_writes_no_file(repo: Repo) -> None:
    # proves: S-080-16
    methods = {name for name in vars(RulesReader) if not name.startswith("_")}
    assert methods == {"branch_rules", "ruleset", "rulesets", "protection"}  # each a GET
    _github_origin(repo)
    _commit_ci(repo)
    reader = FakeRules(rules=[checks_rule(1, "Checks")], sets={1: {"name": "main"}})
    assert _run(repo, "--land", "act", reader=reader) == 0
    assert _run(repo, "--json", reader=reader) == 0
    assert repo.git.run("status", "--porcelain", "--ignored") == ""
    assert reader.reads == ["rules o/demo main", "ruleset 1", "protection main"] * 2
