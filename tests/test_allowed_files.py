"""Spec 085: an agent's pull request lands only with the files its issue allows, end to end
through pr_gate.py with test_pr_gate.py's stand-in gh on PATH (S-085-1 to S-085-10)"""

from pathlib import Path
from typing import Any

import pytest

from .conftest import Repo
from .test_app_gh_merge import FakeGate
from .test_merge_gate import run as merge
from .test_pr_gate import (
    BOT,
    MAIN_READY,
    asked,
    at,
    branched,
    calls_of,
    checkout,
    comment,
    committed,
    gate,
    git,
    headed,
    pr,
    push,
    ready_line,
    review,
    run_gate,
    thread,
)

FRAGMENTS = '[changelog]\nfragments = "changelog.d"\n'
HELD = MAIN_READY.replace("READY", "NEEDS_DECISION")
CI = ".github/workflows/ci.yml"


def allowing(body: str, when: str = at(9), login: str = "shipmill-demo", association: str = "NONE") -> dict[str, Any]:
    """A comment on the issue, by the App unless login names someone else, before the PR opened (10:00)"""
    return comment(body, when, login=login, association=association, bot=login == "shipmill-demo")


def verdict(*files: str, when: str = at(9), **kw: Any) -> dict[str, Any]:
    """The App's implement verdict, its plan's `- Files:` line naming files in backticks"""
    named = ", ".join(f"`{f}`" for f in files)
    body = f"Triage: **implement**. The fix is small.\n\n- Serves: G-1\n- Files: {named}\n\n<!-- shipmill:agent -->\n"
    return allowing(body, when, **kw)


def gated(
    tmp_path: Path,
    files: tuple[str, ...],
    issues: dict[int, dict[str, Any]],
    body: str = "Fixes #12",
    work: Path | None = None,
    **kw: Any,
) -> Any:
    """The gate on #7, the App's ready, green PR changing files, its issues' threads as given"""
    data = pr(body=body, files=files, **{k: v for k, v in kw.items() if k in ("renamed", "draft", "login")})
    return run_gate(tmp_path, work, {7: data}, "--bot-login", BOT, issues=issues)


def outside(path: str, issues: str = "#12", verb: str = "allows") -> str:
    return f"  files: {path} is outside what {issues} {verb}"


def held(proc: Any) -> list[str]:
    assert proc.returncode == gate.NEEDS_DECISION == 5, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[0] == HELD.rstrip("\n"), proc.stdout
    return list(proc.stdout.splitlines()[1:])


def ready(proc: Any) -> None:
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stdout + proc.stderr


# S-085-4


def test_s085_4_a_file_outside_the_issues_allowance_holds_the_agents_pr(tmp_path: Path) -> None:
    work = checkout(tmp_path, {".github/shipmill.toml": FRAGMENTS})
    proc = gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"))}, work=work)
    assert held(proc) == [outside(CI)]


def test_s085_4_the_allowed_file_and_its_changelog_fragment_read_ready(tmp_path: Path) -> None:
    work = checkout(tmp_path, {".github/shipmill.toml": FRAGMENTS})
    ready(gated(tmp_path, ("src/a.py", "changelog.d/1523-a.md"), {12: thread(verdict("src/a.py"))}, work=work))


# S-085-1


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("Triage: **implement**.\n\n- Files: `src/a.py`\n", id="implement"),
        pytest.param("Proposed plan:\n\n1. Fix it\n\nFiles: `src/a.py`\n", id="proposed plan"),
        pytest.param("Triage: **implement**.\n\n* Files: `src/a.py`\n", id="a star bullet"),
    ],
)
def test_s085_1_a_counting_comments_files_lines_give_the_allowance(tmp_path: Path, body: str) -> None:
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(allowing(body))})) == [outside(CI)]


def test_s085_1_several_files_lines_add_up(tmp_path: Path) -> None:
    body = "Triage: **implement**.\n\n- Files: `src/a.py`\n\nAnd the workflow:\n\n- Files: `.github/`\n"
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(allowing(body))}))


def test_s085_1_a_files_line_in_a_fence_adds_nothing(tmp_path: Path) -> None:
    body = f"Triage: **implement**.\n\n```\n- Files: `{CI}`\n```\n\n- Files: `src/a.py`\n"
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(allowing(body))})) == [outside(CI)]


def test_s085_1_the_newest_counting_comment_gives_the_allowance(tmp_path: Path) -> None:
    older, newer = verdict("src/a.py", CI, when=at(8)), verdict("src/a.py", when=at(9))
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(older, newer)})) == [outside(CI)]
    # a newer comment that isn't a counting one changes nothing
    note = allowing(f"Files: `{CI}`, as I said", when=at(9, 30))
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(newer, note)})) == [outside(CI)]


def test_s085_1_a_counting_comment_without_a_files_line_declares_no_allowance(tmp_path: Path) -> None:
    """the newest counting comment names no files: the issue declares none, so the PR reads as before"""
    newer = allowing("Triage: **implement**, unblocked.\n", when=at(9, 30))
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"), newer)}))


def proposed_plan(lead: str = "<!-- shipmill:needs-decision -->\n<!-- shipmill:zone fix -->\n") -> dict[str, Any]:
    """The App's `Proposed plan:` under fix = "propose", as autonomy.md writes it: the marker and the
    zone line first, then the plan, its `Files:` line, and the ask to reply `apply`"""
    body = (
        f"{lead}Proposed plan: read the flag before the merge.\n\n"
        "- Serves: quality bar\n- Files: `src/a.py`\n- Order: the test first\n- Proof: a new test\n\n"
        "@romamo Reply `apply` to build this plan, or reply with your own.\n"
    )
    return allowing(body, when=at(8))


def test_s085_1_a_proposed_plan_under_its_markers_gives_the_allowance(tmp_path: Path) -> None:
    """#1594: the leading `<!-- shipmill:... -->` lines are skipped, so the answered plan's `Files:` counts;
    the `apply` reply takes no recommended option, so it lifts nothing"""
    applied = comment("apply", at(9))
    assert outside("src/b.py") in held(gated(tmp_path, ("src/b.py",), {12: thread(proposed_plan(), applied)}))


@pytest.mark.parametrize(
    "lead",
    [
        pytest.param("<!-- a note -->\n", id="an html comment that isn't shipmill's"),
        pytest.param("Note:\n<!-- shipmill:zone fix -->\n", id="a marker after text"),
    ],
)
def test_s085_1_only_leading_shipmill_markers_are_skipped(tmp_path: Path, lead: str) -> None:
    ready(gated(tmp_path, ("src/b.py",), {12: thread(proposed_plan(lead), comment("apply", at(9)))}))


def test_s085_13_a_proposed_plan_under_its_markers_edited_after_the_pr_opened_holds_it(tmp_path: Path) -> None:
    edited = {**proposed_plan(), "lastEditedAt": at(11)}
    lines = held(gated(tmp_path, ("src/a.py",), {12: thread(edited, comment("apply", at(9)))}))
    assert "  files: the allowance on #12 changed after this pull request opened" in lines


def test_s085_1_a_maintainers_counting_comment_counts(tmp_path: Path) -> None:
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        mine = verdict("src/a.py", login="romamo", association=association)
        assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(mine)})) == [outside(CI)], association


# S-085-2


@pytest.mark.parametrize(
    "later",
    [
        pytest.param(verdict("src/a.py", CI, login="eve", association="CONTRIBUTOR"), id="a contributor"),
        pytest.param(verdict("src/a.py", CI, login="other-app", association="NONE"), id="a person with no tie"),
        pytest.param(
            comment(f"Triage: **implement**.\n- Files: `src/a.py`, `{CI}`", at(9, 30), "other-app", "NONE", bot=True),
            id="another bot",
        ),
        pytest.param(verdict("src/a.py", CI, when=at(11)), id="the app after the pr opened"),
        pytest.param(
            verdict("src/a.py", CI, when=at(11), login="romamo", association="OWNER"), id="the maintainer after"
        ),
    ],
)
def test_s085_2_a_comment_that_doesnt_count_leaves_the_older_allowance(tmp_path: Path, later: dict[str, Any]) -> None:
    proc = gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py", when=at(8)), later)})
    assert held(proc) == [outside(CI)]


def test_s085_2_a_comment_after_the_pr_opened_alone_declares_no_allowance(tmp_path: Path) -> None:
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py", when=at(11)))}))
    outsider = verdict("src/a.py", login="eve", association="CONTRIBUTOR")
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(outsider)}))


# S-085-3


@pytest.mark.parametrize(
    ("allowed", "path", "covered"),
    [
        ("src/a.py", "src/a.py", True),
        ("src/a.py", "src/b.py", False),
        ("src/", "src/x/a.py", True),
        ("src", "src/a.py", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/x/a.py", False),
        ("src/**", "src/a.py", True),
        ("src/**", "src/x/a.py", True),
        ("tests/test_?.py", "tests/test_a.py", True),
        ("tests/test_?.py", "tests/test_ab.py", False),
    ],
)
def test_s085_3_a_path_is_covered_by_spec_061s_grammar(allowed: str, path: str, covered: bool) -> None:
    lines = gate.files_outside([gate.Allowance(12, (allowed,))], [path], None)
    assert lines == (() if covered else (f"{path} is outside what #12 allows",))


def test_s085_3_a_renamed_files_old_path_must_be_covered_too(tmp_path: Path) -> None:
    issues = {12: thread(verdict("src/a.py"))}
    proc = gated(tmp_path, ("src/a.py",), issues, renamed={"src/a.py": "lib/a.py"})
    assert held(proc) == [outside("lib/a.py")]
    ready(gated(tmp_path, ("src/a.py",), {12: thread(verdict("src/a.py", "lib/"))}, renamed={"src/a.py": "lib/a.py"}))


def test_s085_3_only_a_file_directly_inside_the_base_configs_fragments_folder_is_covered(tmp_path: Path) -> None:
    work = checkout(tmp_path, {".github/shipmill.toml": FRAGMENTS})
    files = ("src/a.py", "changelog.d/1.md", "changelog.d/x/2.md", "changelog.e/3.md")
    proc = gated(tmp_path, files, {12: thread(verdict("src/a.py"))}, work=work)
    assert held(proc) == [outside("changelog.d/x/2.md"), outside("changelog.e/3.md")]


def test_s085_3_the_fragments_folder_is_the_base_configs_not_the_prs(tmp_path: Path) -> None:
    """no fragments on the base: the PR's own config setting them covers nothing"""
    work = checkout(tmp_path, {".github/shipmill.toml": "[changelog]\n"})
    files = ("src/a.py", ".github/shipmill.toml", "changelog.d/1.md")
    proc = gated(tmp_path, files, {12: thread(verdict("src/a.py"))}, work=work)
    assert held(proc) == [outside(".github/shipmill.toml"), outside("changelog.d/1.md")]


@pytest.mark.parametrize("folder", ['"/abs"', '"../up"', '"."', '"changelog.d/"', "1"])
def test_s085_3_a_fragments_value_that_names_no_folder_covers_nothing(folder: str) -> None:
    assert gate.fragments_folder(f"[changelog]\nfragments = {folder}\n", "cfg") is None


# S-085-5


def test_s085_5_two_issues_allowances_add_up_and_one_declaring_none_adds_nothing(tmp_path: Path) -> None:
    issues = {
        12: thread(verdict("src/a.py")),
        13: thread(verdict("docs/")),
        14: thread(allowing("Triage: **implement**.\n")),
    }
    files = ("src/a.py", "docs/x.md", CI)
    proc = gated(tmp_path, files, issues, body="Fixes #12\n\nPart of #13\nPart of #14\n")
    assert held(proc) == [outside(CI, "#12, #13", "allow")]


# S-085-6


def test_s085_6_more_than_20_paths_outside_print_20_lines_and_a_count(tmp_path: Path) -> None:
    files = ("src/a.py", *(f"lib/m{i:02d}.py" for i in range(25)))
    lines = held(gated(tmp_path, files, {12: thread(verdict("src/a.py"))}))
    assert lines == [
        *(outside(f"lib/m{i:02d}.py") for i in range(20)),
        "  files: and 5 more outside the allowed files",
    ]


# S-085-7


def test_s085_7_a_persons_pr_is_judged_as_before(tmp_path: Path) -> None:
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"))}, login="amy"))


def test_s085_7_a_draft_is_judged_as_before(tmp_path: Path) -> None:
    proc = gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"))}, draft=True)
    assert proc.returncode == gate.DRAFT, proc.stdout + proc.stderr
    assert "files:" not in proc.stdout


def test_s085_7_an_agents_pr_whose_issues_declare_none_is_judged_as_before(tmp_path: Path) -> None:
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(allowing("Triage: **implement**.\n"))}))
    assert "files" not in calls_of(tmp_path)  # the files API isn't read for it


def test_s085_7_an_agents_pr_naming_no_issue_is_judged_as_before(tmp_path: Path) -> None:
    ready(gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"))}, body="Spec for #12"))


# S-085-8


@pytest.mark.parametrize(
    ("line", "why"),
    [
        pytest.param("- Files: src/a.py", "`Files:` names no path in backticks", id="no backticks"),
        pytest.param("- Files:", "`Files:` names no path in backticks", id="nothing"),
        pytest.param("- Files: `src/a.py`, ` `", "`Files:` names an empty path", id="empty"),
        pytest.param("- Files: `/etc/passwd`", "`Files:` names an absolute path, `/etc/passwd`", id="absolute"),
        pytest.param("- Files: `src/../x`", "`Files:` names a path holding `..`, `src/../x`", id="dot dot"),
    ],
)
def test_s085_8_a_files_line_that_cant_be_read_holds_the_pr(tmp_path: Path, line: str, why: str) -> None:
    body = f"Triage: **implement**.\n\n- Files: `src/a.py`\n{line}\n"
    proc = gated(tmp_path, ("src/a.py",), {12: thread(allowing(body))})
    assert held(proc) == [f"  files: #12's allowed files can't be read: {why}"]


CUT_OFF = "  files: the thread of #12 is cut off at 100 comments: its allowed files can't be read, so a person looks"


def test_s085_8_a_thread_cut_off_with_no_counting_comment_in_its_newest_100_holds_the_pr(tmp_path: Path) -> None:
    note = allowing("a note", at(9, 30))
    assert held(gated(tmp_path, ("src/a.py",), {12: thread(note, whole=False)})) == [CUT_OFF]
    # one created after the PR opened doesn't count, so it doesn't stand in for the cut-off part
    late = verdict("src/a.py", when=at(11))
    assert held(gated(tmp_path, ("src/a.py",), {12: thread(late, whole=False)})) == [CUT_OFF]


def test_s085_8_a_cut_off_thread_with_a_counting_comment_reads_it(tmp_path: Path) -> None:
    ready(gated(tmp_path, ("src/a.py",), {12: thread(verdict("src/a.py"), whole=False)}))
    assert held(gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"), whole=False)})) == [outside(CI)]


# S-085-9


def answered(
    tmp_path: Path, data: dict[str, Any], pr_thread: dict[str, Any], issue: dict[str, Any], work: Path | None = None
) -> Any:
    """The gate on #7, the App's PR data, its thread pr_thread, #12's thread issue; romamo, who
    answers, has admin on the repo and approved the PR's head (spec 055)"""
    reviews = {7: [review(commit=data["headRefOid"])]}
    return run_gate(
        tmp_path,
        work,
        {7: data},
        "--bot-login",
        BOT,
        issues={12: issue},
        threads={7: pr_thread},
        permissions={"romamo": "admin"},
        reviews=reviews,
    )


def test_s085_9_the_maintainers_accepting_answer_lifts_the_files_lines_and_ci_decides(tmp_path: Path) -> None:
    issue = thread(verdict("src/a.py"))
    data = headed(body="Fixes #12", files=("src/a.py", CI))
    proc = answered(tmp_path, data, thread(asked(), comment("1", at(12))), issue)
    assert (proc.returncode, proc.stdout) == (0, MAIN_READY), proc.stdout + proc.stderr
    data["statusCheckRollup"] = [{"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"}]
    proc = answered(tmp_path, data, thread(asked(), comment("1", at(12))), issue)
    assert proc.returncode == gate.FAILED, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == ["  failed: test (FAILURE)"]


def test_s085_9_an_answer_not_taking_the_recommended_option_keeps_the_files_lines(tmp_path: Path) -> None:
    data = headed(body="Fixes #12", files=("src/a.py", CI))
    proc = answered(tmp_path, data, thread(asked(), comment("2", at(12))), thread(verdict("src/a.py")))
    assert held(proc) == ["  needs-decision: the answer doesn't take the recommended option", outside(CI)]


def test_s085_9_a_head_whose_own_change_differs_keeps_the_files_lines(tmp_path: Path) -> None:
    work = checkout(tmp_path, {})
    first = branched(tmp_path, work, {"src/a.py": "a = 1\n", CI: "on: push\n"})
    head = committed(work, {CI: "on: pull_request\n"}, "Change the workflow")
    data = headed(head, ((first, at(10, 30)), (head, at(13))), body="Fixes #12", files=("src/a.py", CI))
    proc = answered(tmp_path, data, thread(asked(head=first), comment("1", at(12))), thread(verdict("src/a.py")), work)
    assert proc.returncode == gate.NEEDS_DECISION, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[1:] == [
        f"  needs-decision: answered at {first[:7]}, and the change differs since",
        outside(CI),
    ]


def test_s085_9_a_rebase_with_the_same_own_change_keeps_the_answer(tmp_path: Path) -> None:
    """spec 055: the answer binds to the change, not the sha, so a rebase alone keeps it"""
    work = checkout(tmp_path, {})
    first = branched(tmp_path, work, {"src/a.py": "a = 1\n", CI: "on: push\n"})
    git(work, "rebase", "-q", "origin/main")
    head = git(work, "rev-parse", "HEAD").strip()
    data = headed(head, ((head, at(13)),), body="Fixes #12", files=("src/a.py", CI))
    rebased = thread(asked(head=first), comment("1", at(12)), pushes=(push(at(13), first),))
    proc = answered(tmp_path, data, rebased, thread(verdict("src/a.py")), work)
    assert (proc.returncode, proc.stdout) == (0, ready_line(head)), proc.stdout + proc.stderr


def test_s085_9_a_new_verdict_by_the_app_after_the_pr_opened_doesnt_lift_the_files_lines(tmp_path: Path) -> None:
    later = verdict("src/a.py", CI, when=at(11))
    proc = gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"), later)})
    assert held(proc) == [outside(CI)]


# S-085-10


def test_s085_10_a_merge_of_a_pr_the_files_lines_hold_exits_2_before_gh(repo: Repo, tmp_path: Path) -> None:
    """the gate's own output for S-085-4's pull request, as `shipmill gh pr merge 7` reads it"""
    proc = gated(tmp_path, ("src/a.py", CI), {12: thread(verdict("src/a.py"))})
    assert proc.returncode == gate.NEEDS_DECISION, proc.stdout + proc.stderr
    runner, refused = merge(repo, tmp_path, ["pr", "merge", "7", "--squash"], FakeGate(proc.stdout, proc.returncode))
    assert runner.calls == []  # gh never ran
    assert refused is not None and "is refused: pr_gate.py reads #7 NEEDS_DECISION" in refused
    assert outside(CI) in refused.splitlines()
