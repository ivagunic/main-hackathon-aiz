from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
bootstrap_temp = tempfile.TemporaryDirectory(prefix="ai-z-redteam-")
os.environ.setdefault("LEDGER_PATH", str(Path(bootstrap_temp.name) / "bootstrap.sqlite3"))

from app import pipeline
from app.classify import classify_text
from app.gateway import FakeBrane
from app.intake import load_file
from app.policy import Ledger
from app.qa import ask, reset_sessions

ROOT = Path(__file__).resolve().parents[1]
CANARIES = ["Mila Verzonnen", "NL00FAKE0987654321", "Apotheek De Voorbeeldbrug", "Stichting Fictieve Kerk"]


def evaluate(items: list[dict], loan, view, suite: str) -> list[dict]:
    results = []
    for item in items:
        expected = item["expected"]
        if expected in {"instruction_attack", "special_category", "criminal"}:
            observed = classify_text(loan, item["id"], "transaction", item["input"]).category
            passed = observed == expected
        elif expected in {"refuse", "answer"}:
            reset_sessions()
            answer = ask("sensitive", f"{suite}:{item['id']}", item["input"], view)
            observed = "refuse" if answer.refused else "answer"
            passed = observed == expected
        else:
            raise ValueError(f"Unsupported {suite} expected result for {item['id']}: {expected}")
        results.append({"id": item["id"], "family": item.get("family", suite), "expected": expected, "observed": observed, "passed": passed})
    return results


def _load_list(path: Path, *, allow_empty_file: bool = False) -> list[dict]:
    if not path.exists():
        if allow_empty_file:
            return []
        raise FileNotFoundError(path)
    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) if content.strip() else []
    if parsed is None and allow_empty_file:
        return []
    if not isinstance(parsed, list):
        raise TypeError(f"{path.name} must contain a YAML list")
    return parsed


def _write_report(path: Path, suite: str, source_file: str, results: list[dict]) -> bool:
    report = {"suite": suite, "source_file": source_file, "policy_version": pipeline.ACTIVE_POLICY_VERSION,
        "passed": all(row["passed"] for row in results), "results": results}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report["passed"]


def main() -> None:
    os.environ["BRANE_MODE"] = "fake"
    os.environ["PRESCRUB"] = "on"
    fake = FakeBrane()
    pipeline.get_cloud = lambda: fake
    pipeline.LEDGER = Ledger(Path(bootstrap_temp.name) / "redteam.sqlite3")
    view = pipeline.process("sensitive")
    loan = load_file(ROOT / "data" / "files" / "sensitive.json")

    attacks = _load_list(ROOT / "redteam" / "attacks.yaml")
    legit = _load_list(ROOT / "redteam" / "legit.yaml")
    attack_results = evaluate(attacks, loan, view, "attacks")
    attack_results.extend(evaluate(legit, loan, view, "legitimate"))
    surface = str(fake.payloads) + str(view.model_dump())
    attack_results.append({"id": "CANARY", "family": "egress", "expected": "no canaries",
        "observed": "clear" if not any(value in surface for value in CANARIES) else "leak",
        "passed": not any(value in surface for value in CANARIES)})

    unseen_path = ROOT / "redteam" / "unseen.yaml"
    unseen = _load_list(unseen_path, allow_empty_file=True)
    unseen_results = evaluate(unseen, loan, view, "unseen")
    unseen_results.append({"id": "CANARY", "family": "egress", "expected": "no canaries",
        "observed": "clear" if not any(value in surface for value in CANARIES) else "leak",
        "passed": not any(value in surface for value in CANARIES)})

    base_passed = _write_report(ROOT / "redteam" / "results" / f"{pipeline.ACTIVE_POLICY_VERSION}.json", "attacks+legit", "attacks.yaml + legit.yaml", attack_results)
    unseen_passed = _write_report(ROOT / "redteam" / "results" / f"{pipeline.ACTIVE_POLICY_VERSION}-unseen.json", "unseen", "unseen.yaml", unseen_results)
    pipeline.EVENTS.setdefault("sensitive", []).append({"type": "redteam_result", "suite": "attacks+legit", "version": pipeline.ACTIVE_POLICY_VERSION, "passed": base_passed})
    pipeline.EVENTS.setdefault("sensitive", []).append({"type": "redteam_result", "suite": "unseen", "version": pipeline.ACTIVE_POLICY_VERSION, "passed": unseen_passed})
    if not base_passed or not unseen_passed:
        proposals = ROOT / "redteam" / "proposals"
        proposals.mkdir(exist_ok=True)
        failures = [row for row in attack_results + unseen_results if not row["passed"]]
        (proposals / f"{pipeline.ACTIVE_POLICY_VERSION}.json").write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(1)
    proposal_path = ROOT / "redteam" / "proposals" / f"{pipeline.ACTIVE_POLICY_VERSION}.json"
    proposal_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
