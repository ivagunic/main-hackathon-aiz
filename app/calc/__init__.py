from __future__ import annotations

from app.models import Affordability, Element, LoanFile
from app.pseudo import identity_map, scrub

HOUSING_TERMS = ("rent", "huur", "housing", "woonlast", "hypotheek", "mortgage")
UTILITY_TERMS = ("energy", "energie", "electric", "water", "gas", "utilities", "nuts")
DEBT_TERMS = ("loan", "lening", "credit repayment", "aflossing", "finance payment", "debt")
SALARY_TERMS = ("salary", "salaris", "payroll", "loon", "net pay")


def compute(file: LoanFile, elements: list[Element]) -> Affordability:
    # Sensitive (P4) and criminal (P5) transactions are excluded from every
    # aggregate, including positive salary-like credits.
    excluded_ids = {
        element.source_ref.removeprefix("tx:")
        for element in elements
        if element.category in {"special_category", "criminal"} and element.source_ref.startswith("tx:")
    }
    # Excluded lines must not influence the averaging period either (P4, P5).
    months = max(len({tx.date.strftime("%Y-%m") for tx in file.transactions if tx.id not in excluded_ids}), 1)
    printed_net = sum(slip.net_cents for slip in file.payslips)
    # The applicant's own name and address never decide a budget category (P8).
    identity = identity_map(file)

    def line_text(tx) -> str:
        return scrub(f"{tx.counterparty} {tx.description}", identity).casefold()

    salary_credits = [
        tx for tx in file.transactions
        if tx.id not in excluded_ids and tx.amount_cents > 0
        and any(term in line_text(tx) for term in SALARY_TERMS)
    ]
    salary_credit_total = sum(tx.amount_cents for tx in salary_credits)
    net_pay = printed_net

    housing_total = utilities_total = debt_total = 0
    housing_refs: list[str] = []
    utilities_refs: list[str] = []
    debt_refs: list[str] = []
    for tx in sorted(file.transactions, key=lambda item: (item.date, item.id)):
        if tx.id in excluded_ids or tx.amount_cents >= 0:
            continue
        text = line_text(tx)
        amount = -tx.amount_cents
        if any(term in text for term in DEBT_TERMS):
            debt_total += amount
            debt_refs.append(tx.id)
        elif any(term in text for term in HOUSING_TERMS):
            housing_total += amount
            housing_refs.append(tx.id)
        elif any(term in text for term in UTILITY_TERMS):
            utilities_total += amount
            utilities_refs.append(tx.id)

    questions: list[str] = []
    if salary_credits and printed_net:
        difference = abs(salary_credit_total - printed_net) * 100 / max(printed_net, 1)
        if difference > 5:
            questions.append("Payslip net pay differs from salary credits; reconcile the source lines.")
    refs = {
        "net_pay": sorted([slip.id for slip in file.payslips] + [tx.id for tx in salary_credits]),
        "housing": sorted(housing_refs),
        "utilities": sorted(utilities_refs),
        "debt_payment": sorted(debt_refs),
    }
    return Affordability(
        net_pay_cents=net_pay,
        housing_cents=housing_total // months,
        utilities_cents=utilities_total // months,
        debt_payment_cents=(debt_total + file.application.declared_debts) // months,
        open_questions=questions,
        source_refs=refs,
    )
