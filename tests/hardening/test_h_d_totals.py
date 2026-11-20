"""D. Adding or removing a sensitive (P4) or criminal (P5) line changes none of the four figures."""
from __future__ import annotations

import copy

import pytest
from hardening_helpers import FIXTURES, load_fixture

from app.calc import compute
from app.classify import classify
from app.intake import parse_file_data

SENSITIVE_LINES = [
    ("Apotheek Zonnebloem", "Medicijnen", -4200),
    ("Stichting Kerk Noord", "Collecte", -1000),
    ("Vakbond Voorbeeld", "Contributie", -1800),
    ("CJIB", "Boete kenmerk 12", -9000),
    ("Reclassering Voorbeeld", "Bijdrage", -500),
    ("Politieke Partij Voorbeeld", "Lidmaatschap", -1200),
    ("Ziekenhuis Voorbeeld", "Eigen bijdrage", -15000),
    # Sensitive lines that also contain budget words must still be excluded.
    ("Stichting Kerk Noord", "Huur zaal", -30000),
    ("CJIB", "Aflossing lening boete", -25000),
    ("Apotheek Zonnebloem", "Energie toeslag", -700),
    # Positive sensitive credit with a salary word.
    ("Vakbond Voorbeeld", "Salaris stakingsuitkering", 50000),
]
DATES = ["2026-10-14", "2026-09-14", "2026-11-14", "2026-08-01"]  # same month and other months


def _figures(raw: dict) -> dict:
    loan = parse_file_data(__import__("json").dumps(raw))
    result = compute(loan, classify(loan))
    return {k: getattr(result, k) for k in ("net_pay_cents", "housing_cents", "utilities_cents", "debt_payment_cents")}


@pytest.mark.parametrize("case_id", FIXTURES)
@pytest.mark.parametrize("line", SENSITIVE_LINES, ids=lambda line: f"{line[0]}|{line[1]}")
@pytest.mark.parametrize("date", DATES)
def test_adding_sensitive_or_cjib_line_changes_no_figure(case_id, line, date):
    raw = load_fixture(case_id)
    before = _figures(raw)
    changed = copy.deepcopy(raw)
    counterparty, description, amount = line
    changed["transactions"].append({"id": "added", "date": date, "counterparty": counterparty,
                                    "description": description, "amount_cents": amount, "page": 3})
    assert _figures(changed) == before


def test_removing_sensitive_lines_from_sensitive_fixture_changes_no_figure():
    raw = load_fixture("sensitive")
    before = _figures(raw)
    for drop in ("t1", "t2"):
        changed = copy.deepcopy(raw)
        changed["transactions"] = [tx for tx in changed["transactions"] if tx["id"] != drop]
        assert _figures(changed) == before, drop
    changed = copy.deepcopy(raw)
    changed["transactions"] = [tx for tx in changed["transactions"] if tx["id"] not in {"t1", "t2"}]
    assert _figures(changed) == before


def test_many_sensitive_lines_across_months_change_no_figure():
    raw = load_fixture("clean")
    before = _figures(raw)
    changed = copy.deepcopy(raw)
    for index, (line, date) in enumerate((line, date) for line in SENSITIVE_LINES for date in DATES):
        changed["transactions"].append({"id": f"s{index}", "date": date, "counterparty": line[0],
                                        "description": line[1], "amount_cents": line[2], "page": 3})
    assert _figures(changed) == before
