"""K. API abuse: unknown ids, traversal, oversized and malformed uploads, concurrency."""
from __future__ import annotations

import json
import threading

import pytest
from hardening_helpers import load_fixture

from app import pipeline


def test_unknown_case_id_is_404_without_server_paths(client, brane):
    assert client.post("/cases", data={"case_id": "nosuchcase"}).status_code == 404
    response = client.post("/cases/nosuchcase/process")
    assert response.status_code == 404
    assert "\\" not in response.text and "/Users" not in response.text and "Errno" not in response.text
    assert client.get("/cases/nosuchcase/view").status_code == 404
    assert brane.payloads == []


@pytest.mark.parametrize("case_id", [
    "..%5C..%5Cdata%5Cfiles%5Cclean", "..%5Cclean", "C:%5CWindows%5Cwin", "clean%00", "..", "...",
    "clean.json", "%2e%2e%5cclean", "clean%20", "cl%C3%A9an",
])
def test_path_traversal_in_case_id_is_rejected(client, brane, case_id):
    for method, url in (("post", f"/cases/{case_id}/process"), ("get", f"/cases/{case_id}/view"),
                        ("get", f"/cases/{case_id}/ledger"), ("post", f"/cases/{case_id}/ask")):
        response = getattr(client, method)(url, **({"json": {"session_id": "s", "question": "q"}} if url.endswith("ask") else {}))
        assert response.status_code in (404, 409, 422), (url, response.status_code)
    assert brane.payloads == []
    assert pipeline.VIEWS == {}


def test_traversal_in_form_case_id_is_rejected(client):
    for case_id in ("../clean", "..\\clean", "clean.json", ""):
        assert client.post("/cases", data={"case_id": case_id}).status_code in (404, 422)


def test_oversized_upload_is_rejected(client, brane):
    raw = load_fixture("clean")
    raw["raw_pages"] = ["x" * 1024] * 6000  # ~6 MB of page text
    response = client.post("/cases", files={"file": ("big.json", json.dumps(raw).encode(), "application/json")})
    assert response.status_code == 413
    assert brane.payloads == []


@pytest.mark.parametrize(("content", "ctype"), [
    (b"%PDF-1.4 synthetic", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"<loan>synthetic</loan>", "text/xml"),
    (b"{not json", "application/json"),
    (b"[]", "application/json"),
    (b"null", "application/json"),
    (b'{"case_id": "x"}', "application/json"),
    (json.dumps({**load_fixture("clean"), "unexpected": 1}).encode(), "application/json"),
    ("﻿{".encode(), "application/json"),
    (b"\xff\xfe\x00", "application/json"),
])
def test_wrong_type_or_malformed_upload_is_a_clean_4xx(client, brane, content, ctype):
    response = client.post("/cases", files={"file": ("f", content, ctype)})
    assert 400 <= response.status_code < 500, response.status_code
    assert "Traceback" not in response.text
    assert brane.payloads == []


def test_upload_case_id_must_be_alphanumeric_and_match(client):
    raw = load_fixture("clean")
    raw["case_id"] = "../evil"
    assert client.post("/cases", files={"file": ("f.json", json.dumps(raw).encode(), "application/json")}).status_code == 422
    raw["case_id"] = "clean"
    assert client.post("/cases", data={"case_id": "other"}, files={"file": ("f.json", json.dumps(raw).encode(), "application/json")}).status_code == 422


def test_malformed_json_bodies_on_json_endpoints(client, brane):
    client.post("/cases", data={"case_id": "clean"})
    client.post("/cases/clean/process")
    client.get("/cases/clean/view")
    for url in ("/cases/clean/review", "/cases/clean/ask"):
        for body in (b"{bad", b"[]", b"null", b'{"question": 5}'):
            response = client.post(url, content=body, headers={"content-type": "application/json"})
            assert response.status_code == 422, (url, body, response.status_code)


def test_two_cases_processed_concurrently_do_not_mix(client, brane):
    baselines = {}
    for case_id in ("clean", "sensitive"):
        baselines[case_id] = pipeline.process(case_id).model_dump(mode="json")
    errors: list[BaseException] = []
    results: dict[str, list[dict]] = {"clean": [], "sensitive": []}

    def worker(case_id):
        try:
            for _ in range(10):
                results[case_id].append(pipeline.process(case_id).model_dump(mode="json"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(c,)) for c in ("clean", "sensitive", "clean", "sensitive")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    for case_id, views in results.items():
        for view in views:
            assert view == baselines[case_id]
        events = pipeline.EVENTS[case_id]
        assert all(e.get("case_id", case_id) == case_id for e in events)
    assert "Nora Voorbeeld" not in json.dumps(results["sensitive"])
    assert "Mila Verzonnen" not in json.dumps(results["clean"])
    for payload in brane.payloads:
        expected = {f: baselines[payload["case_id"]]["affordability"][f] for f in pipeline.OUTBOUND_FIELDS}
        assert json.loads(payload["user"]) == expected, payload["case_id"]
