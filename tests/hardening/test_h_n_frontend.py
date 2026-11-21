"""N. Demo page: same-origin only, no lending verdicts, and nothing hidden can reach what it renders."""
from __future__ import annotations

import json
import random
import re

import pytest
from hardening_helpers import (
    FIXTURES,
    ROOT,
    find_canaries,
    load_fixture,
    make_canary_file,
)

PAGE = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

# Everything identifying or sensitive in the four demo fixtures.
FIXTURE_SECRETS = {
    "clean": ["Nora Voorbeeld", "NL00BANK0123456789", "123456789", "Fictiefstraat 12", "Voorbeeld Atelier"],
    "sensitive": ["Mila Verzonnen", "NL00FAKE0987654321", "987654324", "Demoweg 8", "Fictief Drukwerk",
                  "Stichting Fictieve Kerk", "Apotheek De Voorbeeldbrug", "Ik ben ziek"],
    "variant_a": ["Alex Voorbeeld", "NL00MOCK22223333444455", "111111110", "Testlaan 4", "Testatelier Voorbeeld"],
    "variant_b": ["Sam Fictief", "NL00SAMP33334444555566", "123456789", "Proefpad 19", "Voorbeeldwerk BV"],
}


def _page_calls(client, case_id: str) -> str:
    """Replay exactly what the page fetches for one file and return every response body it can render."""
    bodies = []
    for method, url, kwargs in (
        ("post", "/cases", {"data": {"case_id": case_id}}),
        ("post", f"/cases/{case_id}/process", {}),
        ("get", f"/cases/{case_id}/view", {}),
        ("get", f"/cases/{case_id}/ledger", {}),
        ("get", f"/cases/{case_id}/ledger?fmt=csv", {}),
        ("post", f"/cases/{case_id}/ask", {"json": {"session_id": "page", "question": "What is the housing amount?"}}),
        ("post", f"/cases/{case_id}/ask", {"json": {"session_id": "page2", "question": "Which church does she pay?"}}),
        ("post", f"/cases/{case_id}/review", {"json": {"officer_id": "presenter", "action": "ask_more", "reason": "Need the October statement page two."}}),
    ):
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 200, (url, response.status_code, response.text[:200])
        bodies.append(response.text)
    return "\n".join(bodies)


def _digits_loose(value: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\d)" + r"[.\s-]*".join(value) + r"(?!\d)") if value.isdigit() else re.compile(
        r"\s*".join(map(re.escape, value.replace(" ", ""))), re.IGNORECASE)


def test_page_is_served_at_root_with_same_origin_policy(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    csp = response.headers["content-security-policy"]
    assert "connect-src 'self'" in csp and "default-src 'none'" in csp
    assert "Loan file assistant" in response.text


def test_page_has_no_outside_links_or_model_calls():
    assert not re.search(r"(?i)\b(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}", PAGE), "outside address in page"
    assert not re.search(r"(?i)<(?:link|img|iframe|object|embed)\b|@import|@font-face|src\s*=", PAGE)
    for fetched in re.findall(r"api\(\s*\"[A-Z]+\",\s*`?\"?([^`\",]+)", PAGE):
        assert fetched.startswith(("/cases", "/admin/brane")), fetched
    assert not re.search(r"(?i)openai|anthropic|claude|brane\.|/v1/|chat/completions", PAGE)


def test_page_never_reads_the_raw_file(client):
    assert "data/files" not in PAGE and "raw_pages" not in PAGE and "payslips" not in PAGE
    assert client.get("/data/files/sensitive.json").status_code == 404
    assert "visible_transactions" in PAGE


def test_question_answer_has_a_plain_brane_check_line():
    assert '<p id="answer-check"' in PAGE
    assert "Checked by BRANE: ${label}" in PAGE
    # The label is never invented by the page: a missing label must not default to any verdict word.
    assert '|| "blocked"' not in PAGE and "|| 'blocked'" not in PAGE
    assert 'const ANSWER_LABELS = ["allowed", "name replaced", "kept inside the bank"];' in PAGE


def test_refusal_shows_only_the_refusal_sentence_and_answers_need_a_positive_label():
    body = PAGE[PAGE.index("async function askQuestion"):PAGE.index("async function toggleOffline")]
    refused = body.index("if (result.data.refused)")
    positive = body.index("ANSWER_LABELS.includes(label)")
    unchecked = body.index("MSG.unchecked")
    # Refusal is decided first, then a positive label, otherwise the answer is withheld.
    assert refused < positive < unchecked
    assert "The assistant will not answer this question." not in body


def test_page_has_no_score_rating_verdict_or_recommendation():
    visible_text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", PAGE, flags=re.DOTALL)
    assert not re.search(r"(?i)\b(score\w*|rating\w*|recommend\w*|verdict\w*|risk\w*|eligib\w*)\b", visible_text)
    script = re.search(r"<script>(.*)</script>", PAGE, re.DOTALL).group(1)
    assert not re.search(r"(?i)\b(score|rating|recommend\w*|risk)\b", script)
    # Narrowed (approved): the page may read the stored decision only to get the X-Brane routing header.
    assert not re.search(r"(?i)payload_sha256|raw_response|\.fields\b", script), "page must not surface hashes or response text"
    uses = re.findall(r"[^\n]*brane_verdict[^\n]*", script)
    allowed = (r"JSON\.parse\(row\.brane_verdict\)", r"filter\(\(row\) => row\.brane_verdict\)", r'decided\.brane_verdict === "allow"')
    assert uses and all(any(re.search(pattern, line) for pattern in allowed) for line in uses), uses
    assert "x-brane-routed-to" in script
    assert "The assistant does not decide. You do." in PAGE


@pytest.mark.parametrize("case_id", FIXTURES)
def test_nothing_hidden_reaches_what_the_page_renders(client, brane, case_id):
    rendered = _page_calls(client, case_id)
    for secret in FIXTURE_SECRETS[case_id]:
        assert not _digits_loose(secret).search(rendered), (case_id, secret)
    assert all(secret not in PAGE for secrets in FIXTURE_SECRETS.values() for secret in secrets)


@pytest.mark.parametrize("seed", range(10))
def test_page_responses_for_invented_files_carry_no_canary(client, brane, seed):
    raw, canary = make_canary_file(random.Random(5000 + seed), 700 + seed)
    created = client.post("/cases", files={"file": ("f.json", json.dumps(raw).encode(), "application/json")})
    assert created.status_code == 200
    case_id = raw["case_id"]
    bodies = [client.post(f"/cases/{case_id}/process").text, client.get(f"/cases/{case_id}/view").text,
              client.get(f"/cases/{case_id}/ledger").text, client.get(f"/cases/{case_id}/ledger?fmt=csv").text]
    assert not find_canaries("\n".join(bodies), canary)


def test_offline_switch_path_used_by_the_page(client, monkeypatch):
    from app import gateway, pipeline
    monkeypatch.setattr(pipeline, "get_cloud", gateway.get_cloud)
    assert client.post("/admin/brane/down").status_code == 200
    try:
        view = client.post("/cases/clean/process").json()
    finally:
        assert client.post("/admin/brane/up").status_code == 200
    assert "brane_unavailable" in view["flags"]
    assert load_fixture("clean")["applicant"]["name"] not in json.dumps(view)
