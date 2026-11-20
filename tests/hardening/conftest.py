from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hardening_helpers import RecordingBrane, write_case

from app import pipeline
from app.api import main as api
from app.policy import Ledger
from app.qa import reset_sessions

_LOOPBACK_NAMES = {"localhost", "testserver"}


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True  # AF_UNIX / socketpair internals
    host = str(address[0])
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any non-localhost connection attempt fails the test."""
    attempts: list[str] = []
    real_connect, real_connect_ex, real_create = socket.socket.connect, socket.socket.connect_ex, socket.create_connection

    def guard(address):
        if not _is_loopback(address):
            attempts.append(repr(address))
            raise AssertionError(f"Network egress attempted to {address!r}")

    def connect(self, address):
        guard(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        guard(address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        guard(address)
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    yield attempts
    assert not attempts, f"Network egress attempted: {attempts}"


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BRANE_MODE", "fake")
    monkeypatch.setenv("PRESCRUB", "on")
    monkeypatch.setenv("HARDSHIP_ENABLED", "false")
    monkeypatch.setenv("BRANE_DEMO_DOWN", "off")
    monkeypatch.setenv("AGE_PROXY_ENABLED", "off")
    for name in ("BRANE_BASE_URL", "BRANE_API_KEY", "BRANE_MODEL", "BRANE_POLICY_CONFIRMED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pipeline, "ACTIVE_POLICY_VERSION", "v1")
    monkeypatch.setattr(pipeline, "LEDGER", Ledger(tmp_path / "ledger.sqlite3"))
    monkeypatch.setattr(pipeline, "EVENTS", {})
    monkeypatch.setattr(pipeline, "VIEWS", {})
    monkeypatch.setattr(api, "OPENED", {})
    monkeypatch.setattr(api, "UPLOADS", {})
    reset_sessions()
    yield
    reset_sessions()


@pytest.fixture
def brane(monkeypatch) -> RecordingBrane:
    fake = RecordingBrane()
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


@dataclass
class Run:
    case_id: str
    view: dict
    brane: RecordingBrane
    sse: str
    ledger_jsonl: str
    ledger_csv: str
    rows: list[dict]

    def surfaces(self) -> dict[str, str]:
        return {
            "cloud_payloads": json.dumps(self.brane.payloads, ensure_ascii=False),
            "officer_view": json.dumps(self.view, ensure_ascii=False),
            "sse_events": self.sse,
            "ledger_export": self.ledger_jsonl + "\n" + self.ledger_csv,
        }

    @property
    def figures(self) -> dict[str, int]:
        return {k: self.view["affordability"][k] for k in ("net_pay_cents", "housing_cents", "utilities_cents", "debt_payment_cents")}


@pytest.fixture
def run_case(brane, client, tmp_path):
    """Process a synthetic loan file and collect every observable surface."""

    def _run(raw_or_case: dict | str, path: Path | None = None) -> Run:
        if isinstance(raw_or_case, dict):
            case_id = raw_or_case["case_id"]
            path = write_case(tmp_path, raw_or_case)
        else:
            case_id = raw_or_case
        before = len(brane.payloads)
        view = pipeline.process(case_id, path).model_dump(mode="json")
        sse = client.get(f"/cases/{case_id}/events").text
        run_brane = RecordingBrane()
        run_brane.payloads = brane.payloads[before:]
        return Run(case_id, view, run_brane, sse, pipeline.LEDGER.export(case_id, "jsonl"),
                   pipeline.LEDGER.export(case_id, "csv"), pipeline.LEDGER.rows(case_id))

    return _run
