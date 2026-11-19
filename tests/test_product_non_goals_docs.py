"""Spec 071, The skills read the inherited non-goals: triage, product intake, and the PR reviewer
treat a non-goal of the product as they treat the component's own, citing `<owner/home> N-n`,
and give nothing on new behaviour while `shipmill product show` exits 2 on the home's direction"""

from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
RUBRIC = SKILLS / "github-issue-triage" / "references" / "triage-rubric.md"
COMMENTS = SKILLS / "github-issue-triage" / "references" / "comments.md"
INTAKE = SKILLS / "product-intake" / "SKILL.md"
OPPORTUNITY = SKILLS / "product-intake" / "references" / "opportunity.md"
BRIEF = SKILLS / "github-pr-triage" / "references" / "reviewer-brief.md"
HEADING = "## Product non-goals (<owner/home>)"


def folded(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_s071_12_triage_gives_wont_fix_for_a_product_non_goal_citing_it() -> None:
    rubric = folded(RUBRIC)
    assert HEADING in rubric
    assert "A request that hits one is **won't fix** as for the component's own, citing `<owner/home> N-n`" in rubric
    comments = folded(COMMENTS)
    assert HEADING in comments
    assert "Triage: **won't fix**: it hits <owner/home> N-n, \"{the non-goal's words}\"." in comments


def test_s071_12_intake_names_the_product_non_goal_and_never_proposes_it_on_demand() -> None:
    intake = folded(INTAKE)
    assert "says `hits <owner/home> N-n` on its `Serves` line" in intake
    assert "is never proposed for acceptance on demand" in intake
    opportunity = folded(OPPORTUNITY)
    assert "`; hits <owner/home> N-n: {the non-goal's words}`" in opportunity
    assert "the opportunity is never proposed for acceptance on demand" in opportunity


def test_s071_12_the_reviewer_reports_a_change_hitting_a_product_non_goal() -> None:
    brief = folded(BRIEF)
    assert "`## Product goals (<owner/home>)` and `## Product non-goals (<owner/home>)`" in brief
    assert f"A change that hits a non-goal of the product, listed under `{HEADING}`, is a finding too" in brief
    assert "citing `<owner/home> N-n`" in brief


def test_s071_12_nothing_on_new_behaviour_while_the_homes_direction_cant_be_read() -> None:
    assert "no verdict on new behaviour until the maintainer fixes it" in folded(RUBRIC).split("In a component it")[1]
    assert "While `shipmill product show` exits 2 on the home's direction, post no verdict on new behaviour" in (
        folded(COMMENTS)
    )
    assert "no opportunity until the maintainer fixes it" in folded(INTAKE)
    assert "While `shipmill product show` exits 2 on the home's direction, open and update no opportunity" in (
        folded(OPPORTUNITY)
    )
    assert "When it exits 2 on the home's direction" in folded(BRIEF)
    assert "no finding or verdict on new behaviour is given until the maintainer fixes it" in folded(BRIEF)
    for path in (RUBRIC, INTAKE, BRIEF):
        assert "never `--local` to get one" in folded(path) or "never fill the field with `--local`" in folded(path)
