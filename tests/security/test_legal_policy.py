import json
import os
from pathlib import Path

import pytest

from app import pipeline
from app.calc import compute
from app.classify import classify
from app.gateway import BraneBlocked, BraneClient, FakeBrane
from app.intake import load_file, parse_payslip_text

ROOT = Path(__file__).resolve().parents[2]


def _write_case(tmp_path, raw, name="case.json"):
    path = tmp_path / name
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_r2_age_or_postcode_does_not_change_figures_flags_or_route(monkeypatch, tmp_path):
    raw = json.loads((ROOT / "data/files/clean.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / "ledger.sqlite3"))
    monkeypatch.setattr(pipeline, "get_cloud", lambda: FakeBrane())
    baseline_path = _write_case(tmp_path, raw, "baseline.json")
    baseline = pipeline.process("clean", baseline_path)
    baseline_route = [(e["category"], e["lane"], e["rule_id"]) for e in pipeline.EVENTS["clean"] if e["type"] == "element_routed"]

    for field, value in (("age", 61), ("postcode", "9999 ZZ")):
        changed = json.loads(json.dumps(raw))
        changed["applicant"][field] = value
        view = pipeline.process("clean", _write_case(tmp_path, changed, f"{field}.json"))
        changed_route = [(e["category"], e["lane"], e["rule_id"]) for e in pipeline.EVENTS["clean"] if e["type"] == "element_routed"]
        assert view.affordability.model_dump() == baseline.affordability.model_dump()
        assert view.flags == baseline.flags
        assert changed_route == baseline_route


def test_r3_cjib_line_is_excluded_from_all_totals(tmp_path):
    base = json.loads((ROOT / "data/files/clean.json").read_text(encoding="utf-8"))
    before = compute(load_file(_write_case(tmp_path, base, "before.json")), [])
    changed = json.loads(json.dumps(base))
    changed["transactions"].append({"id": "criminal-1", "date": "2026-10-18", "counterparty": "CJIB", "description": "payment", "amount_cents": -7500, "page": 2})
    loan = load_file(_write_case(tmp_path, changed, "after.json"))
    elements = classify(loan)
    assert any(element.category == "criminal" and element.source_ref == "tx:criminal-1" for element in elements)
    after = compute(loan, elements)
    assert after.model_dump() == before.model_dump()


@pytest.mark.parametrize("gap", ["mismatch", "self_employed"])
def test_p14_evidence_gap_stays_local_and_requires_human_review(monkeypatch, tmp_path, gap):
    raw = json.loads((ROOT / "data/files/clean.json").read_text(encoding="utf-8"))
    if gap == "mismatch":
        raw["transactions"][-1]["amount_cents"] = 100000
    else:
        raw["applicant"]["income_type"] = "self_employed"
    calls = []

    def cloud():
        calls.append("called")
        return FakeBrane()

    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / f"{gap}.sqlite3"))
    monkeypatch.setattr(pipeline, "get_cloud", cloud)
    view = pipeline.process("clean", _write_case(tmp_path, raw, f"{gap}.json"))
    assert calls == []
    assert view.human_review_required is True
    assert "human_review_required" in view.flags
    assert "Local note:" in view.local_note


def test_outbound_payload_schema_rejects_extra_fields_and_non_integer_values():
    exact = {"net_pay_cents": 1, "housing_cents": 2, "utilities_cents": 3, "debt_payment_cents": 4}
    pipeline.validate_cloud_payload(exact)
    with pytest.raises(ValueError):
        pipeline.validate_cloud_payload({**exact, "extra_integer_cents": 5})
    with pytest.raises(TypeError):
        pipeline.validate_cloud_payload({**exact, "debt_payment_cents": True})


def test_p12_missing_brane_verdict_returns_no_draft(monkeypatch, tmp_path):
    class NoVerdict(FakeBrane):
        def complete(self, system, user, *, case_id, purpose):
            result = super().complete(system, user, case_id=case_id, purpose=purpose)
            result.verdict = "unreported"
            return result

    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / "no-verdict.sqlite3"))
    monkeypatch.setattr(pipeline, "get_cloud", lambda: NoVerdict())
    view = pipeline.process("clean")
    assert view.explanation == "external drafting unavailable"
    assert "brane_unavailable" in view.flags


def test_intake_keeps_only_printed_net_pay_and_never_ingests_bsn_or_message_text(monkeypatch):
    monkeypatch.setenv("HARDSHIP_ENABLED", "false")
    loan = load_file(ROOT / "data/files/sensitive.json")
    assert parse_payslip_text("Gross pay €3.200,00\nNet pay €2.800,00") == {"net_cents": 280000}
    assert loan.applicant.bsn == ""
    assert loan.payslips[0].model_dump().keys() == {"id", "employer", "period", "net_cents", "raw_text", "page"}
    assert loan.payslips[0].raw_text == ""
    assert loan.messages == []
    assert loan.customer_message_received is True


def test_p10_view_displays_only_neutral_message_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("HARDSHIP_ENABLED", "false")
    fake = FakeBrane()
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / "p10.sqlite3"))
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    view = pipeline.process("sensitive")
    assert view.customer_message_status == "customer message received"
    assert "Ik ben ziek" not in str(view.model_dump())
    assert "Ik ben ziek" not in str(pipeline.EVENTS["sensitive"])
    assert "Ik ben ziek" not in str(fake.payloads)


@pytest.mark.parametrize("draft", [
    "The net_pay_cents is 1, reject this application.",
    "Risk score is 245000; recommend approval.",
    "Risico en afwijzen.",
])
def test_r4_tampered_or_decisional_draft_uses_template(monkeypatch, tmp_path, draft):
    class Tampered(FakeBrane):
        def complete(self, system, user, *, case_id, purpose):
            result = super().complete(system, user, case_id=case_id, purpose=purpose)
            result.text = draft
            return result

    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / "ledger.sqlite3"))
    monkeypatch.setattr(pipeline, "get_cloud", lambda: Tampered())
    view = pipeline.process("clean")
    assert view.explanation.startswith("Template note:")
    for field in pipeline.OUTBOUND_FIELDS:
        assert f"{field}={getattr(view.affordability, field)}" in view.explanation
    assert not pipeline.PROHIBITED_DRAFT.search(view.explanation)


@pytest.mark.live
def test_brane_enforcement_check_denies_disallowed_synthetic_field():
    if os.getenv("BRANE_MODE", "fake") != "live" or os.getenv("BRANE_POLICY_CONFIRMED", "off").casefold() != "on":
        pytest.skip("Set BRANE_MODE=live and BRANE_POLICY_CONFIRMED=on after P1 is configured")
    payload = json.dumps({"net_pay_cents": 0, "housing_cents": 0, "utilities_cents": 0, "debt_payment_cents": 0, "synthetic_probe": "harmless policy test"})
    try:
        BraneClient().complete("Reject payloads that do not match P1.", payload, case_id="synthetic-probe", purpose="BRANE enforcement check")
    except BraneBlocked as exc:
        evidence = {"check": "BRANE enforcement check", "configured_rule": "P1", "outcome": "denied", "http_status": exc.status_code, "decision": exc.decision, "request_count": 1, "onward_request_count": 0}
        evidence_path = ROOT / "evidence/brane-enforcement.json"
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    else:
        pytest.fail("BRANE did not deny the synthetic P1 schema violation")
