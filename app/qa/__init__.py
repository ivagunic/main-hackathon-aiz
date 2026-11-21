from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field

from app import pipeline
from app.gateway import BraneBlocked, BraneUnavailable
from app.models import OfficerView
from app.pseudo import load_map, mask_identifiers, scrub

OFFLINE_ANSWER = "The safety check is offline, so the question was not sent."
SAFE_ANSWER = "I can only explain the four figures shown."
_AMOUNT = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[,.]\d{2})?(?![\w.,])")
PROTECTED = re.compile(
    r"\b(muslim|religion|religious|union member|union members|health condition|wellbeing|well-being|political|sexual life|"
    r"church|kerk\w*|mosque|moskee|synagog\w*|faith|godsdienst|geloof|religie|"
    r"pharmac\w*|apothe\w*|medic\w*|medicijn\w*|health|gezondheid|ziek\w*|doctor|huisarts|"
    r"union|vakbond|politi\w*|partij|party|dating|sexual\w*|"
    r"cjib|criminal|crimineel|strafblad|fines?|boetes?|reclassering|"
    r"bsn|national id\w*|burgerservicenummer|iban|account number|rekeningnummer|"
    r"name|naam|address|adres|employer|werkgever)\b",
    re.IGNORECASE,
)
DECISION = re.compile(
    r"\b(should i approve|should we approve|approve\w*|approval|risk\w*|score\w*|credit score|recommend\w*|"
    r"would you approve|eligib\w*|creditworth\w*|default probability|"
    r"goedkeur\w*|afwijz\w*|afkeur\w*|advies|advise\w*|aanrad\w*|aanbevel\w*|risico\w*|kredietwaardig\w*)\b",
    re.IGNORECASE,
)
HIDDEN = re.compile(
    r"\b(hidden|withheld|concealed|translate the hidden|which organisations|which organizations|which organisation|"
    r"which organization|organisation|organization|organisatie|who receives|who received|received it|recipient\w*|"
    r"what day|day of the week|spend on|left out|excluded|omitted|counterpart\w*|which shop|which line|which merchant|"
    r"donat\w*|verborgen|weggelaten|uitgesloten|tegenpartij|ontvanger)\b",
    re.IGNORECASE,
)


@dataclass
class Answer:
    text: str
    refused: bool = False
    rule_id: str | None = None
    citation: str | None = None
    brane_headers: dict[str, str] = field(default_factory=dict)
    brane_verdict: str | None = None
    payload_sha256: str | None = None
    aiz_decision: str = "block"
    # Empty means the question never reached BRANE (local refusal or fail-closed).
    checked_by: str = ""


_history: dict[str, list[str]] = {}


def reset_sessions() -> None:
    _history.clear()


def _amount_cents(value: str, *, cents_unit: bool = False) -> int:
    if cents_unit:
        return int(re.sub(r"\D", "", value))
    if "," in value and value.rfind(",") > value.rfind("."):
        normalized = value.replace(".", "").replace(",", ".")
    else:
        normalized = value.replace(",", "")
    whole, dot, fraction = normalized.partition(".")
    return int(whole) * 100 + int((fraction + "00")[:2]) if dot else int(whole)


def _answer_is_safe(text: str, view: OfficerView) -> bool:
    if pipeline._prohibited(text):
        return False
    # The fixture amounts are euro cents; a different currency symbol changes
    # the meaning even when the digits happen to match after cent conversion.
    if re.search(r"(?:[$£¥]\s*\d|\d\s*(?:USD|GBP)\b)", text, re.IGNORECASE):
        return False
    figures = {
        view.affordability.net_pay_cents,
        view.affordability.housing_cents,
        view.affordability.utilities_cents,
        view.affordability.debt_payment_cents,
    }
    try:
        for match in _AMOUNT.finditer(text):
            suffix = text[match.end():match.end() + 12]
            cents_unit = bool(re.match(r"\s*cents?\b", suffix, re.IGNORECASE))
            if _amount_cents(match.group(), cents_unit=cents_unit) not in figures:
                return False
        return True
    except ValueError:
        return False


def _plain_brane_refusal(reason: str) -> tuple[str, str]:
    value = reason.casefold()
    if "autonomous_credit_decision" in value:
        return ("Q-BRANE-CREDIT-DECISION",
            "Blocked by the bank's AI firewall: requests for a credit decision or recommendation are not allowed")
    if "proxy_attribute" in value:
        return ("Q-BRANE-PROXY", "Blocked by the bank's AI firewall: proxy attributes cannot be used to assess an applicant")
    if "national_id_bsn" in value or "ssn" in value or "tax_number" in value:
        return ("Q-BRANE-NATIONAL-ID", "Blocked by the bank's AI firewall: national identifiers are not processed")
    if "criminal_payment" in value:
        return ("Q-BRANE-CRIMINAL", "Blocked by the bank's AI firewall: criminal or probation details are not processed")
    if "sensitive_merchant" in value or "health_data" in value or "religious_belief" in value:
        return ("Q-BRANE-SENSITIVE", "Blocked by the bank's AI firewall: sensitive transaction details are not processed")
    return ("Q-BRANE-REFUSAL", "Blocked by the bank's AI firewall: this request is not allowed")


def _safe_verdict(verdict: str | None) -> str | None:
    if not verdict:
        return None
    try:
        value = json.loads(verdict)
    except (TypeError, ValueError):
        return None
    if isinstance(value, dict):
        value.pop("raw_response", None)
        return json.dumps(value, sort_keys=True, default=str)
    return None


LABEL_ALLOWED = "allowed"
LABEL_NAME_REPLACED = "name replaced"
LABEL_LOCAL = "kept inside the bank"
LABEL_BLOCKED = "blocked"
POSITIVE_LABELS = frozenset({LABEL_ALLOWED, LABEL_NAME_REPLACED, LABEL_LOCAL})


def brane_label(headers: dict[str, str] | None) -> str:
    """Plain label taken only from the X-Brane-Routed-To and X-Brane-Action headers of one request."""
    headers = headers or {}
    routed_to = pipeline._header(headers, "x-brane-routed-to").casefold()
    action = pipeline._header(headers, "x-brane-action").casefold()
    if routed_to == "refused" or action in {"refuse", "refused", "block", "blocked", "deny", "denied"}:
        return LABEL_BLOCKED
    if routed_to == "local" and action in {"allow", "local", "placeholder"}:
        return LABEL_LOCAL
    if routed_to == "cloud" and action == "placeholder":
        return LABEL_NAME_REPLACED
    if routed_to == "cloud" and action == "allow":
        return LABEL_ALLOWED
    return ""


def _offline() -> Answer:
    return Answer(OFFLINE_ANSWER, True, "Q-BRANE-OFFLINE", "Fail closed: BRANE safety verdict unavailable")


def ask(case_id: str, session_id: str, question: str, view: OfficerView) -> Answer:
    normalized = " ".join(question.casefold().split())
    session_key = f"{case_id}:{session_id}"
    history = _history.setdefault(session_key, [])

    # Existing local guards remain the first decision point; history still supports accumulation.
    prior = " ".join(history)
    direct_decision = DECISION.search(normalized) or DECISION.search(f"{prior} {normalized}")
    direct_protected = PROTECTED.search(normalized) or PROTECTED.search(f"{prior} {normalized}")
    direct_hidden = HIDDEN.search(normalized) or HIDDEN.search(f"{prior} {normalized}")
    try:
        mapping = load_map(case_id, pipeline.LEDGER.path)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        mapping = None
    scrubbed_question = scrub(question, mapping) if mapping else question
    safe_question = mask_identifiers(scrubbed_question)
    contains_identifier = safe_question != question
    history.append("[identifier redacted]" if contains_identifier else normalized)
    combined = " ".join(history)

    if direct_decision or DECISION.search(combined):
        return Answer("I can’t make or recommend a credit decision. That decision remains with the officer.",
            True, "R-QA-DECISION", "Officer retains decision responsibility")
    if direct_protected or PROTECTED.search(combined):
        return Answer("I can’t infer or reveal protected characteristics or sensitive personal information.",
            True, "R-QA-PROTECTED", "Data minimisation")
    if direct_hidden or HIDDEN.search(combined):
        return Answer("I can only discuss information available in the officer view; hidden transaction details are withheld.",
            True, "R-QA-HIDDEN", "Data minimisation")

    if os.getenv("PRESCRUB", "on").casefold() != "on" or mapping is None:
        return _offline()
    if any(value.casefold() in safe_question.casefold() for value, _token in mapping.replacements if value):
        return _offline()

    figures = view.affordability
    system = (
        f"net_pay_cents={figures.net_pay_cents}; housing_cents={figures.housing_cents}; "
        f"utilities_cents={figures.utilities_cents}; debt_payment_cents={figures.debt_payment_cents}. "
        f"{view.caveat}"
    )
    try:
        result = pipeline.get_cloud().complete_question(system, safe_question, case_id=case_id)
    except BraneBlocked as exc:
        decision = pipeline._brane_decision(exc.decision)
        rule_id, text = _plain_brane_refusal(decision.reason)
        # A refusal never carries answer text, whatever the label headers say.
        return Answer(text, True, rule_id, decision.reason or "BRANE refused the question",
            exc.response_headers, _safe_verdict(exc.decision), None, "block", LABEL_BLOCKED)
    except BraneUnavailable:
        return _offline()
    except Exception:  # noqa: BLE001 - every gateway or validation error fails closed
        return _offline()

    # The label comes from the stored decision record of this exact request.
    decision = pipeline._brane_decision(result.verdict)
    label = brane_label(_verdict_headers(result.verdict))
    if decision.refused or label == LABEL_BLOCKED:
        rule_id, text = _plain_brane_refusal(decision.reason)
        return Answer(text, True, rule_id, decision.reason or "BRANE refused the question",
            result.response_headers, _safe_verdict(result.verdict), result.payload_sha256, "block", LABEL_BLOCKED)
    if not decision.positive or label not in POSITIVE_LABELS:
        return _offline()

    aiz_decision = {LABEL_LOCAL: "local only", LABEL_NAME_REPLACED: "protect", LABEL_ALLOWED: "allow"}[label]
    if not _answer_is_safe(result.text, view):
        return Answer(SAFE_ANSWER, False, "P13", "Only verified local figures may be stated",
            result.response_headers, _safe_verdict(result.verdict), result.payload_sha256, aiz_decision, label)
    return Answer(result.text, False, "P13", "Answer checked against locally computed figures",
        result.response_headers, _safe_verdict(result.verdict), result.payload_sha256, aiz_decision, label)


def _verdict_headers(verdict: str | None) -> dict[str, str]:
    try:
        record = json.loads(verdict or "")
    except (TypeError, ValueError):
        return {}
    headers = record.get("headers") if isinstance(record, dict) else None
    return {str(k): str(v) for k, v in headers.items()} if isinstance(headers, dict) else {}
