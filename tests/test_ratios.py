"""Expected values computed independently (float math, Canadian semi-annual compounding)
and rounded to the cent / basis point."""
from decimal import Decimal as D

import pytest

from underwriting.ratios import (
    gds, housing_costs, ltv, min_down_payment, monthly_payment, qualifying_rate, tds,
)

TIERS = [{"from": 0, "to": 500000, "pct": 5}, {"from": 500000, "to": 1500000, "pct": 10}]


@pytest.mark.parametrize("principal,rate,years,expected", [
    (D("480000"), D("4.79"), 25, D("2734.60")),
    (D("480000"), D("6.79"), 25, D("3299.99")),
    (D("400000"), D("3.00"), 30, D("1682.41")),
])
def test_monthly_payment_semi_annual_compounding(principal, rate, years, expected):
    assert monthly_payment(principal, rate, years) == expected


def test_zero_rate_payment_is_straight_line():
    assert monthly_payment(D("300000"), D("0"), 25) == D("1000.00")


@pytest.mark.parametrize("contract,expected", [
    (D("4.79"), D("6.79")),   # contract + 2 wins
    (D("3.00"), D("5.25")),   # floor wins
    (D("3.25"), D("5.25")),   # exactly at the floor
])
def test_qualifying_rate(contract, expected):
    assert qualifying_rate(contract, buffer_pct=D("2"), floor_pct=D("5.25")) == expected


def test_housing_costs_include_half_condo_fees():
    assert housing_costs(D("3299.99"), monthly_property_tax=D("350"), monthly_heat=D("100"),
                         monthly_condo_fees=D("400"), condo_fee_share_pct=D("50")) == D("3949.99")


def test_gds_and_tds():
    income = D("95000") / 12
    housing = housing_costs(D("3299.99"), D("350"), D("100"), D("0"), D("50"))
    assert gds(housing, income) == D("47.37")
    assert tds(housing, other_monthly_debts=D("400"), gross_monthly_income=income) == D("52.42")


def test_ratio_with_zero_income_raises():
    with pytest.raises(ValueError):
        gds(D("1000"), D("0"))


@pytest.mark.parametrize("price,appraised,expected", [
    (D("600000"), D("600000"), D("80.00")),
    (D("600000"), D("590000"), D("81.36")),   # lending value = lower of price and appraisal
    (D("600000"), None, D("80.00")),
])
def test_ltv_uses_lending_value(price, appraised, expected):
    assert ltv(D("480000"), price, appraised) == expected


@pytest.mark.parametrize("price,expected", [
    (D("400000"), D("20000.00")),
    (D("500000"), D("25000.00")),
    (D("600000"), D("35000.00")),
    (D("1499999"), D("124999.90")),
    (D("1500000"), D("300000.00")),           # 20% at or above $1.5M
])
def test_min_down_payment_tiers(price, expected):
    assert min_down_payment(price, TIERS, at_or_above_price=D("1500000"), pct_at_or_above=D("20")) == expected
