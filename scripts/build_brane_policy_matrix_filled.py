#!/usr/bin/env python3
"""Fill the workbench policy export without altering its row or column layout."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(r"C:\Users\Iva\Downloads\MAIN_Policy_Matrix_Export.csv")
OUTPUT = ROOT / "evidence" / "pack" / "brane_policy_matrix_filled.csv"
POLICY = ROOT / "policy" / "policy.v1.yaml"
GAPS = ROOT / "evidence" / "pack" / "product-gaps.md"
EVIDENCE = ROOT / "evidence" / "test_evidence_run.csv"

P2_CODES = {"PERSON", "EMAIL", "PHONE", "ADDRESS", "IP_ADDRESS", "ORG", "TRADE_REGISTER", "VAT_ID", "IBAN", "ACCOUNT_NUMBER"}
P4_CODES = {"HEALTH_DATA", "ETHNIC_ORIGIN", "POLITICAL_OPINION", "RELIGIOUS_BELIEF", "SEXUAL_ORIENTATION", "TRADE_UNION", "SENSITIVE_CONTEXT"}
SPECIAL_CREDENTIAL_CODES = {"PASSWORD", "SECRET_KEY"}
NONNECESSARY_CODES = {"PASSPORT", "TAX_NUMBER", "INSURANCE_NUMBER", "CREDIT_CARD"}
SEMANTIC_RULES = {
    "AUTONOMOUS_CREDIT_DECISION": "P15", "SENSITIVE_MERCHANT": "P4",
    "CRIMINAL_PAYMENT": "P5", "PROXY_ATTRIBUTE": "P8",
    "NATIONAL_ID_BSN": "P3", "OVERRIDE_ATTEMPT": "P11",
}

COL_LEGAL = "Legal or Business Source (Exact Article / Guidance)"
COL_CONFIGURED = "Configured in BRANE AIF Today (Yes / Partial / Not Yet)"
COL_AGENT = "Handled in Agent Code or Human Process"
COL_GAP = "Product Gap / Feature Request (if Partial or Not Yet)"
COL_TEST = "Verification Test ID"


def _rule_citations() -> dict[str, str]:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    return {str(rule["id"]): str(rule["citation"]) for rule in policy.get("rules", [])}


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def _category(row: dict[str, str]) -> tuple[str, str | None]:
    scenario = row.get("Data / Decision Scenario", "")
    semantic = re.match(r"Semantic Category ([A-Z0-9_]+):", scenario)
    if semantic:
        code = semantic.group(1)
        return code, SEMANTIC_RULES.get(code)
    match = re.match(r"([A-Z][A-Z0-9_]*)\s*\(", scenario)
    return (match.group(1), None) if match else ("", None)


def _citation(row: dict[str, str], code: str, rule_id: str | None, citations: dict[str, str]) -> str:
    source = row.get(COL_LEGAL, "")
    if "[ADD SPECIFIC ARTICLE / DPA SOURCE]" in source:
        if code in P2_CODES:
            replacement = f"{citations['P2']} [P2]"
        elif code == "SSN":
            replacement = f"{citations['P3']} [P3]"
        elif code == "DATE_OF_BIRTH":
            replacement = f"{citations['P8']} [P8]"
        elif code in P4_CODES:
            replacement = f"{citations['P4']} [P4]"
        elif code in SPECIAL_CREDENTIAL_CODES:
            replacement = "GDPR Art. 5(1)(c): not necessary for the task; GDPR Art. 32(1)"
        elif code in NONNECESSARY_CODES:
            replacement = "GDPR Art. 5(1)(c): not necessary for the task"
        else:
            return source
        return source.replace("[ADD SPECIFIC ARTICLE / DPA SOURCE]", replacement)
    if rule_id:
        suffix = f"[{rule_id}]"
        return source if source.strip().endswith(suffix) else f"{source.strip()} {suffix}".strip()
    return source


def _gap_lines() -> str:
    return GAPS.read_text(encoding="utf-8") if GAPS.exists() else ""


def _configured(code: str) -> str:
    if code == "PERSON":
        return "Partial. BRANE alone missed repeated, abbreviated and upper-case name variants (row T3-brane-only). Covered by the agent's pre-scrub."
    if code == "ORG":
        return "Partial. Employer name not detected in our test (row T3-brane-only). Covered by the agent's pre-scrub."
    if code == "SSN":
        return "Partial. A Dutch BSN was classified as ACCOUNT_NUMBER (row P3-BSN). Covered by custom rule NATIONAL_ID_BSN."
    if code in {"HEALTH_DATA", "RELIGIOUS_BELIEF", "TRADE_UNION"}:
        return "Partial. Indirect payee names and a medical note in a transfer were not detected (E5 before fix). Covered by custom rule SENSITIVE_MERCHANT."
    if code == "OVERRIDE_ATTEMPT":
        return "Partial. BRANE's built-in injection guard routes to local rather than refusing; the custom OVERRIDE_ATTEMPT refusal rule was added."
    return "None observed in our tests"


def _product_gap(code: str, gaps: str) -> str:
    prefixes = {
        "PERSON": ("- BRANE misses repeated",), "ORG": ("- BRANE does not detect employer",),
        "SSN": ("- BRANE did not treat BSN",),
        "HEALTH_DATA": ("- BRANE's broad `SENSITIVE_MERCHANT`",),
        "RELIGIOUS_BELIEF": ("- BRANE's broad `SENSITIVE_MERCHANT`",),
        "TRADE_UNION": ("- BRANE's broad `SENSITIVE_MERCHANT`",),
        "OVERRIDE_ATTEMPT": ("- BRANE's built-in injection guard",),
    }
    matches = [line.removeprefix("- ").strip() for line in gaps.splitlines()
        if line.startswith("- ") and any(line.startswith(prefix) for prefix in prefixes.get(code, ()))]
    return " ".join(matches) if matches else "None observed in our tests"


def _agent_action(code: str) -> str:
    if code in {"PERSON", "ADDRESS", "ORG", "IBAN"}:
        return "Agent pre-scrubs known applicant identifiers; drafting sends only the four integer totals."
    if code in P2_CODES:
        return "Source documents and transaction text are not sent for drafting; only the four integer totals leave."
    if code in {"SSN", "NATIONAL_ID_BSN"}:
        return "Intake clears BSN; a BRANE 422 is shown as a refusal and left to the officer."
    if code in P4_CODES or code == "SENSITIVE_MERCHANT":
        return "Sensitive transaction lines stay local and are excluded from officer report and totals; only four totals leave."
    if code in {"CRIMINAL_PAYMENT", "CRIMINAL_PAYMENT_CONTEXT"}:
        return "CJIB/reclassering lines are excluded from all totals and the officer report."
    if code in {"DATE_OF_BIRTH", "PROXY_ATTRIBUTE"}:
        return "Date of birth and proxy attributes are not used as assessment features; the officer retains the decision."
    if code == "AUTONOMOUS_CREDIT_DECISION":
        return "The agent refuses automated credit decisions; the authorised officer records the action and reason."
    if code == "OVERRIDE_ATTEMPT":
        return "Document text is not sent; a BRANE 422 is shown as a refusal and left to the officer."
    if code in NONNECESSARY_CODES | SPECIAL_CREDENTIAL_CODES:
        return "A BRANE 422 is shown as a refusal and left to the officer."
    return "Source details remain local; only the four integer totals can leave for drafting."


def _test_ids() -> set[str]:
    if not EVIDENCE.exists():
        return set()
    _, rows = _rows(EVIDENCE)
    return {row.get("Test ID", "") for row in rows}


def _verification_id(code: str, row_ids: set[str]) -> str:
    expected = {
        "PERSON": ("T3", "T3-brane-only"), "ADDRESS": ("T3", "T3-brane-only"),
        "ORG": ("T3", "T3-brane-only"), "IBAN": ("T3", "T3-brane-only", "T4b"),
        "SSN": ("P3-BSN", "T4"), "HEALTH_DATA": ("T2", "E2", "E5 (before fix)", "E5 (after fix)"),
        "RELIGIOUS_BELIEF": ("T2", "E3"), "TRADE_UNION": ("T2", "E3"),
        "SENSITIVE_CONTEXT": ("T2b",),
        "SENSITIVE_MERCHANT": ("T2", "T2b", "E2", "E3", "E4", "E5 (before fix)", "E5 (after fix)"),
        "NATIONAL_ID_BSN": ("P3-BSN",), "OVERRIDE_ATTEMPT": ("T4", "T4b"),
    }
    present = [test_id for test_id in expected.get(code, ()) if test_id in row_ids]
    return "; ".join(present) if present else "not separately tested"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    if not args.source.exists():
        raise FileNotFoundError(f"Workbench export not found: {args.source}")
    headers, rows = _rows(args.source)
    required = {COL_LEGAL, COL_CONFIGURED, COL_AGENT, COL_GAP, COL_TEST, "Data / Decision Scenario"}
    if not required.issubset(headers):
        raise ValueError("Workbench export columns do not match the expected matrix")
    citations = _rule_citations()
    gaps = _gap_lines()
    row_ids = _test_ids()
    output_rows = []
    for original in rows:
        row = original.copy()
        code, rule_id = _category(row)
        row[COL_LEGAL] = _citation(row, code, rule_id, citations)
        row[COL_CONFIGURED] = _configured(code)
        row[COL_AGENT] = _agent_action(code)
        row[COL_GAP] = _product_gap(code, gaps)
        row[COL_TEST] = _verification_id(code, row_ids)
        output_rows.append(row)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(output_rows)} rows; source cells preserved outside requested columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
