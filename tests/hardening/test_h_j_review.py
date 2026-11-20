"""J. Human review gate (P15) and absence of any score or recommendation."""
from __future__ import annotations

import json
import re

import pytest

from app.api.main import app
from app.models import Affordability, OfficerView

GOOD = {"officer_id": "synthetic-officer", "action": "ask_more", "reason": "Payslip and salary credit need a manual check."}
LENDING_WORDS = re.compile(r"score|rating|recommend|risk|verdict|eligib|creditworth", re.IGNORECASE)


@pytest.fixture
def processed(client, brane):
    assert client.post("/cases", data={"case_id": "clean"}).status_code == 200
    assert client.post("/cases/clean/process").status_code == 200
    return "clean"


def test_review_before_view_opened_is_refused(client, processed):
    assert client.post(f"/cases/{processed}/review", json=GOOD).status_code == 409


def test_review_after_reprocessing_requires_reopening(client, processed):
    assert client.get(f"/cases/{processed}/view").status_code == 200
    assert client.post(f"/cases/{processed}/process").status_code == 200
    assert client.post(f"/cases/{processed}/review", json=GOOD).status_code == 409


@pytest.mark.parametrize("body", [
    {k: v for k, v in GOOD.items() if k != "reason"},
    {**GOOD, "reason": ""},
    {**GOOD, "reason": "ok"},
    {**GOOD, "reason": "too short reason"},
    {**GOOD, "reason": " " * 40},
    {**GOOD, "reason": "\u200b" * 40},
    {**GOOD, "reason": "\u200b \u200b" * 15},
    {**GOOD, "reason": "." * 25},
    {**GOOD, "reason": None},
    {**GOOD, "reason": 12345678901234567890123},
], ids=["missing", "empty", "two_chars", "sixteen_chars", "spaces", "zero_width", "zero_width_and_spaces", "dots", "null", "number"])
def test_review_without_a_real_reason_is_refused(client, processed, body):
    client.get(f"/cases/{processed}/view")
    assert client.post(f"/cases/{processed}/review", json=body).status_code == 422


@pytest.mark.parametrize("action", ["", "APPROVE", "approve ", "auto_approve", "score", "recommend", "accept", None, 1])
def test_review_with_invalid_action_is_refused(client, processed, action):
    client.get(f"/cases/{processed}/view")
    assert client.post(f"/cases/{processed}/review", json={**GOOD, "action": action}).status_code == 422


@pytest.mark.parametrize("action", ["approve", "decline", "ask_more"])
def test_valid_review_is_recorded(client, processed, action):
    client.get(f"/cases/{processed}/view")
    assert client.post(f"/cases/{processed}/review", json={**GOOD, "action": action}).status_code == 200


def test_review_on_unknown_case_is_refused(client):
    assert client.post("/cases/nosuchcase/review", json=GOOD).status_code in (404, 409)


def test_no_endpoint_field_or_text_returns_a_score_or_recommendation(client, processed):
    schema = client.get("/openapi.json").json()
    for path in schema["paths"]:
        assert not LENDING_WORDS.search(path), path
    for name, component in schema.get("components", {}).get("schemas", {}).items():
        for prop in component.get("properties", {}):
            assert not LENDING_WORDS.search(prop), (name, prop)
    for model in (OfficerView, Affordability):
        for field in model.model_fields:
            assert not LENDING_WORDS.search(field), field
    view = client.get(f"/cases/{processed}/view").json()
    text = json.dumps(view)
    assert not re.search(r"\b(approv\w*|reject\w*|declin\w*|score\w*|recommend\w*|risk\w*|goedkeur\w*|afwijz\w*)\b", text, re.IGNORECASE), text
    events = client.get(f"/cases/{processed}/events").text
    assert not re.search(r"\b(score|recommend\w*|risk)\b", events, re.IGNORECASE)
    assert {route.path for route in app.routes} >= {"/cases/{case_id}/review"}
