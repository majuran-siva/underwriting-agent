"""Prototype agent against the synthetic case library: each planted issue is caught, nothing is invented."""
from decimal import Decimal as D
from pathlib import Path

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


SAMPLES = Path(__file__).parent.parent / "samples"


def upload_case(client, case_id, skip=()):
    batch = client.post("/api/uploads").json()["batch_id"]
    for f in sorted((SAMPLES / case_id).iterdir()):
        if f.name not in skip:
            client.post(f"/api/uploads/{batch}/files", files={"file": (f.name, f.read_bytes())})
    return batch, client.post(f"/api/uploads/{batch}/review").json()


def test_uploaded_sample_files_are_recognized(client):
    batch, v = upload_case(client, "case01")
    assert all(u["recognized"] for u in v["uploads"])
    assert v["recommendation"] == "approve"


def test_unrecognized_file_is_reported_not_read(client):
    batch = client.post("/api/uploads").json()["batch_id"]
    r = client.post(f"/api/uploads/{batch}/files", files={"file": ("my_paystub.pdf", b"%PDF-1.4 real file")}).json()
    assert r["recognized"] is False
    assert client.post(f"/api/uploads/{batch}/review").status_code == 422


def test_files_not_uploaded_show_as_missing(client):
    _, v = upload_case(client, "case01", skip={"scan001.pdf"})  # Priya's pay stub
    assert any(f["check"] == "missing_document" and "pay stub" in f["title"] for f in v["flags"])


def test_agent_sends_only_document_requests_by_itself(client):
    _, v = upload_case(client, "case06")
    [msg] = v["review"]["messages"]
    assert msg["from"].startswith("Agent")
    assert "Notice of Assessment" in msg["body"] and "legible copy" in msg["body"]
    assert "2-year" not in msg["body"]  # judgment items wait for the underwriter
    _, clean = upload_case(client, "case01")
    assert clean["review"]["messages"] == []


def test_override_recalculates_and_persists(client):
    batch, _ = upload_case(client, "case06")
    r = client.post(f"/api/uploads/{batch}/action", json={"kind": "override", "target": "rent:0", "value": "1800",
                                                           "reason": "Source document reviewed"}).json()
    assert next(i for i in r["inputs"] if i["key"] == "rent:0")["value"] == "1800"
    again = client.get(f"/api/uploads/{batch}").json()
    assert next(i for i in again["inputs"] if i["key"] == "rent:0")["value"] == "1800"
    assert any("rent:0" in a["text"] for a in again["review"]["audit"])


def test_override_requires_reason(client):
    batch, _ = upload_case(client, "case01")
    resp = client.post(f"/api/uploads/{batch}/action", json={"kind": "override", "target": "income:0:0", "value": "1"})
    assert resp.status_code == 422


def test_sending_blocked_until_issues_reviewed_and_documents_confirmed(client):
    batch, v = upload_case(client, "case06")
    act = lambda body: client.post(f"/api/uploads/{batch}/action", json=body)
    assert act({"kind": "approve"}).status_code == 409
    for f in v["flags"]:
        if f["check"] not in ("missing_document", "low_confidence"):  # already requested from the broker
            act({"kind": "flag", "target": f["id"], "action": "confirm"})
    assert act({"kind": "approve"}).status_code == 409   # blurry statement not confirmed yet
    act({"kind": "confirm_doc", "target": "bank"})
    done = act({"kind": "approve"}).json()
    assert done["review"]["approved"]["conditions"]
    assert done["review"]["messages"][-1]["from"].startswith("Underwriter")
