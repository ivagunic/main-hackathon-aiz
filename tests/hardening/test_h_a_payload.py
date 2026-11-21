"""A. P1 payload allowlist: exactly four integer fields, everything else rejected before the gateway."""
from __future__ import annotations

import pytest
from hardening_helpers import FIELDS, FIXTURES, load_fixture

from app import pipeline

GOOD = {"net_pay_cents": 245000, "housing_cents": 85000, "utilities_cents": 12000, "debt_payment_cents": 0}


@pytest.mark.parametrize("case_id", FIXTURES)
def test_every_fixture_sends_exactly_four_integer_fields(run_case, case_id):
    run = run_case(case_id)
    for payload in run.brane.user_payloads():
        assert set(payload) == set(FIELDS)
        assert all(type(payload[f]) is int for f in FIELDS)
        assert payload == run.figures
    # The officer view and SSE stream never carry a richer payload either.
    assert {field: run.view["affordability"][field] for field in FIELDS} == run.figures
    for extra in ("monthly_margin", "extra_integer_cents", "disposable_income", "total_expenditure"):
        assert extra not in run.surfaces()["sse_events"], extra


BAD_PAYLOADS = {
    "fifth_field": {**GOOD, "applicant_name": "Synthetic"},
    "fifth_int_field": {**GOOD, "extra_integer_cents": 1},
    "missing_field": {k: v for k, v in GOOD.items() if k != "debt_payment_cents"},
    "renamed_field": {**{k: v for k, v in GOOD.items() if k != "housing_cents"}, "Housing_cents": 1},
    "string_value": {**GOOD, "housing_cents": "85000"},
    "float_value": {**GOOD, "net_pay_cents": 245000.0},
    "fractional_float": {**GOOD, "net_pay_cents": 2450.5},
    "bool_value": {**GOOD, "utilities_cents": True},
    "none_value": {**GOOD, "utilities_cents": None},
    "nested_object": {**GOOD, "debt_payment_cents": {"value": 1}},
    "nested_list": {**GOOD, "debt_payment_cents": [1]},
    "negative": {**GOOD, "housing_cents": -1},
    "huge": {**GOOD, "net_pay_cents": 10**15},
    "huge_negative": {**GOOD, "debt_payment_cents": -(10**15)},
    "not_a_dict": [("net_pay_cents", 1)],
    "empty": {},
}


@pytest.mark.parametrize("name", sorted(BAD_PAYLOADS))
def test_validator_rejects_malformed_payload(name):
    with pytest.raises((ValueError, TypeError)):
        pipeline.validate_cloud_payload(BAD_PAYLOADS[name])


def test_validator_accepts_the_exact_allowlist():
    pipeline.validate_cloud_payload(dict(GOOD))
    pipeline.validate_cloud_payload({f: 0 for f in FIELDS})


@pytest.mark.parametrize("name", ["fifth_field", "string_value", "float_value", "nested_object", "negative", "huge"])
def test_injected_payload_never_reaches_gateway(monkeypatch, run_case, name):
    """Tamper with the figures the pipeline builds; the gateway must not be called and a ledger row must exist."""
    bad = BAD_PAYLOADS[name]
    monkeypatch.setattr(pipeline, "_figures", lambda _aff: dict(bad))
    run = run_case("clean")
    assert run.brane.payloads == []
    assert "fail_closed" in run.view["flags"] or "brane_unavailable" in run.view["flags"]
    assert any(row["rule_id"] == "P12" and row["aiz_decision"] == "block" for row in run.rows)
    assert '"fail_closed"' in run.sse


@pytest.mark.parametrize("net_cents", [-50000, 10**13])
def test_out_of_range_source_figures_fail_closed_not_crash(run_case, net_cents):
    raw = load_fixture("clean")
    raw["payslips"][0]["net_cents"] = net_cents
    raw["transactions"][-1]["amount_cents"] = net_cents  # keep reconciliation consistent so P14 does not intercept
    run = run_case(raw)
    assert run.brane.payloads == []
    assert any(row["rule_id"] == "P12" for row in run.rows)
