"""C. Classifier robustness (P4, P5): misspellings, abbreviations, languages, unicode tricks and negatives."""
from __future__ import annotations

import pytest
from hardening_helpers import ROOT

from app.classify import classify_text
from app.intake import load_file

ZW = "\u200b"   # zero-width space
ZWJ = "‍"  # zero-width joiner
SHY = "­"  # soft hyphen


def fullwidth(text: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else "　" if c == " " else c for c in text)


SENSITIVE = [
    # misspellings
    ("apotheeek", "special_category"), ("apoteek", "special_category"), ("Apotheck Centrum", "special_category"),
    ("apoteke zahlung", "special_category"), ("Kirchensteur", "special_category"), ("Gewerkschaf beitrag", "special_category"),
    ("pharmacy", "special_category"), ("Vakbnd contributie", "special_category"),
    # abbreviations
    ("GGZ", "special_category"), ("GGZ Noord", "special_category"), ("CJIB", "criminal"), ("CJIB boete", "criminal"),
    ("cjib", "criminal"), ("FNV contributie", "special_category"), ("CNV Vakmensen", "special_category"),
    # other languages
    ("Apotheke", "special_category"), ("Kirchensteuer", "special_category"), ("Gewerkschaft", "special_category"),
    ("pharmacie", "special_category"), ("syndicat", "special_category"), ("Kirche Spende", "special_category"),
    ("Krankenhaus Rechnung", "special_category"), ("hôpital paiement", "special_category"), ("Farmacia Centrale", "special_category"),
    ("église don", "special_category"), ("Moschee Spende", "special_category"), ("mosquée don", "special_category"),
    ("Moskee Al Fictief", "special_category"), ("Synagoge bijdrage", "special_category"), ("Parochie Sint Fictief", "special_category"),
    ("Partei Mitgliedsbeitrag", "special_category"), ("Reclassering", "criminal"), ("Tandarts Fictief", "special_category"),
    # unicode tricks
    ("Apothéek", "special_category"), (f"Apo{ZW}theek", "special_category"), (f"K{ZW}e{ZW}r{ZW}k collecte", "special_category"),
    (f"Vak{ZWJ}bond", "special_category"), (f"Apo{SHY}theek", "special_category"), (fullwidth("Apotheek"), "special_category"),
    (fullwidth("CJIB"), "criminal"), ("aPoThEeK", "special_category"), ("VAKBOND", "special_category"),
    ("  Apotheek    De   Voorbeeldbrug  ", "special_category"), ("Apo.theek", "special_category"), ("Apo-theek", "special_category"),
    ("V.a.k.b.o.n.d", "special_category"), ("C.J.I.B.", "criminal"), ("C J I B", "criminal"), ("Ge-werk-schaft", "special_category"),
    ("Kérk", "special_category"), ("Phármacie", "special_category"), ("Gewerkſchaft", "special_category"),
    ("A P O T H E E K", "special_category"), ("Vakbond\tVoorbeeld", "special_category"), ("Apotheek\nbetaling", "special_category"),
    ("tinder gold", "special_category"), ("Ziekenhuis Fictief", "special_category"),
]

NEUTRAL = [
    "Church Street Cafe", "Church Street Café", "Union Square Parking", "Kerkstraat Bakkerij", "Party City",
    "Apotheekstraat rent", "Huur Kerkstraat 12", "Kerkweg Garage", "Kerkplein Parkeren", "Apotheekweg 3 huur",
    "Union Street Bakery", "Albert Heijn", "Jumbo Supermarkt", "NS Reizen", "Eneco Energie", "Vattenfall termijn",
    "Ziggo internet", "KPN mobiel", "Woonstichting Fictief huur", "Shell tankstation", "Gemeente belastingen",
    "Partyverhuur Feest", "Hypotheek Bank Fictief", "Waterbedrijf Fictief", "Lening aflossing Kredietbank",
    "Salaris Voorbeeld Werk", "Bakkerij De Korenaar", "Kerkhofstraat Fietsenmaker",
]


def _loan():
    return load_file(ROOT / "data" / "files" / "clean.json")


def test_table_size_meets_the_brief():
    assert len(SENSITIVE) + len(NEUTRAL) >= 80
    assert len(NEUTRAL) >= 20


@pytest.mark.parametrize(("text", "expected"), SENSITIVE, ids=[repr(t) for t, _ in SENSITIVE])
def test_sensitive_variant_is_detected(text, expected):
    element = classify_text(_loan(), "tx:test", "transaction", text)
    assert element.category == expected, (text, element.category, element.subcategory)


@pytest.mark.parametrize("text", NEUTRAL)
def test_negative_stays_neutral(text):
    element = classify_text(_loan(), "tx:test", "transaction", text)
    assert element.category not in {"special_category", "criminal"}, (text, element.subcategory)
