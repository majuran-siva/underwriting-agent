"""Prototype agent against the synthetic case library: each planted issue is caught, nothing is invented."""
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.main import app
from underwriting.agent import run
from underwriting.demo_cases import get_case


def checks(result):
    return {f["check"] for f in result["flags"]}


def test_clean_file_has_no_flags_and_only_standard_conditions():
    r = run(get_case("case01"))
    assert r["flags"] == []
    assert r["recommendation"] == "approve"
    assert all(c["raised_by"] is None for c in r["conditions"])


def test_self_employed_deposit_and_undisclosed_debt_are_caught():
    r = run(get_case("case02"))
    assert {"large_deposit", "undisclosed_debt", "tds_limit"} <= checks(r)
    debt = next(f for f in r["flags"] if f["check"] == "undisclosed_debt")
    assert any(e["field"] == "withdrawals" for e in debt["evidence"])  # corroborated by the bank statement
    assert r["recommendation"] == "refer_for_review"
    assert any("$25,000.00 deposit" in c["text"] for c in r["conditions"])


def test_undisclosed_debt_pushes_tds_over_limit():
    r = run(get_case("case03"))
    assert D(r["ratios"]["tds_qualifying"]) > 44
    assert "undisclosed_debt" in checks(r)


def test_income_mismatch_shows_all_sources_and_does_not_pick_one():
    r = run(get_case("case04"))
    flag = next(f for f in r["flags"] if f["check"] == "income_mismatch")
    assert len(flag["evidence"]) == 3
    assert r["inputs"][0]["value"] == "95000"  # ratios stay on stated income
    assert r["comparison"] and D(r["comparison"]["tds"]) > D(r["ratios"]["tds_qualifying"])


def test_altered_paystub_and_hidden_instruction_are_flagged_not_obeyed():
    r = run(get_case("case05"))
    assert {"paystub_ytd", "pdf_edited", "hidden_instruction"} <= checks(r)
    assert r["recommendation"] == "refer_for_review"
    assert not any("fraud" in f["title"].lower() for f in r["flags"])  # neutral wording, no accusation


def test_missing_and_unreadable_documents_become_conditions():
    r = run(get_case("case06"))
    assert {"missing_document", "low_confidence"} <= checks(r)
    assert any("Notice of Assessment" in c["text"] for c in r["conditions"])
    assert any("legible copy" in c["text"] for c in r["conditions"])


def test_same_inputs_give_same_output():
    assert run(get_case("case02")) == run(get_case("case02"))


def test_rejecting_undisclosed_debt_flag_removes_it_from_tds():
    before = run(get_case("case03"))
    after = run(get_case("case03"), dismissed={"undisclosed_debt:Summit Auto Lease"})
    assert D(after["ratios"]["tds_qualifying"]) < D(before["ratios"]["tds_qualifying"])


@pytest.fixture
def client():
    return TestClient(app)


def test_override_recalculates_and_persists(client):
    client.post("/api/cases/case06/run")
    r = client.post("/api/cases/case06/action", json={"kind": "override", "target": "rent:0", "value": "1800",
                                                      "reason": "Source document reviewed"}).json()
    assert next(i for i in r["inputs"] if i["key"] == "rent:0")["value"] == "1800"
    again = client.get("/api/cases/case06").json()
    assert next(i for i in again["inputs"] if i["key"] == "rent:0")["value"] == "1800"
    assert any("rent:0" in a["text"] for a in again["review"]["audit"])


def test_override_requires_reason(client):
    client.post("/api/cases/case01/run")
    resp = client.post("/api/cases/case01/action", json={"kind": "override", "target": "income:0:0", "value": "1"})
    assert resp.status_code == 422


def test_approval_blocked_until_flags_and_low_confidence_reviewed(client):
    v = client.post("/api/cases/case06/run").json()
    assert client.post("/api/cases/case06/action", json={"kind": "approve"}).status_code == 409
    for f in v["flags"]:
        client.post("/api/cases/case06/action", json={"kind": "flag", "target": f["id"], "action": "confirm"})
    assert client.post("/api/cases/case06/action", json={"kind": "approve"}).status_code == 409
    client.post("/api/cases/case06/action", json={"kind": "confirm_doc", "target": "bank"})
    done = client.post("/api/cases/case06/action", json={"kind": "approve"}).json()
    assert done["review"]["approved"]["conditions"]
