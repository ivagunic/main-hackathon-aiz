from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from app.models import LoanFile


class LeakDetected(ValueError):
    """Raised when an outbound string contains an identifier."""


@dataclass
class PseudoMap:
    replacements: list[tuple[str, str]] = field(default_factory=list)


def build_map(file: LoanFile) -> PseudoMap:
    mapping = PseudoMap()
    a = file.applicant
    for value, token in ((a.name, "<PERSON_1>"), (a.iban, "<IBAN_1>"), (a.address, "<ADDRESS_1>")):
        if value:
            mapping.replacements.append((value, token))
    for number, employer in enumerate(sorted({p.employer for p in file.payslips if p.employer}), 1):
        mapping.replacements.append((employer, f"<EMPLOYER_{number}>"))
    return mapping


def _pattern_for(value: str, token: str) -> re.Pattern[str]:
    if token.startswith("<IBAN"):
        return re.compile(r"(?<![A-Z0-9])" + r"\s*".join(map(re.escape, list(re.sub(r"\s+", "", value)))) + r"(?![A-Z0-9])", re.IGNORECASE)
    if token == "<REMOVED_NATIONAL_ID>":
        digits = re.sub(r"\D", "", value)
        return re.compile(r"(?<!\d)" + r"[.\s-]*".join(map(re.escape, digits)) + r"(?!\d)")
    if token == "<PERSON_1>":
        parts = value.split()
        names = {value, value.upper(), value.lower()}
        if len(parts) >= 2:
            surname_start = next((index for index, part in enumerate(parts) if part.casefold() in {"de", "van", "der", "den", "ten", "ter", "van de"}), len(parts) - 1)
            surname = " ".join(parts[surname_start:])
            given = parts[:surname_start]
            if not given:
                given, surname = parts[:-1], parts[-1]
            names.update({surname + " " + " ".join(given), " ".join(given[:1] + [surname]), " ".join(given[:1] + [surname]) + "."})
            initials = " ".join(f"{part[0]}" for part in given)
            names.update({f"{initials}. {surname}", f"{surname} {initials}", f"{surname} {initials}."})
        alternatives = sorted((re.escape(n).replace(r"\ ", r"\s+") for n in names), key=len, reverse=True)
        if len(parts) >= 2:
            # "A.M. Surname", "A. M. Surname", "A M Surname"
            alternatives.append(r"\.?\s*".join(re.escape(part[0]) for part in given) + r"\.?\s*" + re.escape(surname).replace(r"\ ", r"\s+"))
        return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE)
    escaped = re.escape(value.strip()).replace(r"\ ", r"\s+")
    return re.compile(escaped, re.IGNORECASE)


def scrub(text: str, map: PseudoMap) -> str:
    for value, token in sorted(map.replacements, key=lambda item: len(item[0]), reverse=True):
        text = _pattern_for(value, token).sub(token, text)
    return text


_GENERIC_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.IGNORECASE)
_GENERIC_NATIONAL_ID = re.compile(r"(?<![\d.])\d(?:[.\s-]*\d){8}(?![\d])")


def mask_identifiers(text: str) -> str:
    """Mask IBAN- and BSN-shaped values that are not in the applicant map (P2, P3)."""
    return _GENERIC_NATIONAL_ID.sub("<REMOVED_NATIONAL_ID>", _GENERIC_IBAN.sub("<IBAN>", text))


def identity_map(file: LoanFile) -> PseudoMap:
    """Applicant name and address only: used to keep them out of keyword matching (P8)."""
    a = file.applicant
    return PseudoMap([(value, token) for value, token in ((a.name, "<PERSON_1>"), (a.address, "<ADDRESS_1>")) if value])


def restore(text: str, map: PseudoMap) -> str:
    for value, token in sorted(map.replacements, key=lambda item: len(item[1]), reverse=True):
        text = text.replace(token, value)
    return text


def store_map(case_id: str, map: PseudoMap, path: str | Path = "ledger.sqlite3") -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS pseudonym_maps (case_id TEXT PRIMARY KEY, mapping TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO pseudonym_maps VALUES (?, ?)", (case_id, repr(map.replacements)))


def load_map(case_id: str, path: str | Path = "ledger.sqlite3") -> PseudoMap:
    import ast
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT mapping FROM pseudonym_maps WHERE case_id=?", (case_id,)).fetchone()
    if row is None:
        raise KeyError(case_id)
    return PseudoMap(ast.literal_eval(row[0]))


def assert_clean(text: str, file: LoanFile) -> None:
    def reject(pattern: re.Pattern[str], label: str) -> None:
        match = pattern.search(text)
        if match:
            digest = hashlib.sha256(match.group().encode()).hexdigest()[:12]
            raise LeakDetected(f"Potential {label} pattern detected (span hash {digest})")

    mapping = build_map(file)
    for value, token in mapping.replacements:
        if _pattern_for(value, token).search(text):
            digest = hashlib.sha256(value.encode()).hexdigest()[:12]
            raise LeakDetected(f"Potential identifier leak (span hash {digest})")
    reject(re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.IGNORECASE), "IBAN")
    reject(re.compile(r"\b\d(?:[.\s-]*\d){8}\b"), "national identifier")
    reject(re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "email")
    reject(re.compile(r"(?<!\w)\+?\d[\d .()-]{7,}\d(?!\w)"), "phone")
