"""Clickable prototype: upload a loan file, let the agent review it, then review and send as the underwriter.

Uploads are real; reading is simulated. Each sample file carries a marker naming its case and filename
(scripts/generate_samples.py), and the agent reviews only the documents that were actually uploaded, so a
partial upload shows up as missing documents. Unmarked files are accepted but reported as not recognized.

State lives in memory per upload batch (prototype only). Every human action is logged and re-runs the agent.

Run: .venv/bin/uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from underwriting import agent, broker, decisions
from underwriting.demo_cases import CASES, REVIEWED, get_case

ROOT = Path(__file__).parent.parent
STATIC = Path(__file__).parent / "static"
SAMPLES = ROOT / "samples"
MARKER = re.compile(rb"UWPROTO\|(case\d+)\|([\w.\-]+)")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = FastAPI(title="Underwriting agent prototype")
app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")
BATCHES: dict[str, dict] = {}

REASON_CODES = ["Source document reviewed", "Agent read the value wrongly", "Explained by other evidence",
                "Not relevant to this file", "Policy allows it", "Other"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _batch(batch_id: str) -> dict:
    if batch_id not in BATCHES:
        raise HTTPException(404, "Unknown upload")
    return BATCHES[batch_id]


def _log(st: dict, who: str, text: str):
    st["audit"].append({"at": _now(), "who": who, "text": text})


def _case_for(st: dict) -> dict:
    """The case restricted to the documents that were uploaded."""
    case = dict(get_case(st["case_id"]))
    case["documents"] = [d for d in case["documents"] if d["filename"] in st["filenames"]]
    return case


def _view(batch_id: str) -> dict:
    st = _batch(batch_id)
    if not st.get("case_id"):
        raise HTTPException(409, "No recognized documents to review")
    result = agent.run(_case_for(st), st["overrides"], st["dismissed"])
    low_conf = [d["id"] for d in result["documents"] if d["confidence"] < agent.LOW_CONFIDENCE]
    requested = {cid for m in st["messages"] for cid in m["condition_ids"]}
    open_flags = [f["id"] for f in result["flags"] if f["id"] not in st["flag_reviews"]
                  and f["check"] not in broker.DOCUMENT_REQUEST_CHECKS]   # those are handled by requesting the document
    unconfirmed = [d for d in low_conf if d not in st["confirmed_docs"] and d not in st["declined_docs"]]
    blockers = ([f"review {len(open_flags)} issue{'s' * (len(open_flags) != 1)}"] if open_flags else []) + \
               ([f"confirm {len(unconfirmed)} hard-to-read document{'s' * (len(unconfirmed) != 1)}"] if unconfirmed else [])
    decision = st["decision"]
    if decision and decision["type"] in ("refer", "hold", "decline", "withdrawn"):
        blockers = []   # these letters don't depend on the review being finished
    review = {
        "flag_reviews": st["flag_reviews"], "condition_reviews": st["condition_reviews"],
        "confirmed_docs": sorted(st["confirmed_docs"]), "declined_docs": sorted(st["declined_docs"]), "overrides": st["overrides"], "audit": st["audit"],
        "approved": st["approved"], "blockers": blockers, "reason_codes": REASON_CODES, "messages": st["messages"],
        "request_draft": None if st["request_sent"] or decision else broker.document_request(result), "decision": decision}
    if decision and not decision.get("sent_at"):
        review["draft"] = broker.decision_message(result, decision, st["condition_reviews"], requested, decisions.DECLINE_REASONS)
    elif not st["approved"] and not decision:
        review["draft"] = broker.review_message(result, st["condition_reviews"], requested)
    else:
        review["draft"] = None
    review["report"] = broker.review_report(result, st["condition_reviews"], requested)
    review["decision_options"] = decisions.options(result, review)
    review["facts"] = decisions.file_facts(result, review)
    return {**result, "batch_id": batch_id, "uploads": st["uploads"], "review": review}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/samples")
def samples():
    """Sample loan files available to drag in (or upload with one click)."""
    out = []
    for c in CASES:
        folder = SAMPLES / c["id"]
        files = sorted(p.name for p in folder.iterdir()) if folder.exists() else []
        app = c["application"]
        out.append({"id": c["id"], "title": c["title"], "summary": c["summary"], "files": files, "pos": c["pos"],
                    "borrowers": [b["name"] for b in app["borrowers"]], "address": app["property"]["address"],
                    "loan_amount": app["loan"]["amount"], "purchase_price": app["property"]["purchase_price"],
                    "closing_date": next((d["fields"]["closing_date"] for d in c["documents"]
                                          if d["type"] == "purchase_agreement"), None),
                    "income_type": "Self-employed" if any(i["type"] == "self_employed" for b in app["borrowers"]
                                                          for i in b["incomes"]) else "Salaried"})
    return out


@app.get("/api/reviewed")
def reviewed():
    """Files sent to the broker in this session, newest first, followed by earlier (dummy) reviews."""
    out = []
    for st in reversed(list(BATCHES.values())):
        if not (st["approved"] or st["decision"]):
            continue
        case = get_case(st["case_id"])
        app_, pos = case["application"], case["pos"]
        started = datetime.fromisoformat(st["audit"][0]["at"])
        sent = datetime.fromisoformat((st["decision"] or st["approved"])["at"])
        out.append({"app_no": pos["app_no"], "source": pos["source"], "borrowers": [b["name"] for b in app_["borrowers"]],
                    "address": app_["property"]["address"],
                    "loan_amount": ((st["decision"] or {}).get("terms") or {}).get("amount") or app_["loan"]["amount"],
                    "broker": pos["broker"], "brokerage": pos["brokerage"],
                    "outcome": decisions.LABELS[st["decision"]["type"]] if st["decision"] else "Conditions sent",
                    "reviewed_by": "You", "turnaround_min": max(1, round((sent - started).total_seconds() / 60)),
                    "reviewed_min_ago": 0})
    return out + REVIEWED


@app.post("/api/uploads")
def new_batch():
    batch_id = f"b{len(BATCHES) + 1:04d}"
    BATCHES[batch_id] = {"uploads": [], "filenames": set(), "case_id": None, "overrides": {}, "dismissed": set(),
                         "flag_reviews": {}, "condition_reviews": {}, "confirmed_docs": set(), "declined_docs": set(), "audit": [],
                         "messages": [], "approved": None, "request_sent": False, "decision": None}
    return {"batch_id": batch_id}


@app.post("/api/uploads/{batch_id}/files")
async def upload(batch_id: str, file: UploadFile):
    st = _batch(batch_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 20 MB")
    match = MARKER.search(data)
    entry = {"filename": file.filename, "size": len(data), "recognized": False, "documents": []}
    if match:
        case_id, filename = match.group(1).decode(), match.group(2).decode()
        try:
            case = get_case(case_id)
        except StopIteration:
            case = None
        docs = [d for d in case["documents"] if d["filename"] == filename] if case else []
        if docs:
            entry.update(recognized=True, case_id=case_id, source_filename=filename,
                         documents=[{"label": d["label"], "type": d["type"], "page": d["page"]} for d in docs])
    st["uploads"].append(entry)
    return entry


@app.post("/api/uploads/{batch_id}/review")
def start_review(batch_id: str):
    st = _batch(batch_id)
    recognized = [u for u in st["uploads"] if u["recognized"]]
    if not recognized:
        raise HTTPException(422, "None of the uploaded files could be read. Use the sample files for this prototype.")
    case_id = Counter(u["case_id"] for u in recognized).most_common(1)[0][0]
    for u in st["uploads"]:
        if u["recognized"] and u["case_id"] != case_id:
            u.update(recognized=False, note="Belongs to a different loan file")
    st.update(case_id=case_id, filenames={u["source_filename"] for u in st["uploads"] if u["recognized"]})
    _log(st, "Agent", f"Received {len(st['uploads'])} files; review started (policy {agent.load_policy().credit['version']})")
    view = _view(batch_id)
    _log(st, "Agent", f"Review ready: {len(view['flags'])} issues, {len(view['conditions'])} draft conditions")
    request = broker.document_request(view)
    if request:   # drafted only; the underwriter decides when it goes
        _log(st, "Agent", f"Drafted document request for the broker ({len(request['condition_ids'])} items)")
    return _view(batch_id)


@app.get("/api/uploads/{batch_id}")
def get_review(batch_id: str):
    return _view(batch_id)


@app.get("/api/uploads/{batch_id}/whatif")
def what_if(batch_id: str, amount: float | None = None, amortization: int | None = None):
    """Ratios for counter-offer terms, without changing the file."""
    st = _batch(batch_id)
    overrides = {**st["overrides"], **({"loan:amount": {"value": amount}} if amount else {}),
                 **({"loan:amortization": {"value": amortization}} if amortization else {})}
    result = agent.run(_case_for(st), overrides, st["dismissed"])
    over = [f["title"] for f in result["flags"] if f["id"].startswith("policy:")]
    r = result["ratios"]
    return {"gds": r["gds_qualifying"], "tds": r["tds_qualifying"], "ltv": r["ltv"], "payment": r["monthly_payment_contract"],
            "within_policy": not over, "over": over}


class Action(BaseModel):
    kind: Literal["flag", "condition", "override", "confirm_doc", "send_request", "approve", "decide"]
    target: str = ""
    action: str = ""  # flag: confirm | reject | escalate | undo; condition: accept | edit | reject | fulfill
    value: str | None = None
    reason: str | None = None
    reasons: list[str] = []          # decide
    note: str | None = None          # decide
    follow_up: str | None = None     # decide: hold
    terms: dict | None = None        # decide: counter_offer {amount, amortization}


@app.post("/api/uploads/{batch_id}/action")
def act(batch_id: str, a: Action):
    st = _batch(batch_id)
    decision_open = st["decision"] and not st["decision"].get("sent_at")
    if a.kind == "decide":
        return _decide(batch_id, st, a)
    if st["approved"] and not (a.kind == "approve" and decision_open):
        raise HTTPException(409, "Already sent to the broker")
    needs_reason = (a.kind == "flag" and a.action == "reject") or a.kind == "override" or \
                   (a.kind == "condition" and a.action in ("edit", "reject"))
    if needs_reason and not a.reason:
        raise HTTPException(422, "A reason is required")

    if a.kind == "flag" and a.action == "undo":
        st["flag_reviews"].pop(a.target, None)
        st["dismissed"].discard(a.target)
        _log(st, "Underwriter", f"Issue {a.target}: review reopened")
    elif a.kind == "flag":
        st["flag_reviews"][a.target] = {"action": a.action, "reason": a.reason}
        if a.action == "reject":
            st["dismissed"].add(a.target)
        else:
            st["dismissed"].discard(a.target)
        _log(st, "Underwriter", f"Issue {a.target}: {a.action}" + (f" ({a.reason})" if a.reason else ""))
    elif a.kind == "condition":
        previous = st["condition_reviews"].get(a.target, {})
        text = a.value if a.action == "edit" else previous.get("text")   # keep an edit when fulfilling or restoring
        st["condition_reviews"][a.target] = {"action": a.action, "text": text, "reason": a.reason}
        _log(st, "Underwriter", f"Condition {a.target}: {a.action}" + (f" ({a.reason})" if a.reason else ""))
    elif a.kind == "override":
        try:
            float(a.value or "")
        except ValueError:
            raise HTTPException(422, "Value must be a number")
        st["overrides"][a.target] = {"value": a.value, "reason": a.reason}
        _log(st, "Underwriter", f"Changed {a.target} to {a.value} ({a.reason}); ratios recalculated")
    elif a.kind == "confirm_doc":   # action: approve (values match) | decline (they don't; clearer copy stays required)
        if a.action == "decline":
            st["declined_docs"].add(a.target)
            st["confirmed_docs"].discard(a.target)
            _log(st, "Underwriter", f"Declined the agent's read of {a.target}; clearer copy required"
                 + (f" ({a.reason})" if a.reason else ""))
        else:
            st["confirmed_docs"].add(a.target)
            st["declined_docs"].discard(a.target)
            _log(st, "Underwriter", f"Approved the agent's read of {a.target} against the source")
    elif a.kind == "send_request":
        request = _view(batch_id)["review"]["request_draft"]
        if not request:
            raise HTTPException(409, "No document request to send")
        st["messages"].append({**request, "at": _now()})
        st["request_sent"] = True
        _log(st, "Underwriter", f"Sent document request to broker ({len(request['condition_ids'])} items)")
    elif a.kind == "approve":   # send the current draft: the decision letter if there is one, else the conditions
        view = _view(batch_id)
        if view["review"]["blockers"]:
            raise HTTPException(409, "Before sending: " + "; ".join(view["review"]["blockers"]))
        if not view["review"]["draft"]:
            raise HTTPException(409, "Nothing to send")
        message = {**view["review"]["draft"], "at": _now()}
        st["request_sent"] = True   # the full message covers any unsent document request
        st["messages"].append(message)
        if decision_open:
            st["decision"]["sent_at"] = message["at"]
        st["approved"] = st["approved"] or {"at": message["at"], "conditions": message["condition_ids"]}
        _log(st, "Underwriter", f"Sent to broker: {message['subject']}")
    return _view(batch_id)


def _decide(batch_id: str, st: dict, a: Action) -> dict:
    """Record (or clear) the underwriter's decision. A counter-offer also restructures the loan for the ratios."""
    if a.action == "clear":
        if st["decision"] and st["decision"].get("sent_at"):
            raise HTTPException(409, "The decision letter has already been sent")
        st["decision"] = None
        st["overrides"].pop("loan:amount", None)
        st["overrides"].pop("loan:amortization", None)
        _log(st, "Underwriter", "Decision cleared")
        return _view(batch_id)
    if st["decision"] and st["decision"].get("sent_at"):
        raise HTTPException(409, "The decision letter has already been sent")
    view = _view(batch_id)
    error = decisions.validate(a.action, a.reasons, a.note, a.follow_up, a.terms, view, view["review"])
    if error:
        raise HTTPException(422, error)
    if a.action == "counter_offer":
        previous = {k: st["overrides"].get(k) for k in ("loan:amount", "loan:amortization")}
        if a.terms.get("amount"):
            st["overrides"]["loan:amount"] = {"value": float(a.terms["amount"]), "reason": "Counter-offer"}
        if a.terms.get("amortization"):
            st["overrides"]["loan:amortization"] = {"value": int(a.terms["amortization"]), "reason": "Counter-offer"}
        over = [f["title"] for f in _view(batch_id)["flags"] if f["id"].startswith("policy:")]
        if over:
            for k, v in previous.items():
                st["overrides"].pop(k, None) if v is None else st["overrides"].__setitem__(k, v)
            raise HTTPException(422, "Counter-offer terms are still outside policy: " + "; ".join(over))
    st["decision"] = {"type": a.action, "label": decisions.LABELS[a.action], "reasons": a.reasons, "note": a.note,
                      "follow_up": a.follow_up, "terms": a.terms, "at": _now(), "by": "You"}
    _log(st, "Underwriter", f"Decision: {decisions.LABELS[a.action]}"
         + (f" ({', '.join(a.reasons)})" if a.reasons else "") + (f". Note: {a.note}" if a.note else ""))
    return _view(batch_id)
