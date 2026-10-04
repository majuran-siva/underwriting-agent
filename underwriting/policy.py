"""Applies the lender's layered policy (policy/*.yaml) to an application.

All thresholds come from the YAML files; this module holds none of its own.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from underwriting import ratios as r
from underwriting.schemas import (
    Application, Area, Evidence, Finding, IncomeType, PolicyRef, PropertyType, Status,
)

POLICY_DIR = Path(__file__).parent.parent / "policy"
CALC = "calculation"  # evidence source for derived values


@dataclass
class Policy:
    credit: dict
    products: dict
    insurers: dict
    regulatory: dict
    _refs: list[PolicyRef]

    def refs(self) -> list[PolicyRef]:
        return list(self._refs)


def load_policy(directory: Path = POLICY_DIR) -> Policy:
    layers, refs = {}, []
    for name in ("credit_policy", "products", "insurers", "regulatory"):
        path = directory / f"{name}.yaml"
        raw = path.read_bytes()
        layers[name] = yaml.safe_load(raw)
        refs.append(PolicyRef(file=path.name, version=str(layers[name]["version"]),
                              sha256=hashlib.sha256(raw).hexdigest()))
    return Policy(layers["credit_policy"], layers["products"], layers["insurers"], layers["regulatory"], refs)


def _d(value) -> Decimal:
    return Decimal(str(value))


def _finding(check: str, ok: bool, message: str, evidence: list[Evidence]) -> Finding:
    return Finding(area=Area.POLICY, check=check, status=Status.PASS if ok else Status.FAIL,
                   message=message, evidence=evidence)


def check_limit(check: str, value: Decimal, limit: Decimal, margin: Decimal, doc: str) -> Finding:
    """value ≤ limit passes; above it fails, and is a near miss when within `margin` points."""
    ok = value <= limit
    finding = _finding(check, ok, f"{check.split('_')[0].upper()} {value}% vs limit {limit}%",
                       [Evidence(doc=doc, field=check, value=f"{value}%")])
    finding.near_miss = not ok and value <= limit + margin
    return finding


def evaluate(app: Application, policy: Policy) -> tuple[dict[str, Decimal], list[Finding]]:
    """Returns (ratios, findings). Ratios are computed at both the contract and the qualifying rate."""
    credit, reg, ins, prod = policy.credit, policy.regulatory, policy.insurers, policy.products
    loan, prop = app.loan, app.property

    # Income: employment income plus the policy share of rent from existing properties.
    annual_income = sum((i.annual_amount for b in app.borrowers for i in b.incomes
                         if i.type != IncomeType.RENTAL), Decimal(0))
    rent = sum((p.monthly_rental_income for p in app.existing_properties), Decimal(0))
    monthly_income = annual_income / 12 + rent * _d(credit["rental_income_offset_pct"]) / 100

    # Other obligations: open debts plus carrying costs of properties already owned.
    other_debts = sum((l.monthly_payment for l in app.liabilities if not l.paid_off_before_closing), Decimal(0))
    other_debts += sum((p.monthly_mortgage_payment + p.monthly_property_tax + p.monthly_heat
                        for p in app.existing_properties), Decimal(0))

    q_rate = r.qualifying_rate(loan.contract_rate, _d(reg["qualifying_rate"]["buffer_pct"]),
                               _d(reg["qualifying_rate"]["floor_pct"]))
    # Insured loans (LTV on the base loan above the insurer threshold) add the premium to the loan.
    ltv = r.ltv(loan.amount, prop.purchase_price, prop.appraised_value)
    insured = ltv > _d(ins["applies_above_ltv_pct"])
    premium = Decimal(0)
    if insured and ltv <= _d(ins["premium"]["tiers"][-1]["max_ltv_pct"]):
        premium = r.insurance_premium(loan.amount, ltv, loan.amortization_years, ins["premium"]["tiers"],
                                      _d(ins["premium"]["surcharge_over_25_years_pct"]))
    total_loan = loan.amount + premium

    heat = prop.monthly_heat if prop.monthly_heat is not None else _d(credit["default_monthly_heat"])

    def housing(rate: Decimal) -> tuple[Decimal, Decimal]:
        payment = r.monthly_payment(total_loan, rate, loan.amortization_years)
        return payment, r.housing_costs(payment, prop.annual_property_tax / 12, heat, prop.monthly_condo_fees,
                                        _d(credit["condo_fee_gds_share_pct"]))

    pay_c, housing_c = housing(loan.contract_rate)
    pay_q, housing_q = housing(q_rate)
    ratios = {
        "qualifying_rate": q_rate,
        "qualifying_monthly_income": r.round_cents(monthly_income),
        "other_monthly_debts": r.round_cents(other_debts),
        "monthly_payment_contract": pay_c,
        "monthly_payment_qualifying": pay_q,
        "gds_contract": r.gds(housing_c, monthly_income),
        "tds_contract": r.tds(housing_c, other_debts, monthly_income),
        "gds_qualifying": r.gds(housing_q, monthly_income),
        "tds_qualifying": r.tds(housing_q, other_debts, monthly_income),
        "ltv": ltv,
        "insurance_premium": premium,
        "total_loan": total_loan,
    }

    margin = _d(credit["exception"]["ratio_margin_pct"])
    findings = [
        check_limit("gds_limit", ratios["gds_qualifying"], _d(credit["gds_max_pct"]), margin, CALC),
        check_limit("tds_limit", ratios["tds_qualifying"], _d(credit["tds_max_pct"]), margin, CALC),
    ]

    # Minimum down payment (regulatory).
    mdp = reg["min_down_payment"]
    required = r.min_down_payment(prop.purchase_price, mdp["tiers"], _d(mdp["at_or_above_price"]),
                                  _d(mdp["pct_at_or_above"]))
    findings.append(_finding("min_down_payment", loan.down_payment >= required,
                             f"Down payment ${loan.down_payment:,} vs required minimum ${required:,}",
                             [Evidence(doc="application", field="down_payment", value=f"{loan.down_payment}"),
                              Evidence(doc=CALC, field="min_down_payment", value=f"{required}")]))

    # Insured vs conventional path.
    ltv_ev = Evidence(doc=CALC, field="ltv", value=f"{ltv}%")
    path_ev = [ltv_ev] + ([Evidence(doc=CALC, field="insurance_premium", value=f"{premium}")] if premium else [])
    findings.append(_finding("insurance_path", True,
                             f"Insured (LTV {ltv}%), premium ${premium:,} added to loan" if insured
                             else f"Conventional (LTV {ltv}%)", path_ev))
    first_time_or_new = any(b.first_time_buyer for b in app.borrowers) or prop.new_build
    if insured:
        price_ok = prop.purchase_price < _d(ins["max_purchase_price"])
        findings.append(_finding("insurance_eligibility", price_ok,
                                 "Purchase price within insurable limit" if price_ok
                                 else f"Insured mortgage not available at price ${prop.purchase_price:,}",
                                 [ltv_ev, Evidence(doc="application", field="purchase_price",
                                                   value=f"{prop.purchase_price}")]))
        max_amort = ins["max_amortization_years_first_time_or_new_build" if first_time_or_new
                        else "max_amortization_years"]
    else:
        max_amort = prod["conventional_max_amortization_years"]
    findings.append(_finding("max_amortization", loan.amortization_years <= max_amort,
                             f"Amortization {loan.amortization_years} yrs vs max {max_amort}",
                             [Evidence(doc="application", field="amortization_years",
                                       value=str(loan.amortization_years))]))

    # Credit score: insured needs one borrower at the insurer minimum; conventional needs all at lender minimum.
    scores = [b.credit_score for b in app.borrowers if b.credit_score is not None]
    if scores:
        if insured:
            min_score, score_ok = ins["min_credit_score_one_borrower"], max(scores) >= ins["min_credit_score_one_borrower"]
        else:
            min_score, score_ok = credit["min_credit_score"], min(scores) >= credit["min_credit_score"]
        findings.append(_finding("min_credit_score", score_ok, f"Credit score(s) {scores} vs minimum {min_score}",
                                 [Evidence(doc="credit_report", field="score", value=str(s)) for s in scores]))

    # Product rules.
    product = next((p for p in prod["products"] if p["name"] == loan.product), None)
    prod_ev = [Evidence(doc="application", field="product", value=loan.product), ltv_ev]
    if product is None:
        findings.append(_finding("product", False, f"Unknown product '{loan.product}'", prod_ev))
    else:
        ok = ltv <= _d(product["max_ltv_pct"]) and loan.term_years == product["term_years"]
        findings.append(_finding("product", ok, f"{loan.product}: max LTV {product['max_ltv_pct']}%, "
                                 f"term {product['term_years']} yrs", prod_ev))

    # Property type rules.
    type_ev = [Evidence(doc="appraisal", field="property_type", value=prop.type.value)]
    if prop.type == PropertyType.RURAL and not prod["rural_allowed"]:
        findings.append(_finding("property_type", False, "Rural property not eligible", type_ev))
    elif prop.type == PropertyType.CONDO and (prop.living_area_sqft or 0) < prod["condo_min_living_area_sqft"]:
        type_ev.append(Evidence(doc="appraisal", field="living_area_sqft", value=str(prop.living_area_sqft)))
        findings.append(_finding("property_type", False,
                                 f"Condo below minimum {prod['condo_min_living_area_sqft']} sq ft", type_ev))
    else:
        findings.append(_finding("property_type", True, f"{prop.type.value} eligible", type_ev))

    return ratios, findings
