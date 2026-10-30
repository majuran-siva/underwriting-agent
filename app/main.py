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

from underwriting import agent, broker
from underwriting.demo_cases import CASES, get_case

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
    unconfirmed = [d for d in low_conf if d not in st["confirmed_docs"]]
    blockers = ([f"review {len(open_flags)} issue{'s' * (len(open_flags) != 1)}"] if open_flags else []) + \
               ([f"confirm {len(unconfirmed)} hard-to-read document{'s' * (len(unconfirmed) != 1)}"] if unconfirmed else [])
    return {**result, "batch_id": batch_id, "uploads": st["uploads"], "review": {
        "flag_reviews": st["flag_reviews"], "condition_reviews": st["condition_reviews"],
        "confirmed_docs": sorted(st["confirmed_docs"]), "overrides": st["overrides"], "audit": st["audit"],
        "approved": st["approved"], "blockers": blockers, "reason_codes": REASON_CODES,
        "messages": st["messages"], "draft": broker.review_message(result, st["condition_reviews"], requested),
        "request_draft": None if st["request_sent"] else broker.document_request(result)}}


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
        out.append({"id": c["id"], "title": c["title"], "summary": c["summary"], "files": files})
    return out


@app.post("/api/uploads")
def new_batch():
    batch_id = f"b{len(BATCHES) + 1:04d}"
    BATCHES[batch_id] = {"uploads": [], "filenames": set(), "case_id": None, "overrides": {}, "dismissed": set(),
                         "flag_reviews": {}, "condition_reviews": {}, "confirmed_docs": set(), "audit": [],
                         "messages": [], "approved": None, "request_sent": False}
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


class Action(BaseModel):
    kind: Literal["flag", "condition", "override", "confirm_doc", "send_request", "approve"]
    target: str = ""
    action: str = ""  # flag: confirm | reject | escalate | undo; condition: accept | edit | reject
    value: str | None = None
    reason: str | None = None


@app.post("/api/uploads/{batch_id}/action")
def act(batch_id: str, a: Action):
    st = _batch(batch_id)
    if st["approved"]:
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
        st["condition_reviews"][a.target] = {"action": a.action, "text": a.value, "reason": a.reason}
        _log(st, "Underwriter", f"Condition {a.target}: {a.action}" + (f" ({a.reason})" if a.reason else ""))
    elif a.kind == "override":
        try:
            float(a.value or "")
        except ValueError:
            raise HTTPException(422, "Value must be a number")
        st["overrides"][a.target] = {"value": a.value, "reason": a.reason}
        _log(st, "Underwriter", f"Changed {a.target} to {a.value} ({a.reason}); ratios recalculated")
    elif a.kind == "confirm_doc":
        st["confirmed_docs"].add(a.target)
        _log(st, "Underwriter", f"Confirmed hard-to-read document {a.target} against the source")
    elif a.kind == "send_request":
        request = _view(batch_id)["review"]["request_draft"]
        if not request:
            raise HTTPException(409, "No document request to send")
        st["messages"].append({**request, "at": _now()})
        st["request_sent"] = True
        _log(st, "Underwriter", f"Sent document request to broker ({len(request['condition_ids'])} items)")
    elif a.kind == "approve":
        view = _view(batch_id)
        if view["review"]["blockers"]:
            raise HTTPException(409, "Before sending: " + "; ".join(view["review"]["blockers"]))
        message = {**view["review"]["draft"], "at": _now()}
        st["request_sent"] = True   # the conditions message covers any unsent document request
        st["messages"].append(message)
        st["approved"] = {"at": message["at"], "conditions": message["condition_ids"]}
        _log(st, "Underwriter", f"Approved and sent conditions to broker ({len(message['condition_ids'])} conditions)")
    return _view(batch_id)
