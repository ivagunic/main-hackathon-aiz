from fastapi.testclient import TestClient

from app import pipeline
from app.api.main import OPENED, app
from app.gateway import FakeBrane
from app.policy import Ledger


def test_api_review_gate_ask_and_policy_switch(monkeypatch, tmp_path):
    fake = FakeBrane()
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    monkeypatch.setattr(pipeline, "LEDGER", Ledger(tmp_path / "api.sqlite"))
    OPENED.pop("clean", None)
    client = TestClient(app)
    created = client.post("/cases", data={"case_id": "clean"})
    assert created.status_code == 200
    processed = client.post("/cases/clean/process")
    assert processed.status_code == 200
    assert client.post("/cases/clean/review", json={"officer_id": "synthetic", "action": "approve", "reason": "A sufficiently long reason for audit."}).status_code == 409
    assert client.get("/cases/clean/view").status_code == 200
    assert client.post("/cases/clean/review", json={"officer_id": "synthetic", "action": "approve", "reason": "A sufficiently long reason for audit."}).status_code == 200
    answer = client.post("/cases/clean/ask", json={"session_id": "api-e5", "question": "Should I approve this application?"})
    assert answer.status_code == 200 and answer.json()["refused"]
    assert client.post("/admin/policy/v0").json()["active_policy"] == "v0"
    assert client.post("/admin/policy/v1").json()["active_policy"] == "v1"
