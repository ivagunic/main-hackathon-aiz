from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml

from app.gateway import guarded_local_complete
from app.models import Affordability, CustomerMessage, Element, LoanFile

TERMS_PATH = Path(__file__).resolve().parents[2] / "data" / "dictionaries" / "hardship_terms.yaml"


def detect(messages: list[CustomerMessage], file: LoanFile) -> list[Element]:
    if os.getenv("HARDSHIP_ENABLED", "false").casefold() != "true":
        return []
    terms = yaml.safe_load(TERMS_PATH.read_text(encoding="utf-8"))
    results = []
    for message in sorted(messages, key=lambda item: item.id):
        matched = any(term.casefold() in message.text.casefold() for term in terms.get(message.language, []))
        if not matched:
            continue
        confirmation = guarded_local_complete("Confirm whether this text reports payment hardship. Return yes or no only.", message.text, file).strip().casefold()
        if confirmation not in {"yes", "true", "hardship", "hardship_signal"}:
            continue
        results.append(Element(id=hashlib.sha1(f"hardship:{message.id}".encode()).hexdigest()[:12], source_ref=f"msg:{message.id}", kind="message_span", text=message.text, category="hardship_signal", subcategory="payment_difficulty", detector="dictionary+local_model", lane="local_only"))
    return results


def draft_options(affordability: Affordability) -> list[str]:
    return ["Consider a payment holiday.", "Consider reduced instalments.", "Offer a referral to independent debt advice."]
