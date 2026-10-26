"""Spec 038, #589: the instructions the coordinator and a component's sessions follow for work
across repos: github-issue-triage's Reports from other repos, comments.md's Upstream report,
the rubric's stand-in, and github-issue-resolve's upstream verdict"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "skills" / "github-issue-triage"


def doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body of a ``## heading`` section, up to the next heading of its level outside a
    code fence (a template's own ``## Reproduce`` stays in it)"""
    assert f"\n{heading}\n" in text, heading
    lines, fenced = [], False
    for line in text.split(f"\n{heading}\n", 1)[1].splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if line.startswith("## ") and not fenced:
            break
        lines.append(line)
    return "\n" + "\n".join(lines) + "\n"


def flat(text: str) -> str:
    return " ".join(text.split())


def test_s038_22_triage_has_a_reports_from_other_repos_section_for_the_coordinator() -> None:
    reports = flat(section(doc(TRIAGE / "SKILL.md"), "## Reports from other repos"))
    # routes with the product token and links each issue as the report's child
    assert "shipmill gh --product <owner/repo> issue create -R <owner/repo>" in reports
    assert "chains.py link --product <owner/repo#report> --child <owner/repo#issue>" in reports
    assert "ROUTE_DUE" in reports and "link owner/repo#N" in reports
    # asks through needs-decision when it can't tell the owner
    ask = reports.split("**Ask when you can't tell the owner:**", 1)[1].split("- **", 1)[0]
    assert "needs-decision protocol" in ask and "D-21" in ask and "shipmill gh --product" in ask
    assert "ANSWERED" in ask
    # closes with a summary of each child, how it closed, and its pull request
    close = reports.split("**CLOSE_DUE, close it:**", 1)[1].split("- **", 1)[0]
    for part in ("summary", "each child", "how it closed", "the pull request that closed it"):
        assert part in close, part
    assert "as completed, or as not planned" in close and "`not_planned`" in close
    # never writes code, branches, pull requests, or merges outside the home repo
    assert (
        "never changes files, pushes, creates a branch, opens a pull request, or merges outside the home repo (D-47)"
        in reports
    )
    assert "never plans the product" in reports
    # the home repo's report routes too, its link through the session's own token (S-038-29, #596)
    assert "can't link it yet" not in reports
    assert "A report in the home repo itself is routed the same way" in reports
    assert "`chains.py link --product` writes its link through that token too" in reports
    # the coordinator's session finds the section from Take stock and the scripts table
    skill = doc(TRIAGE / "SKILL.md")
    assert "scripts/upstream_state.py <owner/repo> --bot-login '<slug>[bot]'" in skill
    assert "| `scripts/upstream_state.py <owner/home>` |" in skill


def test_s038_23_comments_has_the_upstream_report_and_clarify_files_nothing_upstream() -> None:
    comments = doc(TRIAGE / "references" / "comments.md")
    report = section(comments, "## Upstream report")
    for heading in ("## Reproduce", "## Touches", "## Suspected code"):
        assert f"\n{heading}\n" in report, heading
    assert "starts with `Guess:`" in report
    assert "labelled `upstream`" in report and "--label upstream --body-file" in report
    assert "Stands in for owner/repo#N" in report
    assert "chains.py link <owner/repo#N> --blocked-by <owner/repo#R>" in report
    # the triage comment's two variants: routed by the coordinator, or waiting on the maintainer
    variants = [line for line in report.splitlines() if line.startswith("Triage: **upstream**.")]
    assert variants == [
        "Triage: **upstream**. Routed by {owner/home}, the product's coordinator: it files the work in the "
        "repos that own it and closes this with what changed.",
        "Triage: **upstream**. No coordinator routes it: it waits for @{maintainer}, who reports it to the "
        "owning repo and closes this with what changed.",
    ]
    assert all("implement" not in v for v in variants)  # triage_state.py would read NEEDS_PR
    # the coordinator's close lists each child, how it closed, and its pull request
    assert "- {owner/repo#C}: {completed | not planned}, {by owner/repo#PR | with no pull request}" in report
    # the Clarify template no longer files upstream itself
    clarify = section(comments, "## Clarify")
    assert "Filed upstream as" not in comments
    assert "upstream report in this repo" in clarify


def test_s038_23_the_rubric_has_a_component_write_a_stand_in() -> None:
    rubric = doc(TRIAGE / "references" / "triage-rubric.md")
    links = flat(section(rubric, "## Links between issues"))
    component = links.split("**In a component**", 1)[1]
    assert "`[product] home`" in component and "exits 2" in component
    assert "as a stand-in instead of a direct `Depends on owner/repo#N` line" in component
    assert "labelled `upstream`" in component and "Stands in for owner/repo#N" in component
    assert "chains.py link <owner/repo#N> --blocked-by <owner/repo#S>" in component
    assert "File an issue on the spec repo" not in rubric


def test_s038_23_resolve_phase_2_has_the_upstream_verdict() -> None:
    resolve = doc(ROOT / "skills" / "github-issue-resolve" / "SKILL.md")
    phase = section(resolve, "## Phase 2: Triage")
    [row] = [line for line in phase.splitlines() if line.startswith("| The cause is in a module another repo owns")]
    assert "(**upstream**)" in row
    assert "Report it in this repo, never in the other one" in row and "labelled `upstream`" in row
    for part in ("Reproduce", "Touches", "Suspected code", "`Guess:`"):
        assert part in row, part
    assert "chains.py link <owner/repo#N> --blocked-by <owner/repo#R>" in row
    assert (
        "Never file an issue in another repo, vendor the other module, patch an installed dependency, "
        "or open a pull request elsewhere" in row
    )
    # the step that filed an issue on another repo is gone from Phase 2
    assert "file an issue on the spec repo" not in phase
    triage = doc(TRIAGE / "SKILL.md")
    assert "file the gap on the spec repo" not in triage and "file an issue there and link it" not in triage
