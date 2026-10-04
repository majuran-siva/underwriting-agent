from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

from underwriting.schemas import (
    Application, Borrower, CaseRecord, Income, IncomeType, Loan, Property,
    PropertyType, Recommendation, Review,
)

POLICY_DIR = Path(__file__).parent.parent / "policy"


def sample_application() -> Application:
    return Application(
        borrowers=[Borrower(name="Test Borrower", incomes=[
            Income(type=IncomeType.SALARY, annual_amount=Decimal("95000"), employer="Acme")])],
        property=Property(address="1 Main St, Toronto ON", type=PropertyType.DETACHED,
                          purchase_price=Decimal("600000"), annual_property_tax=Decimal("4200")),
        loan=Loan(amount=Decimal("480000"), contract_rate=Decimal("4.79"), amortization_years=25,
                  term_years=5, product="5-Year Fixed", down_payment=Decimal("120000")),
    )


def test_application_round_trips_through_json():
    app = sample_application()
    assert Application.model_validate_json(app.model_dump_json()) == app
    assert app.loan.amount == Decimal("480000")


def test_case_record_holds_review():
    now = datetime(2026, 10, 4, 10, 0)
    review = Review(application=sample_application(), ratios={"gds": Decimal("30.10")}, findings=[],
                    conditions=[], recommendation=Recommendation.APPROVE, recommendation_reasons=[])
    record = CaseRecord(case_id="01-clean", created_at=now, updated_at=now, documents=[], policies=[],
                        model="claude-opus-5-5", prompt_version="v1", review=review)
    assert CaseRecord.model_validate_json(record.model_dump_json()) == record


def test_all_policy_files_load_with_version():
    files = sorted(POLICY_DIR.glob("*.yaml"))
    assert {f.stem for f in files} == {"credit_policy", "insurers", "products", "regulatory"}
    for f in files:
        data = yaml.safe_load(f.read_text())
        assert data["version"], f"{f.name} missing version"
