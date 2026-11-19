"""The skills read the product's direction, the plan, and the review rubric (spec 024)"""

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
TRIAGE = SKILLS / "github-issue-triage"
RESOLVE = SKILLS / "github-issue-resolve" / "SKILL.md"
PR_TRIAGE = SKILLS / "github-pr-triage"
SETUP = SKILLS / "shipmill-setup" / "SKILL.md"
INTAKE = SKILLS / "product-intake"


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
    assert "a **feature** (new behaviour the maintainer already wants) gets **postpone**" in direction
    assert "**A user's request that serves no goal** still gets **opportunity** and goes to product intake" in direction
    assert "not handed to product intake" not in direction
    assert "**A bug fix or a contract tweak** serves the quality bar and needs no goal" in direction
    assert "A repo without `docs/product.md` keeps the verdicts above as they are" in direction
    verdicts = section(rubric, "## Verdicts")
    assert "it hits a non-goal of the direction (`N-n`)" in verdicts
    assert "a feature that serves no goal of the direction" in verdicts


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
    assert "a **feature** that serves no goal is **postpone**" in skill
    assert "a user's request that serves no goal still goes to product intake as an **opportunity**" in skill
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
    serves = template.splitlines()[2]
    assert "quality bar, as two plain words, for a bug fix" in serves
    assert "`" not in serves  # copied literally, a backticked `quality bar` fails pr_gate.py's Serves check
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


def _phase4() -> str:
    return flat(read(RESOLVE).split("\n## Phase 4:", 1)[1].split("\n## Phase 5:", 1)[0])


def test_s076_12_resolve_writes_kind_and_tests_changed_in_the_plan() -> None:
    phase = _phase4()
    assert "**Say what kind of change it is (spec 076).**" in phase
    assert "a bug fix whose proof is a new or changed test adds `- Kind: fix`" in phase
    assert "a change meant to leave behaviour as it is adds `- Kind: refactor`" in phase
    assert "any other change writes no `Kind:` line" in phase
    assert "`- Tests changed:` names each existing test file the change had to edit" in phase
    assert "in backticks, each followed by `: ` and its reason, entries separated by `;`" in phase
    assert "`pr_gate.py` reads neither line" in phase
    # the template keeps the four lines pr_gate.py reads (S-024-9); the two optional lines sit outside it
    assert "Kind:" not in fenced(read(RESOLVE).split("\n## Phase 4:", 1)[1].split("\n## Phase 5:", 1)[0])[0]


def test_s076_12_a_fix_commits_its_test_first_and_a_refactor_leaves_tests_alone() -> None:
    phase = _phase4()
    assert "**A `Kind: fix` change commits its test first and alone.**" in phase
    assert "The first commit touches test files only and holds the new or changed test" in phase
    assert "the fix comes in the commits after it" in phase
    assert "no later commit removes or changes a line of the files that first commit touched" in phase
    assert "**A `Kind: refactor` change leaves existing test files alone.**" in phase
    assert "It modifies, deletes, or renames no test file the default branch has" in phase
    assert "commit that test on its own, before the fix" in phase


def test_s076_12_the_implementer_brief_and_the_test_gate_carry_the_commit_order() -> None:
    brief = flat(read(TRIAGE / "references" / "implementer-brief.md"))
    assert "Commit order (spec 076): a bug fix proven by a new or changed test (`Kind: fix`)" in brief
    assert "commits that test first and alone, a commit touching test files only" in brief
    assert "then the fix in the commits after it" in brief
    assert "a refactor (`Kind: refactor`) leaves existing test files alone" in brief
    assert "plus `- Kind: fix`" in brief and "`- Kind: refactor`" in brief and "`- Tests changed:`" in brief
    gate = flat(section(read(RESOLVE.parent / "references" / "test-gate.md"), "## Commit order"))
    assert "A new or changed test is committed before the fix (spec 076)" in gate
    assert "its own first commit, touching test files only" in gate


def _open_pr_brief() -> str:
    return section(read(PR_TRIAGE / "references" / "reviewer-brief.md"), "## Open PR")


def test_s076_13_the_open_pr_brief_runs_test_proof_after_the_rebase_before_own_fixes() -> None:
    brief = _open_pr_brief()
    step2 = flat(brief.split("\n2. ", 1)[1].split("\n3. ", 1)[0])
    assert "{When the brief's plan has a `Kind:` line:} Test proof (spec 076)" in step2
    assert "after the rebase and before any fix of your own" in step2
    # The PR's own base, not the default branch: a stacked PR's range from the default branch
    # starts with its base PR's commits, which `fix` would read as the test commit (#1410)
    assert "`{test_proof_script} <kind> --base origin/{base} --plan-file tmp/pr-{N}-body.md --" in step2
    assert "--base origin/{default}" not in step2
    step1 = flat(brief.split("\n1. ", 1)[1].split("\n2. ", 1)[0])
    assert "Rebase onto origin/{base} locally" in step1
    fields = flat(read(PR_TRIAGE / "references" / "reviewer-brief.md").split("## Open PR", 1)[0])
    assert "- `{base}`: the PR's base branch, its `baseRefName`" in fields
    assert "`UNPROVEN` is a finding quoting its `fail:` lines" in step2
    assert "`NO_TEST` on a `Kind: fix` plan is a finding" in step2
    assert "`BASELINE_RED` is the base's failure, reported as such and not a finding against the PR" in step2
    assert brief.index("\n1. ") < brief.index("Test proof (spec 076)") < brief.index("\n4. Reproduce each real bug")


def test_s076_13_a_missing_kind_line_is_a_finding_and_the_report_holds_a_test_proof_line() -> None:
    brief = _open_pr_brief()
    step3 = flat(brief.split("\n3. ", 1)[1].split("\n4. ", 1)[0])
    assert "calls it a bug fix with a new or changed test, or a refactor, while its plan has no `Kind:` line" in step3
    step5 = flat(brief.split("\n5. ", 1)[1])
    assert 'a "Test proof" line with `test_proof.py`\'s verdict' in step5
    assert "which goes into the review record" in step5


def test_s076_13_the_post_merge_brief_has_none_of_it_and_the_scripts_table_lists_it() -> None:
    post = section(read(PR_TRIAGE / "references" / "reviewer-brief.md"), "## Post-merge review")
    for word in ("test_proof", "Kind:", "Test proof", "UNPROVEN", "BASELINE_RED", "NO_TEST"):
        assert word not in post
    table = read(PR_TRIAGE / "SKILL.md")
    assert "| `test_proof.py fix\\|refactor --base <ref> [--plan-file <file>] -- <command>` |" in table
    assert (PR_TRIAGE / "scripts" / "test_proof.py").is_file()


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


def _intake_rule() -> str:
    skill = flat(read(INTAKE / "SKILL.md"))
    rule = skill.split("8. **An opportunity names the goal it serves (D-34, spec 024).**", 1)[1]
    return rule.split("## The script", 1)[0]


def test_s024_18_intake_reads_goals_and_non_goals() -> None:
    skill = read(INTAKE / "SKILL.md")
    stock = skill.split("### 1. Take stock", 1)[1].split("### 2. Group", 1)[0]
    assert "shipmill product show --section mission --section users --section goals --section non-goals" in stock
    assert re.search(r"uvx shipmill==\d+\.\d+\.\d+ product show", stock)  # the plugin's pinned CLI (spec 031)
    assert "open and update no opportunity that pass, and name the problem in the report" in flat(stock)
    assert "read its Mission, Users, Goals, and Non-goals" in _intake_rule()


def test_s024_18_an_opportunity_names_the_goal_it_serves_or_none() -> None:
    rule = _intake_rule()
    assert "body says `Serves: G-n` (several as `Serves: G-2, G-3`) or `Serves no goal`" in rule
    assert "Every opportunity issue's body says" in rule
    assert "One that hits a non-goal says `Serves no goal; hits N-n`" in rule
    assert "A repo without `docs/product.md` groups and recommends as before, with no `Serves` line" in rule
    reference = read(INTAKE / "references" / "opportunity.md")
    template = fenced(reference)[0]  # the opportunity issue's body, the file's first template
    assert template.startswith("Serves: {G-n}\n\n## Problem")
    prose = flat(reference)
    assert "`Serves: G-n`, several as `Serves: G-2, G-3`, or `Serves no goal`" in prose
    assert "`; hits N-n: {the non-goal's words}` when it hits a non-goal" in prose


def test_s024_18_the_accept_question_says_the_goal() -> None:
    rule = _intake_rule()
    assert "the accept question to the maintainer, intake's triage line on the opportunity" in rule
    assert "and its line in the report, says the same" in rule
    lines = section(read(INTAKE / "references" / "opportunity.md"), "## Intake's triage line on the opportunity")
    served, unserved = fenced(lines)[:2]
    assert served.startswith("Triage: **opportunity**.{ Serves: G-n.} ")
    assert unserved.startswith("Triage: **opportunity**. Serves no goal{; hits N-n:")
    report = flat(read(INTAKE / "SKILL.md")).split("## Report", 1)[1]
    assert "the goal it serves or that it serves none (rule 8)" in report


def test_s024_18_no_goal_is_never_proposed_for_acceptance_on_demand_alone() -> None:
    rule = _intake_rule()
    assert "an opportunity that serves no goal is never proposed for acceptance on demand alone" in rule
    assert "the maintainer adds the goal it would need to the direction, or declines it" in rule
    assert "intake still files it and never declines it itself (rule 4)" in rule
    unserved = fenced(section(read(INTAKE / "references" / "opportunity.md"), "## Intake's triage line"))[1]
    assert "demand alone doesn't make it a candidate" in unserved
    report = flat(read(INTAKE / "SKILL.md")).split("## Report", 1)[1]
    assert "never accept on its demand alone" in report


def test_s024_18_intake_comments_keep_triage_state_reading_them_right() -> None:
    """triage_state.py reads "implement" as NEEDS_PR and a hold phrase before #N as BLOCKED"""
    lines = section(read(INTAKE / "references" / "opportunity.md"), "## Intake's triage line on the opportunity")
    for block in fenced(lines):
        assert not re.search(r"\bimplement\b", block, re.I), block
        assert not re.search(r"(waits on|on hold|blocked)", block, re.I), block
