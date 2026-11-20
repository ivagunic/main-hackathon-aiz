"""H. Fail closed (P12): no cloud call (or no draft) and a ledger row whenever a check cannot run."""
from __future__ import annotations

import json
import shutil
import sqlite3

import httpx
import pytest
from hardening_helpers import RecordingBrane

from app import pipeline
from app.gateway import BraneClient

REAL_CLIENT = httpx.Client


def _fail_closed(run, *, cloud_calls: int = 0):
    assert len(run.brane.payloads) == cloud_calls
    flags = set(run.view["flags"])
    assert flags & {"fail_closed", "brane_unavailable", "brane_blocked"}, flags
    assert run.view["explanation"] in ("", "external drafting unavailable")
    assert any(r["rule_id"] == "P12" and r["lane"] == "refuse" and r["aiz_decision"] == "block" for r in run.rows)
    assert '"fail_closed"' in run.sse
    assert not any(r["category"] == "financial_fact" and r["brane_verdict"] for r in run.rows if r["rule_id"] == "P1")


# ---------- BRANE itself misbehaves (live client against an in-memory transport) ----------

def _live_client(monkeypatch, tmp_path, handler):
    requests: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return handler(request)

    monkeypatch.setenv("BRANE_BASE_URL", "https://brane.invalid")
    monkeypatch.setenv("BRANE_MODEL", "synthetic-model")
    monkeypatch.setenv("BRANE_API_KEY", "synthetic-test-key-not-a-secret")
    monkeypatch.setenv("BRANE_CACHE_PATH", str(tmp_path / "cache.sqlite3"))
    monkeypatch.setattr(httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(recording), **kw))
    monkeypatch.setattr(pipeline, "get_cloud", BraneClient)
    return requests


def _ok_body(verdict="allow", text="A short factual note."):
    body = {"choices": [{"message": {"content": text}}]}
    if verdict is not None:
        body["brane_verdict"] = verdict
    return body


def _timeout(request):
    raise httpx.ReadTimeout("synthetic timeout", request=request)


def _connect_error(request):
    raise httpx.ConnectError("synthetic refused", request=request)


SCENARIOS = {
    "down_connect_error": _connect_error,
    "timeout": _timeout,
    "http_500": lambda r: httpx.Response(500, json={"error": "synthetic"}),
    "http_503": lambda r: httpx.Response(503, text="unavailable"),
    "http_401": lambda r: httpx.Response(401, text="unauthorised"),
    "http_302": lambda r: httpx.Response(302, headers={"location": "https://elsewhere.invalid/"}),
    "malformed_json": lambda r: httpx.Response(200, text="{not json"),
    "json_list": lambda r: httpx.Response(200, json=["allow"]),
    "missing_choices": lambda r: httpx.Response(200, json={"brane_verdict": "allow"}),
    "no_verdict": lambda r: httpx.Response(200, json=_ok_body(verdict=None)),
    "verdict_block": lambda r: httpx.Response(200, json=_ok_body(verdict="block")),
    "verdict_empty": lambda r: httpx.Response(200, json=_ok_body(verdict="")),
    "verdict_object": lambda r: httpx.Response(200, json=_ok_body(verdict={"verdict": "allow"})),
    "http_403_block": lambda r: httpx.Response(403, json={"brane_verdict": "block"}),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_brane_failure_modes_fail_closed_without_retry_or_fallback(monkeypatch, tmp_path, run_case, name):
    requests = _live_client(monkeypatch, tmp_path, SCENARIOS[name])
    run = run_case("clean")
    assert len(requests) == 1 and requests[0].startswith("https://brane.invalid/"), f"exactly one attempt, to BRANE only: {requests}"
    assert run.view["explanation"] == "external drafting unavailable"
    assert set(run.view["flags"]) & {"brane_unavailable", "brane_blocked"}
    assert any(r["rule_id"] == "P12" and r["aiz_decision"] == "block" for r in run.rows)


def test_live_client_harness_positive_control(monkeypatch, tmp_path, run_case):
    requests = _live_client(monkeypatch, tmp_path, lambda r: httpx.Response(200, json=_ok_body()))
    run = run_case("clean")
    assert len(requests) == 1
    assert run.view["explanation"].startswith("A short factual note.")


def test_live_verdict_record_does_not_copy_model_text_into_ledger_or_events(monkeypatch, tmp_path, run_case):
    """Matrix section D: ledger rows and events hold decisions, not model or document text."""
    marker = "Synthetic draft sentence that must stay out of the ledger."
    _live_client(monkeypatch, tmp_path, lambda r: httpx.Response(200, json=_ok_body(text=marker)))
    run = run_case("clean")
    assert marker not in json.dumps(run.rows), "model text copied into ledger brane_verdict"
    assert marker not in run.sse, "model text copied into SSE brane_call event"


def test_demo_switch_down_means_no_cloud_call(monkeypatch, run_case, client):
    from app import gateway
    monkeypatch.setattr(pipeline, "get_cloud", gateway.get_cloud)  # use the real switch, not the test double
    assert client.post("/admin/brane/down").status_code == 200
    try:
        run = run_case("clean")
    finally:
        client.post("/admin/brane/up")
    assert run.view["explanation"] == "external drafting unavailable"
    assert any(r["rule_id"] == "P12" for r in run.rows)


# ---------- local controls missing or broken: no cloud call at all ----------

def test_dictionary_missing(monkeypatch, tmp_path, run_case):
    import app.classify as classifier
    monkeypatch.setattr(classifier, "DICTIONARY", tmp_path / "missing.yaml")
    _fail_closed(run_case("sensitive"))


@pytest.mark.parametrize("content", ["- just\n- a list\n", ":::not yaml", "", "pharmacy: 12\n"])
def test_dictionary_invalid(monkeypatch, tmp_path, run_case, content):
    import app.classify as classifier
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(classifier, "DICTIONARY", path)
    _fail_closed(run_case("sensitive"))


def _policy_root(monkeypatch, tmp_path, policy_text: str | None):
    root = tmp_path / "root"
    (root / "policy").mkdir(parents=True)
    shutil.copytree(pipeline.ROOT / "data", root / "data")
    if policy_text is not None:
        (root / "policy" / "policy.v1.yaml").write_text(policy_text, encoding="utf-8")
    monkeypatch.setattr(pipeline, "ROOT", root)


def test_policy_missing(monkeypatch, tmp_path, run_case):
    _policy_root(monkeypatch, tmp_path, None)
    _fail_closed(run_case("clean", pipeline.ROOT / "data" / "files" / "clean.json"))


VALID_DEFAULT = "default: {lane: refuse, rule_id: P12, citation: x, brane_policy_ref: y}\n"
INVALID_POLICIES = {
    "garbage": ":::",
    "not_mapping": "- a\n- b\n",
    "no_rules": "version: v1\n" + VALID_DEFAULT,
    "rules_not_list": "version: v1\n" + VALID_DEFAULT + "rules: {}\n",
    "bad_lane": "version: v1\n" + VALID_DEFAULT + "rules:\n  - {id: P1, match: {}, action: calculate, lane: cloud_raw, citation: x, brane_policy_ref: y}\n",
    "rule_not_mapping": "version: v1\n" + VALID_DEFAULT + "rules:\n  - just-a-string\n",
    "duplicate_ids": "version: v1\n" + VALID_DEFAULT + "rules:\n  - {id: P1, match: {}, action: calculate, lane: refuse, citation: x, brane_policy_ref: y}\n"
                     "  - {id: P1, match: {}, action: calculate, lane: refuse, citation: x, brane_policy_ref: y}\n",
    "no_default": "version: v1\nrules: []\n",
}


@pytest.mark.parametrize("name", sorted(INVALID_POLICIES))
def test_policy_invalid(monkeypatch, tmp_path, run_case, name):
    _policy_root(monkeypatch, tmp_path, INVALID_POLICIES[name])
    _fail_closed(run_case("clean", pipeline.ROOT / "data" / "files" / "clean.json"))


def test_policy_that_does_not_allow_the_aggregate_blocks_the_cloud_call(monkeypatch, tmp_path, run_case):
    """A valid policy with no P1 allow rule routes everything to the refuse default; egress must follow the policy."""
    _policy_root(monkeypatch, tmp_path, "version: v1\n" + VALID_DEFAULT + "rules: []\n")
    run = run_case("clean", pipeline.ROOT / "data" / "files" / "clean.json")
    assert run.brane.payloads == []
    assert any(r["rule_id"] == "P12" for r in run.rows)


def test_classifier_raises(monkeypatch, run_case):
    def boom(_loan):
        raise RuntimeError("synthetic classifier failure")
    monkeypatch.setattr(pipeline, "classify", boom)
    _fail_closed(run_case("sensitive"))


def test_calculator_raises(monkeypatch, run_case):
    monkeypatch.setattr(pipeline, "compute", lambda *_: (_ for _ in ()).throw(ArithmeticError("synthetic")))
    _fail_closed(run_case("clean"))


def test_ledger_locked_blocks_everything(monkeypatch, tmp_path, brane):
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real_connect(*a, **{**k, "timeout": 0.2}))
    path = tmp_path / "locked.sqlite3"
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(path))
    holder = real_connect(path, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        try:
            view = pipeline.process("clean")
        except sqlite3.OperationalError:
            view = None
        assert brane.payloads == [], "cloud call made while the ledger could not record it"
        if view is not None:
            assert "fail_closed" in view.flags
    finally:
        holder.rollback()
        holder.close()


def test_ledger_failure_after_dispatch_is_not_silent(monkeypatch, run_case):
    """If the ledger cannot record the aggregate decision, the draft must not be shown as a normal result."""
    original = pipeline.record

    def flaky(case_id, element, version, ledger, **kw):
        if element.source_ref == "aggregate:explanation":
            raise sqlite3.OperationalError("database is locked")
        return original(case_id, element, version, ledger, **kw)

    monkeypatch.setattr(pipeline, "record", flaky)
    run = run_case("clean")
    assert run.view["explanation"] == "external drafting unavailable"
    assert any(r["rule_id"] == "P12" for r in run.rows)


def test_socket_guard_is_active(no_network):
    import socket
    with pytest.raises(AssertionError, match="Network egress"):
        socket.create_connection(("192.0.2.1", 443), timeout=0.01)
    with pytest.raises(AssertionError, match="Network egress"):
        socket.socket().connect(("198.51.100.7", 80))
    assert len(no_network) == 2
    no_network.clear()  # intentional probes; any other attempt still fails the test


def test_recording_brane_is_json(run_case):
    run = run_case("clean")
    assert json.loads(run.brane.payloads[0]["user"]) == run.figures
    assert isinstance(run.brane, RecordingBrane)
