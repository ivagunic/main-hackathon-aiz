#!/usr/bin/env python3
"""Render the P1-P15 policy matrix into the starter-kit CSV column layout."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

DOC = ROOT / "docs" / "policy-matrix.md"
POLICY_YAML = ROOT / "policy" / "policy.v1.yaml"
BRANE_POLICY = ROOT / "policy" / "brane_policy.json"
EVIDENCE = ROOT / "evidence" / "test_evidence_run.csv"
OUTPUT = ROOT / "evidence" / "policy_matrix.csv"
HEADERS = [
    "Rule ID", "Use-case data category", "Why needed (or not needed) for task",
    "Legal or governance source (Article / Guideline)",
    "Target decision: ALLOW / PROTECT / LOCAL ONLY / BLOCK / HUMAN APPROVAL",
    "How enforced in BRANE AIF + Agent code today",
    "Product gap note (what finer rule you wished BRANE had per-category)",
    "Evidence captured (X-Brane-* headers / UI step)", "Linked Test IDs",
]
TARGET = {
    "P1": "ALLOW", "P2": "PROTECT", "P3": "BLOCK", "P4": "BLOCK", "P5": "BLOCK",
    "P6": "BLOCK", "P7": "LOCAL ONLY", "P8": "BLOCK", "P9": "BLOCK", "P10": "BLOCK",
    "P11": "BLOCK", "P12": "BLOCK", "P13": "BLOCK", "P14": "HUMAN APPROVAL", "P15": "HUMAN APPROVAL",
}
LINKS = {
    "P1": "T1", "P2": "T3", "P3": "T3", "P4": "T2", "P5": "R3",
    "P6": "T1", "P7": "T2", "P8": "R2", "P9": "Design check", "P10": "Out of scope",
    "P11": "T4", "P12": "T5", "P13": "R4", "P14": "R1", "P15": "Demo",
}


def _markdown_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| P"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] in TARGET:
            rows[cells[0]] = cells
    if set(rows) != set(TARGET):
        raise ValueError("docs/policy-matrix.md must contain exactly one row for each P1-P15")
    return rows


def _brane_actions() -> tuple[dict[str, str], bool]:
    if not BRANE_POLICY.exists():
        return {}, False
    policy = yaml.safe_load(BRANE_POLICY.read_text(encoding="utf-8")) or {}
    if not isinstance(policy, dict):
        return {}, True
    categories = policy.get("categories", {})
    semantic = policy.get("semanticCategories", [])
    actions = {str(code): str(action) for code, action in categories.items()} if isinstance(categories, dict) else {}
    if isinstance(semantic, list):
        for item in semantic:
            if isinstance(item, dict) and item.get("code"):
                actions[str(item["code"])] = str(item.get("action", "unconfigured"))
    return actions, True


def _evidence_rows() -> dict[str, dict[str, str]]:
    if not EVIDENCE.exists():
        return {}
    with EVIDENCE.open(newline="", encoding="utf-8-sig") as stream:
        return {row.get("Test ID", ""): row for row in csv.DictReader(stream)}


def main() -> int:
    policy = yaml.safe_load(POLICY_YAML.read_text(encoding="utf-8"))
    rules = {item["id"]: item for item in policy.get("rules", [])}
    doc_rows = _markdown_rows()
    actions, was_pulled = _brane_actions()
    evidence = _evidence_rows()
    result = []
    for rule_id in TARGET:
        cells = doc_rows[rule_id]
        rule = rules[rule_id]
        refs = [part.strip() for part in str(rule.get("brane_policy_ref", "agent-only")).split(",")]
        if refs == ["agent-only"]:
            enforcement = f"Agent only: lane={rule.get('lane')}; action={rule.get('action')}; BRANE equivalent not configured."
        else:
            if not was_pulled:
                brane_detail = "BRANE policy has not been pulled; live action unverified."
            else:
                brane_detail = "; ".join(f"{ref}={actions.get(ref, 'not configured')}" for ref in refs)
            enforcement = f"Agent lane={rule.get('lane')}, action={rule.get('action')}; BRANE {brane_detail}"
        linked = LINKS[rule_id]
        captured = []
        for test_id in linked.split(" / "):
            ev = evidence.get(test_id, {})
            headers = ev.get("X-Brane-Pii-Types / Local-Cause", "")
            route = ev.get("X-Brane-Routed-To", "")
            if route or headers:
                captured.append(f"{test_id}: route={route}; {headers}")
        result.append({
            "Rule ID": rule_id,
            "Use-case data category": cells[1],
            "Why needed (or not needed) for task": cells[2],
            "Legal or governance source (Article / Guideline)": cells[4],
            "Target decision: ALLOW / PROTECT / LOCAL ONLY / BLOCK / HUMAN APPROVAL": TARGET[rule_id],
            "How enforced in BRANE AIF + Agent code today": enforcement,
            "Product gap note (what finer rule you wished BRANE had per-category)": "",
            "Evidence captured (X-Brane-* headers / UI step)": " | ".join(captured),
            "Linked Test IDs": linked,
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(result)
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(result)} P1-P15 rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
