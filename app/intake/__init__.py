from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from app.models import LoanFile, Transaction


def parse_file_data(text: str | bytes) -> LoanFile:
    try:
        # Drop fields that this workflow is not permitted to ingest before model
        # validation. In particular, BSN and all payslip content except printed
        # net pay are never represented in the runtime object.
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise TypeError("Loan file must be a JSON object")
        raw["customer_message_received"] = bool(raw.get("messages"))
        applicant = raw.get("applicant", {})
        if isinstance(applicant, dict):
            applicant["bsn"] = ""
        # The employer name is kept only so P2 can pseudonymise it wherever it recurs
        # (for example as the salary counterparty); no other payslip line is read.
        raw["payslips"] = [
            {key: slip[key] for key in ("id", "employer", "period", "net_cents", "page") if key in slip}
            for slip in raw.get("payslips", [])
        ]
        raw["raw_pages"] = []
        raw["messages"] = raw.get("messages", []) if os.getenv("HARDSHIP_ENABLED", "false").casefold() == "true" else []
        return LoanFile.model_validate(raw)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid loan file: {exc}") from exc


def load_file(path: str | Path) -> LoanFile:
    file_path = Path(path)
    try:
        return parse_file_data(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid loan file {file_path}: {exc}") from exc


def dump_file(file: LoanFile, path: str | Path) -> None:
    Path(path).write_text(file.model_dump_json(indent=2), encoding="utf-8")


def parse_amount(value: str) -> int:
    """Convert a Dutch or plain decimal amount to integer cents."""
    normalized = value.strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not normalized:
        raise ValueError("Amount is empty")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif normalized.count(".") > 1:
        pieces = normalized.split(".")
        if len(pieces[-1]) == 3:
            normalized = "".join(pieces)
        else:
            raise ValueError(f"Ambiguous amount: {value}")
    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {value}") from exc
    return int(amount * 100)


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date: {value}")


def load_statement_csv(path: str | Path) -> list[Transaction]:
    transactions: list[Transaction] = []
    aliases = {"id": ("id", "transaction_id", "referentie"), "date": ("date", "datum"),
        "counterparty": ("counterparty", "merchant", "tegenpartij", "naam"),
        "description": ("description", "omschrijving", "details"), "amount": ("amount", "bedrag"),
        "page": ("page", "pagina")}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 2):
            normalized = {str(key).strip().casefold(): (value or "").strip() for key, value in row.items() if key}
            values = {target: next((normalized[key] for key in keys if key in normalized), "") for target, keys in aliases.items()}
            try:
                if not values["date"] or not values["counterparty"] or not values["amount"]:
                    raise ValueError("required date, counterparty, or amount is missing")
                transactions.append(Transaction(id=values["id"] or str(row_number - 1), date=parse_date(values["date"]),
                    counterparty=values["counterparty"], description=values["description"], amount_cents=parse_amount(values["amount"]),
                    page=int(values["page"] or 1)))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Malformed statement row {row_number}: {exc}") from exc
    return transactions


def parse_payslip_text(text: str) -> dict[str, int]:
    match = re.search(r"\bnet\b\s*(?:pay|to pay|salary)?\s*[:=]?\s*€?\s*([\d.,]+)", text, re.IGNORECASE)
    return {"net_cents": parse_amount(match.group(1))} if match else {}


def extract_pdf_text(path: str | Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF support requires pypdf") from exc
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]
