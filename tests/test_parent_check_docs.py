"""Spec 042, #719: the instructions a session follows on a parent's ## Check: the rubric's and
comments.md's A parent's check, github-issue-triage's Chains and Reports from other repos, the
spec gate's check on a feature issue, and the upstream report's optional ## Check"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "skills" / "github-issue-triage"
SCRIPTS = TRIAGE / "scripts"


def doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body of a ``## heading`` section, up to the next heading of its level outside a
    code fence"""
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


def marker(script: str, name: str) -> str:
    """A marker constant as the script defines it, so the docs can't drift from the code"""
    found = re.search(rf'^{name} = "([^"]+)"$', doc(SCRIPTS / script), re.MULTILINE)
    assert found is not None, name
    return found.group(1)


VERIFIED = marker("triage_state.py", "VERIFIED_MARKER")
CHECK_FAILED = marker("triage_state.py", "CHECK_FAILED_MARKER")
OPTIONS = ("leave it open: I check it and close it by hand", "close it unchecked")


def test_s042_9_the_rubric_describes_a_parent_s_check() -> None:
    rubric = doc(TRIAGE / "references" / "triage-rubric.md")
    check = flat(section(rubric, "## A parent's check"))
    for state in ("| VERIFY_DUE |", "| CHECK_FAILED |", "| VERIFY_CLOSED |"):
        assert state in check, state
    assert "`children K/N closed`" in check and "`run its ## Check`" in check and "`check failed <date>`" in check
    assert f"`{VERIFIED}`" in check and f"`{CHECK_FAILED}`" in check
    # it holds: the close first, then the verified comment with the check and what came back
    holds = check.split("**It holds:**", 1)[1].split("- **", 1)[0]
    assert holds.index("gh issue close <n> --reason completed") < holds.index("then post the verified comment")
    assert "the check that ran, what came back" in holds
    # it fails: the check-failed comment, and the fix filed as a child
    assert "post the check-failed comment" in check.split("**It fails:**", 1)[1]
    assert "chains.py link <owner/repo#parent> --child <owner/repo#fix>" in check
    # not in production yet: no comment
    assert "**The change hasn't reached production yet**" in check
    assert "no comment and no close" in check.split("**The change hasn't reached production yet**", 1)[1]
    # can't run it: the needs-decision question with its two options
    cant = check.split("**The session can't run it**", 1)[1].split("- **", 1)[0]
    assert "needs-decision protocol" in cant and "(D-21)" in cant
    for option in OPTIONS:
        assert f'"{option}"' in cant, option
    # never writes to production
    assert "**Never a write to production.** A check only reads" in check
    # the flag table and UNBLOCKED name it
    flags = section(rubric, "## Flags from `triage_state.py`")
    assert "| CHECK_FAILED |" in flags and "A parent with a `## Check` never reads UNBLOCKED" in flags
    assert flags.count("[A parent's check](#a-parents-check)") >= 3


def test_s042_9_comments_has_a_parent_s_check_templates() -> None:
    comments = doc(TRIAGE / "references" / "comments.md")
    check = section(comments, "## A parent's check")
    blocks = re.findall(r"```markdown\n(.*?)```", check, re.DOTALL)
    first_lines = [b.splitlines()[0] for b in blocks]
    # the verified comment, the check-failed comment, the fix issue, and the question
    assert first_lines[0] == VERIFIED and "`{the check}` returned {what came back}" in blocks[0]
    assert first_lines[1] == CHECK_FAILED and "`{the check}` returned {what came back}" in blocks[1]
    assert "## Check of #{parent} fails in production" in blocks[2]
    assert first_lines[3] == "<!-- shipmill:needs-decision -->"
    question = blocks[3].splitlines()
    assert question[1].startswith("@{maintainer} Decision needed:")
    numbered = [line for line in question if re.match(r"\d\. ", line)]
    assert numbered[0].startswith("1. Leave it open: I check it and close it by hand (recommended):")
    assert numbered[1].startswith("2. Close it unchecked:")
    text = flat(check)
    # the close comes before the verified comment, never through close --comment
    assert (
        "close the parent as completed (`gh issue close <n> --reason completed`), then post the verified comment"
        in text
    )
    assert "Never post it with `gh issue close --comment`" in text
    assert "`chains.py link <owner/repo#parent> --child <owner/repo#fix>`" in text
    assert "**The change hasn't reached production yet**" in text and "no comment and no close" in text
    assert "never writes to production" in text
    # A parent's close points a parent with a check here
    assert "A parent with a `## Check` never takes this comment" in section(comments, "## A parent's close")


def test_s042_9_triage_skill_says_the_same_in_chains_and_reports() -> None:
    skill = doc(TRIAGE / "SKILL.md")
    chains = flat(section(skill, "## Chains"))
    parent = chains.split("**A parent's check.**", 1)[1].split("- **", 1)[0]
    assert f"`{VERIFIED}`" in parent and f"`{CHECK_FAILED}`" in parent
    assert "close the parent as completed, then post the verified comment with the check and what came back" in parent
    assert "`chains.py link <owner/repo#parent> --child <owner/repo#fix>`" in parent
    assert "The change hasn't reached production yet: no comment and no close" in parent
    assert "never writes to production" in parent
    for option in OPTIONS:
        assert f'"{option}"' in parent, option
    reports = flat(section(skill, "## Reports from other repos"))
    upstream = reports.split("**VERIFY_DUE, CHECK_FAILED:**", 1)[1].split("- **", 1)[0]
    assert "never writes to production" in upstream
    assert "the summary comment as CLOSE_DUE says, with the check and what came back, then close" in upstream
    assert f"`{CHECK_FAILED}`" in upstream
    assert "`chains.py link --product <owner/repo#report> --child <owner/repo#fix>`" in upstream
    assert "The change hasn't reached production yet: nothing" in upstream
    assert "needs-decision question on the report" in upstream and "shipmill gh --product" in upstream
    # a report without a check still closes as CLOSE_DUE says
    assert "one without a check reads CLOSE_DUE as before" in upstream


def test_s042_9_the_coordinator_takes_up_a_check_question_s_answer_without_routing() -> None:
    # upstream_state.py reads the question ASKED, then ANSWERED, before the check; the only
    # other ANSWERED line says "route it by the answer", which a check question's answer isn't
    skill = doc(TRIAGE / "SKILL.md")
    reports = flat(section(skill, "## Reports from other repos"))
    upstream = reports.split("**VERIFY_DUE, CHECK_FAILED:**", 1)[1].split("- **", 1)[0]
    asked = upstream.split("The coordinator can't run it:", 1)[1]
    assert "It reads ASKED until a trusted reply, then ANSWERED: remove the label, never route it" in asked
    unchecked = asked.split('on "close it unchecked",', 1)[1]
    assert unchecked.index("the summary comment as CLOSE_DUE says") < unchecked.index(
        "then close the report as completed"
    )
    assert "no check ran." in unchecked
    # comments.md says the same for a report: its summary, not the verified comment alone
    comments = flat(section(doc(TRIAGE / "references" / "comments.md"), "## A parent's check"))
    report = comments.split('On "close it unchecked"', 1)[1]
    assert "On a report, the coordinator posts the summary comment" in report


CHECK_WAITING = marker("triage_state.py", "CHECK_WAITING_MARKER")


def test_s042_13_leave_it_open_posts_the_check_waiting_comment() -> None:
    comments = section(doc(TRIAGE / "references" / "comments.md"), "## A parent's check")
    blocks = re.findall(r"```markdown\n(.*?)```", comments, re.DOTALL)
    [waiting] = [b for b in blocks if b.splitlines()[0] == CHECK_WAITING]
    # the login in a code span, which triage_state.py reads as it reads a bare one (D-61, #771)
    assert waiting.splitlines()[1].startswith('`@{login}` answered "leave it open":')
    assert 'On "leave it open", post the check-waiting comment' in flat(comments)
    rubric = flat(section(doc(TRIAGE / "references" / "triage-rubric.md"), "## A parent's check"))
    assert f"`{CHECK_WAITING}`" in rubric and "| WITH_PERSON |" in rubric
    assert 'on "leave it open", post the check-waiting comment naming who answered' in rubric
    skill = doc(TRIAGE / "SKILL.md")
    parent = flat(section(skill, "## Chains")).split("**A parent's check.**", 1)[1].split("- **", 1)[0]
    assert f'on "leave it open", post the `{CHECK_WAITING}` comment naming who answered' in parent
    reports = flat(section(skill, "## Reports from other repos"))
    upstream = reports.split("**VERIFY_DUE, CHECK_FAILED:**", 1)[1].split("- **", 1)[0]
    assert f'on "leave it open", the `{CHECK_WAITING}` comment naming who answered' in upstream
    assert "nothing more" not in upstream and "nothing more" not in parent


def test_s042_10_the_spec_gate_asks_for_a_check_and_drops_fixes_feature() -> None:
    gate = doc(TRIAGE / "references" / "spec-gate.md")
    split = flat(gate.split("### Split it into build issues", 1)[1].split("### Dispatch the build", 1)[0])
    ask = split.split("**Before the split, ask for a `## Check` on the feature issue when its build deploys**", 1)
    assert len(ask) == 2 and ask[1].index("add a `## Check` section to the feature issue's body") < ask[1].index(
        "1. **Propose the graph.**"
    )
    assert "A feature issue whose build doesn't deploy gets none" in ask[1]
    dispatch = flat(gate.split("### Dispatch the build", 1)[1].split("## Tests name the criteria", 1)[0])
    last = dispatch.split("**The last build issue:**", 1)[1].split("- **", 1)[0]
    assert (
        "For a feature issue with a `## Check`, the PR that closes the last build issue doesn't say `Fixes #<feature>`"
        in last
    )
    assert "reads VERIFY_DUE once that PR merges, and closes on its check" in last


def test_s042_11_the_upstream_report_has_an_optional_check() -> None:
    comments = doc(TRIAGE / "references" / "comments.md")
    report = section(comments, "## Upstream report")
    template = report.split("```markdown\n", 1)[1].split("```", 1)[0]
    assert "\n## Check\n" in template
    assert template.index("## Suspected code") < template.index("## Check")
    assert "{Optional, for a fault that shows in production:" in template
    assert "The `## Check` section is optional: add it when the fault shows in production" in flat(report)
    resolve = doc(ROOT / "skills" / "github-issue-resolve" / "SKILL.md")
    phase = section(resolve, "## Phase 2: Triage")
    [row] = [line for line in phase.splitlines() if line.startswith("| The cause is in a module another repo owns")]
    assert "an optional `## Check` for a fault that shows in production" in row
