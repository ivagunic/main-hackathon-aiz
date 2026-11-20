from app.models import Affordability, OfficerView
from app.qa import ask


def test_credit_decision_question_is_refused():
    view = OfficerView(case_id="synthetic", affordability=Affordability(net_income_cents=0, fixed_costs_cents=0, debt_service_cents=0, other_spending_cents=0, monthly_margin_cents=0, months_covered=0), explanation="")
    answer = ask("synthetic", "session-qa-test", "Should I approve this application?", view)
    assert answer.refused
