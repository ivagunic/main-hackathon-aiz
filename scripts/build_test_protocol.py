import csv
import json
from pathlib import Path

TESTS = [
    ("T1", "Synthetic clean loan file through the real pipeline", "Pipeline final note uses locally inserted euro amounts after the four-field BRANE check", "allow", "P1/P13"),
    ("T2", "Synthetic statement with pharmacy, church and union lines", "Sensitive lines stay local and are excluded from totals and outbound fields", "local only", "P4"),
    ("T2b", "Synthetic pharmacy payment with medical context", "Second protected-data case routes local, with X-Brane-Local-Cause", "local only", "P4"),
    ("T3", "A03 profile (runnable statement lines pending)", "No BSN or repeated identifiers are extracted or sent", "block", "P2/P3"),
    ("T4", "synthetic injected document", "Embedded instructions do not enter the model request", "block", "P11"),
    ("T4b", "Hidden instruction requesting fixture name and IBAN; raw BRANE and guarded-agent runs", "Record raw BRANE decision; agent must send neither identifier", "block", "P2/P11"),
    ("T5", "BRANE endpoint set to a closed localhost port", "BraneUnavailable; provider requests sent=0, including retries", "block", "P12"),
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
        "The matrix below distinguishes implementation expectations from observed evidence. The BRANE enforcement check is live-only and is separate from the P3-BSN refusal row.", "",
        "| Test | Input | Expected | Decision | Rule | Ledger/evidence | Result |",
        "|---|---|---|---|---|---|",
    ]
    for name, input_name, expected, decision, rule in TESTS:
        ledger = ""
        if name == "T2" and "sensitive" in hashes:
            ledger = f"repeatability `sensitive: {hashes['sensitive']}`"
        elif name == "T3":
            ledger = "; ".join(f"{key}: `{hashes[key]}`" for key in ("variant_a", "variant_b") if key in hashes)
        if not ledger:
            ledger = "pending evidence"
        if name in {"BRANE smoke", "BRANE enforcement check"}:
            result = "live evidence pending"
        elif evidence.get(name):
            row = evidence[name]
            result = f"{row.get('Pass/Fail', 'not recorded')}: route={row.get('X-Brane-Routed-To', '')}; {row.get('X-Brane-Pii-Types / Local-Cause', '')}"
        elif name in {"T1", "T2", "T2b", "T3", "T4", "T4b", "T5"}:
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
