"""The only package permitted to make network requests."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from app.models import LoanFile

DEFAULT_BRANE_BASE_URL = "https://brane.ai-z.io/api/v1"
CHAT_COMPLETIONS_PATH = "/chat/completions"
MODELS_PATH = "/models"
EXPECTED_CLOUD_FIELDS = frozenset({"net_pay_cents", "housing_cents", "utilities_cents", "debt_payment_cents"})


class BraneUnavailable(RuntimeError):
    pass


class BraneBlocked(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, decision: str | None = None,
        response_headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.decision = decision
        self.response_headers = response_headers or {}


@dataclass
class CloudResult:
    text: str
    verdict: str
    payload_sha256: str
    http_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)


def build_brane_request(
    *, base_url: str, path: str, model: str, api_key: str, system: str = "", user: str = "", method: str = "POST",
    request_body: dict | None = None,
) -> tuple[str, dict[str, str], dict | None]:
    """Centralize BRANE method, URL, auth header, and chat body construction."""
    endpoint = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"User-Agent": "BRANE-Starter-Kit/1.0 (MAIN-Summit-2026)"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = None if method.upper() == "GET" else request_body if request_body is not None else {
        "model": model,
        "temperature": 0,
        "seed": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    return endpoint, headers, body


def _decision_headers(headers: httpx.Headers) -> dict[str, str]:
    prefixes = ("x-brane-", "brane-", "x-policy-", "x-verdict-", "x-decision-")
    return {name: value for name, value in headers.items() if name.casefold().startswith(prefixes)}


def _decision_fields(body: object) -> dict[str, object]:
    if not isinstance(body, dict):
        return {}
    keywords = ("brane", "verdict", "decision", "policy", "protect", "blocked", "deny", "error", "reason")
    return {str(name): value for name, value in body.items() if any(term in str(name).casefold() for term in keywords)}


def _decision_snapshot(status_code: int, headers: httpx.Headers, body: object = None) -> tuple[str, dict[str, str]]:
    decision_headers = _decision_headers(headers)
    metadata = {
        "status_code": status_code,
        "headers": decision_headers,
        "fields": _decision_fields(body),
        # Preserve the complete response so protected text or provider-specific
        # policy details are not silently lost by the adapter.
        "raw_response": body,
    }
    return json.dumps(metadata, sort_keys=True, default=str), decision_headers


def _blocked_decision(status_code: int, headers: httpx.Headers, body: object) -> bool:
    if status_code in {400, 403, 422, 451}:
        return True
    fields = _decision_fields(body)
    candidates = [value for name, value in fields.items()
        if any(term in name.casefold() for term in ("verdict", "decision", "status", "action", "blocked", "deny"))]
    candidates.extend(value for name, value in _decision_headers(headers).items()
        if any(term in name.casefold() for term in ("verdict", "decision", "status", "action")))
    return any(isinstance(value, str) and value.casefold() in {"block", "blocked", "deny", "denied", "refuse", "refused"} for value in candidates)


def _require_four_integer_fields(user: str) -> None:
    try:
        payload = json.loads(user)
    except (TypeError, ValueError) as exc:
        raise BraneUnavailable("Cloud request must be a JSON object with the four approved integer fields") from exc
    if not isinstance(payload, dict) or set(payload) != EXPECTED_CLOUD_FIELDS or any(
        isinstance(value, bool) or not isinstance(value, int) for value in payload.values()
    ):
        raise BraneUnavailable("Cloud request must contain exactly the four approved integer fields")


def _require_positive_verdict(body: object, headers: httpx.Headers, status_code: int) -> None:
    if not isinstance(body, dict):
        raise BraneUnavailable("BRANE returned no explicit positive verdict")
    candidates = [body.get(name) for name in ("brane_verdict", "verdict", "decision")]
    candidates.extend(value for name, value in _decision_headers(headers).items()
        if any(term in name.casefold() for term in ("verdict", "decision", "action")))
    positive = {"allow", "allowed", "protect", "protected", "placeholder", "local"}
    if not any(isinstance(value, str) and value.casefold() in positive
        for value in candidates):
        raise BraneUnavailable(f"BRANE returned no explicit positive verdict (HTTP {status_code})")


class CloudLLM(Protocol):
    def complete(self, system: str, user: str, *, case_id: str, purpose: str) -> CloudResult: ...


class LocalLLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class FakeBrane:
    def __init__(self) -> None:
        self.payloads: list[dict[str, str]] = []

    def complete(self, system: str, user: str, *, case_id: str, purpose: str) -> CloudResult:
        payload = {"system": system, "user": user, "case_id": case_id, "purpose": purpose}
        self.payloads.append(payload)
        digest = hashlib.sha256((system + user).encode()).hexdigest()
        return CloudResult("The assessment uses the supplied income and expense aggregates.", "allow", digest)


class FakeLocal:
    def complete(self, system: str, user: str) -> str:
        lowered = user.casefold()
        if any(term in lowered for term in ("ignore previous", "disregard", "approve this", "system:")):
            return "instruction_attack"
        if any(term in lowered for term in ("ziek", "scheiding", "baan verloren", "ill", "divorce", "job loss", "krank", "scheidung", "arbeitslos")):
            return "hardship_signal"
        return "neutral"


def outbound_guard(payload: str, file: LoanFile) -> None:
    """Reject identifiers and sensitive merchant strings before cloud egress."""
    from app.pseudo import LeakDetected, assert_clean

    assert_clean(payload, file)
    lowered = payload.casefold()
    for transaction in file.transactions:
        if transaction.counterparty and transaction.counterparty.casefold() in lowered:
            raise LeakDetected("Sensitive counterparty detected in outbound payload")


def guarded_local_complete(system: str, user: str, file: LoanFile) -> str:
    from app.pseudo import build_map, scrub

    mode = os.getenv("PRESCRUB", "on").casefold()
    if mode == "on":
        user = scrub(user, build_map(file))
        outbound_guard(user, file)
    elif mode == "off":
        fixture = Path(__file__).resolve().parents[2] / "data" / "files" / f"{file.case_id}.json"
        if os.getenv("BRANE_MODE", "fake") != "live" or os.getenv("BRANE_POLICY_CONFIRMED", "off").casefold() != "on" or not fixture.is_file():
            raise BraneUnavailable("PRESCRUB=off requires a confirmed live BRANE policy and a synthetic fixture")
    else:
        raise ValueError("PRESCRUB must be on or off")
    return get_local().complete(system, user)


class BraneClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("BRANE_BASE_URL", DEFAULT_BRANE_BASE_URL).rstrip("/")
        self.api_key = os.getenv("BRANE_API_KEY", "")
        self.model = os.getenv("BRANE_MODEL", "auto")
        self._cache_path = os.getenv("BRANE_CACHE_PATH", "brane-cache.sqlite3")

    def complete(self, system: str, user: str, *, case_id: str, purpose: str) -> CloudResult:
        if not self.base_url or not self.model or not self.api_key:
            raise BraneUnavailable("BRANE endpoint, API key, and model are required")
        _require_four_integer_fields(user)
        digest = hashlib.sha256((self.base_url + "\0" + system + "\0" + user + "\0" + self.model).encode()).hexdigest()
        Path(self._cache_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._cache_path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, text TEXT NOT NULL, verdict TEXT NOT NULL)")
            cached = db.execute("SELECT text, verdict FROM cache WHERE key=?", (digest,)).fetchone()
        if cached:
            return CloudResult(cached[0], cached[1], digest)
        url, headers, body = build_brane_request(base_url=self.base_url, path=CHAT_COMPLETIONS_PATH, model=self.model,
            api_key=self.api_key, system=system, user=user)
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                response = client.post(url, headers=headers, json=body)
            if response.status_code >= 500:
                raise BraneUnavailable(f"BRANE returned HTTP {response.status_code}")
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text
            if _blocked_decision(response.status_code, response.headers, response_body):
                decision, brane_headers = _decision_snapshot(response.status_code, response.headers, response_body)
                raise BraneBlocked(f"BRANE blocked the request (HTTP {response.status_code})", response.status_code,
                    decision, brane_headers)
            response.raise_for_status()
            _require_positive_verdict(response_body, response.headers, response.status_code)
            if not isinstance(response_body, dict):
                raise ValueError("BRANE returned a non-object response")
            text = response_body["choices"][0]["message"]["content"]
            verdict, brane_headers = _decision_snapshot(response.status_code, response.headers, response_body)
        except BraneUnavailable:
            raise
        except BraneBlocked:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise BraneUnavailable("BRANE request failed") from exc
        with closing(sqlite3.connect(self._cache_path)) as db, db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (digest, text, verdict))
        return CloudResult(text, verdict, digest, response.status_code, brane_headers)

    def complete_synthetic_policy_evidence(self, prompt: str, *, test_id: str) -> CloudResult:
        """Send one explicitly synthetic policy-evidence prompt through BRANE.

        This bypasses the application's four-figure prompt validator only for
        the opt-in evidence runner; normal `complete` remains exact-schema only.
        """
        if not test_id or not test_id.startswith(("T", "E")):
            raise ValueError("synthetic policy evidence requires a T/E test ID")
        if os.getenv("BRANE_MODE", "fake").casefold() != "live":
            raise BraneUnavailable("synthetic BRANE evidence requires BRANE_MODE=live")
        if not self.api_key or not self.model:
            raise BraneUnavailable("BRANE_API_KEY and BRANE_MODEL are required")
        system = "Draft a neutral note for human review."
        digest = hashlib.sha256((self.base_url + "\0evidence\0" + test_id + "\0" + prompt).encode()).hexdigest()
        url, headers, body = build_brane_request(base_url=self.base_url, path=CHAT_COMPLETIONS_PATH,
            model=self.model, api_key=self.api_key, system=system, user=prompt)
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                response = client.post(url, headers=headers, json=body)
            if response.status_code >= 500:
                raise BraneUnavailable(f"BRANE returned HTTP {response.status_code}")
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text
            if _blocked_decision(response.status_code, response.headers, response_body):
                decision, response_headers = _decision_snapshot(response.status_code, response.headers, response_body)
                raise BraneBlocked(f"BRANE blocked synthetic evidence request (HTTP {response.status_code})",
                    response.status_code, decision, response_headers)
            response.raise_for_status()
            answer = ""
            if isinstance(response_body, dict):
                answer = str(response_body.get("choices", [{}])[0].get("message", {}).get("content", ""))
            decision, response_headers = _decision_snapshot(response.status_code, response.headers, response_body)
            return CloudResult(answer, decision, digest, response.status_code, response_headers)
        except (BraneUnavailable, BraneBlocked):
            raise
        except httpx.HTTPError as exc:
            raise BraneUnavailable("BRANE synthetic evidence request failed") from exc

    def test_policy_prompt(self, prompt: str) -> tuple[object, dict[str, str]]:
        """Ask BRANE's live policy test bench for detections and egress preview."""
        if not self.api_key:
            raise BraneUnavailable("BRANE_API_KEY is required")
        url, headers, body = build_brane_request(base_url=self.base_url, path="/policy/test", model="",
            api_key=self.api_key, request_body={"prompt": prompt, "executeCompletion": False})
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                response = client.post(url, headers=headers, json=body)
            if response.status_code >= 500:
                raise BraneUnavailable(f"BRANE returned HTTP {response.status_code}")
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text
            if _blocked_decision(response.status_code, response.headers, response_body):
                decision, decision_headers = _decision_snapshot(response.status_code, response.headers, response_body)
                raise BraneBlocked(f"BRANE policy test refused the prompt (HTTP {response.status_code})",
                    response.status_code, decision, decision_headers)
            response.raise_for_status()
            return response_body, _decision_headers(response.headers)
        except (BraneUnavailable, BraneBlocked):
            raise
        except httpx.HTTPError as exc:
            raise BraneUnavailable("BRANE policy test failed") from exc

    def list_models(self) -> tuple[int, object, str, dict[str, str]]:
        if not self.base_url or not self.api_key:
            raise BraneUnavailable("BRANE endpoint and API key are required")
        url, headers, _ = build_brane_request(base_url=self.base_url, path=MODELS_PATH, model="",
            api_key=self.api_key, method="GET")
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=10.0)) as client:
                response = client.get(url, headers=headers)
            if response.status_code >= 500:
                raise BraneUnavailable(f"BRANE returned HTTP {response.status_code}")
            try:
                body = response.json()
            except ValueError:
                body = response.text
            if _blocked_decision(response.status_code, response.headers, body):
                decision, decision_headers = _decision_snapshot(response.status_code, response.headers, body)
                raise BraneBlocked(f"BRANE blocked model listing (HTTP {response.status_code})", response.status_code,
                    decision, decision_headers)
            response.raise_for_status()
            snapshot, decision_headers = _decision_snapshot(response.status_code, response.headers, body)
            return response.status_code, body, snapshot, decision_headers
        except (BraneUnavailable, BraneBlocked):
            raise
        except httpx.HTTPError as exc:
            raise BraneUnavailable("BRANE model listing failed") from exc

    def brane_ok(self) -> bool:
        try:
            self.list_models()
            return True
        except (BraneUnavailable, BraneBlocked):
            return False


class LocalClient:
    """Local inference routed through BRANE's configured local endpoint."""

    def __init__(self) -> None:
        self.base_url = os.getenv("BRANE_BASE_URL", DEFAULT_BRANE_BASE_URL).rstrip("/")
        self.api_key = os.getenv("BRANE_API_KEY", "")
        self.model = os.getenv("BRANE_LOCAL_MODEL", "vllm:deepseek-v4.1-flash")

    def complete(self, system: str, user: str) -> str:
        if not self.base_url or not self.model or not self.api_key:
            raise BraneUnavailable("BRANE local endpoint, API key, and model are required")
        url, headers, body = build_brane_request(base_url=self.base_url, path=CHAT_COMPLETIONS_PATH, model=self.model,
            api_key=self.api_key, system=system, user=user)
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                response = client.post(url, headers=headers, json=body)
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text
            if _blocked_decision(response.status_code, response.headers, response_body):
                decision, decision_headers = _decision_snapshot(response.status_code, response.headers, response_body)
                raise BraneBlocked(f"BRANE blocked the local request (HTTP {response.status_code})", response.status_code,
                    decision, decision_headers)
            response.raise_for_status()
            if not isinstance(response_body, dict):
                raise ValueError("BRANE returned a non-object local response")
            return str(response_body["choices"][0]["message"]["content"])
        except BraneBlocked:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise BraneUnavailable("BRANE local request failed") from exc

def brane_ok() -> bool:
    if os.getenv("BRANE_MODE", "fake") == "fake":
        return True
    return BraneClient().brane_ok()


def get_cloud() -> CloudLLM:
    if os.getenv("BRANE_DEMO_DOWN", "off").casefold() == "on":
        class ForcedUnavailable:
            def complete(self, system: str, user: str, *, case_id: str, purpose: str) -> CloudResult:
                raise BraneUnavailable("BRANE was set to down for the demo")
        return ForcedUnavailable()
    return FakeBrane() if os.getenv("BRANE_MODE", "fake") == "fake" else BraneClient()


def get_local() -> LocalLLM:
    return FakeLocal() if os.getenv("BRANE_MODE", "fake") == "fake" else LocalClient()
