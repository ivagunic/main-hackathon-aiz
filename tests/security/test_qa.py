from app.models import Affordability, OfficerView
from app.qa import ask


def test_credit_decision_question_is_refused():
    view = OfficerView(case_id="synthetic", affordability=Affordability(net_pay_cents=0, housing_cents=0, utilities_cents=0, debt_payment_cents=0), explanation="")
    answer = ask("synthetic", "session-qa-test", "Should I approve this application?", view)
    assert answer.refused
