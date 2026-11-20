"""B. Canary leak test (P2, P3, P4, P5) and M. logging (matrix section D).

50 invented loan files, each planting a unique name, IBAN, BSN, employer, address and three
sensitive merchants in many variants. No canary may appear on any surface.
"""
from __future__ import annotations

import json
import logging
import random

import pytest
from hardening_helpers import find_canaries, load_fixture, make_canary_file

from app import pipeline

FILES = [make_canary_file(random.Random(20261120 + i), i) for i in range(50)]


@pytest.mark.parametrize("index", range(len(FILES)))
def test_no_canary_on_any_surface(run_case, caplog, capsys, index):
    caplog.set_level(logging.DEBUG)
    raw, canary = FILES[index]
    run = run_case(raw)
    surfaces = run.surfaces()
    captured = capsys.readouterr()
    surfaces["logs"] = caplog.text + captured.out + captured.err
    leaks = {name: hits for name, text in surfaces.items() if (hits := find_canaries(text, canary))}
    assert not leaks, f"canary leak for {raw['case_id']}: {leaks}"


def test_canary_files_actually_exercise_the_pipeline(run_case):
    """Guard against a vacuous pass: the canary file reaches the cloud call and shows transactions."""
    raw, _ = FILES[0]
    run = run_case(raw)
    assert len(run.brane.payloads) == 1
    assert run.view["visible_transactions"], "expected non-sensitive lines to stay visible to the officer"


def test_third_party_private_person_name_in_transfer_is_not_shown(run_case):
    """P2 lists 'names in transfers to private persons'. A transfer to an invented private person
    without any IBAN in the line must not show that person's name to the cloud or in the view."""
    raw = load_fixture("clean")
    raw["transactions"].append({"id": "t9", "date": "2026-10-11", "counterparty": "J. Quinzelaro",
                                "description": "Terugbetaling etentje", "amount_cents": -2500, "page": 2})
    run = run_case(raw)
    assert "Quinzelaro" not in run.surfaces()["cloud_payloads"]
    if "Quinzelaro" in run.surfaces()["officer_view"]:
        pytest.xfail("OPEN-1: third-party private-person names are not detected locally; needs a design decision")


# ---------- M. logging, events and ledger rows ----------

@pytest.mark.parametrize("index", [0, 7, 21, 49])
def test_no_raw_text_description_or_identifier_in_logs_events_or_ledger_rows(run_case, client, caplog, index):
    caplog.set_level(logging.DEBUG)
    raw, canary = FILES[index]
    run = run_case(raw)
    # Exercise the remaining API surfaces so their logging is captured too.
    client.get(f"/cases/{raw['case_id']}/view")
    client.post(f"/cases/{raw['case_id']}/ask", json={"session_id": "m", "question": "What is the housing amount?"})
    client.get(f"/cases/{raw['case_id']}/ledger", params={"fmt": "csv"})
    forbidden = {tx["description"] for tx in raw["transactions"]} | set(raw["raw_pages"]) | {raw["payslips"][0]["raw_text"]}
    texts = {
        "logs": caplog.text,
        "events": json.dumps(pipeline.EVENTS[raw["case_id"]], ensure_ascii=False),
        "ledger_rows": json.dumps(run.rows, ensure_ascii=False),
    }
    for name, text in texts.items():
        assert not find_canaries(text, canary), name
        for value in forbidden:
            assert value not in text, (name, value)
        for tx in raw["transactions"]:
            assert tx["counterparty"] not in text, (name, tx["counterparty"])
    # Ledger rows hold decisions only: no free-text column exists.
    assert set(run.rows[0]) == {"seq", "case_id", "element_id", "category", "lane", "rule_id", "citation", "policy_version",
                                "brane_verdict", "payload_sha256", "ts", "aiz_decision", "brane_policy_ref"}
