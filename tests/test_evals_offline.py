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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "evals" / "bin" / "gh"
SCAFFOLD = ROOT / "evals" / "scaffold.sh"
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


def test_stub_and_scaffold_are_executable_in_git() -> None:
    staged = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "evals/bin/gh", "evals/scaffold.sh"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert [line.split()[0] for line in staged.splitlines()] == ["100755", "100755"]
    assert STUB.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n")


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
    alternates = ws / ".git" / "objects" / "info" / "alternates"
    assert alternates.is_file()  # a shared clone, not a copy of the objects


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
