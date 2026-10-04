"""Typed data for the underwriting review. Money is Decimal, never float."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


# --- Application data (extracted from documents) ---

class IncomeType(str, Enum):
    SALARY = "salary"
    HOURLY = "hourly"
    BONUS = "bonus"
    COMMISSION = "commission"
    OVERTIME = "overtime"
    SELF_EMPLOYED = "self_employed"
    RENTAL = "rental"
    OTHER = "other"


class Income(BaseModel):
    type: IncomeType
    annual_amount: Decimal
    employer: str | None = None
    position: str | None = None
    start_date: date | None = None


class Borrower(BaseModel):
    name: str
    date_of_birth: date | None = None
    first_time_buyer: bool = False
    incomes: list[Income] = []
    credit_score: int | None = None


class LiabilityType(str, Enum):
    CREDIT_CARD = "credit_card"
    LINE_OF_CREDIT = "line_of_credit"
    AUTO_LOAN = "auto_loan"
    STUDENT_LOAN = "student_loan"
    MORTGAGE = "mortgage"
    OTHER = "other"


class Liability(BaseModel):
    type: LiabilityType
    lender: str
    balance: Decimal
    monthly_payment: Decimal
    paid_off_before_closing: bool = False


class Asset(BaseModel):
    description: str
    value: Decimal
    liquid: bool = True


class ExistingProperty(BaseModel):
    address: str
    value: Decimal
    mortgage_balance: Decimal = Decimal("0")
    monthly_mortgage_payment: Decimal = Decimal("0")
    monthly_property_tax: Decimal = Decimal("0")
    monthly_heat: Decimal = Decimal("0")
    monthly_rental_income: Decimal = Decimal("0")


class PropertyType(str, Enum):
    DETACHED = "detached"
    SEMI_DETACHED = "semi_detached"
    TOWNHOUSE = "townhouse"
    CONDO = "condo"
    RURAL = "rural"
    OTHER = "other"


class Property(BaseModel):
    address: str
    type: PropertyType
    purchase_price: Decimal
    appraised_value: Decimal | None = None
    annual_property_tax: Decimal
    monthly_heat: Decimal | None = None
    monthly_condo_fees: Decimal = Decimal("0")
    living_area_sqft: int | None = None
    new_build: bool = False
    marketability: str | None = None  # appraiser's rating, e.g. "good", "average", "poor"
    days_on_market: int | None = None


class Loan(BaseModel):
    amount: Decimal
    contract_rate: Decimal  # annual %, e.g. Decimal("4.79")
    amortization_years: int
    term_years: int
    product: str
    down_payment: Decimal
    closing_date: date | None = None


class Application(BaseModel):
    borrowers: list[Borrower]
    property: Property
    loan: Loan
    liabilities: list[Liability] = []
    assets: list[Asset] = []
    existing_properties: list[ExistingProperty] = []


# --- Review output ---

class Status(str, Enum):
    PASS = "pass"
    ATTENTION = "attention"
    FAIL = "fail"


class Area(str, Enum):
    BORROWER = "borrower"
    PROPERTY = "property"
    POLICY = "policy"
    AUTHENTICITY = "authenticity"


class Evidence(BaseModel):
    doc: str
    field: str
    value: str


class Finding(BaseModel):
    area: Area
    check: str
    status: Status
    message: str
    evidence: list[Evidence] = []
    near_miss: bool = False  # failed within the exception margin
    needs_referral: bool = False  # requires human judgment (e.g. possible misrepresentation)


class ExceptionCase(BaseModel):
    gap: str
    additional_income: str
    excludable_liabilities: str
    compensating_strengths: str
    alternative_products: str
    policy_exception: str
    recomputed_ratios: dict[str, Decimal] = {}
    narrative: str = ""


class ConditionStatus(str, Enum):
    OPEN = "open"
    CLEARED = "cleared"


class Condition(BaseModel):
    id: str
    text: str
    raised_by: str | None = None  # Finding.check, or None for standard conditions
    status: ConditionStatus = ConditionStatus.OPEN
    cleared_by_doc: str | None = None
    cleared_at: datetime | None = None


class Recommendation(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    REFER = "refer_for_review"
    DECLINE = "decline"


class Review(BaseModel):
    application: Application
    ratios: dict[str, Decimal]
    findings: list[Finding]
    exception_case: ExceptionCase | None = None
    conditions: list[Condition]
    recommendation: Recommendation
    recommendation_reasons: list[str]


# --- Case record: the agent's only persistent state ---

class DocumentRef(BaseModel):
    filename: str
    sha256: str


class PolicyRef(BaseModel):
    file: str
    version: str
    sha256: str


class UnderwriterDecision(BaseModel):
    decision: Recommendation
    decided_at: datetime


class CaseRecord(BaseModel):
    case_id: str
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentRef]
    policies: list[PolicyRef]
    model: str
    prompt_version: str
    review: Review
    underwriter_decision: UnderwriterDecision | None = None
    history: list[str] = Field(default_factory=list)  # e.g. "2026-10-04T10:12 condition C3 cleared by gift-letter.pdf"
