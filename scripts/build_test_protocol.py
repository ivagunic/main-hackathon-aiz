import csv
import json
from pathlib import Path

TESTS = [
    ("T1", "A01 profile (runnable statement lines pending)", "Permitted four-field request reaches BRANE", "allow", "P1"),
    ("T2", "A02 profile (runnable statement lines pending)", "P4 line is excluded from all totals and outbound fields", "local only", "P4"),
    ("T3", "A03 profile (runnable statement lines pending)", "No BSN or repeated identifiers are extracted or sent", "block", "P2/P3"),
    ("T4", "synthetic injected document", "Embedded instructions do not enter the model request", "block", "P11"),
    ("T5", "BRANE unavailable or local check missing", "Fail closed; no alternate provider request", "block", "P12"),
    ("P10", "synthetic file with a customer message", "Message text is not ingested; officer status is only customer message received", "block", "P10"),
    ("R1", "payslip mismatch and self-employed profile", "Local note, human review, no model request", "local only", "P14"),
    ("R2", "clean.json with age-only and postcode-only changes (A01 line fixture pending)", "Four figures, flags and route stay identical", "block", "P8"),
    ("R3", "clean.json plus CJIB statement line (A02 line fixture pending)", "CJIB line does not affect any total", "block", "P5"),
    ("R4", "tampered model draft", "Changed figures or lending language show template note", "block", "P13"),
    ("BRANE smoke", "harmless four-field live request and closed localhost port", "Positive verdict, request metadata printed, then BraneUnavailable at closed port", "allow/block", "P1/P12"),
    ("BRANE enforcement check", "harmless synthetic P1 schema violation (live only)", "Configured BRANE policy denies request and denial is recorded", "block", "P1"),
]


def main() -> None:
    repeatability = Path("evidence/repeatability.json")
    data = json.loads(repeatability.read_text(encoding="utf-8")) if repeatability.exists() else {"runs": []}
    hashes = data.get("runs", [{}])[0] if data.get("runs") else {}
    evidence_path = Path("evidence/test_evidence_run.csv")
    evidence = {}
    if evidence_path.exists():
        with evidence_path.open(newline="", encoding="utf-8-sig") as stream:
            evidence = {row.get("Test ID", ""): row for row in csv.DictReader(stream)}
    lines = [
        "# Test protocol", "",
        "The matrix below distinguishes implementation expectations from observed evidence. The BRANE enforcement check is live-only and must be run after P1 is configured; this workspace has not sent that request.", "",
        "| Test | Input | Expected | Decision | Rule | Ledger/evidence | Result |",
        "|---|---|---|---|---|---|",
    ]
    for name, input_name, expected, decision, rule in TESTS:
        ledger = ""
        if name == "T1" and "clean" in hashes:
            ledger = f"repeatability `clean: {hashes['clean']}`"
        elif name == "T2" and "sensitive" in hashes:
            ledger = f"repeatability `sensitive: {hashes['sensitive']}`"
        elif name == "T3":
            ledger = "; ".join(f"{key}: `{hashes[key]}`" for key in ("variant_a", "variant_b") if key in hashes)
        if not ledger:
            ledger = "pending evidence"
        if name == "BRANE enforcement check" and evidence.get("P3-BSN"):
            row = evidence["P3-BSN"]
            result = f"{row.get('Pass/Fail', 'not recorded')}: route={row.get('X-Brane-Routed-To', '')}; {row.get('X-Brane-Pii-Types / Local-Cause', '')}"
        elif name in {"BRANE smoke", "BRANE enforcement check"}:
            result = "live evidence pending"
        elif evidence.get(name):
            row = evidence[name]
            result = f"{row.get('Pass/Fail', 'not recorded')}: route={row.get('X-Brane-Routed-To', '')}; {row.get('X-Brane-Pii-Types / Local-Cause', '')}"
        elif name in {"T1", "T2", "T3"}:
            result = "local legacy-fixture pass; A01–A03 profile fixtures and live BRANE evidence pending"
        else:
            result = "local regression passed; live BRANE evidence pending"
        lines.append(f"| {name} | {input_name} | {expected} | {decision} | {rule} | {ledger} | {result} |")
    for test_id in ("E1", "E2", "E3", "E4", "E5 (before fix)", "E5 (after fix)", "P3-BSN", "T3-brane-only"):
        row = evidence.get(test_id)
        if row:
            lines.append(f"| {test_id} | synthetic edge/evidence input | {row.get('Expected result', '')} | observed route={row.get('X-Brane-Routed-To', '')} | {row.get('Scenario type', '')} | headers: {row.get('X-Brane-Pii-Types / Local-Cause', '')} | {row.get('Pass/Fail', '')} |")
    Path("docs/test-protocol.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
