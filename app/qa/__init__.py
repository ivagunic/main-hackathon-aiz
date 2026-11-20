from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import OfficerView

PROTECTED = re.compile(r"\b(muslim|religion|religious|union member|union members|health condition|wellbeing|well-being|political|sexual life)\b", re.IGNORECASE)
DECISION = re.compile(r"\b(should i approve|should we approve|approve this|risk score|credit score|recommendation|would you approve|would you recommend|recommend this loan|is this applicant eligible)\b", re.IGNORECASE)
HIDDEN = re.compile(r"\b(hidden|withheld|concealed|translate the hidden|which organisations|which organizations|who receives|recipient organisation|recipient organization|what day|day of the week|spend on)\b", re.IGNORECASE)


@dataclass
class Answer:
    text: str
    refused: bool = False
    rule_id: str | None = None
    citation: str | None = None


_history: dict[str, list[str]] = {}


def reset_sessions() -> None:
    _history.clear()


def ask(case_id: str, session_id: str, question: str, view: OfficerView) -> Answer:
    normalized = " ".join(question.casefold().split())
    history = _history.setdefault(f"{case_id}:{session_id}", [])
    history.append(normalized)
    combined = " ".join(history)
    if DECISION.search(combined):
        return Answer("I can’t make or recommend a credit decision. That decision remains with the officer.", True, "R-QA-DECISION", "Officer retains decision responsibility")
    if PROTECTED.search(combined):
        return Answer("I can’t infer or reveal protected characteristics or sensitive personal information.", True, "R-QA-PROTECTED", "Data minimisation")
    if HIDDEN.search(combined) and view.hidden_summary:
        return Answer("I can only discuss information available in the officer view; hidden transaction details are withheld.", True, "R-QA-HIDDEN", "Data minimisation")
    if "housing" in normalized or "rent" in normalized or "huur" in normalized:
        return Answer(f"The recorded housing amount is {view.affordability.housing_cents} cents.")
    if "utilities" in normalized or "energy" in normalized or "energie" in normalized:
        return Answer(f"The recorded utilities amount is {view.affordability.utilities_cents} cents.")
    if "debt" in normalized or "loan repayment" in normalized:
        return Answer(f"The recorded debt payment is {view.affordability.debt_payment_cents} cents.")
    if "income" in normalized or "net salary" in normalized:
        return Answer(f"The recorded printed net pay is {view.affordability.net_pay_cents} cents.")
    return Answer("I can explain the displayed net pay, housing, utilities, or debt-payment figures.")
