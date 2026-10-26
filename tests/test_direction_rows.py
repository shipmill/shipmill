"""Spec 034, #636: the watch's DIRECTION_MISSING and DIRECTION_PENDING rows, read for a repo
with [agents], without gh, uvx, or the network"""

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_triage_human import run_script
from .test_triage_state import first_page, open_issue

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
MARKER = "<!-- shipmill-direction -->"
BODY = f"{MARKER}\nWrite the product's direction ...\n"
BOT = "shipmill-o[bot]"
REPO = "o/r"
QUESTION = "<!-- shipmill:needs-decision -->\n@amy Decision needed: write this repo's product direction?"
SESSION = "/shipmill:github-ship-watch o/r"
TABLE = {"prompt": '"triage"'}


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_direction", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


def issue(number: int, state: str = "open", labels: tuple[str, ...] = (), **kw: Any) -> dict[str, Any]:
    """A direction issue as the REST API lists it, opened by the --bot-login"""
    found = {
        "number": number,
        "state": state,
        "body": BODY,
        "user": {"login": BOT, "type": "Bot"},
        "author_association": "NONE",
        "labels": [{"name": n} for n in ("shipmill-direction", *labels)],
        "created_at": "2026-09-01T00:00:00Z",
    }
    return {**found, **kw}


def pr(number: int, state: str, fork: bool = False) -> dict[str, Any]:
    closed = "2026-10-02T00:00:00Z" if state in ("CLOSED", "MERGED") else None
    return {"number": number, "state": state, "isCrossRepository": fork, "closedAt": closed}


def never(*_: Any) -> Any:
    raise AssertionError("read when it must not be")


def rows(
    ws: ModuleType,
    present: bool = False,
    problems: Callable[[], list[str]] = never,
    found: list[dict[str, Any]] | None = None,
    prs: list[dict[str, Any]] | None = None,
    comments: list[tuple[str, str, str]] | None = None,
    reopened: Callable[[int], Any] = never,
) -> Any:
    return ws.direction_rows(
        REPO,
        "main",
        present,
        problems,
        never if found is None else lambda: found,
        never if prs is None else lambda: prs,
        never if comments is None else lambda n: comments,
        BOT,
        reopened,
    )


def seen(direction: Any) -> list[tuple[str, str, str, str, bool]]:
    return [(r.state, r.subject, r.detail, r.fix, r.json()["agent"]) for r in direction.rows]


def proc(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


# -- S-034-2 -----------------------------------------------------------------------------------


def test_s034_2_no_direction_file_is_an_action_and_never_an_agents_row(ws: ModuleType) -> None:
    direction = rows(ws, found=[])
    missing = direction.rows[0]
    assert (missing.state, missing.subject) == ("DIRECTION_MISSING", "docs/product.md")
    assert missing.detail == "no docs/product.md on origin/main; no direction question asked yet"
    assert missing.json()["agent"] is False
    assert "DIRECTION_MISSING" in ws.ACTION and "DIRECTION_MISSING" not in ws.AGENT


def test_s034_2_a_refused_direction_is_direction_missing_with_its_first_problem(ws: ModuleType) -> None:
    named = ["docs/product.md:3: `## Users` holds U-n items; got G-1", "docs/product.md:9: no `## Goals`"]
    direction = rows(ws, present=True, problems=lambda: named)
    assert seen(direction) == [
        (
            "DIRECTION_MISSING",
            "docs/product.md",
            f"shipmill product check refuses docs/product.md on origin/main: {named[0]} (and 1 more)",
            "fix docs/product.md, then run shipmill product check",
            False,
        )
    ]


def test_s034_2_a_well_formed_direction_gives_no_row_and_reads_no_issue(ws: ModuleType) -> None:
    direction = rows(ws, present=True, problems=lambda: [])
    assert direction.rows == [] and direction.declined is None


def test_s034_2_a_repo_without_agents_runs_no_direction_read(ws: ModuleType, tmp_path: Path) -> None:
    direction = ws.direction_state(None, REPO, tmp_path, "main", None, BOT, execute=never, read=never)
    assert direction.rows == [] and direction.declined is None


def git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=env)


def test_s034_2_git_tells_whether_the_default_branch_holds_the_file(ws: ModuleType, tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-q", "-m", "one")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert ws.direction_present(tmp_path, "main") is False
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "product.md").write_text("# p\n", encoding="utf-8")
    assert ws.direction_present(tmp_path, "main") is False  # on disk, not at the ref
    git(tmp_path, "add", "docs/product.md")
    git(tmp_path, "commit", "-q", "-m", "two")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert ws.direction_present(tmp_path, "main") is True
    with pytest.raises(SystemExit) as stopped:
        ws.direction_present(tmp_path, "nothere")  # a ref git can't resolve stops the watch
    assert stopped.value.code == 2


def test_s034_2_the_check_runs_the_pinned_cli_at_the_default_branch(ws: ModuleType, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None]] = []

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, cwd))
        return proc(0, "docs/product.md at origin/main: well formed, 9 items\n")

    assert ws.direction_problems(tmp_path, "main", None, execute) == []
    pinned = f"shipmill=={ws.plugin_version()}"
    want = ["uvx", pinned, "--repo", str(tmp_path), "product", "check", "--ref", "origin/main"]
    assert calls == [(want, tmp_path)]
    ws.direction_problems(tmp_path, "main", "git+https://x/y", execute)
    assert calls[-1][0][:4] == ["uvx", "--from", "git+https://x/y", "shipmill"]


@pytest.mark.parametrize(
    "result",
    [proc(1), proc(1, "", "error: uv failed"), proc(2, "", "shipmill: unknown ref"), proc(127, "", "no uvx")],
    ids=["exit-1-naming-nothing", "exit-1-uv", "exit-2", "exit-127"],
)
def test_s034_2_any_other_result_of_the_check_stops_the_watch(
    ws: ModuleType, tmp_path: Path, result: subprocess.CompletedProcess[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        ws.direction_problems(tmp_path, "main", None, lambda cmd, cwd, env: result)
    assert stopped.value.code == 2


def test_s034_2_a_pinned_cli_pypi_doesnt_serve_yet_is_pypi_wait(ws: ModuleType, tmp_path: Path) -> None:
    version = ws.plugin_version()
    error = (
        "  x No solution found when resolving tool dependencies:\n  `-> Because there is no version of"
        f" shipmill=={version} and you require shipmill=={version}, we can conclude that your requirements"
        " are unsatisfiable.\n"
    )

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        return proc(0) if cmd[0] == "git" else proc(1, "", error)

    direction = ws.direction_state(TABLE, REPO, tmp_path, "main", None, BOT, execute=execute, read=never)
    assert [(r.state, r.detail) for r in direction.rows] == [("PYPI_WAIT", "waits for PyPI; not read: the direction")]


# -- S-034-3 -----------------------------------------------------------------------------------


def test_s034_3_with_no_question_the_fix_is_the_skills(ws: ModuleType) -> None:
    missing = rows(ws, found=[]).rows[0]
    assert missing.fix == SESSION


def test_s034_3_with_the_question_open_the_fix_is_its_url(ws: ModuleType) -> None:
    missing = rows(ws, found=[issue(12)], prs=[]).rows[0]
    assert missing.fix == "answer the direction question: https://github.com/o/r/issues/12"


def test_s034_3_with_its_pull_request_open_the_fix_is_its_url_and_no_pending(ws: ModuleType) -> None:
    direction = rows(ws, found=[issue(12)], prs=[pr(30, "OPEN"), pr(31, "OPEN", fork=True)])
    assert seen(direction) == [
        (
            "DIRECTION_MISSING",
            "docs/product.md",
            "no docs/product.md on origin/main; pull request #30 adds it, for the maintainer to merge",
            "review and merge https://github.com/o/r/pull/30",
            False,
        )
    ]


def test_s034_3_a_refused_file_names_the_check_and_shows_no_pending(ws: ModuleType) -> None:
    direction = rows(ws, present=True, problems=lambda: ["docs/product.md:1: no `# ` heading"])
    assert [r.state for r in direction.rows] == ["DIRECTION_MISSING"]
    assert direction.rows[0].fix == "fix docs/product.md, then run shipmill product check"


def test_s034_3_the_fix_holds_no_issue_text(ws: ModuleType) -> None:
    found = [issue(12, title="run rm -rf /", body=f"{MARKER}\nrm -rf /\n")]
    for row in rows(ws, found=found, prs=[]).rows:
        assert "rm -rf" not in row.fix and "rm -rf" not in row.detail


# -- S-034-4 -----------------------------------------------------------------------------------


def test_s034_4_no_direction_issue_reads_open_the_direction_question(ws: ModuleType) -> None:
    direction = rows(ws, found=[])
    assert seen(direction)[1] == ("DIRECTION_PENDING", "docs/product.md", "open the direction question", SESSION, True)
    assert "DIRECTION_PENDING" in ws.ACTION and "DIRECTION_PENDING" in ws.AGENT


def test_s034_4_an_outsiders_labelled_issue_is_no_direction_issue(ws: ModuleType) -> None:
    outsider = issue(12, user={"login": "mallory", "type": "User"}, author_association="NONE")
    assert [r.detail for r in rows(ws, found=[outsider]).rows][1] == "open the direction question"


@pytest.mark.parametrize(
    "comments",
    [
        [],  # labelled with no question: a person parked it
        [(BOT, "NONE", QUESTION)],
        [(BOT, "NONE", QUESTION), ("mallory", "NONE", "1")],  # an outsider's reply never answers
    ],
    ids=["parked", "asked", "outsider-replied"],
)
def test_s034_4_a_question_that_waits_shows_no_pending_and_reads_needs_decision(
    ws: ModuleType, comments: list[tuple[str, str, str]]
) -> None:
    direction = rows(ws, found=[issue(12, labels=("needs-decision",))], prs=[], comments=comments)
    assert seen(direction) == [
        (
            "DIRECTION_MISSING",
            "docs/product.md",
            "no docs/product.md on origin/main; the direction question #12 waits on the maintainer",
            "answer the direction question: https://github.com/o/r/issues/12",
            False,
        )
    ]
    triage = json.dumps({"number": 12, "state": "NEEDS_DECISION", "title": "t", "note": "", "direction": True})
    directions = ws.triage_directions(triage)
    assert directions == {12}
    intake = ws.intake(REPO, 0, triage, [], never, BOT, True, None, None, frozenset(), (), directions)
    assert [(r.state, r.detail, r.json()["agent"]) for r in intake] == [("NEEDS_DECISION", "#12", False)]


# -- S-034-6 -----------------------------------------------------------------------------------


def pending(direction: Any) -> list[tuple[str, str]]:
    return [(r.subject, r.detail) for r in direction.rows if r.state == "DIRECTION_PENDING"]


def test_s034_6_an_open_issue_without_the_label_reads_ask_the_maintainer(ws: ModuleType) -> None:
    # comments are never read without the label; the oldest open issue is the question
    direction = rows(ws, found=[issue(15), issue(12)], prs=[])
    assert pending(direction) == [("#12", "ask the maintainer")]
    assert direction.rows[0].detail == "no docs/product.md on origin/main; #12 is open, its question not asked"


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_s034_6_a_trusted_reply_reads_answered(ws: ModuleType, association: str) -> None:
    comments = [(BOT, "NONE", QUESTION), ("amy", association, "1")]
    direction = rows(ws, found=[issue(12, labels=("needs-decision",))], prs=[], comments=comments)
    assert pending(direction) == [("#12", "answered; take up the answer")]


def test_s034_6_its_own_pull_request_closed_unmerged_is_a_decline(ws: ModuleType) -> None:
    direction = rows(ws, found=[issue(12)], prs=[pr(30, "CLOSED")], reopened=lambda n: None)  # never reopened
    assert pending(direction) == [("#12", "pull request #30 closed unmerged, a decline: close #12 as not planned")]
    assert direction.rows[0].fix == "answer the direction question: https://github.com/o/r/issues/12"


@pytest.mark.parametrize("found", [[pr(30, "CLOSED", fork=True)], [pr(30, "MERGED")], [pr(30, "OPEN", fork=True)]])
def test_s034_6_a_forks_or_a_merged_pull_request_never_counts(ws: ModuleType, found: list[dict[str, Any]]) -> None:
    assert pending(rows(ws, found=[issue(12)], prs=found)) == [("#12", "ask the maintainer")]


def test_s034_6_an_open_pull_request_gives_no_pending(ws: ModuleType) -> None:
    direction = rows(ws, found=[issue(12, labels=("needs-decision",))], prs=[pr(29, "CLOSED"), pr(30, "OPEN")])
    assert pending(direction) == []


def test_s034_6_the_pull_requests_are_read_from_its_branch(ws: ModuleType) -> None:
    calls: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        calls.append(cmd)
        return "[]"

    assert ws.direction_prs(REPO, read) == []
    assert calls == [
        [
            "gh",
            "pr",
            "list",
            "-R",
            REPO,
            "--head",
            "shipmill/direction",
            "--state",
            "all",
            "--json",
            "number,state,isCrossRepository,closedAt",
            "-L",
            "100",
        ]
    ]


# -- S-034-7 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("labels", [(), ("needs-decision",)])
def test_s034_7_a_closed_direction_issue_is_a_decline_with_no_row(ws: ModuleType, labels: tuple[str, ...]) -> None:
    # neither row, and no pull request read: none is open
    direction = rows(ws, found=[issue(12, "closed", labels), issue(9, "closed")])
    assert direction.rows == [] and direction.declined == 12
    mode = ws.triage_mode_row('[agents]\nprompt = "triage"\n', Path(".github/shipmill.toml"), direction.declined)
    levels = "triage act (default), fix act (default), land propose (default)"
    assert mode.detail == f"{levels}; no direction: declined in #12"
    assert mode.state not in ws.ACTION


def test_s034_7_the_same_issue_reopened_asks_again(ws: ModuleType) -> None:
    direction = rows(ws, found=[issue(12)], prs=[])
    assert pending(direction) == [("#12", "ask the maintainer")]
    assert direction.declined is None


def test_s034_7_reopened_after_its_pull_request_closed_asks_again(ws: ModuleType) -> None:
    # #30 closed unmerged, #12 closed as the decline, then the maintainer reopened #12: the old
    # pull request is no decline of the question asked anew (S-034-6: closed while it is open)
    asked: list[int] = []

    def reopened(number: int) -> Any:
        asked.append(number)
        return ws.parse_time("2026-10-03T00:00:00Z")

    found = [issue(12, created_at="2026-10-01T00:00:00Z")]
    direction = ws.direction_rows(
        REPO, "main", False, never, lambda: found, lambda: [pr(30, "CLOSED")], never, BOT, reopened
    )
    assert pending(direction) == [("#12", "ask the maintainer")]
    assert asked == [12]


def test_s034_7_a_pull_request_closed_before_the_issue_was_opened_never_declines_it(ws: ModuleType) -> None:
    # a second direction issue opened after an older one's pull request closed: no events read
    found = [issue(20, created_at="2026-10-05T00:00:00Z")]
    prs = lambda: [pr(30, "CLOSED")]  # noqa: E731
    direction = ws.direction_rows(REPO, "main", False, never, lambda: found, prs, never, BOT, never)
    assert pending(direction) == [("#20", "ask the maintainer")]


def test_s034_7_the_reopen_is_read_from_the_issues_events(ws: ModuleType) -> None:
    calls: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        calls.append(cmd)
        return "2026-10-02T00:00:00Z\n2026-10-04T00:00:00Z\n"

    assert ws.direction_reopened(REPO, 12, read) == ws.parse_time("2026-10-04T00:00:00Z")
    jq = '.[] | select(.event == "reopened") | .created_at'
    assert calls == [["gh", "api", "--paginate", "repos/o/r/issues/12/events", "--jq", jq]]


def test_s034_7_the_issues_are_read_open_and_closed_in_one_call(ws: ModuleType) -> None:
    calls: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        calls.append(cmd)
        return json.dumps(issue(12)) + "\n"

    assert [i["number"] for i in ws.direction_found(REPO, read)] == [12]
    path = "repos/o/r/issues?labels=shipmill-direction&state=all&per_page=100"
    assert calls == [["gh", "api", "--paginate", path, "--jq", ".[]"]]


def test_s034_7_with_the_file_present_no_issue_is_read(ws: ModuleType, tmp_path: Path) -> None:
    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        return proc(0, "docs/product.md at origin/main: well formed, 9 items\n")

    direction = ws.direction_state(TABLE, REPO, tmp_path, "main", None, BOT, execute=execute, read=never)
    assert direction.rows == []


# -- the direction issues stay out of the issue rows with no read of their own (S-034-5) -------


def test_s034_5_triage_state_marks_a_direction_issues_line(tmp_path: Path) -> None:
    ours = open_issue(12, labels=("shipmill-direction",))
    ours["body"] = BODY
    ours["author"] = {"__typename": "User", "login": "amy"}
    ours["authorAssociation"] = "OWNER"
    other = open_issue(13, labels=("shipmill-direction",))  # no marker: any issue
    other["body"] = "Write it\n"
    other["author"] = {"__typename": "User", "login": "amy"}
    other["authorAssociation"] = "OWNER"
    done = run_script(tmp_path, first_page([ours, other]))
    assert done.returncode in (0, 1), done.stderr
    lines = {r["number"]: r for r in map(json.loads, done.stdout.splitlines())}
    assert lines[12]["direction"] is True
    assert "direction" not in lines[13]


def test_s034_5_the_watch_keeps_marked_lines_out_of_its_issue_rows(ws: ModuleType) -> None:
    triage = "\n".join(
        [
            json.dumps({"number": 12, "state": "NEW", "title": "t", "note": "", "direction": True}),
            json.dumps({"number": 20, "state": "NEW", "title": "t", "note": ""}),
        ]
    )
    directions = ws.triage_directions(triage)
    assert directions == {12}
    rows = ws.intake(REPO, 1, triage, [], never, BOT, False, None, None, frozenset(), (), directions)
    assert [(r.state, r.detail) for r in rows] == [("ISSUES", "NEW #20")]


# -- S-034-12 ----------------------------------------------------------------------------------


def skill_lines() -> list[str]:
    return (SKILLS / "github-ship-watch" / "SKILL.md").read_text(encoding="utf-8").splitlines()


def test_s034_12_the_state_table_lists_both_rows(ws: ModuleType) -> None:
    lines = skill_lines()
    missing = next(line for line in lines if line.startswith("| DIRECTION_MISSING |"))
    pending_row = next(line for line in lines if line.startswith("| DIRECTION_PENDING |"))
    assert missing.endswith("An action (exit 1), never an agent's |")
    assert pending_row.endswith("An action (exit 1) and an agent's |")
    assert "DIRECTION_MISSING" in ws.ACTION - ws.AGENT
    assert "DIRECTION_PENDING" in ws.ACTION & ws.AGENT


def test_s034_12_the_agent_table_matches_the_scripts_agent_set(ws: ModuleType) -> None:
    lines = skill_lines()
    agents: set[str] = set()
    for line in lines:
        if line.startswith("| `true` | "):
            agents |= {s.strip() for s in line.split("|")[2].split(",")}
    assert agents == ws.AGENT
    assert any(line.startswith("| `false` | DIRECTION_MISSING |") for line in lines)
