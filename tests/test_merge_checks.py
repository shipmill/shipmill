import json
from pathlib import Path

import pytest

from shipmill.errors import ReleaseError
from shipmill.merge_checks import Command, Kind, Reading, classify, coverage, parts, read
from shipmill.workflows import Step, jobs, steps

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
    assert _kinds(text, tmp_path) == {"if ruff check .": Kind.LINT, "mypy src": Kind.TYPE_CHECK}


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
