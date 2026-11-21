"""Shared synthetic-data generators and surface collectors for the hardening suite.

Everything here is invented. IBANs use the deliberately invalid NL00 check digits.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.gateway import CloudResult, FakeBrane

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ("clean", "sensitive", "variant_a", "variant_b")
FIELDS = ("net_pay_cents", "housing_cents", "utilities_cents", "debt_payment_cents")

# Syllables chosen so generated words never contain a dictionary stem or a budget term.
_SYL = ("ka", "lo", "mi", "ze", "ru", "bra", "vo", "quin", "del", "sar", "nok", "fey", "lin", "dro", "pel", "wim", "zan", "tor", "xu", "jo")


def load_fixture(case_id: str) -> dict:
    return json.loads((ROOT / "data" / "files" / f"{case_id}.json").read_text(encoding="utf-8"))


def write_case(tmp_path: Path, raw: dict, name: str | None = None) -> Path:
    path = tmp_path / (name or f"{raw['case_id']}-{random.random():.12f}.json")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


class RecordingBrane(FakeBrane):
    """FakeBrane that can return a scripted draft text and verdict."""

    def __init__(self, text: str | None = None, verdict: str = "allow") -> None:
        super().__init__()
        self.text = text
        self.verdict = verdict

    def complete(self, system: str, user: str, *, case_id: str, purpose: str) -> CloudResult:
        result = super().complete(system, user, case_id=case_id, purpose=purpose)
        if self.text is not None:
            result.text = self.text
        if self.verdict != "allow":
            record = json.loads(result.verdict)
            record["brane_verdict"] = self.verdict
            result.verdict = json.dumps(record, sort_keys=True)
        return result

    def user_payloads(self) -> list[dict]:
        return [json.loads(p["user"]) for p in self.payloads]


def _word(rng: random.Random, low: int = 2, high: int = 3) -> str:
    return "".join(rng.choice(_SYL) for _ in range(rng.randint(low, high))).capitalize()


@dataclass
class Canary:
    given: list[str]
    surname: str
    iban: str
    bsn: str
    employer: str
    address: str
    merchants: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return " ".join([*self.given, self.surname])

    @property
    def initials_form(self) -> str:
        return " ".join(f"{g[0]}." for g in self.given) + " " + self.surname

    @property
    def spaced_iban(self) -> str:
        return " ".join(self.iban[i:i + 4] for i in range(0, len(self.iban), 4))

    @property
    def dotted_bsn(self) -> str:
        return f"{self.bsn[:3]}.{self.bsn[3:6]}.{self.bsn[6:]}"

    def patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        """Case-, spacing- and separator-insensitive search patterns for every canary."""
        def loose(text: str) -> re.Pattern[str]:
            return re.compile(r"\s*".join(map(re.escape, text.replace(" ", ""))), re.IGNORECASE)

        found = [
            ("name", loose(self.name)),
            ("initials", re.compile(r"\b" + r"\.?\s*".join(g[0] for g in self.given) + r"\.?\s+" + re.escape(self.surname) + r"\b", re.IGNORECASE)),
            ("iban", loose(self.iban)),
            ("bsn", re.compile(r"(?<!\d)" + r"[.\s-]*".join(self.bsn) + r"(?!\d)")),
            ("employer", loose(self.employer)),
            ("address", loose(self.address)),
        ]
        found += [(f"merchant:{m}", loose(m)) for m in self.merchants]
        return found


SENSITIVE_TEMPLATES = (
    "Apotheek {w}", "Stichting Kerk {w}", "Vakbond {w}", "Politieke Partij {w}", "GGZ {w}", "Ziekenhuis {w}",
    "CJIB", "Reclassering {w}", "{w} Dating App", "Moskee {w}", "Parochie {w}", "FNV", "Tandarts {w}",
    "Synagoge {w}", "Fysio {w}", "Huisarts {w}",
)


def make_canary_file(rng: random.Random, index: int) -> tuple[dict, Canary]:
    given = [_word(rng)] if rng.random() < 0.6 else [_word(rng), _word(rng)]
    surname = _word(rng, 3, 4)
    letters = "".join(rng.choice("BCDFGHJKMPQRSTVWXZ") for _ in range(4))
    iban = f"NL00{letters}{rng.randrange(10**9, 10**10)}"
    bsn = str(rng.randrange(10**8, 10**9))
    employer = f"{_word(rng)} {rng.choice(('Logistiek', 'Techniek', 'Atelier', 'Drukwerk'))}"
    address = f"{_word(rng)}{rng.choice(('straat', 'laan', 'weg'))} {rng.randint(1, 199)}"
    merchants = [t.format(w=_word(rng)) for t in rng.sample(SENSITIVE_TEMPLATES, 3)]
    c = Canary(given, surname, iban, bsn, employer, address, merchants)
    net = rng.randrange(150000, 400000, 100)
    every_page = f"{c.name} {c.address} {c.spaced_iban} BSN {c.dotted_bsn} {c.employer}"
    raw = {
        "case_id": f"canary{index:03d}",
        "applicant": {"name": c.name, "address": c.address, "postcode": "1000 AA", "iban": c.iban, "bsn": c.bsn,
                      "dob": "1990-01-01", "nationality": "NL", "gender": "X"},
        "application": {"amount_cents": 300000, "term_months": 24, "purpose": "synthetic", "declared_debts": 0},
        "payslips": [{"id": "p1", "employer": c.employer, "period": "2026-10", "net_cents": net,
                      "raw_text": f"{every_page} Net pay {net}", "page": 1}],
        "transactions": [
            {"id": "t1", "date": "2026-10-01", "counterparty": f"Woonstichting {_word(rng)}",
             "description": f"Huur {c.address} {c.name} BSN {c.bsn}", "amount_cents": -rng.randrange(50000, 120000, 100), "page": 1},
            {"id": "t2", "date": "2026-10-03", "counterparty": f"Energie {_word(rng)}",
             "description": f"Termijn {c.initials_form} kenmerk {c.dotted_bsn}", "amount_cents": -rng.randrange(5000, 20000, 100), "page": 1},
            {"id": "t3", "date": "2026-10-25", "counterparty": c.employer,
             "description": f"Salaris {c.name.upper()} {c.spaced_iban}", "amount_cents": net, "page": 2},
            {"id": "t4", "date": "2026-10-12", "counterparty": c.employer,
             "description": f"Onkostenvergoeding {c.name.lower()}", "amount_cents": 2500, "page": 2},
            {"id": "t5", "date": "2026-10-06", "counterparty": merchants[0], "description": f"Betaling {c.name.lower()}", "amount_cents": -3100, "page": 1},
            {"id": "t6", "date": "2026-10-20", "counterparty": merchants[0], "description": "Maandelijks", "amount_cents": -3100, "page": 2},
            {"id": "t7", "date": "2026-10-09", "counterparty": merchants[1], "description": f"Bijdrage {c.initials_form}", "amount_cents": -1500, "page": 1},
            {"id": "t8", "date": "2026-10-15", "counterparty": "Kredietbank Lening", "description": f"Aflossing {c.surname} {c.given[0][0]}.",
             "amount_cents": -9000, "page": 2},
            {"id": "t9", "date": "2026-10-17", "counterparty": "Overboeking", "description": f"{merchants[2]} {c.name}", "amount_cents": -2000, "page": 2},
        ],
        "messages": [],
        "raw_pages": [every_page] * 3,
    }
    return raw, c


def find_canaries(text: str, canary: Canary) -> list[str]:
    return [label for label, pattern in canary.patterns() if pattern.search(text)]
