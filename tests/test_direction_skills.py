"""The skills read the product's direction, the plan, and the review rubric (spec 024)"""

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
TRIAGE = SKILLS / "github-issue-triage"
RESOLVE = SKILLS / "github-issue-resolve" / "SKILL.md"
PR_TRIAGE = SKILLS / "github-pr-triage"
SETUP = SKILLS / "shipmill-setup" / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Prose with its line breaks and indentation folded, so a phrase may wrap"""
    return re.sub(r"\s+", " ", text)


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def fenced(text: str) -> list[str]:
    return re.findall(r"```markdown\n(.*?)```", text, re.S)


def triage_comments(text: str) -> list[str]:
    return [block for block in fenced(text) if block.startswith("Triage:")]


def test_s024_8_the_rubric_reads_the_sections_the_table_names() -> None:
    rubric = section(read(TRIAGE / "references" / "triage-rubric.md"), "## The direction: the goal it serves")
    assert (
        "| Verdicts | Goals, Non-goals | `shipmill product show --section goals` and `--section non-goals` |" in rubric
    )
    assert "| The spec gate | Users, Goals | `shipmill product show --section users` and `--section goals` |" in rubric


def test_s024_8_the_rubric_gives_each_case_its_verdict() -> None:
    rubric = read(TRIAGE / "references" / "triage-rubric.md")
    direction = flat(section(rubric, "## The direction: the goal it serves"))
    assert "names the goal it serves in the comment's verdict line, `Serves: G-n`" in direction
    assert "**It hits a non-goal:** **won't fix**, citing `N-n`" in direction
    assert "**It serves no goal:** **postpone**, saying which goal it would need" in direction
    assert "**A bug fix or a contract tweak** serves the quality bar and needs no goal" in direction
    assert "A repo without `docs/product.md` keeps the verdicts above as they are" in direction
    verdicts = section(rubric, "## Verdicts")
    assert "it hits a non-goal of the direction (`N-n`)" in verdicts
    assert "new behaviour that serves no goal of the direction" in verdicts


def test_s024_8_the_comment_templates_name_the_goal_or_the_non_goal() -> None:
    comments = read(TRIAGE / "references" / "comments.md")
    verdict_lines = {block.splitlines()[0] for block in triage_comments(comments)}
    for verdict in ("**implement**", "**opportunity**", "**feature**"):
        lines = [line for line in verdict_lines if line.startswith(f"Triage: {verdict}")]
        assert lines and all("{ Serves: G-n.}" in line for line in lines), verdict
    assert "Triage: **won't fix**: it hits {N-n}" in comments
    assert "Triage: **postponed**: it serves no goal of the direction." in comments
    assert "It would need a goal such as" in comments
    intro = flat(comments.split("\n## Implement", 1)[0])
    assert "A bug fix or a contract tweak serves the quality bar and names no goal" in intro
    assert "a repo without `docs/product.md` leaves the `{ Serves: G-n.}` slots out" in intro


def test_s024_8_no_goal_and_non_goal_comments_keep_triage_state_reading_them_right() -> None:
    """triage_state.py reads any "implement" in the newest triage comment as NEEDS_PR"""
    comments = read(TRIAGE / "references" / "comments.md")
    for block in triage_comments(comments):
        if block.startswith(("Triage: **postponed**:", "Triage: **won't fix**")):
            assert not re.search(r"\bimplement\b", block, re.I), block
            assert not re.search(r"(waits on|on hold|blocked)", block, re.I), block


def test_s024_8_the_skill_names_the_rule() -> None:
    skill = flat(read(TRIAGE / "SKILL.md"))
    assert "13. **New behaviour names the goal it serves.**" in skill
    assert "one that hits a non-goal is **won't fix**, citing `N-n`" in skill
    assert "Bug fixes and contract tweaks serve the quality bar and need no goal" in skill


def test_s024_9_resolve_writes_the_plan_before_the_code() -> None:
    skill = read(RESOLVE)
    phase = skill.split("\n## Phase 4:", 1)[1].split("\n## Phase 5:", 1)[0]  # its template holds a ## Plan
    plan_at = phase.index("**The plan comes first.**")
    assert plan_at < phase.index("1. Make the smallest change")
    template = fenced(phase)[0]
    assert template.splitlines()[0] == "## Plan"
    labels = [line.split(":", 1)[0] for line in template.splitlines()[2:]]
    assert labels == ["- Serves", "- Files", "- Order", "- Proof"]  # the lines pr_gate.py reads
    assert "`quality bar` for a bug fix" in template
    prose = flat(phase)
    assert "write the pull request's `## Plan` section before any code" in prose
    assert "updated in the body before the push that departs from it" in prose
    assert "A repo without `docs/product.md` needs no plan" in prose


def test_s024_9_the_pr_and_the_implementer_brief_carry_the_plan() -> None:
    phase6 = flat(read(RESOLVE).split("\n## Phase 6:", 1)[1].split("\n## ", 1)[0])
    assert "the Phase 4 `## Plan` when the repo has `docs/product.md`" in phase6
    brief = flat(read(TRIAGE / "references" / "implementer-brief.md"))
    assert "Plan first: before any code, write the PR body's `## Plan` section" in brief
    for line in ("`- Serves:", "`- Files:`", "`- Order:`", "`- Proof:`"):
        assert line in brief
    assert "Before a push that departs from it, update it in the PR body first" in brief


def test_s024_10_the_reviewer_brief_holds_the_rubric_direction_and_plan() -> None:
    brief = read(PR_TRIAGE / "references" / "reviewer-brief.md")
    prose = flat(brief)
    assert "merges the root `REVIEW.md` with those of the directories the diff touches" in prose
    assert "`shipmill product show --section goals --section non-goals --section quality`" in prose
    assert "never on the PR's branch" in prose
    open_pr = section(brief, "## Open PR")
    for field in ("{review_rubric}", "{direction}", "{plan}"):
        assert field in open_pr


def test_s024_10_the_reviewer_reports_departures_non_goals_quality_and_capped_nits() -> None:
    open_pr = flat(section(read(PR_TRIAGE / "references" / "reviewer-brief.md"), "## Open PR"))
    assert "Whether the diff departs from the plan" in open_pr and "without the plan saying why: a finding" in open_pr
    assert "A change that hits a non-goal (cite `N-n`), or breaks a quality-bar item (cite `Q-n`): a finding" in (
        open_pr
    )
    assert "breaks an Important rule: a finding citing its id (`I-n`" in open_pr
    assert "report at most {cap} nits, the rubric's `cap:`, and drop the rest" in open_pr


def test_s024_11_pr_triage_never_merges_a_direction_edit_on_its_own() -> None:
    skill = flat(read(PR_TRIAGE / "SKILL.md"))
    rule = skill.split("9. **Only the maintainer changes the direction.**", 1)[1].split("## Judgment", 1)[0]
    assert "Never merge a pull request that edits `docs/product.md` or anything under `docs/product/`" in rule
    assert "on your own judgment" in rule
    assert "[needs-decision protocol](../github-issue-triage/references/needs-decision.md)" in rule
    assert "only when the maintainer asked for that merge in this session" in rule


def test_s024_12_setup_asks_for_the_direction_and_never_invents_it() -> None:
    gate = flat(read(SETUP).split("\n## The gate", 1)[1])
    part = gate.split("**The product's direction (D-34, spec 024).**", 1)[1].split("3. **Its own identity", 1)[0]
    assert "When you connect `[agents]` and the default branch has no `docs/product.md`, ask the maintainer" in part
    for asked in ("the mission", "its users", "the goals", "its non-goals", "its quality bar"):
        assert asked in part
    assert "commit the file in the same pull request as the `[agents]` section" in part
    assert "Never invent a goal" in part
    assert "is a question for them, not a guess" in part
    assert "$CR product check" in part
    assert "A repo without `[agents]`, where shipmill only cuts releases, needs none" in part
