import httpx
import pytest

from app.gateway import (
    BraneBlocked,
    BraneClient,
    BraneUnavailable,
    FakeBrane,
    LocalClient,
    build_brane_request,
    outbound_guard,
)
from app.intake import load_file


def test_live_gateway_without_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("BRANE_BASE_URL", raising=False)
    monkeypatch.delenv("BRANE_MODEL", raising=False)
    with pytest.raises(BraneUnavailable):
        BraneClient().complete("system", "aggregate", case_id="synthetic", purpose="test")


def test_live_gateway_fails_closed_on_closed_braneserver_without_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("BRANE_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("BRANE_MODEL", "synthetic-model")
    monkeypatch.setenv("BRANE_API_KEY", "synthetic-test-key-not-a-secret")  # the client now refuses to run without a key
    monkeypatch.setenv("BRANE_CACHE_PATH", str(tmp_path / "cache.sqlite3"))
    contacts = []
    four_zero_payload = '{"debt_payment_cents": 0, "housing_cents": 0, "net_pay_cents": 0, "utilities_cents": 0}'

    def fail_connect(self, url, **kwargs):
        contacts.append(str(url))
        raise httpx.ConnectError("closed test port")

    monkeypatch.setattr(httpx.Client, "post", fail_connect)
    with pytest.raises(BraneUnavailable):
        BraneClient().complete("system", four_zero_payload, case_id="synthetic", purpose="test")
    assert contacts == ["http://127.0.0.1:1/chat/completions"]


def test_outbound_guard_rejects_identifier_payload():
    loan = load_file("data/files/sensitive.json")
    with pytest.raises(ValueError, match="span hash"):
        outbound_guard('{"customer":"Mila Verzonnen"}', loan)


def test_local_client_has_no_unapproved_ollama_fallback(monkeypatch):
    monkeypatch.delenv("BRANE_BASE_URL", raising=False)
    monkeypatch.delenv("BRANE_MODEL", raising=False)
    monkeypatch.delenv("BRANE_API_KEY", raising=False)
    with pytest.raises(BraneUnavailable):
        LocalClient().complete("system", "message")


def test_brane_request_construction_is_centralized():
    url, headers, body = build_brane_request(base_url="https://brane.invalid/", path="/chat/completions",
        model="synthetic-model", api_key="test-token", system="system", user="four fields")
    assert url == "https://brane.invalid/chat/completions"
    assert headers == {"Authorization": "Bearer test-token", "User-Agent": "BRANE-Starter-Kit/1.0 (MAIN-Summit-2026)"}
    assert body == {"model": "synthetic-model", "temperature": 0, "seed": 0,
        "messages": [{"role": "system", "content": "system"}, {"role": "user", "content": "four fields"}]}


def test_fake_brane_returns_live_shaped_positive_decision():
    fake = FakeBrane()
    result = fake.complete("system", '{"net_pay_cents":1,"housing_cents":2,"utilities_cents":3,"debt_payment_cents":4}',
        case_id="synthetic", purpose="test")
    assert result.http_status == 200
    assert result.response_headers["x-brane-routed-to"] == "cloud"
    assert result.response_headers["x-brane-action"] == "allow"
    assert '"status_code": 200' in result.verdict
    assert "[NET_PAY]" in result.text


def test_fake_brane_refusal_returns_http_422_shape():
    fake = FakeBrane(refuse=True)
    with pytest.raises(BraneBlocked) as caught:
        fake.complete("system", '{"net_pay_cents":1,"housing_cents":2,"utilities_cents":3,"debt_payment_cents":4}',
            case_id="synthetic", purpose="test")
    assert caught.value.status_code == 422
    assert caught.value.response_headers["x-brane-routed-to"] == "refused"
    assert caught.value.response_headers["x-brane-action"] == "refuse"
