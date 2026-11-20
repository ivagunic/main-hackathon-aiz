"""L. Repeatability: every fixture processed 20 times in random order gives identical figures and decisions hash."""
from __future__ import annotations

import random

from hardening_helpers import FIXTURES

from app import pipeline
from app.policy import Ledger


def test_twenty_runs_in_random_order_are_identical(brane, tmp_path):
    order = [case_id for case_id in FIXTURES for _ in range(20)]
    random.Random(1120).shuffle(order)
    seen: dict[str, set] = {case_id: set() for case_id in FIXTURES}
    for index, case_id in enumerate(order):
        pipeline.LEDGER = Ledger(tmp_path / f"run-{index}.sqlite3")
        view = pipeline.process(case_id)
        figures = tuple(getattr(view.affordability, f) for f in pipeline.OUTBOUND_FIELDS)
        seen[case_id].add((figures, tuple(view.flags), view.explanation, pipeline.LEDGER.decisions_hash(case_id)))
    for case_id, outcomes in seen.items():
        assert len(outcomes) == 1, (case_id, outcomes)
    payloads = {}
    for payload in brane.payloads:
        payloads.setdefault(payload["case_id"], set()).add(payload["user"])
    assert all(len(values) == 1 for values in payloads.values()), payloads
