"""Spec 025's offline GitHub for eval cases (#438): evals/bin/gh, evals/scaffold.sh, no-miss

The stub runs as a subprocess with a controlled PATH and working directory, as a session
under `claude plugin eval` would run it; no test reaches GitHub.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.cli import main

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases.toml"
INTAKE_CASE = "product-intake/no-goal-not-proposed"
STUB = ROOT / "evals" / "bin" / "gh"
SCAFFOLD = ROOT / "evals" / "scaffold.sh"
CASE_SCAFFOLDS = sorted((ROOT / "evals").glob("*/*/scaffold.sh"))  # each case's own (#929)
NO_MISS = ROOT / "evals" / "graders" / "no-miss.yaml"
VIEW = ["issue", "view", "5", "--repo", "me/demo", "--json", "title,state"]
ANSWER = '{"title": "a bug", "state": "OPEN"}\n'


def key(args: list[str]) -> str:
    return hashlib.sha256(json.dumps(args).encode("utf-8")).hexdigest()[:16]


def workspace(tmp_path: Path, recordings: dict[str, tuple[list[str], str]] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / ".eval" / "gh").mkdir(parents=True)
    for args, stdout in (recordings or {}).values():
        answer = {"args": args, "stdout": stdout, "stderr": "", "exit": 0}
        (ws / ".eval" / "gh" / f"{key(args)}.json").write_text(json.dumps(answer), encoding="utf-8")
    return ws


def gh(cwd: Path, *args: str, path: str = "", stdin: str = "", **env: str) -> subprocess.CompletedProcess[str]:
    environ = {"PATH": path or os.environ["PATH"], "HOME": os.environ.get("HOME", ""), **env}
    return subprocess.run(
        [sys.executable, str(STUB), *args], cwd=cwd, env=environ, input=stdin, capture_output=True, text=True
    )


def lines(ws: Path) -> list[dict[str, object]]:
    text = (ws / ".eval" / "gh.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def fake_gh(tmp_path: Path) -> tuple[Path, Path]:
    """A `gh` that logs its arguments and answers, standing in for the real one"""
    bin_dir = tmp_path / "realbin"
    bin_dir.mkdir()
    calls = tmp_path / "real-calls.log"
    script = bin_dir / "gh"
    script.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nprintf \'{{"title": "live"}}\\n\'\n', encoding="utf-8")
    script.chmod(0o755)
    return bin_dir, calls


def no_miss_pattern() -> re.Pattern[str]:
    text = NO_MISS.read_text(encoding="utf-8")
    assert "match: not_contains" in text
    assert "target: {source: file, path: .eval/gh.jsonl}" in text
    found = re.search(r"^\s*pattern:\s*'(.*)'\s*$", text, re.MULTILINE)
    assert found is not None
    return re.compile(found.group(1))


def passes_no_miss(ws: Path) -> bool:
    """The no-miss grader's verdict: not_contains passes when the pattern finds nothing"""
    return no_miss_pattern().search((ws / ".eval" / "gh.jsonl").read_text(encoding="utf-8")) is None


def test_s025_3_a_recorded_read_answers_from_the_fixture_from_a_subdirectory(tmp_path: Path) -> None:
    ws = workspace(tmp_path, {"view": (VIEW, ANSWER)})
    (ws / "src" / "deep").mkdir(parents=True)
    done = gh(ws / "src" / "deep", "issue", "view", "5", "-R", "me/demo", "--json=title,state")
    assert (done.returncode, done.stdout) == (0, ANSWER)  # -R and --json= key like the recording
    assert lines(ws) == [{"kind": "read", "args": VIEW}]


def test_s025_3_a_write_succeeds_without_github_and_logs_its_body_file(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    bin_dir, calls = fake_gh(tmp_path)
    (ws / "body.md").write_text("Triage: **feature**.\n", encoding="utf-8")
    path = f"{STUB.parent}{os.pathsep}{bin_dir}"
    comment = gh(ws, "issue", "comment", "5", "--repo", "me/demo", "--body-file", "body.md", path=path)
    created = gh(ws, "pr", "create", "--repo", "me/demo", "--title", "t", "-F", "-", path=path, stdin="the plan\n")
    labelled = gh(ws, "issue", "edit", "5", "--add-label", "feature", path=path)
    assert [comment.returncode, created.returncode, labelled.returncode] == [0, 0, 0]
    assert comment.stdout.startswith("https://github.com/me/demo/issues/5#issuecomment-")
    assert re.fullmatch(r"https://github\.com/me/demo/pull/\d+\n", created.stdout)
    assert not calls.exists()  # the real gh was never called
    log = lines(ws)
    assert [line["kind"] for line in log] == ["write", "write", "write"]
    assert log[0]["body"] == "Triage: **feature**.\n"
    assert log[1]["body"] == "the plan\n"
    assert "body" not in log[2]


def test_s025_3_gh_api_writes_by_method_fields_and_mutations(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    (ws / "c.md").write_text("from a file", encoding="utf-8")
    writes = [
        ["api", "-X", "POST", "repos/me/demo/issues/5/labels"],
        ["api", "--method=PATCH", "repos/me/demo/issues/5"],
        ["api", "repos/me/demo/issues/5/comments", "-F", "body=@c.md"],
        ["api", "repos/me/demo/issues/5/comments", "-f", "body=inline"],
        ["api", "graphql", "-f", "query=mutation { addStar(input: {}) { clientMutationId } }"],
    ]
    for args in writes:
        assert gh(ws, *args).returncode == 0, args
    reads = [
        ["api", "repos/me/demo/issues/5"],
        ["api", "-X", "GET", "search/issues", "-f", "q=repo:me/demo"],
        ["api", "graphql", "-f", "query=query { viewer { login } }"],
    ]
    for args in reads:
        assert gh(ws, *args).returncode == 1, args  # unrecorded reads miss, never succeed as writes
    log = lines(ws)
    assert [line["kind"] for line in log] == ["write"] * 5 + ["miss"] * 3
    assert log[2]["body"] == "from a file"
    assert log[3]["body"] == "inline"


def test_s025_4_an_unrecorded_read_exits_1_and_fails_no_miss(tmp_path: Path) -> None:
    ws = workspace(tmp_path, {"view": (VIEW, ANSWER)})
    assert gh(ws, *VIEW).returncode == 0
    assert passes_no_miss(ws)  # reads and writes alone pass the grader
    done = gh(ws, "pr", "view", "7", "--repo", "me/demo")
    assert done.returncode == 1
    assert done.stderr == "gh: no recording for pr view 7 --repo me/demo\n"
    assert lines(ws)[-1] == {"kind": "miss", "args": ["pr", "view", "7", "--repo", "me/demo"]}
    assert not passes_no_miss(ws)


def test_s025_4_a_body_quoting_the_miss_line_does_not_fail_no_miss(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    assert gh(ws, "issue", "comment", "5", "--body-file", "-", stdin='"kind": "miss"').returncode == 0
    assert passes_no_miss(ws)  # JSON escapes the quotes inside a body


def test_s025_4_without_eval_the_stub_fails_rather_than_answer(tmp_path: Path) -> None:
    done = gh(tmp_path, *VIEW)
    assert done.returncode == 1
    assert "no .eval/" in done.stderr


def test_s025_5_record_forwards_a_read_to_the_real_gh_after_the_stub_and_saves_it(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    case = tmp_path / "case"
    (ws / ".eval" / "case").write_text(f"{case}\n", encoding="utf-8")
    bin_dir, calls = fake_gh(tmp_path)
    path = f"{STUB.parent}{os.pathsep}{bin_dir}"
    done = gh(ws, *VIEW, path=path, EVAL_GH_RECORD="1")
    assert (done.returncode, done.stdout) == (0, '{"title": "live"}\n')
    assert calls.read_text(encoding="utf-8") == " ".join(VIEW) + "\n"
    saved = json.loads((case / "fixture" / "gh" / f"{key(VIEW)}.json").read_text(encoding="utf-8"))
    assert saved == {"args": VIEW, "stdout": '{"title": "live"}\n', "stderr": "", "exit": 0}
    assert lines(ws) == [{"kind": "read", "args": VIEW}]
    replay = gh(ws, *VIEW, path=path)  # the recording now answers offline
    assert replay.stdout == '{"title": "live"}\n'
    assert calls.read_text(encoding="utf-8").count("\n") == 1


def test_s025_5_record_never_forwards_a_write_or_an_unknown_call(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    (ws / ".eval" / "case").write_text(f"{tmp_path / 'case'}\n", encoding="utf-8")
    bin_dir, calls = fake_gh(tmp_path)
    path = f"{STUB.parent}{os.pathsep}{bin_dir}"
    assert gh(ws, "pr", "merge", "7", "--squash", path=path, EVAL_GH_RECORD="1").returncode == 0
    assert gh(ws, "api", "-X", "DELETE", "repos/me/demo", path=path, EVAL_GH_RECORD="1").returncode == 0
    unknown = gh(ws, "extension", "install", "x/y", path=path, EVAL_GH_RECORD="1")
    assert unknown.returncode == 1
    assert "forwards only known reads" in unknown.stderr
    assert not calls.exists()
    assert not (tmp_path / "case").exists()


def test_s025_5_record_never_forwards_a_graphql_mutation_from_input_or_a_shown_token(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    (ws / ".eval" / "case").write_text(f"{tmp_path / 'case'}\n", encoding="utf-8")
    (ws / "m.json").write_text('{"query": "mutation { addStar(input: {}) { clientMutationId } }"}', encoding="utf-8")
    bin_dir, calls = fake_gh(tmp_path)
    path = f"{STUB.parent}{os.pathsep}{bin_dir}"
    assert gh(ws, "api", "graphql", "--input", "m.json", path=path, EVAL_GH_RECORD="1").returncode == 0
    assert gh(ws, "auth", "status", "--show-token", path=path, EVAL_GH_RECORD="1").returncode == 1
    assert gh(ws, "auth", "status", "-t", path=path, EVAL_GH_RECORD="1").returncode == 1
    assert not calls.exists()
    assert not (tmp_path / "case").exists()
    assert [line["kind"] for line in lines(ws)] == ["write"]


def test_s025_3_a_workflow_run_field_is_not_read_as_a_body_file(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    done = gh(ws, "workflow", "run", "ci.yml", "-F", "ref=main")
    assert done.returncode == 0, done.stderr
    assert lines(ws) == [{"kind": "write", "args": ["workflow", "run", "ci.yml", "-F", "ref=main"]}]


def test_s025_5_record_finds_the_real_gh_past_a_symlink_to_the_stub(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    (ws / ".eval" / "case").write_text(f"{tmp_path / 'case'}\n", encoding="utf-8")
    link_bin = tmp_path / "linkbin"
    link_bin.mkdir()
    (link_bin / "gh").symlink_to(STUB)
    real_bin, calls = fake_gh(tmp_path)
    python_dir = str(Path(sys.executable).parent)
    env = {"PATH": os.pathsep.join([str(link_bin), python_dir, str(real_bin)]), "EVAL_GH_RECORD": "1"}
    done = subprocess.run(["gh", *VIEW], cwd=ws, env=env, capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, '{"title": "live"}\n'), done.stderr
    assert calls.read_text(encoding="utf-8") == " ".join(VIEW) + "\n"


def test_s025_5_gh_from_path_records_through_the_real_gh_never_itself(tmp_path: Path) -> None:
    # As a session runs it: plain `gh` from PATH, the stub's directory first
    ws = workspace(tmp_path)
    (ws / ".eval" / "case").write_text(f"{tmp_path / 'case'}\n", encoding="utf-8")
    eval_bin = tmp_path / "evalbin"
    eval_bin.mkdir()
    shutil.copy(STUB, eval_bin / "gh")
    (eval_bin / "gh").chmod(0o755)
    python_dir = str(Path(sys.executable).parent)  # python3 for the stub's shebang
    real_bin, calls = fake_gh(tmp_path)

    def run(*path: str) -> subprocess.CompletedProcess[str]:
        env = {"PATH": os.pathsep.join(path), "HOME": os.environ.get("HOME", ""), "EVAL_GH_RECORD": "1"}
        return subprocess.run(["gh", *VIEW], cwd=ws, env=env, capture_output=True, text=True)

    alone = run(str(eval_bin), python_dir, str(eval_bin))  # the stub's directory twice, no real gh
    assert alone.returncode == 1
    assert f"no real gh on PATH after {eval_bin.resolve()}" in alone.stderr
    done = run(str(eval_bin), python_dir, str(real_bin))
    assert (done.returncode, done.stdout) == (0, '{"title": "live"}\n')
    assert calls.read_text(encoding="utf-8") == " ".join(VIEW) + "\n"


def fake_programs(tmp_path: Path) -> tuple[Path, Path]:
    """A real `shipmill` and `uvx` after the stub's directory, each logging `<name> <args>`"""
    bin_dir = tmp_path / "realbin"
    bin_dir.mkdir()
    calls = tmp_path / "real-calls.log"
    for name in ("shipmill", "uvx"):
        script = bin_dir / name
        script.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\necho real {name}\n', encoding="utf-8")
        script.chmod(0o755)
    return bin_dir, calls


def python_bin(tmp_path: Path) -> Path:
    """python3 alone, for the shims' shebang: the venv's bin/ also holds the real shipmill"""
    folder = tmp_path / "pybin"
    folder.mkdir()
    (folder / "python3").symlink_to(sys.executable)
    return folder


def shim(cwd: Path, *argv: str, path: list[Path]) -> subprocess.CompletedProcess[str]:
    """Run argv from PATH, as a session would: `shipmill ...` or `uvx ...`"""
    env = {"PATH": os.pathsep.join(str(p) for p in path), "HOME": os.environ.get("HOME", "")}
    return subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True)


SHIPMILL_GH_FORMS = [
    ["shipmill", "gh"],
    ["shipmill", "--repo", ".", "gh"],
    ["uvx", "--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill", "gh"],
    ["uvx", "-q", "--from=git+https://github.com/shipmill/shipmill@v0", "shipmill", "--repo=.", "gh"],
    ["uvx", "shipmill==0.55.0", "gh"],
    ["uvx", "--python", "3.14", "shipmill@0.55.0", "gh"],
]


def test_494_a_write_through_each_shipmill_gh_form_reaches_the_stub_marked_via_shipmill(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    (ws / "body.md").write_text("Triage: **implement**.\n", encoding="utf-8")
    real_bin, calls = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    for form in SHIPMILL_GH_FORMS:
        done = shim(ws, *form, "issue", "comment", "5", "--repo", "me/demo", "--body-file", "body.md", path=path)
        assert done.returncode == 0, (form, done.stderr)
        assert done.stdout.startswith("https://github.com/me/demo/issues/5#issuecomment-"), form
    assert not calls.exists()  # neither the real shipmill nor the real uvx ran
    args = ["issue", "comment", "5", "--repo", "me/demo", "--body-file", "body.md"]
    expected = {"kind": "write", "via": "shipmill", "args": args, "body": "Triage: **implement**.\n"}
    assert lines(ws) == [expected] * len(SHIPMILL_GH_FORMS)


def test_494_a_plain_gh_write_is_logged_without_via_so_a_grader_tells_them_apart(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    real_bin, _ = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    assert shim(ws, "gh", "issue", "edit", "5", "--add-label", "bug", path=path).returncode == 0
    assert shim(ws, "shipmill", "gh", "issue", "edit", "5", "--add-label", "bug", path=path).returncode == 0
    text = (ws / ".eval" / "gh.jsonl").read_text(encoding="utf-8").splitlines()
    assert text[0].startswith('{"kind": "write", "args": ')  # what a not_contains grader matches
    assert text[1].startswith('{"kind": "write", "via": "shipmill", "args": ')


def test_494_a_read_through_shipmill_gh_replays_the_recording(tmp_path: Path) -> None:
    ws = workspace(tmp_path, {"view": (VIEW, ANSWER)})
    real_bin, _ = fake_programs(tmp_path)
    done = shim(ws, "uvx", "shipmill==0.55.0", "gh", *VIEW, path=[STUB.parent, python_bin(tmp_path), real_bin])
    assert (done.returncode, done.stdout) == (0, ANSWER), done.stderr
    assert lines(ws) == [{"kind": "read", "via": "shipmill", "args": VIEW}]


def test_494_every_other_command_passes_through_to_the_real_program_unchanged(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    real_bin, calls = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    passed = [
        ["uvx", "--from", "actionlint-py", "actionlint", ".github/workflows/ci.yml"],
        ["uvx", "shipmill==0.55.0", "product", "show"],
        ["uvx", "--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill", "status"],
        ["uvx", "--with", "shipmill", "ruff", "gh"],
        ["uvx", "ghost", "gh"],
        ["shipmill", "product", "show", "--repo", "."],
        ["shipmill", "--repo", "gh", "status"],
        ["shipmill", "--", "gh", "pr", "list"],
    ]
    for argv in passed:
        done = shim(ws, *argv, path=path)
        assert (done.returncode, done.stdout) == (0, f"real {argv[0]}\n"), (argv, done.stderr)
    assert calls.read_text(encoding="utf-8").splitlines() == [" ".join(argv) for argv in passed]
    assert not (ws / ".eval" / "gh.jsonl").exists()  # the stub never ran


def test_494_with_no_real_program_after_the_stub_the_shim_fails_rather_than_recurse(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    linked = tmp_path / "linkbin"
    linked.mkdir()
    (linked / "uvx").symlink_to(STUB.parent / "uvx")
    path = [STUB.parent, python_bin(tmp_path), linked, STUB.parent]
    for argv in (["uvx", "--from", "actionlint-py", "actionlint"], ["shipmill", "status"]):
        done = shim(ws, *argv, path=path)
        assert done.returncode == 127, (argv, done.stderr)
        assert f"{argv[0]}: no real {argv[0]} on PATH after {STUB.parent.resolve()}" in done.stderr


LEVELS = {
    "hold": ["#9 stop"],
    "stages": [
        {"stage": "land", "configured": "act", "effective": "propose", "source": "hold"},
        {"stage": "deploy.github-pages", "configured": "act", "effective": "propose", "source": "hold"},
    ],
}


def test_s040_15_shipmill_autonomy_answers_from_the_case_autonomy_json_in_each_form(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    (ws / ".eval" / "autonomy.json").write_text(json.dumps(LEVELS), encoding="utf-8")
    (ws / "sub").mkdir()
    real_bin, calls = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    for form in (
        ["uvx", "shipmill==0.78.0"],
        ["shipmill"],
        ["shipmill", "--repo", "."],
        ["uvx", "-q", "shipmill@0.78.0"],
    ):
        done = shim(ws / "sub", *form, "autonomy", "--json", path=path)
        assert (done.returncode, json.loads(done.stdout)) == (0, LEVELS), (form, done.stderr)
    table = shim(ws, "shipmill", "autonomy", path=path)
    assert table.stdout.splitlines() == [
        "hold: #9 stop",
        "land                act     propose hold",
        "deploy.github-pages act     propose hold",
    ]  # as `shipmill autonomy` prints it
    assert not calls.exists()  # the real programs never ran
    assert not (ws / ".eval" / "gh.jsonl").exists()


def test_s040_15_without_an_autonomy_json_the_real_shipmill_answers(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    real_bin, calls = fake_programs(tmp_path)
    done = shim(ws, "uvx", "shipmill==0.78.0", "autonomy", "--json", path=[STUB.parent, python_bin(tmp_path), real_bin])
    assert (done.returncode, done.stdout) == (0, "real uvx\n"), done.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == ["uvx shipmill==0.78.0 autonomy --json"]


GOALS_JSON = '{\n  "goals": [{"id": "G-1", "text": "Ship it", "measure": null}]\n}\n'
GOALS_TEXT = "## Goals\n\n- G-1: Ship it\n"


def product_show_recordings(ws: Path) -> None:
    recordings = ws / ".eval" / "product-show"
    recordings.mkdir()
    (recordings / "section-goals.json").write_text(GOALS_JSON, encoding="utf-8")
    (recordings / "section-goals.txt").write_text(GOALS_TEXT, encoding="utf-8")
    (recordings / "all.txt").write_text("# Acme\n", encoding="utf-8")
    (recordings / "section-mission-section-non-goals.txt").write_text("## Mission\n", encoding="utf-8")


def test_941_shipmill_product_show_answers_from_the_case_recording_in_each_form(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    product_show_recordings(ws)
    (ws / "sub").mkdir()
    real_bin, calls = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    for form in (
        ["uvx", "shipmill==0.117.3"],
        ["shipmill"],
        ["shipmill", "--repo", "."],
        ["uvx", "-q", "shipmill@0.117.3"],
    ):
        for args, expected in (
            (["--section", "goals", "--json"], GOALS_JSON),
            (["--section", "goals"], GOALS_TEXT),
            (["--repo", ".", "--section=goals"], GOALS_TEXT),
            ([], "# Acme\n"),
            (["--section", "mission", "--section", "non-goals"], "## Mission\n"),
        ):
            done = shim(ws / "sub", *form, "product", "show", *args, path=path)
            assert (done.returncode, done.stdout) == (0, expected), (form, args, done.stderr)
    assert not calls.exists()  # the real programs never ran
    assert not (ws / ".eval" / "gh.jsonl").exists()


def test_941_without_a_recording_for_the_args_the_real_shipmill_answers(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    product_show_recordings(ws)
    real_bin, calls = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    passed = [
        ["uvx", "shipmill==0.117.3", "product", "show", "--json"],
        ["shipmill", "product", "show", "--section", "users"],
        ["shipmill", "product", "show", "--section", "../gh/x"],
        ["shipmill", "product", "check"],
    ]
    for argv in passed:
        done = shim(ws, *argv, path=path)
        assert (done.returncode, done.stdout) == (0, f"real {argv[0]}\n"), (argv, done.stderr)
    assert calls.read_text(encoding="utf-8").splitlines() == [" ".join(argv) for argv in passed]


# Every form of `shipmill product show` the product-intake skill (step 1) and its
# intake_state.py --plans run, as the case records them
INTAKE_SHOW_FORMS = [
    ["--section", "mission", "--section", "users", "--section", "goals", "--section", "non-goals"],
    ["--section", "goals", "--json"],
    ["--section", "goals"],
]


def test_941_the_case_recordings_match_the_real_cli_at_the_case_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """no-goal-not-proposed records what the real `shipmill product show` prints on the
    docs/product.md of the case's commit, in each form intake runs, and nothing else"""
    case = next(c for c in tomllib.loads(CASES.read_text(encoding="utf-8"))["case"] if c["path"] == INTAKE_CASE)
    direction = tmp_path / "direction" / "docs" / "product.md"
    direction.parent.mkdir(parents=True)
    direction.write_text(git(ROOT, "show", f"{case['commit']}:docs/product.md") + "\n", encoding="utf-8")
    ws = workspace(tmp_path)
    shutil.copytree(ROOT / "evals" / INTAKE_CASE / "fixture" / "product-show", ws / ".eval" / "product-show")
    real_bin, calls = fake_programs(tmp_path)
    path = [STUB.parent, python_bin(tmp_path), real_bin]
    for args in INTAKE_SHOW_FORMS:
        assert main(["--repo", str(direction.parents[1]), "product", "show", *args]) == 0
        printed = capsys.readouterr().out
        done = shim(ws, "uvx", "shipmill==0.117.3", "product", "show", *args, path=path)
        assert (done.returncode, done.stdout) == (0, printed), (args, done.stderr)
    assert not calls.exists()  # each form answered from a recording
    recorded = sorted(p.name for p in (ws / ".eval" / "product-show").iterdir())
    assert len(recorded) == len(INTAKE_SHOW_FORMS), recorded


def test_stub_and_scaffold_are_executable_in_git() -> None:
    staged = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "evals/bin/gh", "evals/bin/shipmill", "evals/scaffold.sh"]
        + [str(p.relative_to(ROOT)) for p in CASE_SCAFFOLDS],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert [line.split()[0] for line in staged.splitlines()] == ["100755"] * (3 + len(CASE_SCAFFOLDS))
    assert STUB.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n")
    assert (STUB.parent / "uvx").readlink() == Path("shipmill")  # one shim, two names


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def source_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    """A checkout holding evals/, a first commit, and a later one the case must not see"""
    repo = tmp_path / "source"
    (repo / "evals" / "bin").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "state.txt").write_text("then\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "then")
    then = git(repo, "rev-parse", "--short", "HEAD")
    (repo / "state.txt").write_text("now\n", encoding="utf-8")
    shutil.copy(SCAFFOLD, repo / "evals" / "scaffold.sh")
    for name in ("gh", "shipmill"):
        shutil.copy(STUB.parent / name, repo / "evals" / "bin" / name)
    (repo / "evals" / "bin" / "uvx").symlink_to("shipmill")
    case = repo / "evals" / "github-issue-triage" / "feature-maintainer-filed"
    (case / "fixture" / "gh").mkdir(parents=True)
    (case / "fixture" / "gh" / "abc.json").write_text('{"args": []}\n', encoding="utf-8")
    (case / "fixture" / "shipmill.toml").write_text("[agents]\napp_id = 7\n", encoding="utf-8")
    (repo / "evals" / "cases.toml").write_text(
        "[[case]]\n"
        'path = "github-issue-triage/other"\n'
        'commit = "0000000"\n\n'
        "[[case]]\n"
        'path = "github-issue-triage/feature-maintainer-filed"\n'
        'skill = "github-issue-triage"\n'
        f'commit = "{then}"                     # the state it is set at\n',
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "now")
    return repo, then, case


def test_s025_6_scaffold_leaves_the_repo_at_the_case_commit_with_the_fixture_at_eval(tmp_path: Path) -> None:
    repo, then, case = source_repo(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    done = subprocess.run(
        ["bash", str(repo / "evals" / "scaffold.sh"), str(case)], cwd=ws, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert git(ws, "rev-parse", "--short", "HEAD") == then
    assert (ws / "state.txt").read_text(encoding="utf-8") == "then\n"
    assert (ws / ".eval" / "gh" / "abc.json").read_text(encoding="utf-8") == '{"args": []}\n'
    assert (ws / ".eval" / "shipmill.toml").is_file()
    assert (ws / ".eval" / "gh.jsonl").read_text(encoding="utf-8") == ""
    assert (ws / ".eval" / "case").read_text(encoding="utf-8").strip() == str(case.resolve())
    assert git(ws, "status", "--porcelain") == ""  # .eval/ never shows to a session's git


def test_936_the_clone_works_where_the_session_cannot_read_the_checkout(tmp_path: Path) -> None:
    # The session's sandbox hides the checkout the run starts from: a clone sharing its
    # objects through alternates read `bad object HEAD` there
    repo, then, case = source_repo(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    done = subprocess.run(
        ["bash", str(repo / "evals" / "scaffold.sh"), str(case)], cwd=ws, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert not (ws / ".git" / "objects" / "info" / "alternates").exists()
    shutil.rmtree(repo / ".git")
    assert git(ws, "rev-parse", "--short", "HEAD") == then
    assert git(ws, "log", "--format=%s") == "then"
    assert git(ws, "status", "--porcelain") == ""


def test_936_the_scaffold_clones_from_a_worktree_as_the_merge_base_run_does(tmp_path: Path) -> None:
    repo, then, _ = source_repo(tmp_path)
    tree = tmp_path / "base-tree"
    git(repo, "worktree", "add", "-q", "--detach", str(tree), "HEAD")
    ws = tmp_path / "workspace"
    ws.mkdir()
    case = tree / "evals" / "github-issue-triage" / "feature-maintainer-filed"
    done = subprocess.run(
        ["bash", str(tree / "evals" / "scaffold.sh"), str(case)], cwd=ws, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert not (ws / ".git" / "objects" / "info" / "alternates").exists()
    assert git(ws, "rev-parse", "--short", "HEAD") == then


def test_936_the_session_settings_put_the_workspace_stub_first_on_path(tmp_path: Path) -> None:
    # evals/bin on the run's PATH sits in the checkout the sandbox hides, so the session ran
    # the real gh and uvx: the stub is copied into the workspace and the session's settings
    # env puts it first, with a uv cache the session can write
    repo, _, case = source_repo(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    done = subprocess.run(
        ["bash", str(repo / "evals" / "scaffold.sh"), str(case)], cwd=ws, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    settings = json.loads((ws / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    real = ws.resolve()
    entries = settings["env"]["PATH"].split(os.pathsep)
    assert entries[0] == str(real / ".eval" / "bin")
    assert entries[1:] == os.environ["PATH"].split(os.pathsep)
    assert settings["env"]["UV_CACHE_DIR"] == str(real / ".eval" / "uv-cache")
    assert (ws / ".eval" / "bin" / "uvx").readlink() == Path("shipmill")
    shutil.rmtree(repo)  # nothing the session runs reaches back into the checkout
    sub = ws / "src"
    sub.mkdir()
    env = {"PATH": settings["env"]["PATH"], "HOME": os.environ.get("HOME", "")}
    plain = subprocess.run(["gh", *VIEW], cwd=sub, env=env, capture_output=True, text=True)
    assert plain.returncode == 1
    assert plain.stderr.startswith("gh: no recording for issue view 5")
    via = subprocess.run(
        ["uvx", "shipmill==0.117.2", "app-token", "--check"], cwd=sub, env=env, capture_output=True, text=True
    )
    assert via.returncode == 0, via.stderr
    assert [line["kind"] for line in lines(ws)] == ["miss", "check"]
    assert git(ws, "status", "--porcelain") == ""  # the settings file never shows to git either


def test_s040_15_scaffold_commits_a_case_fixture_repo_over_the_case_commit(tmp_path: Path) -> None:
    repo, then, case = source_repo(tmp_path)
    overlay = case / "fixture" / "repo"
    (overlay / ".github").mkdir(parents=True)
    (overlay / ".github" / "shipmill.toml").write_text('[autonomy]\nland = "propose"\n', encoding="utf-8")
    (overlay / "state.txt").write_text("the case's\n", encoding="utf-8")
    ws = tmp_path / "workspace"
    ws.mkdir()
    done = subprocess.run(
        ["bash", str(repo / "evals" / "scaffold.sh"), str(case)], cwd=ws, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert git(ws, "rev-parse", "--short", "HEAD^") == then  # one commit on top of the case's
    assert (ws / "state.txt").read_text(encoding="utf-8") == "the case's\n"
    assert (ws / ".github" / "shipmill.toml").read_text(encoding="utf-8") == '[autonomy]\nland = "propose"\n'
    assert git(ws, "status", "--porcelain") == ""  # committed, and .eval/ stays out of git
    assert git(ws, "show", "--name-only", "--format=", "HEAD").splitlines() == [".github/shipmill.toml", "state.txt"]


def test_s025_27_every_case_runs_the_shared_scaffold_through_its_own() -> None:
    cases = sorted(p.parent for p in (ROOT / "evals").glob("*/*/case.yaml"))
    assert [p.parent for p in CASE_SCAFFOLDS] == cases
    first = CASE_SCAFFOLDS[0].read_bytes()
    assert all(p.read_bytes() == first for p in CASE_SCAFFOLDS)  # the same few lines in every case
    for case in cases:
        assert "  scaffold_script: scaffold.sh\n" in (case / "case.yaml").read_text(encoding="utf-8")


def test_s025_27_a_case_scaffold_started_as_the_runner_starts_it(tmp_path: Path) -> None:
    # in place, in the empty workspace, with no argument and no EVAL_CASE_DIR (#929)
    repo, then, case = source_repo(tmp_path)
    shutil.copy(CASE_SCAFFOLDS[0], case / "scaffold.sh")
    ws = tmp_path / "workspace"
    ws.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "EVAL_CASE_DIR"}
    done = subprocess.run([str(case / "scaffold.sh")], cwd=ws, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert git(ws, "rev-parse", "--short", "HEAD") == then
    assert (ws / ".eval" / "case").read_text(encoding="utf-8").strip() == str(case.resolve())


def test_s025_6_scaffold_fails_for_a_case_the_manifest_lacks(tmp_path: Path) -> None:
    repo, _, _ = source_repo(tmp_path)
    case = repo / "evals" / "github-pr-triage" / "unlisted"
    (case / "fixture").mkdir(parents=True)
    ws = tmp_path / "workspace"
    done = subprocess.run(
        ["bash", str(repo / "evals" / "scaffold.sh"), str(case), str(ws)], capture_output=True, text=True
    )
    assert done.returncode == 1
    assert 'no [[case]] with path "github-pr-triage/unlisted"' in done.stderr
    assert not ws.exists()


def test_s025_6_scaffold_takes_the_case_from_eval_case_dir(tmp_path: Path) -> None:
    repo, then, case = source_repo(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    env = {**os.environ, "EVAL_CASE_DIR": str(case)}
    done = subprocess.run(
        ["bash", str(repo / "evals" / "scaffold.sh")], cwd=ws, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert git(ws, "rev-parse", "--short", "HEAD") == then
