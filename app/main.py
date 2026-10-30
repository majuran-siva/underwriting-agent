"""Clickable prototype: run the agent on a synthetic file, then review, edit and approve as the underwriter.

Review state lives in memory per case (prototype only). Every human action is appended to the audit log and
re-runs the agent so ratios, conditions and the recommendation reflect the underwriter's edits.

Run: .venv/bin/uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from underwriting import agent
from underwriting.demo_cases import CASES, get_case

app = FastAPI(title="Underwriting agent prototype")
STATIC = Path(__file__).parent / "static"
STATE: dict[str, dict] = {}

REASON_CODES = ["Source document reviewed", "Agent read the value wrongly", "Explained by other evidence",
                "Not relevant to this file", "Policy allows it", "Other"]


def _new_state() -> dict:
    return {"overrides": {}, "dismissed": set(), "flag_reviews": {}, "condition_reviews": {}, "confirmed_docs": set(),
            "audit": [], "approved": None, "started": None}


def _state(case_id: str) -> dict:
    try:
        get_case(case_id)
    except StopIteration:
        raise HTTPException(404, "Unknown case")
    return STATE.setdefault(case_id, _new_state())


def _log(st: dict, who: str, text: str):
    st["audit"].append({"at": datetime.now().isoformat(timespec="seconds"), "who": who, "text": text})


def _view(case_id: str) -> dict:
    st = _state(case_id)
    result = agent.run(get_case(case_id), st["overrides"], st["dismissed"])
    low_conf = [d["id"] for d in result["documents"] if d["confidence"] < agent.LOW_CONFIDENCE]
    open_flags = [f["id"] for f in result["flags"] if f["id"] not in st["flag_reviews"]]
    unconfirmed = [d for d in low_conf if d not in st["confirmed_docs"]]
    blockers = ([f"{len(open_flags)} flag(s) not reviewed"] if open_flags else []) + \
               ([f"{len(unconfirmed)} low-confidence document(s) not confirmed"] if unconfirmed else [])
    return {**result, "review": {
        "flag_reviews": st["flag_reviews"], "condition_reviews": st["condition_reviews"],
        "confirmed_docs": sorted(st["confirmed_docs"]), "overrides": st["overrides"], "audit": st["audit"],
        "approved": st["approved"], "blockers": blockers, "reason_codes": REASON_CODES}}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/cases")
def cases():
    return [{"id": c["id"], "title": c["title"], "summary": c["summary"], "files": len({d["filename"] for d in c["documents"]})}
            for c in CASES]


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str):
    STATE[case_id] = _new_state()
    st = _state(case_id)
    st["started"] = datetime.now().isoformat(timespec="seconds")
    _log(st, "Agent", f"Run started on submission; policy {agent.load_policy().credit['version']}")
    view = _view(case_id)
    _log(st, "Agent", f"Package ready: {len(view['flags'])} flags, {len(view['conditions'])} draft conditions, "
                      f"recommendation {view['recommendation']}")
    return _view(case_id)


@app.get("/api/cases/{case_id}")
def get_review(case_id: str):
    return _view(case_id)


class Action(BaseModel):
    kind: Literal["flag", "condition", "override", "confirm_doc", "approve"]
    target: str = ""
    action: str = ""  # flag: confirm | reject | escalate; condition: accept | edit | reject
    value: str | None = None
    reason: str | None = None


@app.post("/api/cases/{case_id}/action")
def act(case_id: str, a: Action):
    st = _state(case_id)
    if st["approved"]:
        raise HTTPException(409, "Conditions already approved")
    needs_reason = (a.kind == "flag" and a.action == "reject") or a.kind == "override" or \
                   (a.kind == "condition" and a.action in ("edit", "reject"))
    if needs_reason and not a.reason:
        raise HTTPException(422, "A reason is required")

    if a.kind == "flag" and a.action == "undo":
        st["flag_reviews"].pop(a.target, None)
        st["dismissed"].discard(a.target)
        _log(st, "Underwriter", f"Flag {a.target}: review reopened")
    elif a.kind == "flag":
        st["flag_reviews"][a.target] = {"action": a.action, "reason": a.reason}
        if a.action == "reject":
            st["dismissed"].add(a.target)
        else:
            st["dismissed"].discard(a.target)
        _log(st, "Underwriter", f"Flag {a.target}: {a.action}" + (f" ({a.reason})" if a.reason else ""))
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
        _log(st, "Underwriter", f"Confirmed low-confidence values in {a.target} against the source")
    elif a.kind == "approve":
        view = _view(case_id)
        if view["review"]["blockers"]:
            raise HTTPException(409, "Cannot approve: " + "; ".join(view["review"]["blockers"]))
        sent = [c["id"] for c in view["conditions"]
                if st["condition_reviews"].get(c["id"], {}).get("action") != "reject"]
        st["approved"] = {"at": datetime.now().isoformat(timespec="seconds"), "conditions": sent}
        _log(st, "Underwriter", f"Approved conditions list ({len(sent)} conditions) for sending to the broker")
    return _view(case_id)
