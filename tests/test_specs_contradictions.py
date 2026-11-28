"""Spec 099, #1698: specs.py contradictions reports what a spec's Behaviour and Acceptance
criteria name that the code at REF or the decisions log lacks"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from .test_specs import DECISIONS, SCRIPT, commit, git, spec, specs

SPEC = "docs/specs/001-dry-run.md"
PYPROJECT = '[project]\nname = "tool"\n\n[project.scripts]\ntool = "tool.cli:run"\n\n[tool.ruff]\nline-length = 120\n'
CLI = 'def run():\n    sub.add_parser("run")\n    p.add_argument("--dry-run")\n'
CHECK = "import sys\nif sys.argv[1] == 'verify' and '--fast' in sys.argv:\n    pass\n"


def code_repo(tmp_path: Path) -> Path:
    """A repo whose main holds a command `tool` (subcommand run, flag --dry-run), a script
    scripts/check.py (verify, --fast), and the decisions log; no spec yet"""
    root = tmp_path / "repo"
    for folder in ("src/tool", "scripts", "docs/specs"):
        (root / folder).mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    files = {
        "pyproject.toml": PYPROJECT,
        "src/tool/__init__.py": "",
        "src/tool/cli.py": CLI,
        "scripts/check.py": CHECK,
        "docs/decisions.md": DECISIONS,
    }
    commit(root, files)
    return root


def with_spec(tmp_path: Path, behaviour: str, criteria: tuple[str, ...] = ("1: a", "2: b")) -> Path:
    """The code repo with the spec written in its working tree, not committed"""
    root = code_repo(tmp_path)
    (root / SPEC).write_text(spec("001", behaviour=behaviour, criteria=criteria))
    return root


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return specs(root, "contradictions", "--base", "main", *args, SPEC)


def line_of(root: Path, text: str) -> int:
    lines = (root / SPEC).read_text().splitlines()
    return next(n for n, line in enumerate(lines, 1) if text in line)


def test_s099_1_a_spec_whose_names_all_exist_passes_and_a_finding_fails(tmp_path: Path) -> None:
    root = with_spec(tmp_path, "Runs `tool run --dry-run` in `src/tool/cli.py`, as D-2 says.")
    done = run(root)
    assert (done.returncode, done.stdout) == (0, "no contradictions found\n"), done.stderr

    (root / SPEC).write_text(spec("001", behaviour="Changes `src/tool/gone.py` and `tool frob`."))
    done = run(root)
    at = line_of(root, "gone.py")
    assert done.returncode == 1
    assert done.stdout.splitlines() == [
        f"{SPEC}:{at}: missing path: src/tool/gone.py: not in main",
        f'{SPEC}:{at}: missing command: tool frob: no "frob" in src/tool/ at main',
    ]


def test_s099_1_a_missing_spec_file_or_an_unreadable_ref_exits_2(tmp_path: Path) -> None:
    root = code_repo(tmp_path)
    done = run(root)
    assert done.returncode == 2 and "no spec file" in done.stderr

    (root / SPEC).write_text(spec("001"))
    done = specs(root, "contradictions", "--base", "no-such-ref", SPEC)
    assert done.returncode == 2 and "no-such-ref" in done.stderr


def test_s099_2_a_path_missing_at_ref_is_a_finding_at_its_line(tmp_path: Path) -> None:
    criteria = ("1: tool run reads `docs/missing.md`", "2: b")
    root = with_spec(tmp_path, "Reads `src/tool/cli.py`, `cli.py` and `src/tool/`.", criteria)
    done = run(root)
    assert done.returncode == 1
    assert done.stdout == f"{SPEC}:{line_of(root, 'docs/missing.md')}: missing path: docs/missing.md: not in main\n"


def test_s099_2_a_bare_file_name_anywhere_and_a_pattern_are_not_missing_paths(tmp_path: Path) -> None:
    names = ("check.py", "src/<name>.py", "src/{a,b}.py", "src/*.py", "docs/x.md#top", "https://example.com/a.py")
    # a path from a folder of the tree, a path outside the repo, and dotted names that are no file
    others = ("tool/cli.py", "~/.claude/settings.json", "/etc/hosts.conf", "Policy.parse", "github.com", "X.Y.Z")
    root = with_spec(tmp_path, "Reads " + ", ".join(f"`{n}`" for n in names + others) + ".")
    done = run(root)
    assert (done.returncode, done.stdout) == (0, "no contradictions found\n"), done.stdout


def test_s099_3_a_subcommand_its_source_lacks_is_a_missing_command(tmp_path: Path) -> None:
    spans = (
        "`tool frob`",
        "`uvx tool==1.2.3 frob`",
        "`uv run --no-project python scripts/check.py frob`",
        "`check.py frob`",
    )
    root = with_spec(tmp_path, "\n".join(f"Runs {s}." for s in spans))
    done = run(root)
    assert done.returncode == 1
    assert done.stdout.splitlines() == [
        f'{SPEC}:{line_of(root, "Runs `tool frob`")}: missing command: tool frob: no "frob" in src/tool/ at main',
        f'{SPEC}:{line_of(root, "uvx")}: missing command: tool frob: no "frob" in src/tool/ at main',
        f"{SPEC}:{line_of(root, 'uv run')}: missing command: scripts/check.py frob: "
        f'no "frob" in scripts/check.py at main',
        f"{SPEC}:{line_of(root, 'Runs `check.py')}: missing command: check.py frob: "
        f'no "frob" in scripts/check.py at main',
    ]


def test_s099_3_a_known_subcommand_and_another_tool_are_not_findings(tmp_path: Path) -> None:
    behaviour = "Runs `tool run`, `uvx tool==1.2.3 run`, `check.py verify`, `gh pr list`, and `git frob --hard`."
    root = with_spec(tmp_path, behaviour)
    done = run(root)
    assert (done.returncode, done.stdout) == (0, "no contradictions found\n"), done.stdout


def test_s099_4_a_flag_its_source_lacks_is_a_missing_flag(tmp_path: Path) -> None:
    root = with_spec(tmp_path, "Runs `tool run --dry-run --wet` and `check.py verify [--fast] [--slow]`.")
    done = run(root)
    at = line_of(root, "--wet")
    assert done.returncode == 1
    assert done.stdout.splitlines() == [
        f'{SPEC}:{at}: missing flag: --wet: no "--wet" in src/tool/ at main',
        f'{SPEC}:{at}: missing flag: --slow: no "--slow" in scripts/check.py at main',
    ]


def test_s099_5_a_missing_or_superseded_decision_is_a_finding(tmp_path: Path) -> None:
    criteria = ("1: tool run keeps D-1", "2: tool run follows D-9", "3: it supersedes D-1", "4: Superseding D-9 too")
    root = with_spec(tmp_path, "Follows D-2.", criteria)
    done = run(root)
    assert done.returncode == 1
    assert done.stdout.splitlines() == [
        f"{SPEC}:{line_of(root, 'keeps D-1')}: superseded decision: D-1: docs/decisions.md:10: Superseded by: D-2",
        f"{SPEC}:{line_of(root, 'follows D-9')}: missing decision: D-9: not in docs/decisions.md",
    ]


def test_s099_6_names_an_adds_line_declares_are_never_missing(tmp_path: Path) -> None:
    behaviour = "Adds: `src/tool/new.py`, `tool frob --wet`\n\nThen `tool frob --wet` writes `src/tool/new.py`."
    criteria = ("1: `tool frob` reads `src/tool/new.py`", "2: `tool run --wet` is wet")
    root = with_spec(tmp_path, behaviour, criteria)
    done = run(root)
    assert (done.returncode, done.stdout) == (0, "no contradictions found\n"), done.stdout


def test_s099_6_an_added_name_ref_has_already_exists_until_the_spec_is_on_ref(tmp_path: Path) -> None:
    behaviour = "Adds: `src/tool/cli.py`, `tool run`, `tool run --dry-run`, `check.py verify`"
    root = with_spec(tmp_path, behaviour)
    done = run(root)
    at = line_of(root, "Adds:")
    assert done.returncode == 1
    assert done.stdout.splitlines() == [
        f"{SPEC}:{at}: already exists: src/tool/cli.py: src/tool/cli.py at main",
        f'{SPEC}:{at}: already exists: tool run: "run" in src/tool/ at main',
        f'{SPEC}:{at}: already exists: check.py verify: "verify" in scripts/check.py at main',
    ]

    commit(root)  # the spec merged: it is on REF now
    done = run(root)
    assert (done.returncode, done.stdout) == (0, "no contradictions found\n"), done.stdout


def test_s099_7_json_prints_one_object_with_the_same_exit_codes(tmp_path: Path) -> None:
    root = with_spec(tmp_path, "Runs `tool run --wet`.")
    done = run(root, "--json")
    assert done.returncode == 1
    found = {"line": line_of(root, "--wet"), "kind": "missing flag", "name": "--wet"}
    assert json.loads(done.stdout) == {
        "spec": SPEC,
        "base": "main",
        "findings": [{**found, "other": 'no "--wet" in src/tool/ at main'}],
    }

    (root / SPEC).write_text(spec("001", behaviour="Runs `tool run`."))
    done = run(root, "--json")
    assert done.returncode == 0
    assert json.loads(done.stdout) == {"spec": SPEC, "base": "main", "findings": []}

    (root / SPEC).unlink()
    assert run(root, "--json").returncode == 2


def test_s099_8_the_code_is_read_at_ref_and_the_decisions_log_from_the_working_tree(tmp_path: Path) -> None:
    root = with_spec(tmp_path, "Writes `src/tool/local.py` and runs `tool local`, as D-3 says.")
    (root / "src/tool/local.py").write_text('LOCAL = "local"\n')
    decision = "\n## D-3: Local\n\n- Decided: 2026-10-03, in o/r#3\n- Rule: r\n- Why: w\n- Applies to: x\n"
    (root / "docs/decisions.md").write_text(DECISIONS + decision + "- Enforced by: review\n")
    done = run(root)
    at = line_of(root, "local.py")
    assert done.returncode == 1
    assert done.stdout.splitlines() == [
        f"{SPEC}:{at}: missing path: src/tool/local.py: not in main",
        f'{SPEC}:{at}: missing command: tool local: no "local" in src/tool/ at main',
    ]


def test_s099_3_a_command_reads_the_same_from_a_folder_of_the_repo(tmp_path: Path) -> None:
    root = with_spec(tmp_path, "Runs `tool run --dry-run` and `check.py verify --fast`.")
    done = specs(root / "src", "contradictions", "--base", "main", f"../{SPEC}")
    assert (done.returncode, done.stdout) == (0, "no contradictions found\n"), done.stdout


def test_s099_11_check_passes_a_spec_with_contradictions(tmp_path: Path) -> None:
    root = with_spec(tmp_path, "Writes `src/tool/gone.py` with `tool frob --wet`.")
    assert run(root).returncode == 1
    done = specs(root, "check")
    assert (done.returncode, done.stdout) == (0, ""), done.stdout


@pytest.fixture(scope="module")
def module() -> ModuleType:
    folder = str(SCRIPT.parent)
    sys.path.insert(0, folder)  # specs imports decisions, as when run from its folder
    try:
        found = importlib.util.spec_from_file_location("specs_contradictions", SCRIPT)
        assert found is not None and found.loader is not None
        loaded = importlib.util.module_from_spec(found)
        sys.modules[found.name] = loaded
        found.loader.exec_module(loaded)
    finally:
        sys.path.remove(folder)
    return loaded


def test_the_310_reader_reads_project_scripts_as_tomllib_does(module: ModuleType) -> None:
    text = PYPROJECT + "\n[project.scripts.extra]\nx = 1\n"
    expected = {"tool": "tool.cli:run"}
    assert module.project_scripts(PYPROJECT) == expected
    assert module.project_scripts_310(PYPROJECT) == expected
    assert module.project_scripts_310(text.replace('tool = "', "'tool' = \"")) == expected
