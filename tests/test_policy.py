import copy
from decimal import Decimal as D

import pytest

from underwriting.policy import check_limit, evaluate, load_policy
from underwriting.schemas import (
    Application, Borrower, ExistingProperty, Income, IncomeType, Liability, LiabilityType, Loan,
    Property, PropertyType, Status,
)


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def make_app(*, income="150000", price="600000", appraised=None, loan_amount="480000", rate="4.79",
             amortization=25, score=750, first_time=False, prop_type=PropertyType.DETACHED, sqft=None,
             liabilities=(), existing=(), product="5-Year Fixed") -> Application:
    price, loan_amount = D(price), D(loan_amount)
    return Application(
        borrowers=[Borrower(name="Test Borrower", first_time_buyer=first_time, credit_score=score,
                            incomes=[Income(type=IncomeType.SALARY, annual_amount=D(income))])],
        property=Property(address="1 Main St", type=prop_type, purchase_price=price,
                          appraised_value=D(appraised) if appraised else None,
                          annual_property_tax=D("4200"), living_area_sqft=sqft),
        loan=Loan(amount=loan_amount, contract_rate=D(rate), amortization_years=amortization, term_years=5,
                  product=product, down_payment=price - loan_amount),
        liabilities=list(liabilities), existing_properties=list(existing),
    )


def by_check(findings):
    return {f.check: f for f in findings}


# --- check_limit boundaries ---

@pytest.mark.parametrize("value,status,near_miss", [
    (D("44.00"), Status.PASS, False),       # at the limit passes
    (D("44.01"), Status.FAIL, True),
    (D("46.00"), Status.FAIL, True),        # at limit + margin is still a near miss
    (D("46.01"), Status.FAIL, False),
])
def test_check_limit_boundaries(value, status, near_miss):
    f = check_limit("tds", value, limit=D("44"), margin=D("2"), doc="calc")
    assert (f.status, f.near_miss) == (status, near_miss)


# --- ratios ---

def test_ratios_at_contract_and_qualifying_rate(policy):
    ratios, _ = evaluate(make_app(), policy)
    assert ratios["qualifying_rate"] == D("6.79")
    assert ratios["monthly_payment_qualifying"] == D("3299.99")
    # housing = 3299.99 + 350 tax + 100 default heat = 3749.99 on 12500/mo
    assert ratios["gds_qualifying"] == D("30.00")
    assert ratios["tds_qualifying"] == D("30.00")
    assert ratios["ltv"] == D("80.00")


def test_debts_and_existing_property_count_in_tds_rent_offsets_income(policy):
    app = make_app(
        liabilities=[Liability(type=LiabilityType.AUTO_LOAN, lender="Bank", balance=D("20000"),
                               monthly_payment=D("650")),
                     Liability(type=LiabilityType.CREDIT_CARD, lender="Card", balance=D("1000"),
                               monthly_payment=D("50"), paid_off_before_closing=True)],
        existing=[ExistingProperty(address="2 Rental Rd", value=D("400000"),
                                   monthly_mortgage_payment=D("1500"), monthly_property_tax=D("250"),
                                   monthly_heat=D("100"), monthly_rental_income=D("2000"))])
    ratios, _ = evaluate(app, policy)
    # income 12500 + 50% of 2000 rent = 13500; other debts = 650 + 1850 carrying (card paid off)
    assert ratios["qualifying_monthly_income"] == D("13500.00")
    assert ratios["tds_qualifying"] == D("46.30")   # (3749.99 + 2500) / 13500


def test_ltv_uses_lower_appraisal(policy):
    ratios, findings = evaluate(make_app(appraised="590000"), policy)
    assert ratios["ltv"] == D("81.36")
    assert by_check(findings)["insurance_path"].message.startswith("Insured")


# --- policy findings ---

def test_clean_application_passes_everything(policy):
    _, findings = evaluate(make_app(), policy)
    assert all(f.status == Status.PASS for f in findings), [f for f in findings if f.status != Status.PASS]


def test_tds_near_miss_flagged_for_exception(policy):
    _, findings = evaluate(make_app(income="102000"), policy)  # TDS ~44.1%
    tds = by_check(findings)["tds_limit"]
    assert tds.status == Status.FAIL and tds.near_miss


def test_minimum_down_payment(policy):
    _, findings = evaluate(make_app(price="600000", loan_amount="570000"), policy)  # 30K down < 35K
    assert by_check(findings)["min_down_payment"].status == Status.FAIL


def test_insured_amortization_limit_depends_on_first_time_buyer(policy):
    insured = dict(loan_amount="550000", amortization=30)  # LTV 91.67%
    assert by_check(evaluate(make_app(**insured), policy)[1])["max_amortization"].status == Status.FAIL
    assert by_check(evaluate(make_app(**insured, first_time=True), policy)[1])["max_amortization"].status == Status.PASS


def test_insured_not_available_at_or_above_1_5m(policy):
    _, findings = evaluate(make_app(price="1600000", loan_amount="1400000", income="400000"), policy)
    assert by_check(findings)["insurance_eligibility"].status == Status.FAIL


def test_credit_score_minimum(policy):
    assert by_check(evaluate(make_app(score=679), policy)[1])["min_credit_score"].status == Status.FAIL
    assert by_check(evaluate(make_app(score=680), policy)[1])["min_credit_score"].status == Status.PASS


def test_property_type_rules(policy):
    assert by_check(evaluate(make_app(prop_type=PropertyType.CONDO, sqft=350), policy)[1])["property_type"].status == Status.FAIL
    assert by_check(evaluate(make_app(prop_type=PropertyType.RURAL), policy)[1])["property_type"].status == Status.FAIL


def test_unknown_product_fails(policy):
    assert by_check(evaluate(make_app(product="40-Year Magic"), policy)[1])["product"].status == Status.FAIL


def test_changing_policy_value_flips_outcome(policy):
    app = make_app(income="102000")
    assert by_check(evaluate(app, policy)[1])["tds_limit"].status == Status.FAIL
    looser = copy.deepcopy(policy)
    looser.credit["tds_max_pct"] = 45
    assert by_check(evaluate(app, looser)[1])["tds_limit"].status == Status.PASS


def test_findings_carry_evidence(policy):
    _, findings = evaluate(make_app(), policy)
    assert all(f.evidence for f in findings)


def test_policy_refs_have_version_and_hash(policy):
    refs = policy.refs()
    assert len(refs) == 4 and all(r.version and len(r.sha256) == 64 for r in refs)


def test_insured_loan_adds_premium_to_payment(policy):
    ratios, findings = evaluate(make_app(loan_amount="550000", first_time=True, amortization=30), policy)
    assert ratios["insurance_premium"] == D("23100.00")
    assert ratios["total_loan"] == D("573100.00")
    assert ratios["ltv"] == D("91.67")    # LTV is on the base loan
    assert any(e.field == "insurance_premium" for e in by_check(findings)["insurance_path"].evidence)


def test_conventional_loan_has_no_premium(policy):
    ratios, _ = evaluate(make_app(), policy)
    assert ratios["insurance_premium"] == D("0") and ratios["total_loan"] == D("480000")
