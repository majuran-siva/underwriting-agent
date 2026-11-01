"""Prototype agent against the synthetic case library: each planted issue is caught, nothing is invented."""
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from underwriting import evals
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


def test_one_email_covers_missing_documents_and_is_never_sent_by_the_agent(client):
    batch, v = upload_case(client, "case06")
    assert v["review"]["messages"] == []
    assert "request_draft" not in v["review"]
    body = v["review"]["draft"]["body"]
    assert "Notice of Assessment" in body and "legible copy" in body
    assert client.post(f"/api/uploads/{batch}/action", json={"kind": "send_request"}).status_code == 422


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
        if f["check"] not in ("missing_document", "low_confidence"):  # go to the broker as conditions
            act({"kind": "flag", "target": f["id"], "action": "confirm"})
    assert act({"kind": "approve"}).status_code == 409   # blurry statement not confirmed yet
    act({"kind": "confirm_doc", "target": "bank"})
    done = act({"kind": "approve"}).json()
    assert done["review"]["approved"]["conditions"]
    assert done["review"]["messages"][-1]["kind"] == "conditions"


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
    m = v["review"]["draft"]
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


def test_declining_a_document_read_unblocks_sending_but_keeps_it_flagged(client):
    batch, v = upload_case(client, "case06")
    act = lambda body: client.post(f"/api/uploads/{batch}/action", json=body)
    for f in v["flags"]:
        if f["check"] not in ("missing_document", "low_confidence"):
            act({"kind": "flag", "target": f["id"], "action": "confirm"})
    r = act({"kind": "confirm_doc", "target": "bank", "action": "decline", "reason": "Amounts illegible"}).json()
    assert r["review"]["declined_docs"] == ["bank"] and r["review"]["blockers"] == []
    assert any("legible copy" in c["text"] for c in r["conditions"])


def decide(client, batch, decision, **extra):
    return client.post(f"/api/uploads/{batch}/action", json={"kind": "decide", "action": decision, **extra})


def test_critical_flag_blocks_approval_and_suggests_referral(client):
    batch, v = upload_case(client, "case05")
    opts = {o["id"]: o for o in v["review"]["decision_options"]}
    assert not opts["approve_conditions"]["allowed"] and "fraud" in opts["approve_conditions"]["blocked"][0]
    assert opts["refer"]["suggested"] and opts["decline"]["allowed"]
    assert decide(client, batch, "approve_conditions").status_code == 422


def test_clean_file_can_be_approved_and_letter_sent(client):
    batch, v = upload_case(client, "case01")
    r = decide(client, batch, "approve").json()
    assert r["review"]["decision"]["label"] == "Approve"
    assert r["review"]["draft"]["subject"].endswith("commitment") and "approved" in r["review"]["draft"]["body"]
    sent = client.post(f"/api/uploads/{batch}/action", json={"kind": "approve"}).json()
    assert sent["review"]["decision"]["sent_at"] and sent["review"]["draft"] is None
    assert client.get("/api/reviewed").json()[0]["outcome"] == "Approve"


def test_decline_needs_reasons_and_letter_hides_fraud(client):
    batch, _ = upload_case(client, "case05")
    assert decide(client, batch, "decline").status_code == 422
    r = decide(client, batch, "decline", reasons=["Suspected misrepresentation"]).json()
    body = r["review"]["draft"]["body"].lower()
    assert "unable to verify information" in body and "fraud" not in body and "misrepresentation" not in body


def test_counter_offer_is_not_a_decision_option(client):
    batch, v = upload_case(client, "case03")
    assert all(o["id"] != "counter_offer" for o in v["review"]["decision_options"])
    assert decide(client, batch, "counter_offer").status_code == 422


def test_hold_needs_follow_up_and_decision_can_be_cleared(client):
    batch, _ = upload_case(client, "case06")
    assert decide(client, batch, "hold", reasons=["Waiting on documents"]).status_code == 422
    r = decide(client, batch, "hold", reasons=["Waiting on documents"], follow_up="2026-11-06").json()
    assert "on hold" in r["review"]["draft"]["subject"]
    cleared = decide(client, batch, "clear").json()
    assert cleared["review"]["decision"] is None


def test_eval_passes_on_every_inbox_file():
    report = evals.run_all()
    failed = [c for f in report["files"] for c in f["checks"] if not c["passed"]]
    assert report["files_total"] == 6
    assert failed == []


def test_eval_fails_when_the_answer_differs():
    wrong = {**evals.EXPECTED["case05"], "recommendation": "approve", "issues": []}
    result = evals.run_case(get_case("case05"), wrong)
    assert result["passed"] is False
    assert {c["name"] for c in result["checks"] if not c["passed"]} == {"Recommendation", "Issues found, none invented"}


def test_eval_endpoint():
    client = TestClient(app)
    assert client.get("/api/eval").json()["files_passed"] == 6


def _batch_for(client, case_id):
    batch = client.post("/api/uploads").json()["batch_id"]
    folder = Path(__file__).parent.parent / "samples" / case_id
    for path in folder.iterdir():
        client.post(f"/api/uploads/{batch}/files", files={"file": (path.name, path.read_bytes())})
    client.post(f"/api/uploads/{batch}/review")
    return batch


def test_underwriter_can_edit_the_email_and_the_edit_is_what_gets_sent():
    client = TestClient(app)
    batch = _batch_for(client, "case01")
    act = lambda **body: client.post(f"/api/uploads/{batch}/action", json=body)
    kind = client.get(f"/api/uploads/{batch}").json()["review"]["draft"]["kind"]
    assert act(kind="edit_message", target=kind, action="save", value="", note="Hi").status_code == 422
    v = act(kind="edit_message", target=kind, action="save", value="Please call me.", note="Quick note").json()
    assert v["review"]["draft"]["body"] == "Please call me." and v["review"]["draft"]["edited"]
    assert "Edited" in v["review"]["audit"][-1]["text"]
    v = act(kind="edit_message", target=kind, action="reset").json()
    assert v["review"]["draft"]["body"] != "Please call me."
    act(kind="edit_message", target=kind, action="save", value="Please call me.", note="Quick note")
    sent = act(kind="approve").json()["review"]["messages"][-1]
    assert sent["body"] == "Please call me." and sent["subject"] == "Quick note"


def test_primary_demo_file_reports_the_missing_employment_letter():
    r = run(get_case("case03"))
    assert "missing:employment_letter:Hannah Lefebvre" in {f["id"] for f in r["flags"]}
    assert any("employment" in c["text"].lower() for c in r["conditions"])
    assert "low_confidence:id1" in {f["id"] for f in r["flags"]}
    assert any("legible copy" in c["text"] for c in r["conditions"])
    assert r["ratios"]["tds_qualifying"] == "45.65"


def test_every_eval_case_has_a_label_and_expected_behaviour(client):
    assert all("tag" not in sample for sample in client.get("/api/samples").json())  # eval page only
    report = evals.run_all()
    assert all(f["tag"] and f["should"] and f["passes_if"] for f in report["files"])
    assert {f["tag"] for f in report["files"]} >= {"Happy path", "Happy path with issues", "Boundary: must refuse"}
