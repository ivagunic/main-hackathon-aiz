"""The only package permitted to make network requests."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app.models import LoanFile


class BraneUnavailable(RuntimeError):
    pass


class BraneBlocked(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, decision: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.decision = decision


@dataclass
class CloudResult:
    text: str
    verdict: str
    payload_sha256: str


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
        self.base_url = os.getenv("BRANE_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("BRANE_API_KEY", "")
        self.model = os.getenv("BRANE_MODEL", "")
        self._cache_path = os.getenv("BRANE_CACHE_PATH", "brane-cache.sqlite3")

    def complete(self, system: str, user: str, *, case_id: str, purpose: str) -> CloudResult:
        if not self.base_url or not self.model:
            raise BraneUnavailable("BRANE endpoint and model are not configured")
        digest = hashlib.sha256((system + "\0" + user + "\0" + self.model).encode()).hexdigest()
        Path(self._cache_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._cache_path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, text TEXT NOT NULL, verdict TEXT NOT NULL)")
            cached = db.execute("SELECT text, verdict FROM cache WHERE key=?", (digest,)).fetchone()
        if cached:
            return CloudResult(cached[0], cached[1], digest)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                response = client.post(self.base_url + "/v1/chat/completions", headers=headers, json={
                    "model": self.model, "temperature": 0, "seed": 0,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                })
            if response.status_code >= 500:
                raise BraneUnavailable(f"BRANE returned HTTP {response.status_code}")
            if response.status_code in (400, 403, 422, 451):
                decision = {"verdict": response.headers.get("x-brane-verdict", "block"), "http_status": response.status_code,
                    "policy_ref": response.headers.get("x-brane-policy", "unreported"), "protected_input_present": False}
                try:
                    block_body = response.json()
                    if isinstance(block_body, dict):
                        decision["verdict"] = block_body.get("brane_verdict", decision["verdict"])
                        decision["protected_input_present"] = "protected_input" in block_body
                except ValueError:
                    pass
                raise BraneBlocked(f"BRANE blocked the request (HTTP {response.status_code})", response.status_code, json.dumps(decision, sort_keys=True))
            response.raise_for_status()
            body = response.json()
            text = body["choices"][0]["message"]["content"]
            verdict = json.dumps({
                "verdict": body.get("brane_verdict", response.headers.get("x-brane-verdict", "unreported")),
                "http_status": response.status_code,
                "protected_input_present": "protected_input" in body,
                "policy_ref": response.headers.get("x-brane-policy", "unreported"),
            }, sort_keys=True)
        except BraneUnavailable:
            raise
        except BraneBlocked:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise BraneUnavailable("BRANE request failed") from exc
        with closing(sqlite3.connect(self._cache_path)) as db, db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (digest, text, verdict))
        return CloudResult(text, verdict, digest)

    def brane_ok(self) -> bool:
        if not self.base_url:
            return False
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=10.0)) as client:
                response = client.get(self.base_url + "/health")
            return response.is_success
        except httpx.HTTPError:
            return False


class LocalClient:
    """Local inference routed through BRANE's configured local endpoint."""

    def __init__(self) -> None:
        self.base_url = os.getenv("BRANE_BASE_URL", "").rstrip("/")
        self.path = os.getenv("BRANE_LOCAL_PATH", "/v1/local/chat/completions")
        self.api_key = os.getenv("BRANE_API_KEY", "")
        self.model = os.getenv("BRANE_LOCAL_MODEL", os.getenv("BRANE_MODEL", ""))

    def complete(self, system: str, user: str) -> str:
        if not self.base_url or not self.model:
            raise BraneUnavailable("BRANE local endpoint is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                response = client.post(self.base_url + self.path, headers=headers, json={"model": self.model, "temperature": 0, "seed": 0,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])
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
