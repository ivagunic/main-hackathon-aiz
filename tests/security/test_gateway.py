import httpx
import pytest

from app.gateway import BraneClient, BraneUnavailable, LocalClient, outbound_guard
from app.intake import load_file


def test_live_gateway_without_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("BRANE_BASE_URL", raising=False)
    monkeypatch.delenv("BRANE_MODEL", raising=False)
    with pytest.raises(BraneUnavailable):
        BraneClient().complete("system", "aggregate", case_id="synthetic", purpose="test")


def test_live_gateway_fails_closed_on_closed_braneserver_without_fallback(monkeypatch):
    monkeypatch.setenv("BRANE_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("BRANE_MODEL", "synthetic-model")
    contacts = []

    def fail_connect(self, url, **kwargs):
        contacts.append(str(url))
        raise httpx.ConnectError("closed test port")

    monkeypatch.setattr(httpx.Client, "post", fail_connect)
    with pytest.raises(BraneUnavailable):
        BraneClient().complete("system", "aggregate", case_id="synthetic", purpose="test")
    assert contacts == ["http://127.0.0.1:1/v1/chat/completions"]


def test_outbound_guard_rejects_identifier_payload():
    loan = load_file("data/files/sensitive.json")
    with pytest.raises(ValueError, match="span hash"):
        outbound_guard('{"customer":"Mila Verzonnen"}', loan)


def test_local_client_has_no_unapproved_ollama_fallback(monkeypatch):
    monkeypatch.delenv("BRANE_BASE_URL", raising=False)
    monkeypatch.delenv("BRANE_MODEL", raising=False)
    with pytest.raises(BraneUnavailable):
        LocalClient().complete("system", "message")
