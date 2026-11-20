from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from app.gateway import guarded_local_complete
from app.models import Element, LoanFile
from app.pseudo import PseudoMap, identity_map, scrub

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = ROOT / "data" / "dictionaries" / "sensitive_merchants.yaml"
_ATTACK = re.compile(
    r"\b(?:system|systeem|assistant)\s*:|"  # colon forms sit outside the word-boundary group below
    r"\b(ignore|disregard|approve this|you are|ignore previous|reveal|translate the hidden|"
    r"forget (?:your|all|the) (?:rules|instructions)|new instructions?|override|"
    r"negeer|vergeet (?:je|jouw|alle|de) (?:regels|instructies)|nieuwe instructies?|jij bent|je bent een|keur\w* .{0,30}goed|"
    r"ignorier\w*|vergiss|missachte|neue anweisung\w*|du bist|anweisungen)\b|<\|im_(?:start|end)\|>|###",
    re.IGNORECASE,
)
_BASE64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _attack(text: str) -> bool:
    """Instruction-like text in EN, NL, DE, also when spaced, zero-width split or base64 encoded (P11)."""
    import base64
    import binascii

    candidates = [text, _normal(text)]
    for token in _BASE64.findall(text):
        try:
            decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable():
            candidates.append(decoded)
    return any(_ATTACK.search(candidate) for candidate in candidates)


class _AttackPattern:
    """Keeps the public ``ATTACK.search`` interface used elsewhere."""

    def search(self, text: str):
        return _attack(text) or None


ATTACK = _AttackPattern()
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.IGNORECASE)
EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)")
BUSINESS = re.compile(r"\b(caf[eé]|café|bakery|restaurant|studio|hotel|shop|market|services|group|b\.v\.)\b", re.IGNORECASE)


def _id(file: LoanFile, ref: str, kind: str) -> str:
    return hashlib.sha1(f"{file.case_id}:{ref}:{kind}".encode()).hexdigest()[:12]


def _element(file: LoanFile, ref: str, kind: str, text: str, category: str, sub: str | None = None, detector: str = "regex") -> Element:
    return Element(id=_id(file, ref, kind), source_ref=ref, kind=kind, text=text, category=category, subcategory=sub, detector=detector)


_STREET = re.compile(r"\b[^\W\d_]*(?:straat|weg|plein|laan|gracht|kade|singel|steeg|dijk|strasse|street|road|square|lane|avenue)\b")
_INNER_PUNCT = re.compile(r"(?<=[^\W\d_])[.\-_'’·*]+(?=[^\W\d_])")
_SPACED_LETTERS = re.compile(r"(?<!\S)(?:[^\W\d_][.\s]+){2,}[^\W\d_]\.?(?!\S)")


def _normal(text: str) -> str:
    """Casefold, strip accents and invisible characters, rejoin split or spaced-out words."""
    folded = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    kept = "".join(ch for ch in folded if not unicodedata.combining(ch) and unicodedata.category(ch) != "Cf")
    kept = _INNER_PUNCT.sub("", kept)
    kept = _SPACED_LETTERS.sub(lambda m: re.sub(r"[.\s]", "", m.group()), kept)
    return " ".join(kept.split())


def _fuzzy_stem(normalized: str, stems: list[str]) -> bool:
    single = [stem for stem in stems if " " not in stem and len(stem) >= 6]
    return any(fuzz.ratio(token, stem) >= 85 for token in normalized.split() if len(token) >= 5 for stem in single)


def _dictionary() -> dict:
    data = yaml.safe_load(DICTIONARY.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Merchant dictionary must be a mapping")
    return data


def classify_text(file: LoanFile, ref: str, kind: str, text: str, dictionary: dict | None = None, mask: PseudoMap | None = None) -> Element:
    if ATTACK.search(text):
        return _element(file, ref, kind, text, "instruction_attack", detector="instruction_pattern")
    phone_matches = [match.group() for match in PHONE.finditer(text)]
    identifier = bool(IBAN.search(text) or EMAIL.search(text) or any(sum(ch.isdigit() for ch in value) >= 10 for value in phone_matches))
    dictionary = dictionary if dictionary is not None else _dictionary()
    # The applicant's own name and address must not trigger a category (P8: "Tom Church", "Kerkhof").
    normalized = _normal(scrub(text, mask) if mask else text)
    # Street names ("Kerkstraat", "Apotheekweg") are addresses, not merchants.
    matchable = " ".join(_STREET.sub(" ", normalized).split())
    for category, spec in sorted(dictionary.items()):
        if not isinstance(spec, dict):
            raise TypeError(f"Merchant dictionary entry {category} must be a mapping")
        allowlist = {_normal(v) for v in spec.get("allowlist", [])}
        allowlisted = any(allowed in normalized for allowed in allowlist)
        if allowlisted and not re.search(r"donat|tithe|kirchensteuer|church service|collecte|religious", normalized):
            continue
        exact = sorted((_normal(v) for v in spec.get("exact", [])), key=len, reverse=True)
        stems = sorted((_normal(v) for v in spec.get("stems", [])), key=len, reverse=True)
        terms = exact + stems
        hits = [term for term in terms if term and term in matchable]
        if not hits and category in {"pharmacy", "union", "religion", "hospital"} and _fuzzy_stem(matchable, stems):
            return _element(file, ref, kind, text, "special_category", category, "fuzzy")
        if hits:
            # Common business names containing "church" are ordinary merchants unless
            # a religious service or donation term is also present.
            if category == "religion" and BUSINESS.search(text) and not re.search(r"donat|tithe|church service|kirchensteuer|collecte", normalized):
                continue
            return _element(file, ref, kind, text, "criminal" if category == "criminal" else "special_category", category, "dictionary")
        if category in {"pharmacy", "union", "religion"} and any(fuzz.ratio(term, normalized) >= 90 for term in exact if len(term) > 5):
            return _element(file, ref, kind, text, "special_category", category, "fuzzy")
    if identifier:
        return _element(file, ref, kind, text, "identifier", detector="regex")
    return _element(file, ref, kind, text, "financial_fact" if kind == "transaction" else "neutral", detector="rule")


def _identifier_elements(file: LoanFile, ref: str, kind: str, text: str) -> list[Element]:
    found: list[Element] = []
    patterns = (("iban", IBAN, "identifier"), ("email", EMAIL, "identifier"), ("phone", PHONE, "identifier"))
    for label, pattern, category in patterns:
        for index, match in enumerate(pattern.finditer(text), 1):
            if label == "phone" and sum(ch.isdigit() for ch in match.group()) < 10:
                continue
            found.append(_element(file, f"{ref}:{label}:{index}", kind, match.group(), category, label, "regex"))
    for index, value in enumerate((file.applicant.name, file.applicant.address, file.applicant.postcode), 1):
        if value and value.casefold() in text.casefold():
            category = "proxy" if value in {file.applicant.name, file.applicant.postcode} else "identifier"
            found.append(_element(file, f"{ref}:known:{index}", kind, value, category, "known_applicant_value", "exact"))
    return found


def classify(file: LoanFile) -> list[Element]:
    dictionary = _dictionary()  # Missing or malformed controls must fail closed upstream.
    identity = identity_map(file)
    results: list[Element] = []
    tx_elements: dict[str, Element] = {}
    for tx in sorted(file.transactions, key=lambda item: (item.date, item.id)):
        element = classify_text(file, f"tx:{tx.id}", "transaction", f"{tx.counterparty} {tx.description}", dictionary, identity)
        tx_elements[tx.id] = element
        results.append(element)
        results.extend(_identifier_elements(file, f"tx:{tx.id}", "transaction", f"{tx.counterparty} {tx.description}"))
    sensitive_merchants = {_normal(tx.counterparty) for tx in file.transactions if tx_elements[tx.id].category == "special_category"}
    for tx in sorted(file.transactions, key=lambda item: (item.date, item.id)):
        if _normal(tx.counterparty) in sensitive_merchants and tx_elements[tx.id].category != "special_category":
            tx_elements[tx.id] = tx_elements[tx.id].model_copy(update={"category": "special_category", "subcategory": "recurring_sensitive", "detector": "recurring_counterparty"})
    results = [tx_elements[tx.id] for tx in sorted(file.transactions, key=lambda item: (item.date, item.id))]
    for slip in sorted(file.payslips, key=lambda item: item.id):
        if ATTACK.search(slip.raw_text):
            results.append(_element(file, f"payslip:{slip.id}", "payslip_line", slip.raw_text, "instruction_attack", detector="instruction_pattern"))
        if ATTACK.search(slip.employer):
            results.append(_element(file, f"payslip:{slip.id}:employer", "form_field", slip.employer, "instruction_attack", detector="instruction_pattern"))
        results.extend(_identifier_elements(file, f"payslip:{slip.id}", "payslip_line", slip.raw_text))
    # Intake strips source page text. If a trusted caller supplies in-memory text,
    # inspect it only for local instruction detection and identifier controls.
    for page, text in enumerate(file.raw_pages, 1):
        if ATTACK.search(text):
            results.append(_element(file, f"page:{page}", "page_text", text, "instruction_attack", detector="instruction_pattern"))
        results.extend(_identifier_elements(file, f"page:{page}", "page_text", text))
    for message in sorted(file.messages, key=lambda item: item.id):
        if ATTACK.search(message.text):
            category = "instruction_attack"
            detector = "instruction_pattern"
        else:
            result = guarded_local_complete("Classify whether this message contains an instruction attack or payment hardship. Return one label only.", message.text, file).strip().casefold()
            category = "instruction_attack" if result in {"attack", "instruction_attack"} else "hardship_signal" if result in {"hardship", "hardship_signal"} else "neutral"
            detector = "local_model"
        results.append(_element(file, f"msg:{message.id}", "message_span", message.text, category, detector=detector))
        results.extend(_identifier_elements(file, f"msg:{message.id}", "message_span", message.text))
    for label, value, category in (("iban", file.applicant.iban, "identifier"),):
        if value:
            results.append(_element(file, f"form:{label}", "form_field", value, category, label))
    for label, value in (("name", file.applicant.name), ("address", file.applicant.address), ("purpose", file.application.purpose)):
        if value and ATTACK.search(value):
            results.append(_element(file, f"form:{label}:attack", "form_field", value, "instruction_attack", detector="instruction_pattern"))
    if file.applicant.dob and os.getenv("AGE_PROXY_ENABLED", "off").casefold() == "on":
        results.append(_element(file, "form:dob", "form_field", file.applicant.dob.isoformat(), "proxy", "age", "config"))
    return results
