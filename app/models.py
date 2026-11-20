from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["identifier", "national_id", "financial_fact", "special_category", "criminal", "proxy", "hardship_signal", "instruction_attack", "neutral", "social_network", "unavailable_check", "model_output", "evidence_gap", "lending_decision"]
Lane = Literal["cloud_pseudonymised", "cloud_aggregate", "local_only", "excluded", "refuse", "human_review"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Applicant(StrictModel):
    name: str
    address: str = ""
    postcode: str = ""
    iban: str = ""
    bsn: str = ""
    dob: date | None = None
    age: int | None = None
    education: str = ""
    nationality: str = ""
    gender: str = ""
    income_type: str = "employed"


class Application(StrictModel):
    amount_cents: int
    term_months: int
    purpose: str = ""
    declared_debts: int = 0


class CustomerMessage(StrictModel):
    id: str
    text: str
    language: str = "nl"


class Transaction(StrictModel):
    id: str
    date: date
    counterparty: str
    description: str
    amount_cents: int
    page: int = 1


class Payslip(StrictModel):
    id: str
    employer: str = ""
    period: str
    net_cents: int
    raw_text: str = ""
    page: int = 1


class LoanFile(StrictModel):
    case_id: str
    applicant: Applicant
    application: Application
    payslips: list[Payslip] = Field(default_factory=list)
    transactions: list[Transaction] = Field(default_factory=list)
    messages: list[CustomerMessage] = Field(default_factory=list)
    raw_pages: list[str] = Field(default_factory=list)
    customer_message_received: bool = False


class Element(StrictModel):
    id: str
    source_ref: str
    kind: str
    text: str
    category: Category
    subcategory: str | None = None
    detector: str
    lane: Lane | None = None
    rule_id: str | None = None
    citation: str | None = None
    brane_policy_ref: str | None = None


class Decision(StrictModel):
    seq: int
    case_id: str
    element_id: str
    category: Category
    lane: Lane
    rule_id: str
    citation: str
    policy_version: str
    brane_verdict: str | None = None
    payload_sha256: str | None = None
    ts: datetime
    aiz_decision: Literal["allow", "protect", "local only", "block"] | None = None
    brane_policy_ref: str | None = None


class Affordability(StrictModel):
    net_pay_cents: int
    housing_cents: int
    utilities_cents: int
    debt_payment_cents: int
    open_questions: list[str] = Field(default_factory=list)
    source_refs: dict[str, list[str]] = Field(default_factory=dict)


class HiddenChip(StrictModel):
    count: int
    category: str
    citation: str


class OfficerView(StrictModel):
    case_id: str
    affordability: Affordability
    explanation: str
    visible_transactions: list[Transaction] = Field(default_factory=list)
    hidden_summary: list[HiddenChip] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    forbearance_options: list[str] = Field(default_factory=list)
    local_note: str = ""
    human_review_required: bool = False
    customer_message_status: str = ""
    caveat: str = "This file documents selected fixed obligations only. It does not establish total expenditure or disposable income."
