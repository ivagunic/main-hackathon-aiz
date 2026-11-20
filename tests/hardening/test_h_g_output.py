"""G. Output validation (P13): tampered or decisional model drafts are replaced by the template."""
from __future__ import annotations

import pytest
from hardening_helpers import RecordingBrane

from app import pipeline

# clean fixture figures: net 245000, housing 85000, utilities 12000, debt 0
DRAFTS = [
    # a figure changed by one cent / new numbers
    "Net pay is 245001 cents.", "Housing is 84999.", "Utilities 12001 per month.", "Debt payment 1.",
    "Net pay is €2.450,01.", "Net pay 2450.01 euro.", "Net pay ２４５００１.", "Net pay 245 001.",
    "Net pay 245000, housing 85000, margin 148000.", "Over 3 months the figures are stable.", "About 35% goes to housing.",
    # lending words, casing and spacing
    "We approve this file.", "APPROVED.", "aPpRoVe", "Approval is likely.", "a p p r o v e", "ap-prove", "appro\u200bve",
    "We reject it.", "REJECTED", "r e j e c t", "Ｒｅｊｅｃｔ", "The score is high.", "S C O R E", "sc0re", "Low risk.", "RISKY",
    "r i s k", "We recommend the loan.", "Recommendation: proceed.", "re-commend", "Goedkeuren.", "goed keuren", "goedgekeurd",
    "Afwijzen.", "afgewezen", "AF WIJZEN", "Wij adviseren akkoord.", "Hoog risico.", "Aanbevolen.",
]


@pytest.mark.parametrize("draft", DRAFTS)
def test_bad_draft_is_blocked_and_replaced(monkeypatch, run_case, draft):
    fake = RecordingBrane(text=draft)
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    run = run_case("clean")
    explanation = run.view["explanation"]
    assert explanation.startswith("Template note:"), (draft, explanation)
    assert draft.strip() not in explanation
    for field in pipeline.OUTBOUND_FIELDS:
        assert f"{field}={run.view['affordability'][field]}" in explanation


def test_clean_draft_passes_through(monkeypatch, run_case):
    fake = RecordingBrane(text="The note covers net pay, housing, utilities and debt payments of 245000, 85000, 12000 and 0 cents.")
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    run = run_case("clean")
    assert not run.view["explanation"].startswith("Template note:")


def test_draft_carrying_restored_identifier_is_blocked(monkeypatch, run_case):
    fake = RecordingBrane(text="Prepared for <PERSON_1> at <ADDRESS_1>.")
    monkeypatch.setattr(pipeline, "get_cloud", lambda: fake)
    run = run_case("clean")
    assert run.view["explanation"].startswith("Template note:")
    assert "Nora Voorbeeld" not in run.surfaces()["officer_view"]
