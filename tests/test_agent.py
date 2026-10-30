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


def test_agent_drafts_document_request_but_never_sends_it(client):
    batch, v = upload_case(client, "case06")
    assert v["review"]["messages"] == []
    draft = v["review"]["request_draft"]
    assert "Notice of Assessment" in draft["body"] and "legible copy" in draft["body"]
    assert "2-year" not in draft["body"]  # judgment items wait for the full conditions message
    sent = client.post(f"/api/uploads/{batch}/action", json={"kind": "send_request"}).json()
    [msg] = sent["review"]["messages"]
    assert msg["kind"] == "document_request" and sent["review"]["request_draft"] is None
    assert any("Underwriter" in a["who"] and "document request" in a["text"] for a in sent["review"]["audit"])
    _, clean = upload_case(client, "case01")
    assert clean["review"]["request_draft"] is None


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
        if f["check"] not in ("missing_document", "low_confidence"):  # handled by requesting the document
            act({"kind": "flag", "target": f["id"], "action": "confirm"})
    assert act({"kind": "approve"}).status_code == 409   # blurry statement not confirmed yet
    act({"kind": "confirm_doc", "target": "bank"})
    done = act({"kind": "approve"}).json()
    assert done["review"]["approved"]["conditions"]
    assert done["review"]["messages"][-1]["kind"] == "conditions"
    assert done["review"]["request_draft"] is None  # covered by the conditions message


def test_broker_report_covers_the_review_and_conditions(client):
    _, v = upload_case(client, "case02")
    draft = v["review"]["draft"]
    titles = [sec["title"] for sec in draft["report"]]
    assert titles == ["File summary", "Qualification", "Income used to qualify", "Debts included", "Documents",
                      "Conditions before approval", "Conditions before funding"]
    for text in ("Closing date: Dec 1, 2026", "TDS: 44.91% ✗", "Riverside Auto Credit", "$25,000.00 deposit"):
        assert text in draft["body"]


def test_broker_report_leaves_out_internal_notes(client):
    batch, v = upload_case(client, "case05")
    body = v["review"]["draft"]["body"].lower()
    for internal in ("alteration", "editing", "edited", "hidden", "refer", "recommend", "fraud"):
        assert internal not in body
    # a condition the underwriter removes disappears from the report
    cid = next(c["id"] for c in v["conditions"] if c["raised_by"])
    after = client.post(f"/api/uploads/{batch}/action", json={"kind": "condition", "target": cid, "action": "reject",
                                                               "reason": "Not relevant to this file"}).json()
    assert cid not in after["review"]["draft"]["condition_ids"]


def test_messages_are_addressed_to_the_submitting_broker(client):
    _, v = upload_case(client, "case06")
    for m in (v["review"]["request_draft"], v["review"]["draft"]):
        assert m["to"] == "Simone Tremblay <s.tremblay@keystone-home.example>"
        assert m["body"].startswith("Hello Simone,")
    samples = client.get("/api/samples").json()
    assert all(s["pos"]["app_no"].startswith("MR-") for s in samples)


def test_fulfilled_condition_moves_to_satisfied_in_the_report(client):
    batch, v = upload_case(client, "case02")
    cid = next(c["id"] for c in v["conditions"] if c["raised_by"] == "large_deposit")
    after = client.post(f"/api/uploads/{batch}/action", json={"kind": "condition", "target": cid, "action": "fulfill"}).json()
    sections = {s["title"]: s for s in after["review"]["draft"]["report"]}
    assert cid in [i["id"] for i in sections["Conditions satisfied"]["items"]]
    assert cid not in [i["id"] for i in sections["Conditions before approval"]["items"]]
    assert "CONDITIONS SATISFIED" in after["review"]["draft"]["body"]


def test_sent_file_appears_first_in_reviewed_list(client):
    batch, v = upload_case(client, "case01")
    for f in v["flags"]:
        client.post(f"/api/uploads/{batch}/action", json={"kind": "flag", "target": f["id"], "action": "confirm"})
    client.post(f"/api/uploads/{batch}/action", json={"kind": "approve"})
    reviewed = client.get("/api/reviewed").json()
    assert reviewed[0]["app_no"] == "MR-26-10412" and reviewed[0]["reviewed_by"] == "You"
    assert {r["source"] for r in reviewed} <= {"Filogix", "Lendesk", "Velocity"}
