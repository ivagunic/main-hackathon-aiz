#!/usr/bin/env python3
"""Pull, review, check, and explicitly apply the team's BRANE policy."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
POLICY_PATH = ROOT / "policy" / "brane_policy.json"
POLICY_KEYS = ("routingMode", "piiSensitivity", "categories", "semanticCategories")


def _request(method: str, path: str, body: object | None = None) -> tuple[int, object]:
    base = os.getenv("BRANE_BASE_URL", "https://brane.ai-z.io/api/v1").rstrip("/")
    key = os.getenv("BRANE_API_KEY", "")
    if not key:
        raise RuntimeError("BRANE_API_KEY is required in the environment or .env")
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "BRANE-Starter-Kit/1.0 (MAIN-Summit-2026)",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
            try:
                decoded: object = json.loads(payload)
            except json.JSONDecodeError:
                decoded = payload
            return response.status, decoded
    except HTTPError as exc:
        # Never emit request headers or credentials. Response details are safe for
        # inspection and useful when BRANE denies or rejects a policy operation.
        # Do not echo response bodies in the credential-bearing command path.
        exc.close()
        raise RuntimeError(f"BRANE HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"BRANE request failed: {type(exc).__name__}") from None


def _policy_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("policy file must contain a JSON object")
    payload = {key: value[key] for key in POLICY_KEYS if key in value}
    if "routingMode" not in payload or "piiSensitivity" not in payload:
        raise ValueError("policy must contain routingMode and piiSensitivity")
    if "categories" in payload and not isinstance(payload["categories"], dict):
        raise ValueError("categories must be an object")
    if "semanticCategories" in payload and not isinstance(payload["semanticCategories"], list):
        raise ValueError("semanticCategories must be a list")
    return payload


def pull() -> int:
    status, policy = _request("GET", "/policy")
    if not isinstance(policy, dict):
        raise TypeError("GET /policy did not return a JSON object")
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"GET /policy: HTTP {status}; saved current policy to {POLICY_PATH.relative_to(ROOT)}")
    return 0


def push(apply: bool) -> int:
    if not POLICY_PATH.exists():
        raise RuntimeError("policy/brane_policy.json is missing; run `make policy-pull` first")
    desired = _policy_payload(json.loads(POLICY_PATH.read_text(encoding="utf-8")))
    _, current_raw = _request("GET", "/policy")
    current = _policy_payload(current_raw)
    before = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    after = json.dumps(desired, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    diff = "\n".join(difflib.unified_diff(before, after, fromfile="BRANE current policy", tofile="policy/brane_policy.json", lineterm=""))
    print(diff or "No policy changes.")
    if not apply:
        print("Review the diff above. No policy was changed. To apply an approved diff, run `make policy-push-apply`.")
        return 0
    if not diff:
        print("No update needed.")
        return 0
    status, updated = _request("PUT", "/policy", desired)
    print(f"PUT /policy: HTTP {status}")
    print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def check(prompt: str) -> int:
    status, result = _request("POST", "/policy/test", {"prompt": prompt, "executeCompletion": False})
    print(f"POST /policy/test: HTTP {status}")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def check_drafting_prompt() -> int:
    """Verify the exact four-token drafting prompt is allowed to route to cloud."""
    from app.gateway import BraneBlocked, BraneClient, BraneUnavailable
    from app.pipeline import drafting_prompt

    try:
        result, headers = BraneClient().test_policy_prompt(drafting_prompt())
    except (BraneBlocked, BraneUnavailable) as exc:
        print(f"Drafting prompt workbench: denied/unavailable ({type(exc).__name__})")
        return 1
    flattened: dict[str, str] = {key.casefold().replace("_", "-"): str(value).casefold() for key, value in headers.items()}

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                flattened[str(key).casefold().replace("_", "-")] = str(child).casefold()
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(result)
    routed_cloud = any("cloud" == value.strip() for key, value in flattened.items()
        if "routed-to" in key or key in {"route", "routed", "lane", "routedto"})
    allowed = any(value.strip() in {"allow", "allowed"} for key, value in flattened.items()
        if "action" in key or "verdict" in key or "decision" in key)
    print("Drafting prompt workbench response:")
    print(json.dumps({"headers": headers, "result": result}, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"Drafting prompt policy check: {'PASS' if routed_cloud and allowed else 'FAIL'} (allow/cloud required)")
    return 0 if routed_cloud and allowed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pull", help="download current BRANE /policy")
    push_parser = subparsers.add_parser("push", help="show diff; only --apply sends PUT /policy")
    push_parser.add_argument("--apply", action="store_true", help="apply the already displayed policy diff")
    check_parser = subparsers.add_parser("check", help="run a non-completing POST /policy/test")
    check_parser.add_argument("prompt", help="synthetic prompt to evaluate")
    subparsers.add_parser("draft-check", help="check that the token drafting prompt routes allow/cloud")
    args = parser.parse_args(argv)
    try:
        if args.command == "pull":
            return pull()
        if args.command == "push":
            return push(args.apply)
        if args.command == "draft-check":
            return check_drafting_prompt()
        return check(args.prompt)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
