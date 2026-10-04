"""Deterministic mortgage math. No LLM, no policy lookups: callers pass the thresholds in.

Rates are annual percentages (Decimal("4.79")). Results round half-up to the cent (money)
or basis point (ratios, %).
"""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def monthly_payment(principal: Decimal, annual_rate_pct: Decimal, amortization_years: int) -> Decimal:
    """Blended monthly payment. Canadian fixed-rate mortgages compound semi-annually."""
    months = amortization_years * 12
    if annual_rate_pct == 0:
        return round_cents(principal / months)
    monthly_rate = (1 + annual_rate_pct / HUNDRED / 2) ** (Decimal(1) / 6) - 1
    return round_cents(principal * monthly_rate / (1 - (1 + monthly_rate) ** -months))


def qualifying_rate(contract_rate_pct: Decimal, buffer_pct: Decimal, floor_pct: Decimal) -> Decimal:
    """B-20 stress test: the greater of contract + buffer and the floor."""
    return max(contract_rate_pct + buffer_pct, floor_pct)


def housing_costs(monthly_pi: Decimal, monthly_property_tax: Decimal, monthly_heat: Decimal,
                  monthly_condo_fees: Decimal, condo_fee_share_pct: Decimal) -> Decimal:
    return monthly_pi + monthly_property_tax + monthly_heat + monthly_condo_fees * condo_fee_share_pct / HUNDRED


def _ratio(numerator: Decimal, gross_monthly_income: Decimal) -> Decimal:
    if gross_monthly_income <= 0:
        raise ValueError("gross monthly income must be positive")
    return round_cents(numerator / gross_monthly_income * HUNDRED)


def gds(monthly_housing_costs: Decimal, gross_monthly_income: Decimal) -> Decimal:
    return _ratio(monthly_housing_costs, gross_monthly_income)


def tds(monthly_housing_costs: Decimal, other_monthly_debts: Decimal, gross_monthly_income: Decimal) -> Decimal:
    """other_monthly_debts includes existing-property carrying costs not offset by rent."""
    return _ratio(monthly_housing_costs + other_monthly_debts, gross_monthly_income)


def ltv(loan_amount: Decimal, purchase_price: Decimal, appraised_value: Decimal | None) -> Decimal:
    """Loan-to-value on lending value: the lower of purchase price and appraised value."""
    lending_value = purchase_price if appraised_value is None else min(purchase_price, appraised_value)
    return round_cents(loan_amount / lending_value * HUNDRED)


def min_down_payment(price: Decimal, tiers: list[dict], at_or_above_price: Decimal,
                     pct_at_or_above: Decimal) -> Decimal:
    """Tiered minimum down payment. Each tier's pct applies to the slice of price in [from, to)."""
    if price >= at_or_above_price:
        return round_cents(price * pct_at_or_above / HUNDRED)
    total = Decimal(0)
    for tier in tiers:
        low, high = Decimal(tier["from"]), Decimal(tier["to"])
        if price > low:
            total += (min(price, high) - low) * Decimal(tier["pct"]) / HUNDRED
    return round_cents(total)
