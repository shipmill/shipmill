"""#1680: a goal plan that also waits on a needs-decision question is that question's alone
in `shipmill status`, as fleet.py queue lists an item in QUESTION in no other kind (S-069-6)"""

from shipmill.status import Issue, report

from .test_status_picture import facts, lines
from .test_status_plan_waits import URL, plan_row


def test_a_plan_with_a_question_waits_on_the_question_alone() -> None:
    found = report(facts(plan_row("#23 #25"), issues=[Issue(23, "NEEDS_DECISION")]))
    assert [r.text for r in found.reasons] == [
        "issue #23 waits on your decision",
        f"goal plan #25 {URL}/issues/25 waits on your answer",
    ]
    text = lines(facts(plan_row("#23 #25"), issues=[Issue(23, "NEEDS_DECISION")]))
    assert f"  goal plan      #25 {URL}/issues/25" in text
    assert not any(line.startswith("  goal plan      #23") for line in text)
