from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.calc import compute
from app.classify import classify
from app.gateway import BraneBlocked, BraneUnavailable, get_cloud, outbound_guard
from app.hardship import detect
from app.intake import load_file
from app.models import Affordability, Element, OfficerView
from app.policy import Ledger, load_policy, record, route
from app.pseudo import (
    LeakDetected,
    assert_clean,
    build_map,
    mask_identifiers,
    restore,
    scrub,
    store_map,
)

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Ledger(os.getenv("LEDGER_PATH", str(ROOT / "ledger.sqlite3")))
EVENTS: dict[str, list[dict]] = {}
VIEWS: dict[str, OfficerView] = {}
ACTIVE_POLICY_VERSION = "v1"
OUTBOUND_FIELDS = ("net_pay_cents", "housing_cents", "utilities_cents", "debt_payment_cents")
PROHIBITED_DRAFT = re.compile(
    r"\b(approv\w*|reject\w*|score\w*|risk\w*|recommend\w*|"
    r"aanbevel\w*|aanbevol\w*|aanraad\w*|aanrad\w*|advis\w*|adviseer\w*|advies|goedkeur\w*|goedgekeur\w*|afkeur\w*|afgekeur\w*|"
    r"afwijz\w*|afgewez\w*|risico\w*|beoordel\w*)\b",
    re.IGNORECASE,
)
# Stems checked again after removing spacing, punctuation and look-alike digits ("a p p r o v e", "sc0re").
_PROHIBITED_STEMS = ("approv", "reject", "score", "risk", "recommend", "aanbevel", "aanbevol", "aanraad", "aanrad", "advis",
    "advies", "goedkeur", "goedgekeur", "afkeur", "afgekeur", "afwijz", "afgewez", "risico", "beoordel")
_LEET = str.maketrans("013457@$", "oieastas")
MAX_CENTS = 10**9  # EUR 10 million: anything larger is not a plausible monthly figure


def _prohibited(text: str) -> bool:
    import unicodedata

    folded = unicodedata.normalize("NFKC", text).casefold()
    visible = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    if PROHIBITED_DRAFT.search(visible):
        return True
    collapsed = re.sub(r"[^a-z]", "", "".join(ch for ch in unicodedata.normalize("NFKD", visible.translate(_LEET)) if not unicodedata.combining(ch)))
    return any(stem in collapsed for stem in _PROHIBITED_STEMS)


def validate_cloud_payload(payload: dict) -> None:
    """Reject extra fields, non-integer and out-of-range values before gateway dispatch."""
    if not isinstance(payload, dict) or set(payload) != set(OUTBOUND_FIELDS):
        raise ValueError("Outbound payload must contain exactly four approved fields")
    if any(type(payload[name]) is not int for name in OUTBOUND_FIELDS):
        raise TypeError("Outbound values must be integers")
    if any(not 0 <= payload[name] <= MAX_CENTS for name in OUTBOUND_FIELDS):
        raise ValueError("Outbound values must be non-negative and within range")


def _figures(affordability: Affordability) -> dict[str, int]:
    return {field: getattr(affordability, field) for field in OUTBOUND_FIELDS}


_ROUTED_OK = {"cloud", "local"}
_ACTION_OK = {"allow", "placeholder", "local"}


@dataclass(frozen=True)
class BraneDecision:
    """What the stored X-Brane headers say happened to a request."""

    status: int | None = None
    routed_to: str = ""
    action: str = ""
    reason: str = ""

    @property
    def positive(self) -> bool:
        # Positive only when HTTP 200 AND routed to cloud/local AND an allowing action.
        return self.status == 200 and self.routed_to in _ROUTED_OK and self.action in _ACTION_OK

    @property
    def refused(self) -> bool:
        return self.status == 422 or self.routed_to == "refused"


def _header(headers: dict, name: str) -> str:
    return next((str(v).strip() for k, v in headers.items() if str(k).casefold() == name), "")


def _brane_decision(verdict: str | None) -> BraneDecision:
    """Read the gateway's decision record. Anything missing or unreadable yields a non-positive decision."""
    if os.getenv("BRANE_MODE", "fake") == "fake" and verdict == "allow":
        # FakeBrane test double (no network, no headers). Its stored verdict stays the plain "allow",
        # so the record never claims a real routing; live mode never takes this branch.
        return BraneDecision(200, "cloud", "allow")
    try:
        record = json.loads(verdict or "")
    except (TypeError, ValueError):
        return BraneDecision()
    if not isinstance(record, dict) or not isinstance(record.get("headers"), dict):
        return BraneDecision()
    status = record.get("status_code")
    headers = record["headers"]
    reason = _header(headers, "x-brane-refused-by") or _header(headers, "x-brane-policy-triggers")
    reason = mask_identifiers(" ".join(reason.split()))[:200]
    return BraneDecision(status if type(status) is int else None, _header(headers, "x-brane-routed-to").casefold(),
        _header(headers, "x-brane-action").casefold(), reason)


def _positive_brane_verdict(verdict: str) -> bool:
    return _brane_decision(verdict).positive


def _ledger_verdict(verdict: str) -> str:
    """Keep the decision (status, X-Brane headers, verdict fields) but never the model's raw response text (matrix D)."""
    try:
        value = json.loads(verdict)
    except (TypeError, ValueError):
        return verdict
    if isinstance(value, dict) and "raw_response" in value:
        value = {k: v for k, v in value.items() if k != "raw_response"}
        return json.dumps(value, sort_keys=True, default=str)
    return verdict


def _checked_draft(text: str, affordability: Affordability) -> str:
    values = _figures(affordability)
    allowed_numbers = {str(value) for value in values.values()}
    numbers = re.findall(r"(?<!\w)\d+(?:[,.]\d+)?", text)
    if _prohibited(text) or any(value not in allowed_numbers for value in numbers):
        text = "Template note: review the source documents and reconcile the listed figures."
    verified = "; ".join(f"{name}={value}" for name, value in values.items())
    return f"{text.strip()}\nVerified local figures: {verified}."


def _note_view(case_id: str, affordability: Affordability, note: str, *, received: bool) -> OfficerView:
    return OfficerView(case_id=case_id, affordability=affordability, explanation=note,
        flags=["human_review_required"], local_note=note, human_review_required=True,
        customer_message_status="customer message received" if received else "")


def process(case_id: str, path: str | Path | None = None) -> OfficerView:
    if path is None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", case_id):
        raise ValueError("Invalid case id")  # no separators, dots or drive letters in fixture lookups
    source = Path(path) if path else ROOT / "data" / "files" / f"{case_id}.json"
    loan = load_file(source)
    EVENTS[case_id] = [{"type": "case_started", "case_id": case_id, "ts": datetime.now(UTC).isoformat()}]
    try:
        elements = classify(loan)
        hardship = detect(loan.messages, loan) if os.getenv("HARDSHIP_ENABLED", "false").casefold() == "true" else []
        elements.extend(hardship)
        affordability = compute(loan, elements)
        pseudo_map = build_map(loan)
        store_map(case_id, pseudo_map, LEDGER.path)
        policy = load_policy(ROOT / "policy" / f"policy.{ACTIVE_POLICY_VERSION}.yaml")
        routed = [route(element, "calculate", policy) for element in elements]
    except Exception as exc:  # noqa: BLE001 - every protection failure stops egress
        if isinstance(exc, LeakDetected):
            EVENTS[case_id].append({"type": "blocked_before_brane", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
        blocked = Element(id=hashlib.sha1(f"{case_id}:fail-closed".encode()).hexdigest()[:12], source_ref="pipeline:check", kind="control", text="", category="neutral", detector="fail_closed", lane="refuse", rule_id="P12", citation="GDPR Arts. 25(1), 32(1); challenge brief (check-failure test)", brane_policy_ref="BRANE-P12-FAIL-CLOSED")
        record(case_id, blocked, ACTIVE_POLICY_VERSION, LEDGER)
        EVENTS[case_id].append({"type": "fail_closed", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
        empty = Affordability(net_pay_cents=0, housing_cents=0, utilities_cents=0, debt_payment_cents=0)
        view = OfficerView(case_id=case_id, affordability=empty, explanation="", flags=["fail_closed"])
        VIEWS[case_id] = view
        return view

    for seq, element in enumerate(routed, 1):
        record(case_id, element, policy["version"], LEDGER)
        EVENTS[case_id].append({"type": "element_routed", "case_id": case_id, "element_id": element.id,
            "seq": seq, "category": element.category, "lane": element.lane, "rule_id": element.rule_id,
            "citation": element.citation, "ts": datetime.now(UTC).isoformat()})
    if any(e.category == "instruction_attack" for e in elements):
        EVENTS[case_id].append({"type": "flag_raised", "flag": "attack_detected", "ts": datetime.now(UTC).isoformat()})
    if loan.customer_message_received:
        EVENTS[case_id].append({"type": "customer_message_received", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
    EVENTS[case_id].append({"type": "calc_done", "case_id": case_id, "affordability": affordability.model_dump(mode="json"), "ts": datetime.now(UTC).isoformat()})

    visible = []
    for tx in loan.transactions:
        element = next((e for e in routed if e.source_ref == f"tx:{tx.id}"), None)
        if element and element.lane in ("local_only", "excluded", "refuse"):
            continue
        visible.append(tx.model_copy(update={"counterparty": mask_identifiers(scrub(tx.counterparty, pseudo_map)),
            "description": mask_identifiers(scrub(tx.description, pseudo_map))}))

    # P14: an evidence gap is handled locally, without any gateway invocation.
    self_employed = getattr(loan.applicant, "income_type", "") == "self_employed"
    if self_employed or affordability.open_questions:
        if self_employed:
            source_ids = ", ".join(affordability.source_refs.get("net_pay", [])) or "income record"
            reason = f"Self-employed income in {source_ids} is unverified; client receipts are not net payroll."
        else:
            payslips = ", ".join(ref for ref in affordability.source_refs.get("net_pay", []) if ref.startswith("p")) or "payslip"
            credits = ", ".join(ref for ref in affordability.source_refs.get("net_pay", []) if not ref.startswith("p")) or "salary credit"
            reason = f"Reconcile printed net pay in {payslips} with salary credit in {credits}."
        note = f"Local note: {reason} Human review required; this is not an adverse finding."
        view = _note_view(case_id, affordability, note, received=loan.customer_message_received)
        VIEWS[case_id] = view
        EVENTS[case_id].append({"type": "human_review_required", "rule_id": "P14", "ts": datetime.now(UTC).isoformat()})
        return view

    try:
        user_data = _figures(affordability)
        validate_cloud_payload(user_data)
        # Egress follows the active policy: the aggregate must route to the cloud lane before dispatch.
        aggregate = route(Element(id=hashlib.sha1(f"{case_id}:aggregate".encode()).hexdigest()[:12], source_ref="aggregate:explanation", kind="aggregate", text="", category="financial_fact", detector="pipeline"), "calculate", policy)
        if aggregate.lane != "cloud_aggregate":
            raise PermissionError("Active policy does not allow the aggregate payload to leave")
        if os.getenv("PRESCRUB", "on").casefold() != "on":
            raise BraneUnavailable("Outbound raw-source mode is disabled; only the four-field payload is permitted")
        user = json.dumps(user_data, sort_keys=True)
        # Defense in depth: payload schema and source-derived leak checks run before gateway.
        validate_cloud_payload(json.loads(user))
        outbound_guard(user, loan)
        system = (
            "Draft a neutral two-sentence note for a credit officer from these figures: "
            f"net pay {user_data['net_pay_cents']} cents, housing {user_data['housing_cents']} cents, "
            f"utilities {user_data['utilities_cents']} cents, debt payments {user_data['debt_payment_cents']} cents. "
            "Do not add any assessment."
        )
        result = get_cloud().complete(system, user, case_id=case_id, purpose="aggregate_explanation")
        decision = _brane_decision(result.verdict)
        if decision.refused:
            raise BraneBlocked("BRANE refused the request", decision.status, result.verdict)
        if not decision.positive:
            raise BraneUnavailable("BRANE did not return an explicit positive verdict")
        draft = restore(result.text, pseudo_map)
        try:
            assert_clean(draft, loan)
        except LeakDetected:
            draft = "Template note: review the source documents and reconcile the listed figures."
        explanation = _checked_draft(draft, affordability)
        stored_verdict = _ledger_verdict(result.verdict)
        EVENTS[case_id].append({"type": "brane_call", "verdict": stored_verdict, "payload_sha256": result.payload_sha256, "ts": datetime.now(UTC).isoformat()})
        record(case_id, aggregate, policy["version"], LEDGER, verdict=stored_verdict, payload_hash=result.payload_sha256)
    except BraneBlocked as exc:
        blocked = Element(id=hashlib.sha1(f"{case_id}:brane-blocked".encode()).hexdigest()[:12], source_ref="brane:decision", kind="control", text="", category="financial_fact", detector="brane", lane="refuse", rule_id="P12", citation="GDPR Arts. 25(1), 32(1); challenge brief (check-failure test)", brane_policy_ref="BRANE-P12-FAIL-CLOSED")
        record(case_id, blocked, policy["version"], LEDGER, verdict=_ledger_verdict(exc.decision) if exc.decision else f"block: HTTP {exc.status_code}")
        EVENTS[case_id].append({"type": "fail_closed", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
        refusal = _brane_decision(exc.decision)
        note = ""
        if exc.status_code == 422 or refusal.refused:
            # A BRANE refusal: no model note, only the stated reason from X-Brane-Refused-By / X-Brane-Policy-Triggers.
            note = f"BRANE refused the request: {refusal.reason or 'no reason given'}"
        view = OfficerView(case_id=case_id, affordability=affordability, explanation="external drafting unavailable",
            flags=["brane_blocked"], local_note=note)
        VIEWS[case_id] = view
        return view
    except BraneUnavailable:
        unavailable = Element(id=hashlib.sha1(f"{case_id}:brane-unavailable".encode()).hexdigest()[:12], source_ref="brane:unavailable", kind="control", text="", category="financial_fact", detector="brane", lane="refuse", rule_id="P12", citation="GDPR Arts. 25(1), 32(1); challenge brief (check-failure test)", brane_policy_ref="BRANE-P12-FAIL-CLOSED")
        record(case_id, unavailable, policy["version"], LEDGER, verdict="unavailable")
        EVENTS[case_id].append({"type": "fail_closed", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
        view = OfficerView(case_id=case_id, affordability=affordability, explanation="external drafting unavailable", flags=["brane_unavailable"])
        VIEWS[case_id] = view
        return view
    except Exception as exc:  # noqa: BLE001 - outbound checks fail closed
        if isinstance(exc, LeakDetected):
            EVENTS[case_id].append({"type": "blocked_before_brane", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
        blocked = Element(id=hashlib.sha1(f"{case_id}:outbound-failure".encode()).hexdigest()[:12], source_ref="gateway:guard", kind="control", text="", category="neutral", detector="fail_closed", lane="refuse", rule_id="P12", citation="GDPR Arts. 25(1), 32(1); challenge brief (check-failure test)", brane_policy_ref="BRANE-P12-FAIL-CLOSED")
        record(case_id, blocked, policy["version"], LEDGER)
        EVENTS[case_id].append({"type": "fail_closed", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
        view = OfficerView(case_id=case_id, affordability=affordability, explanation="external drafting unavailable", flags=["fail_closed"])
        VIEWS[case_id] = view
        return view

    view = OfficerView(case_id=case_id, affordability=affordability, explanation=explanation,
        visible_transactions=visible,
        flags=["attack_detected"] if any(e.category == "instruction_attack" for e in elements) else [],
        customer_message_status="customer message received" if loan.customer_message_received else "")
    VIEWS[case_id] = view
    EVENTS[case_id].append({"type": "summary_ready", "case_id": case_id, "ts": datetime.now(UTC).isoformat()})
    return view
