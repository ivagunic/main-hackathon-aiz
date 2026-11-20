from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gateway import BraneBlocked, BraneClient, BraneUnavailable

SYSTEM = "Return a brief neutral confirmation for this synthetic four-field smoke test."
PAYLOAD = {
    "net_pay_cents": 0,
    "housing_cents": 0,
    "utilities_cents": 0,
    "debt_payment_cents": 0,
}


def _positive_verdict(value: str) -> bool:
    try:
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            fields = decoded.get("fields", {})
            headers = decoded.get("headers", {})
            decoded = (fields.get("brane_verdict") or fields.get("verdict") or fields.get("decision")
                or headers.get("x-brane-action") or headers.get("x-brane-verdict"))
    except (TypeError, ValueError):
        decoded = value
    return isinstance(decoded, str) and decoded.casefold() in {"allow", "allowed", "protect", "protected", "placeholder", "local"}


def main() -> int:
    if os.getenv("BRANE_MODE", "fake").casefold() != "live":
        print("FAIL: set BRANE_MODE=live to run the real BRANE smoke check")
        return 1
    if not os.getenv("BRANE_API_KEY") or not os.getenv("BRANE_MODEL", "auto"):
        print("FAIL: BRANE_API_KEY is required and BRANE_MODEL cannot be empty")
        return 1
    if os.getenv("PRESCRUB", "on").casefold() != "on":
        print("FAIL: PRESCRUB must be on")
        return 1

    original_base_url = os.getenv("BRANE_BASE_URL", "https://brane.ai-z.io/api/v1")
    original_cache = os.getenv("BRANE_CACHE_PATH")
    failures = []
    with tempfile.TemporaryDirectory(prefix="brane-smoke-") as temp_dir:
        os.environ["BRANE_CACHE_PATH"] = str(Path(temp_dir) / "live.sqlite3")
        try:
            user = json.dumps(PAYLOAD, sort_keys=True)
            list_started = time.perf_counter()
            try:
                list_status, models, list_decision, list_headers = BraneClient().list_models()
                print(f"models_status: {list_status}")
                print(f"models_latency_ms: {(time.perf_counter() - list_started) * 1000:.1f}")
                print(f"models_response: {json.dumps(models, sort_keys=True, default=str)}")
                print(f"models_decision_info: {list_decision}")
                print(f"models_decision_headers: {json.dumps(list_headers, sort_keys=True)}")
            except BraneBlocked as exc:
                print(f"models_status: {exc.status_code}")
                print(f"models_latency_ms: {(time.perf_counter() - list_started) * 1000:.1f}")
                print(f"models_decision_info: {exc.decision}")
                print(f"models_decision_headers: {json.dumps(exc.response_headers, sort_keys=True)}")
                failures.append("BRANE denied model listing")
            except BraneUnavailable as exc:
                print(f"models_status: unavailable ({exc})")
                print(f"models_latency_ms: {(time.perf_counter() - list_started) * 1000:.1f}")
                failures.append("BRANE model listing was unavailable")
            started = time.perf_counter()
            try:
                result = BraneClient().complete(SYSTEM, user, case_id="synthetic-smoke", purpose="smoke")
                latency_ms = (time.perf_counter() - started) * 1000
                print(f"live_status: {result.http_status}")
                print(f"live_latency_ms: {latency_ms:.1f}")
                print(f"brane_decision_info: {result.verdict}")
                print(f"brane_decision_headers: {json.dumps(result.response_headers, sort_keys=True)}")
                if result.http_status is None or not 200 <= result.http_status < 300:
                    failures.append("BRANE did not return a successful HTTP status")
                if not _positive_verdict(result.verdict):
                    failures.append("BRANE did not return an explicit positive verdict")
            except BraneBlocked as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                print(f"live_status: {exc.status_code}")
                print(f"live_latency_ms: {latency_ms:.1f}")
                print(f"brane_decision_info: {exc.decision or 'block'}")
                print(f"brane_decision_headers: {json.dumps(exc.response_headers, sort_keys=True)}")
                failures.append("BRANE denied the harmless four-field smoke request")
            except BraneUnavailable as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                print(f"live_status: unavailable ({exc})")
                print(f"live_latency_ms: {latency_ms:.1f}")
                print("brane_decision_info: unavailable")
                print("brane_decision_headers: {}")
                failures.append("BRANE live request was unavailable")

            os.environ["BRANE_BASE_URL"] = "http://127.0.0.1:1"
            os.environ["BRANE_CACHE_PATH"] = str(Path(temp_dir) / "closed-port.sqlite3")
            try:
                BraneClient().complete(SYSTEM, user, case_id="synthetic-closed-port", purpose="smoke_fail_closed")
            except BraneUnavailable:
                print("closed_port: BraneUnavailable confirmed; no alternate provider was used")
            else:
                failures.append("Closed-port check unexpectedly succeeded")
        finally:
            os.environ["BRANE_BASE_URL"] = original_base_url
            if original_cache is None:
                os.environ.pop("BRANE_CACHE_PATH", None)
            else:
                os.environ["BRANE_CACHE_PATH"] = original_cache
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: live BRANE response and fail-closed closed-port check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
