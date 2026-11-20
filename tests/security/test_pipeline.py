from app.gateway import FakeBrane
from app.models import OfficerView
from app.pipeline import process


def test_synthetic_cases_run_and_sensitive_transactions_are_hidden(monkeypatch, tmp_path):
    from app import pipeline
    fake = FakeBrane()
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / "ledger.sqlite3"))
    view = process("sensitive")
    assert isinstance(view, OfficerView)
    assert "Stichting Fictieve Kerk" not in str(view.model_dump())
    assert fake.payloads
    payload = str(fake.payloads)
    assert "Mila Verzonnen" not in payload
    assert "Apotheek De Voorbeeldbrug" not in payload


def test_aggregate_prompt_contains_no_source_message(monkeypatch, tmp_path):
    from app import pipeline
    fake = FakeBrane()
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.Ledger(tmp_path / "ledger.sqlite3"))
    process("sensitive")
    assert "Ik ben ziek" not in str(fake.payloads)
