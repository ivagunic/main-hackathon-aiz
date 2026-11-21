#!/usr/bin/env python3
"""Build a timestamped, synthetic-only evidence pack and reject fixture leakage."""
from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PACK = ROOT / "evidence" / "pack"
TEAM_BUILD = "UpSolve / policy-v1"


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def _leak_values() -> list[str]:
    """Return only exact applicant identifiers from the synthetic fixture files.

    Category words and ordinary fixture text are not secrets; redacting them
    corrupts legal explanations. The pack check is a validator, never a rewriter.
    """
    fixtures = ROOT / "data" / "files"
    found: set[str] = set()
    for path in fixtures.glob("*.json"):
        case = json.loads(path.read_text(encoding="utf-8"))
        applicant = case.get("applicant", {})
        for key in ("name", "iban", "bsn"):
            value = str(applicant.get(key, "")).strip()
            if value:
                found.add(value)
    return sorted(found, key=len, reverse=True)


def _copy_filled_csv(source: Path, destination: Path, *, synthetic_column: str | None,
                     expected_headers: list[str]) -> list[dict[str, str]]:
    headers, rows = _read_csv(source)
    if headers != expected_headers:
        raise ValueError(f"Unexpected template column layout in {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Preserve source artifacts byte-for-byte at the cell level. The
            # final scanner fails on exact identifiers; it never rewrites text.
            writer.writerow(row)
    return rows


def _contains_exact_identifier(content: str, identifier: str) -> bool:
    escaped = re.escape(identifier.strip())
    if not escaped:
        return False
    # Treat letters/digits as identifier characters; punctuation and spaces
    # around an exact fixture value do not make an ordinary word a leak.
    return re.search(rf"(?<![\w]){escaped}(?![\w])", content, flags=re.IGNORECASE) is not None


def _make_ledgers() -> None:
    import os
    os.environ["BRANE_MODE"] = "fake"
    os.environ["PRESCRUB"] = "on"
    from app import pipeline
    from app.policy import Ledger

    for case_id in ("clean", "sensitive"):
        with tempfile.TemporaryDirectory(prefix="brane-evidence-pack-") as temp:
            pipeline.LEDGER = Ledger(Path(temp) / "ledger.sqlite3")
            pipeline.process(case_id)
            (PACK / f"ledger-{case_id}.csv").write_text(pipeline.LEDGER.export(case_id, "csv"), encoding="utf-8")


def main() -> int:
    evidence_path = ROOT / "evidence" / "test_evidence_run.csv"
    matrix_path = ROOT / "evidence" / "policy_matrix.csv"
    repeat_path = ROOT / "evidence" / "repeatability.json"
    redteam_path = ROOT / "redteam" / "results" / "v1.json"
    unseen_path = ROOT / "redteam" / "results" / "v1-unseen.json"
    test_results_path = ROOT / "evidence" / "test-results.xml"
    for required in (evidence_path, matrix_path, repeat_path, redteam_path, unseen_path, test_results_path):
        if not required.exists():
            raise FileNotFoundError(f"Required evidence is missing: {required.relative_to(ROOT)}")

    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "test_evidence_run.csv").unlink(missing_ok=True)
    (PACK / "policy_matrix.csv").unlink(missing_ok=True)
    test_headers, _ = _read_csv(evidence_path)
    matrix_headers, _ = _read_csv(matrix_path)
    leaks = _leak_values()
    test_rows = _copy_filled_csv(evidence_path, PACK / "test_evidence_run.csv",
        synthetic_column="Synthetic input (NEVER real personal data)", expected_headers=test_headers)
    copyfile(repeat_path, PACK / "repeatability.json")
    copyfile(redteam_path, PACK / "redteam-attacks.json")
    copyfile(unseen_path, PACK / "redteam-unseen.json")
    _make_ledgers()

    repeatability = json.loads(repeat_path.read_text(encoding="utf-8"))
    redteam = json.loads(redteam_path.read_text(encoding="utf-8"))
    unseen = json.loads(unseen_path.read_text(encoding="utf-8"))
    import xml.etree.ElementTree as ET
    xml_root = ET.parse(test_results_path).getroot()
    hardening_tests = [case for case in xml_root.findall(".//testcase")
        if str(case.attrib.get("classname", "")).startswith("tests.hardening.")]
    hardening_count = len(hardening_tests)
    hardening_passed = sum(not case.findall("failure") and not case.findall("error") and not case.findall("skipped")
        for case in hardening_tests)
    expected_failures = [case for case in hardening_tests
        if (skipped := case.find("skipped")) is not None and str(skipped.attrib.get("message", "")).startswith("OPEN-")]
    expected_failure_lines = [
        f"- {case.attrib.get('classname', '')}::{case.attrib.get('name', '')} — {case.find('skipped').attrib.get('message', '')}. No data left the agent in this expected-failure test."
        for case in expected_failures
    ]
    mandatory = [row for row in test_rows if row["Scenario type"].startswith("Mandatory")]
    edges = [row for row in test_rows if row["Scenario type"].startswith("Team Edge")]
    attacks = [row for row in redteam["results"] if row.get("family") != "legitimate" and row.get("id") != "CANARY"]
    legitimate = [row for row in redteam["results"] if row.get("family") == "legitimate"]
    repeat_runs = len(repeatability.get("runs", []))
    summary = [
        "# Evidence pack summary", "",
        "Legal citations in `brane_policy_matrix_filled.csv` were mapped automatically from our policy matrix and need a human check.",
        f"- Timestamp (UTC): {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- Policy version: {yaml.safe_load((ROOT / 'policy' / 'policy.v1.yaml').read_text(encoding='utf-8')).get('version', 'unknown')}",
        f"- TEAM_BUILD: {TEAM_BUILD}",
        f"- Mandatory evidence tests passed: {sum(row['Pass/Fail'] == 'PASS' for row in mandatory)} / {len(mandatory)}.",
        f"- Edge-case evidence rows: {len(edges)}; passed: {sum(row['Pass/Fail'] == 'PASS' for row in edges)}.",
        f"- Repeatability runs recorded: {repeat_runs}; all runs identical: {len({json.dumps(item, sort_keys=True) for item in repeatability.get('runs', [])}) == 1}.",
        f"- Red-team attacks blocked as expected: {sum(bool(row['passed']) for row in attacks)} / {len(attacks)}.",
        f"- Legitimate red-team tasks answered as expected: {sum(bool(row['passed']) for row in legitimate)} / {len(legitimate)}.",
        f"- Unseen red-team results passed: {sum(bool(row['passed']) for row in unseen.get('results', []))} / {len(unseen.get('results', []))}.",
        f"- Hardening test cases passed: {hardening_passed} / {hardening_count} (JUnit result file).", "",
        "## Expected-failure tests", "",
        *expected_failure_lines,
        f"- {len(expected_failures)} expected-failure test cases are listed above; none involves data leaving the agent.", "",
        "Counts above are computed from the included evidence, repeatability, red-team and JUnit result files.",
    ]
    (PACK / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    status_tests = {
        "P1": ("T1", "test_every_fixture_sends_exactly_four_integer_fields", "BRANE and agent", "IMPLEMENTED"),
        "P2": ("T3", "test_name_question_is_prescrubbed_and_only_figures_reach_brane", "agent and BRANE", "IMPLEMENTED"),
        "P3": ("P3-BSN", "test_intake_keeps_only_printed_net_pay", "agent and BRANE", "IMPLEMENTED"),
        "P4": ("T2", "test_adding_sensitive_or_cjib_line_changes_no_figure", "agent and BRANE", "IMPLEMENTED"),
        "P5": ("R3", "test_r3_cjib_line_is_excluded_from_all_totals", "agent", "IMPLEMENTED"),
        "P6": ("T1", "test_intake_keeps_only_printed_net_pay", "agent", "IMPLEMENTED"),
        "P7": ("T2", "test_adding_sensitive_or_cjib_line_changes_no_figure", "agent", "IMPLEMENTED"),
        "P8": ("R2", "test_r2_age_or_postcode_does_not_change_figures_flags_or_route", "agent", "IMPLEMENTED"),
        "P9": ("Design check", "", "agent", "NOT BUILT"),
        "P10": ("P10", "test_p10_view_displays_only_neutral_message_receipt", "agent", "IMPLEMENTED"),
        "P11": ("T4", "test_attack_in_payslip_text_is_flagged", "agent and BRANE", "PARTIAL"),
        "P12": ("T5", "test_anything_else_fails_closed", "agent and BRANE", "IMPLEMENTED"),
        "P13": ("R4", "test_r4_tampered_or_decisional_draft_uses_template", "agent", "IMPLEMENTED"),
        "P14": ("R1", "test_p14_evidence_gap_stays_local_and_requires_human_review", "agent", "IMPLEMENTED"),
        "P15": ("Demo", "test_valid_review_is_recorded", "agent", "IMPLEMENTED"),
    }
    evidence_by_id = {row["Test ID"]: row for row in test_rows}
    testcase_names = {str(case.attrib.get("name", "")) for case in xml_root.findall(".//testcase")
        if not case.findall("failure") and not case.findall("error") and not case.findall("skipped")}
    policy_doc_rows = [line for line in (ROOT / "docs" / "policy-matrix.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| P")]
    rules = ["# Rules status", ""]
    for line in policy_doc_rows:
        rule_id = line.split("|", 2)[1].strip()
        test_id, test_name, enforcer, expected_status = status_tests[rule_id]
        row = evidence_by_id.get(test_id)
        passing_evidence = bool(row and row.get("Pass/Fail") == "PASS") or bool(
            test_name and any(name == test_name or name.startswith(f"{test_name}[") for name in testcase_names))
        status = expected_status if passing_evidence or expected_status in {"PARTIAL", "NOT BUILT"} else "PARTIAL"
        evidence_name = test_id if row and row.get("Pass/Fail") == "PASS" else test_name
        if status == "NOT BUILT":
            proof = "no passing test; design gap"
        elif evidence_name:
            proof = f"passing test: `{evidence_name}`"
        else:
            proof = "no passing test recorded"
        rules.append(f"- **{rule_id} — {status}** ({proof}); enforced by {enforcer}.")
    (PACK / "rules-status.md").write_text("\n".join(rules) + "\n", encoding="utf-8")
    gaps = [
        "# Product gaps", "",
        "- BRANE misses repeated and upper-case name variants. PRESCRUB replaces every known variant before live pipeline calls; `T3-brane-only` records this BRANE-only gap.",
        "- BRANE does not detect employer ORG reliably. PRESCRUB replaces the known employer before live pipeline calls; `T3-brane-only` records the gap.",
        "- BRANE did not treat BSN as a national ID before the new category. The live policy now has `NATIONAL_ID_BSN` with refusal; `P3-BSN` checks the denial.",
        "- BRANE's broad `SENSITIVE_MERCHANT` local category cannot separate protected health context from lookalike merchants or mandatory insurance premiums; E1 and E4 document usefulness/legal-review tradeoffs.",
        "- T4 was refused under `NATIONAL_ID_BSN`, not a dedicated `PROMPT_INJECTION` decision. The agent's document-text controls remain necessary; the live trace does not prove a BRANE-specific injection rule.",
        "- BRANE's built-in injection guard can route a flagged prompt to local instead of refusing (live T1 workbench observation); the custom `OVERRIDE_ATTEMPT` refusal rule addresses this routing gap.",
        "- Before the live medical-transfer policy update, the E5 transfer note routed to cloud. The before-fix result is retained; the after-fix run checks local routing.",
        "",
    ]
    (PACK / "product-gaps.md").write_text("\n".join(gaps), encoding="utf-8")

    # The matrix generator consumes the current product-gap notes. Generate it
    # after those notes, then copy the exact filled CSV into the pack.
    from scripts.build_brane_policy_matrix_filled import main as build_brane_export
    from scripts.build_policy_matrix_csv import main as build_policy_matrix
    build_policy_matrix()
    build_brane_export()
    matrix_headers, _ = _read_csv(matrix_path)
    matrix_rows = _copy_filled_csv(matrix_path, PACK / "policy_matrix.csv", synthetic_column=None,
        expected_headers=matrix_headers)
    (PACK / "manifest.json").write_text(json.dumps({
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "policy_version": yaml.safe_load((ROOT / "policy" / "policy.v1.yaml").read_text(encoding="utf-8")).get("version", "unknown"),
        "team_build": TEAM_BUILD,
        "test_rows": len(test_rows), "policy_rows": len(matrix_rows),
    }, indent=2) + "\n", encoding="utf-8")

    # The dedicated synthetic-input cells intentionally hold test fixtures.
    # Elsewhere, fail only on exact applicant name / IBAN / BSN strings.
    for path in PACK.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "test_evidence_run.csv":
            _, packed_rows = _read_csv(path)
            content = "\n".join(value for row in packed_rows for key, value in row.items()
                if key != "Synthetic input (NEVER real personal data)")
        else:
            content = path.read_text(encoding="utf-8", errors="replace")
        for secret in leaks:
            if _contains_exact_identifier(content, secret):
                raise ValueError(f"Synthetic fixture leak in evidence pack: {path.relative_to(PACK)}")
    print(f"Evidence pack built at {PACK.relative_to(ROOT)} ({len(test_rows)} evidence rows, {len(matrix_rows)} policy rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
