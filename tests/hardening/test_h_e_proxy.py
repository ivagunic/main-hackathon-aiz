"""E. Proxy invariance (P8): varying age, postcode, nationality, gender, education or name changes nothing."""
from __future__ import annotations

import json
import random

import pytest
from hardening_helpers import FIXTURES, load_fixture

from app import pipeline
from app.policy import Ledger

VALUES = {
    "age": [19, 34, 61, 88],
    "postcode": ["9999 ZZ", "1011 AB", "3011 XA"],
    "nationality": ["NL", "MA", "TR", "PL", "SY", "SR"],
    "gender": ["F", "M", "X", ""],
    "education": ["", "MBO", "HBO", "PhD", "none"],
    # Realistic names, several containing dictionary stems or budget words as substrings.
    "name": ["Fatima El Amrani", "Mehmet Yılmaz", "Nguyễn Thị Lan", "Sloane Peters", "Sanne Kerkhof", "Tom Church",
             "Jan van der Kerk", "Gaston Waterman", "Anna-Maria de Huurman", "Lena Gewerkschaft"],
}


def _vary(raw: dict, field: str, value) -> dict:
    if field == "name":
        old = raw["applicant"]["name"]
        text = json.dumps(raw, ensure_ascii=False)
        for a, b in ((old, value), (old.upper(), value.upper()), (old.lower(), value.lower())):
            text = text.replace(a, b)
        return json.loads(text)
    changed = json.loads(json.dumps(raw))
    changed["applicant"][field] = value
    return changed


def _observe(run_case, raw, tmp_path, label) -> dict:
    pipeline.LEDGER = Ledger(tmp_path / f"{label}.sqlite3")
    run = run_case(raw)
    return {
        "figures": run.figures,
        "flags": run.view["flags"],
        "lanes": [(r["element_id"], r["category"], r["lane"], r["rule_id"]) for r in run.rows],
        "hash": pipeline.LEDGER.decisions_hash(raw["case_id"]),
        "payloads": run.brane.user_payloads(),
        "human_review": run.view["human_review_required"],
    }


CASES = [(case_id, field, value) for case_id in FIXTURES for field, values in VALUES.items() for value in values]


@pytest.mark.parametrize(("case_id", "field", "value"), CASES, ids=[f"{c}-{f}-{v}" for c, f, v in CASES])
def test_proxy_change_changes_nothing(monkeypatch, run_case, tmp_path, case_id, field, value):
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.LEDGER)  # restored after the test
    raw = load_fixture(case_id)
    baseline = _observe(run_case, raw, tmp_path, "baseline")
    changed = _observe(run_case, _vary(raw, field, value), tmp_path, "changed")
    assert changed == baseline


def test_random_combinations_change_nothing(monkeypatch, run_case, tmp_path):
    monkeypatch.setattr(pipeline, "LEDGER", pipeline.LEDGER)
    rng = random.Random(8)
    for case_id in FIXTURES:
        raw = load_fixture(case_id)
        baseline = _observe(run_case, raw, tmp_path, f"{case_id}-base")
        for trial in range(5):
            changed = raw
            for field, values in VALUES.items():
                changed = _vary(changed, field, rng.choice(values))
            assert _observe(run_case, changed, tmp_path, f"{case_id}-{trial}") == baseline, (case_id, trial)
