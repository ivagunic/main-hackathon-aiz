"""O. BRANE answer rules, read from the stored X-Brane headers.

Positive only when HTTP 200 AND X-Brane-Routed-To is cloud/local AND X-Brane-Action is allow/placeholder/local.
HTTP 422 or routed-to "refused" = blocked: no note, refusal reason shown.
Anything else (missing/unreadable headers, other status, timeout, connection error) = fail closed with a ledger row.
"""
from __future__ import annotations

import json

import httpx
import pytest
from test_h_h_fail_closed import _live_client, _ok_body

from app import pipeline

NOTE = "The note records [NET_PAY] and [HOUSING]. It also records [UTILITIES] and [DEBT_PAYMENTS]."


def _p12_row(run) -> dict:
    return next(r for r in run.rows if r["rule_id"] == "P12")


@pytest.mark.parametrize(("routed", "action"), [
    ("cloud", "allow"), ("cloud", "placeholder"), ("local", "local"), ("local", "allow"), ("CLOUD", "Allow"),
])
def test_positive_answer_shows_the_note(monkeypatch, tmp_path, run_case, routed, action):
    headers = {"x-brane-routed-to": routed, "x-brane-action": action}
    _live_client(monkeypatch, tmp_path, lambda r: httpx.Response(200, json=_ok_body(text=NOTE), headers=headers))
    run = run_case("clean")
    assert run.view["explanation"].startswith(
        "The note records € 2.450,00 and € 850,00. It also records € 120,00 and € 0,00."
    )
    stored = json.loads(next(r for r in run.rows if r["rule_id"] == "P1" and r["brane_verdict"])["brane_verdict"])
    assert stored["headers"]["x-brane-routed-to"] == routed  # the page reads where the request went from here
    assert "raw_response" not in stored and NOTE not in json.dumps(run.rows) and NOTE not in run.sse


@pytest.mark.parametrize(("header", "reason"), [
    ("x-brane-refused-by", "policy P2 identifier check"),
    ("x-brane-policy-triggers", "BRANE-P4-SENSITIVE-LINES"),
])
def test_http_422_is_blocked_with_reason_and_no_note(monkeypatch, tmp_path, run_case, header, reason):
    _live_client(monkeypatch, tmp_path, lambda r: httpx.Response(
        422, json={"error": "refused", "choices": [{"message": {"content": NOTE}}]}, headers={header: reason}))
    run = run_case("clean")
    assert run.view["flags"] == ["brane_blocked"]
    assert run.view["explanation"] == "external drafting unavailable"
    assert run.view["local_note"] == f"BRANE refused the request: {reason}"
    assert NOTE not in json.dumps(run.view) and NOTE not in json.dumps(run.rows) and NOTE not in run.sse
    assert _p12_row(run)["aiz_decision"] == "block"


@pytest.mark.parametrize("headers", [
    {"x-brane-routed-to": "refused", "x-brane-refused-by": "policy P1 schema"},
    {"x-brane-routed-to": "refused", "x-brane-action": "allow", "x-brane-policy-triggers": "P1"},
])
def test_routed_to_refused_is_blocked_with_reason(monkeypatch, tmp_path, run_case, headers):
    body = {**_ok_body(text=NOTE)}
    _live_client(monkeypatch, tmp_path, lambda r: httpx.Response(200, json=body, headers=headers))
    run = run_case("clean")
    assert run.view["flags"] == ["brane_blocked"]
    assert run.view["local_note"].startswith("BRANE refused the request: ")
    assert run.view["local_note"].endswith(headers.get("x-brane-refused-by") or headers["x-brane-policy-triggers"])
    assert NOTE not in json.dumps(run.view)
    assert _p12_row(run)["aiz_decision"] == "block"


def test_refusal_without_reason_header_says_so(monkeypatch, tmp_path, run_case):
    _live_client(monkeypatch, tmp_path, lambda r: httpx.Response(422, json={"error": "refused"}))
    run = run_case("clean")
    assert run.view["local_note"] == "BRANE refused the request: no reason given"


FAIL_CLOSED = {
    "no_headers": lambda r: httpx.Response(200, json=_ok_body(text=NOTE)),
    "routed_missing": lambda r: httpx.Response(200, json=_ok_body(text=NOTE), headers={"x-brane-action": "allow"}),
    "action_missing": lambda r: httpx.Response(200, json=_ok_body(text=NOTE), headers={"x-brane-routed-to": "cloud"}),
    "routed_unknown": lambda r: httpx.Response(200, json=_ok_body(text=NOTE), headers={"x-brane-routed-to": "elsewhere", "x-brane-action": "allow"}),
    "action_unknown": lambda r: httpx.Response(200, json=_ok_body(text=NOTE), headers={"x-brane-routed-to": "cloud", "x-brane-action": "rewrite"}),
    "action_empty": lambda r: httpx.Response(200, json=_ok_body(text=NOTE), headers={"x-brane-routed-to": "cloud", "x-brane-action": ""}),
    "status_201": lambda r: httpx.Response(201, json=_ok_body(text=NOTE), headers={"x-brane-routed-to": "cloud", "x-brane-action": "allow"}),
    "status_203": lambda r: httpx.Response(203, json=_ok_body(text=NOTE), headers={"x-brane-routed-to": "cloud", "x-brane-action": "allow"}),
    "status_500": lambda r: httpx.Response(500, headers={"x-brane-routed-to": "cloud", "x-brane-action": "allow"}),
    "status_503": lambda r: httpx.Response(503),
    "status_401": lambda r: httpx.Response(401, headers={"x-brane-routed-to": "cloud", "x-brane-action": "allow"}),
    "malformed_json": lambda r: httpx.Response(200, text="{not json", headers={"x-brane-routed-to": "cloud", "x-brane-action": "allow"}),
}


def _timeout(request):
    raise httpx.ReadTimeout("synthetic timeout", request=request)


def _refused_connection(request):
    raise httpx.ConnectError("synthetic refused", request=request)


FAIL_CLOSED["timeout"] = _timeout
FAIL_CLOSED["connection_error"] = _refused_connection


@pytest.mark.parametrize("name", sorted(FAIL_CLOSED))
def test_anything_else_fails_closed(monkeypatch, tmp_path, run_case, name):
    requests = _live_client(monkeypatch, tmp_path, FAIL_CLOSED[name])
    run = run_case("clean")
    assert len(requests) == 1, "exactly one attempt to BRANE, no retry or fallback"
    assert run.view["explanation"] == "external drafting unavailable"
    assert set(run.view["flags"]) & {"brane_unavailable", "brane_blocked", "fail_closed"}
    assert NOTE not in json.dumps(run.view) and NOTE not in json.dumps(run.rows) and NOTE not in run.sse
    assert _p12_row(run)["aiz_decision"] == "block"
    assert not any(r["rule_id"] == "P1" and r["brane_verdict"] for r in run.rows), "no positive decision recorded"


@pytest.mark.parametrize("verdict", [
    "", "allow", "not json", "[]", "null", json.dumps({"status_code": 200}),
    json.dumps({"status_code": 200, "headers": "x-brane-routed-to: cloud"}),
    json.dumps({"status_code": "200", "headers": {"x-brane-routed-to": "cloud", "x-brane-action": "allow"}}),
    json.dumps({"status_code": 200, "headers": {"x-brane-routed-to": "cloud", "x-brane-action": "allow"}, "verdict": "x"}),
])
def test_unreadable_records_are_not_positive_in_live_mode(monkeypatch, verdict):
    monkeypatch.setenv("BRANE_MODE", "live")
    expected = verdict.endswith('"verdict": "x"}')  # the last one is a well-formed positive record
    assert pipeline._positive_brane_verdict(verdict) is expected


def test_plain_allow_is_never_accepted_without_a_decision_record(monkeypatch):
    monkeypatch.setenv("BRANE_MODE", "fake")
    assert not pipeline._positive_brane_verdict("allow")
    monkeypatch.setenv("BRANE_MODE", "live")
    assert not pipeline._positive_brane_verdict("allow")
