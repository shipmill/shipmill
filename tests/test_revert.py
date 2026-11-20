"""Spec 079: `shipmill revert open` backs out the merges that turned the default branch red. git
runs on a local bare origin and its clone; GitHub is a recording fake answering each `gh api`
read by its endpoint, and nothing reaches the network"""

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.revert import Opened, Request, _base_red, open_revert

from .conftest import POLICY

REPO = "demo/app"
API = "repos/{owner}/{repo}"
BOT = "shipmill-demo[bot]"
RUN = "https://github.com/demo/app/actions/runs/900"
PULL = 20
URL = f"https://github.com/{REPO}/pull/{PULL}"
PRODUCT = "# Demo\n\n## Goals\n\n- G-1: one\n- G-2: two\n\n## Quality bar\n\n- Q-1: fail fast\n"
A_BODY = "Adds more.\n\n## Plan\n\n- Serves: G-2\n- Files: `a.txt`\n- Order: one\n- Proof: tests\n\nFixes #5\n"
B_BODY = "Changes b.\n\n## Plan\n\n- Serves: quality bar (Q-1)\n- Files: `b.txt`\n- Order: one\n- Proof: tests\n"


def config(level: str | None) -> str:
    return POLICY if level is None else f'{POLICY}\n[autonomy]\nrevert = "{level}"\n'


def git(root: Path, *args: str) -> str:
    return Git(root).run(*args).strip()


@dataclass
class World:
    """origin, its clone, and main's first-parent history: start, then #11 merged with a merge
    commit (its feature commit beside), then #12 squashed onto it, the red head"""

    root: Path
    origin: Path
    start: str
    feature: str
    merge_a: str
    squash_b: str

    @property
    def head(self) -> str:
        return git(self.root, "rev-parse", "origin/main")

    def first_parent(self) -> list[str]:
        return git(self.root, "rev-list", "--first-parent", "origin/main").split()

    def remote_branches(self) -> list[str]:
        return git(self.root, "ls-remote", "--heads", "origin").split()[1::2]


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build(tmp_path: Path, level: str | None = "act") -> World:
    """origin at a path GitHub's URL pattern reads as demo/app, so the CLI takes it for one"""
    origin = tmp_path / "github.com" / "demo" / "app.git"
    origin.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    root = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for key, value in (("user.name", "Dev"), ("user.email", "dev@example.com"), ("commit.gpgsign", "false")):
        git(root, "config", key, value)
    git(root, "remote", "add", "origin", str(origin))
    write(root, "a.txt", "one\n")
    write(root, "b.txt", "two\n")
    write(root, "docs/product.md", PRODUCT)
    write(root, str(CONFIG_PATH), config(level))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Start")
    start = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "-c", "feature-a")
    write(root, "a.txt", "one\nmore\n")
    git(root, "commit", "-q", "-am", "Add more to a")
    feature = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "feature-a", "-m", "Merge pull request #11 from demo/feature-a")
    merge_a = git(root, "rev-parse", "HEAD")
    write(root, "b.txt", "two\nchanged\n")
    git(root, "commit", "-q", "-am", "Change b (#12)")
    squash_b = git(root, "rev-parse", "HEAD")
    git(root, "push", "-q", "origin", "main")
    return World(root, origin, start, feature, merge_a, squash_b)


def job(conclusion: str, run: int = 900, job_id: int = 901, name: str = "test") -> dict[str, Any]:
    url = f"https://github.com/{REPO}/actions/runs/{run}/job/{job_id}"
    return {
        "id": job_id,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": "2026-11-19T08:00:00Z",
        "html_url": url,
        "details_url": url,
        "check_suite": {"id": run + 7},
        "app": {"id": 15368},
    }


def pull(number: int, sha: str, title: str, body: str, merged_by: str = BOT) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "body": body,
        "merged_at": "2026-11-18T10:00:00Z",
        "merge_commit_sha": sha,
        "base": {"ref": "main"},
        "merged_by": {"login": merged_by},
    }


def closing(*nodes: tuple[int, str, str | None]) -> dict[str, Any]:
    refs = [
        {"number": n, "state": state, "stateReason": reason, "repository": {"nameWithOwner": REPO}}
        for n, state, reason in nodes
    ]
    return {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": refs}}}}}


@dataclass
class FakeGitHub:
    """Each endpoint's answer, as gh api prints it; every read and every write in order"""

    answers: dict[str, Any] = field(default_factory=dict)
    reads: list[list[str]] = field(default_factory=list)
    writes: list[tuple[Any, ...]] = field(default_factory=list)

    def text(self, args: list[str]) -> str:
        self.reads.append(list(args))
        if args[0] == "graphql":
            query = next(a for a in args if a.startswith("query="))
            number = next((a.split("=", 1)[1] for a in args if a.startswith("number=")), "")
            key = f"graphql:closing:{number}" if "closingIssuesReferences" in query else "graphql:tags"
        else:
            key = next(a for a in args if a.startswith("repos/"))
        if key not in self.answers:
            raise ReleaseError(f"gh api {key} exited 1: Not Found (HTTP 404)")
        answer = self.answers[key]
        if "--jq" in args:
            return "".join(json.dumps(item) + "\n" for item in answer)
        return json.dumps(answer)

    def create_label(self, name: str, color: str, description: str) -> None:
        self.writes.append(("label", name))

    def open_pull(self, title: str, body: str, head: str, base: str, label: str) -> str:
        self.writes.append(("pull", title, body, head, base, label))
        return URL

    def comment(self, number: int, body: str) -> None:
        self.writes.append(("comment", number, body))

    def reopen(self, number: int) -> None:
        self.writes.append(("reopen", number))


def github_for(w: World) -> FakeGitHub:
    """main's head failed `test` on its second attempt; #11 and #12 are the App's merges, in no
    tag; #11 closed #5 and #6 (open again) and #8 (not planned); #12 closed #5 and #7"""
    head = w.head
    commits = [
        {
            "sha": sha,
            "parents": [{"sha": p} for p in git(w.root, "rev-list", "--parents", "-n", "1", sha).split()[1:]],
            "commit": {"committer": {"date": f"2026-11-{19 - i:02d}T07:00:00Z"}},
        }
        for i, sha in enumerate(w.first_parent())
    ]
    gh = FakeGitHub()
    gh.answers = {
        f"{API}/commits/main/status?per_page=100": {"sha": head, "total_count": 0, "statuses": []},
        f"{API}/commits/{head}/check-runs?per_page=100&filter=all": [job("failure"), job("success", 910, 911, "lint")],
        f"{API}/issues?state=open&per_page=100": [],
        f"{API}/commits?sha={head}&per_page=100": commits,
        f"{API}/pulls/11": pull(11, w.merge_a, "Add more to a", A_BODY),
        f"{API}/pulls/12": pull(12, w.squash_b, "Change b", B_BODY),
        f"{API}/commits/{w.merge_a}/pulls": [{"number": 11, "merged_at": "x", "merge_commit_sha": w.merge_a}],
        f"{API}/commits/{w.squash_b}/pulls": [{"number": 12, "merged_at": "x", "merge_commit_sha": w.squash_b}],
        "graphql:tags": {"data": {"repository": {"refs": {"nodes": []}}}},
        "graphql:closing:11": closing((5, "CLOSED", "COMPLETED"), (6, "OPEN", None), (8, "CLOSED", "NOT_PLANNED")),
        "graphql:closing:12": closing((5, "CLOSED", "COMPLETED"), (7, "CLOSED", "COMPLETED")),
        f"{API}/labels?per_page=100": [{"name": "bug"}],
        f"{API}/issues/5/comments?per_page=100": [],
        f"{API}/issues/7/comments?per_page=100": [],
    }
    return gh


class NoLeaks:
    """The leak check, which finds nothing; what it was handed"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def body(self, text: str) -> None:
        self.seen.append("body")

    def push(self, refspec: str) -> None:
        self.seen.append(refspec)


def app() -> str:
    return BOT


def opened(w: World, gh: FakeGitHub, *pulls: int) -> Opened:
    return open_revert(w.root, REPO, Request(pulls or (11, 12), RUN), gh, gh, app, NoLeaks())


def refused(w: World, gh: FakeGitHub, *pulls: int, run: str = RUN, as_app: Any = app) -> str:
    """The refusal's message; nothing was pushed and nothing written to GitHub"""
    with pytest.raises(ReleaseError) as raised:
        open_revert(w.root, REPO, Request(pulls or (11, 12), run), gh, gh, as_app, NoLeaks())
    assert gh.writes == []
    assert w.remote_branches() == ["refs/heads/main"]
    return str(raised.value)


# --- S-079-8: every check before the first write -------------------------------------------------


@pytest.mark.parametrize("level", ["observe", None])
def test_s079_8_observe_on_the_default_branch_refuses_before_any_github_read(tmp_path: Path, level: str | None) -> None:
    w = build(tmp_path, level)
    gh = github_for(w)
    said = refused(w, gh)
    assert "[autonomy] revert is observe on main" in said
    assert gh.reads == []


def test_s079_8_the_level_is_read_from_origins_default_branch_not_the_working_tree(tmp_path: Path) -> None:
    w = build(tmp_path, None)
    write(w.root, str(CONFIG_PATH), config("act"))  # raised in the working tree alone
    assert "is observe on main" in refused(w, github_for(w))


def test_s079_8_without_the_app_nothing_is_read_or_written(tmp_path: Path) -> None:
    w = build(tmp_path, "propose")
    gh = github_for(w)

    def unavailable() -> str:
        raise ReleaseError("the App isn't available: no key")

    assert "the App isn't available" in refused(w, gh, as_app=unavailable)
    assert gh.reads == []


@pytest.mark.parametrize(
    "run",
    [
        "https://github.com/demo/app/actions/runs/999",  # no check of the head
        "https://github.com/demo/app/actions/runs/910",  # lint, which passed
    ],
)
def test_s079_8_a_run_naming_no_failed_check_of_the_head_is_refused(tmp_path: Path, run: str) -> None:
    w = build(tmp_path)
    said = refused(w, github_for(w), run=run)
    assert f"--run {run} names no failed completed check on main@{w.head[:7]}" in said
    assert f"failed there: test ({RUN}/job/901)" in said


def test_s079_8_a_pull_request_not_merged_is_refused(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    gh.answers[f"{API}/pulls/12"]["merged_at"] = None
    assert "#12 isn't merged" in refused(w, gh)


def test_s079_8_a_merge_by_a_person_is_refused(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    gh.answers[f"{API}/pulls/11"]["merged_by"] = {"login": "amy"}
    assert "#11 is not revertable: merged by a person" in refused(w, gh)


def test_s079_8_a_merge_a_tag_holds_is_refused(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    tag = {"name": "v1.2.0", "target": {"__typename": "Commit", "oid": w.head, "committedDate": "2026-11-19T07:00:00Z"}}
    gh.answers["graphql:tags"] = {"data": {"repository": {"refs": {"nodes": [tag]}}}}
    assert "#11 is not revertable: released in v1.2.0" in refused(w, gh)


def test_s079_8_a_commit_off_the_first_parent_history_is_refused(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    gh.answers[f"{API}/pulls/11"]["merge_commit_sha"] = w.feature
    assert f"#11's merge commit {w.feature[:7]} isn't on main's first-parent history" in refused(w, gh)


def test_s079_8_an_open_pull_request_repairing_the_run_is_refused(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    gh.answers[f"{API}/issues?state=open&per_page=100"] = [
        {"number": 30, "pull_request": {}, "body": f"Reverts #11\nRepairs: {RUN}/job/901\n"},
    ]
    assert f"#30 already has a Repairs: line naming {RUN}" in refused(w, gh)


def test_s079_8_a_repairs_line_on_an_issue_or_for_another_run_doesnt_count(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    gh.answers[f"{API}/issues?state=open&per_page=100"] = [
        {"number": 30, "body": f"Repairs: {RUN}"},  # an issue
        {"number": 31, "pull_request": {}, "body": "Repairs: https://github.com/demo/app/actions/runs/777"},
    ]
    assert opened(w, gh).url == URL


# --- S-079-9: the branch, one revert per pull request, newest first --------------------------------


def test_s079_9_the_branch_holds_one_revert_per_pull_request_newest_first(tmp_path: Path) -> None:
    w = build(tmp_path)
    head = w.head
    opened(w, github_for(w), 11, 12)
    branch = f"revert/11-{head[:7]}"  # the oldest reverted pull request, and the red head
    assert w.remote_branches() == ["refs/heads/main", f"refs/heads/{branch}"]
    git(w.root, "fetch", "-q", "origin", branch)
    subjects = git(w.root, "log", "--format=%s", f"{head}..FETCH_HEAD").splitlines()
    assert subjects == ['Revert "Merge pull request #11 from demo/feature-a"', 'Revert "Change b (#12)"']
    assert git(w.root, "rev-parse", "FETCH_HEAD~2") == head  # cut from origin/main
    assert git(w.root, "rev-parse", "FETCH_HEAD^{tree}") == git(w.root, "rev-parse", f"{w.start}^{{tree}}")
    message = git(w.root, "log", "-1", "--format=%B", "FETCH_HEAD")
    assert f"This reverts commit {w.merge_a}, reversing\nchanges made to {w.start}." in message  # -m 1


def test_s079_9_the_working_tree_index_and_branch_stay_as_they_were(tmp_path: Path) -> None:
    w = build(tmp_path)
    write(w.root, "a.txt", "local edit\n")
    opened(w, github_for(w))
    assert git(w.root, "branch", "--show-current") == "main"
    assert git(w.root, "status", "--porcelain") == "M a.txt"


def test_s079_9_a_revert_that_conflicts_names_the_files_and_pushes_nothing(tmp_path: Path) -> None:
    w = build(tmp_path)
    write(w.root, "b.txt", "two\nchanged again\n")  # a direct push over #12's line
    git(w.root, "commit", "-q", "-am", "Edit b")
    git(w.root, "push", "-q", "origin", "main")
    gh = github_for(w)
    said = refused(w, gh, 12)
    assert "the revert of #12 conflicts in b.txt" in said
    assert "nothing was written" in said


def test_s079_9_origin_moved_past_the_head_github_reads_is_refused(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    write(w.root, "c.txt", "new\n")
    git(w.root, "add", "c.txt")
    git(w.root, "commit", "-q", "-m", "Later")
    git(w.root, "push", "-q", "origin", "main")
    assert "the branch moved" in refused(w, gh)


# --- S-079-10: the pull request ------------------------------------------------------------------


def test_s079_10_the_pull_request_is_labelled_titled_and_carries_reverts_repairs_and_a_plan(tmp_path: Path) -> None:
    w = build(tmp_path)
    head = w.head
    gh = github_for(w)
    opened(w, gh, 11, 12)
    assert gh.writes[0] == ("label", "revert")  # the repo lacked it
    [(_, title, body, branch, base, label)] = [write for write in gh.writes if write[0] == "pull"]
    assert (title, branch, base, label) == ("Revert #11, #12", f"revert/11-{head[:7]}", "main", "revert")
    lines = body.splitlines()
    assert lines[:3] == ["Reverts #11", "Reverts #12", f"Repairs: {RUN}"]
    assert "- Serves: G-2, Q-1" in lines
    assert "- Files: `a.txt`, `b.txt`" in lines
    assert "- Proof: `test` green on this pull request's head" in lines
    gate = _base_red().gate
    ids = gate.direction_ids(lambda path: PRODUCT if path == gate.DIRECTION else None)
    assert gate.plan_problems(body, ids) == []
    assert gate.is_revert(body)  # what pr_gate.py reads as the revert (S-079-12)
    assert gate.repairs_of(body) == [RUN]


def test_s079_10_one_pull_request_takes_githubs_revert_title_and_serves_quality_bar_without_ids(
    tmp_path: Path,
) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    gh.answers[f"{API}/pulls/12"]["body"] = "No plan here."
    gh.answers[f"{API}/labels?per_page=100"] = [{"name": "revert"}]
    opened(w, gh, 12)
    [(_, title, body, branch, *_)] = [write for write in gh.writes if write[0] == "pull"]
    assert title == 'Revert "Change b"'
    assert branch == f"revert/12-{w.head[:7]}"
    assert "- Serves: quality bar" in body.splitlines()
    assert not any(write[0] == "label" for write in gh.writes)  # the label exists


def test_s079_10_no_closing_keyword_in_the_body_names_a_reverted_pull_request(tmp_path: Path) -> None:
    """`Reverts #N` must not close #N on merge: it is no closing keyword of triage_state.py's"""
    w = build(tmp_path)
    gh = github_for(w)
    opened(w, gh)
    [body] = [write[2] for write in gh.writes if write[0] == "pull"]
    keywords = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#\d+", re.IGNORECASE)
    assert keywords.search(body) is None


# --- S-079-11: the reopened issues ---------------------------------------------------------------


def test_s079_11_each_issue_closed_as_completed_is_reopened_with_one_comment(tmp_path: Path) -> None:
    w = build(tmp_path)
    head = w.head
    gh = github_for(w)
    result = opened(w, gh, 11, 12)
    assert result.text() == f"{URL}\nreopened: #5\nreopened: #7\n"
    issue_writes = [write for write in gh.writes if write[0] in ("comment", "reopen")]
    expected = (
        f"<!-- shipmill:reverted #12 by #{PULL} -->\nReopened: #12, which closed this, is being reverted in #{PULL}. "
        f"`test` failed on main@{head[:7]} after it merged: {RUN}"
    )
    assert issue_writes == [("comment", 5, expected), ("reopen", 5), ("comment", 7, expected), ("reopen", 7)]


def test_s079_11_the_marker_is_the_one_triage_state_reads() -> None:
    from shipmill.revert import MARKER

    ts = _base_red().gate.triage_state()
    assert ts.REVERTED_MARKER.fullmatch(MARKER.format(pull=12, revert=20))


def test_s079_11_an_issue_carrying_the_apps_marker_for_the_revert_gets_no_second_comment(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    marker = f"<!-- shipmill:reverted #12 by #{PULL} -->"
    gh.answers[f"{API}/issues/5/comments?per_page=100"] = [{"user": {"login": "amy"}, "body": f"{marker}\nby a person"}]
    gh.answers[f"{API}/issues/7/comments?per_page=100"] = [{"user": {"login": BOT}, "body": f"{marker}\nReopened"}]
    result = opened(w, gh, 11, 12)
    assert result.reopened == (5,)  # a person's marker counts for nothing
    assert [write[:2] for write in gh.writes if write[0] in ("comment", "reopen")] == [("comment", 5), ("reopen", 5)]


def test_s079_11_an_open_or_not_planned_issue_is_left_alone(tmp_path: Path) -> None:
    w = build(tmp_path)
    gh = github_for(w)
    result = opened(w, gh, 11)
    assert result.reopened == (5,)  # #6 is open, #8 closed as not planned
    assert {write[1] for write in gh.writes if write[0] in ("comment", "reopen")} == {5}


# --- the command ---------------------------------------------------------------------------------


@dataclass
class RecordingGh:
    calls: list[Sequence[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Any) -> tuple[int, str]:
        self.calls.append(list(argv))
        return 1, ""


def command(w: World, home: Path, gh: RecordingGh) -> int:
    return main(["--repo", str(w.root), "revert", "open", "11", "--run", RUN], environ={}, home=home, gh_capture=gh)


# proves: S-079-8
def test_s079_8_the_command_refuses_under_observe_and_without_app_id_running_no_gh(tmp_path: Path) -> None:
    w = build(tmp_path, None)
    gh = RecordingGh()
    with pytest.raises(ReleaseError, match="revert is observe on main"):
        command(w, tmp_path, gh)
    other = build(tmp_path / "act", "act")
    with pytest.raises(ReleaseError, match="the App isn't available: .* sets no \\[agents\\] app_id"):
        command(other, tmp_path, gh)
    assert gh.calls == []
    assert other.remote_branches() == ["refs/heads/main"]
