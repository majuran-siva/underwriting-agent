"""Underwriter decisions: what can be decided on a file right now, and why not.

The agent never decides. It recommends; these rules only stop a decision that the file doesn't support yet
(for example approving with an open fraud signal or a ratio over policy). Every decision is made by a person.
"""
from __future__ import annotations

from underwriting.broker import DOCUMENT_REQUEST_CHECKS

DECISIONS = [
    {"id": "approve", "label": "Approve", "tone": "good",
     "desc": "Issue a commitment with standard conditions only."},
    {"id": "approve_conditions", "label": "Approve with conditions", "tone": "good",
     "desc": "Issue a commitment; outstanding conditions must be met before funding."},
    {"id": "refer", "label": "Refer to senior", "tone": "attn",
     "desc": "Send to a senior underwriter or credit committee: exception, authority limit or concern."},
    {"id": "hold", "label": "Hold", "tone": "attn",
     "desc": "Pause the file while waiting on documents or information."},
    {"id": "decline", "label": "Decline", "tone": "bad",
     "desc": "The file doesn't meet policy. Reasons are required."},
    {"id": "withdrawn", "label": "Withdrawn", "tone": "muted",
     "desc": "The broker or borrower withdrew the application."},
]
LABELS = {d["id"]: d["label"] for d in DECISIONS}

# Internal reason → wording safe to send to the broker (never mention suspected fraud).
DECLINE_REASONS = {
    "Debt service ratios over policy": "Debt service ratios exceed our lending guidelines.",
    "Income could not be verified": "We were unable to verify the income provided.",
    "Credit history": "The credit history does not meet our lending guidelines.",
    "Insufficient down payment or funds": "The down payment or closing funds could not be confirmed.",
    "Property not acceptable": "The property does not meet our lending guidelines.",
    "Suspected misrepresentation": "We were unable to verify information provided in the application.",
    "Other": "The application does not meet our lending guidelines.",
}
REFER_REASONS = ["Policy exception needed", "Over my approval limit", "Possible misrepresentation", "Complex income",
                 "Other"]
HOLD_REASONS = ["Waiting on documents", "Waiting on appraisal", "Waiting on borrower explanation", "Other"]
WITHDRAWN_REASONS = ["Broker withdrew", "Borrower chose another lender", "Purchase fell through", "Other"]
REASONS = {"decline": list(DECLINE_REASONS), "refer": REFER_REASONS, "hold": HOLD_REASONS, "withdrawn": WITHDRAWN_REASONS}

SUGGESTED = {"approve": "approve", "approve_with_conditions": "approve_conditions", "refer_for_review": "refer",
             "decline": "decline"}


def file_facts(view: dict, review: dict) -> dict:
    """What the decision rules look at, also shown to the underwriter as a checklist."""
    flags = [f for f in view["flags"] if not f["dismissed"]]
    issues = [f for f in flags if f["check"] not in DOCUMENT_REQUEST_CHECKS]
    reviewed = review["flag_reviews"]
    low_conf = [d["id"] for d in view["documents"] if d["confidence"] < 0.8]
    cond = review["condition_reviews"]
    outstanding = [c for c in view["conditions"] if c["raised_by"]
                   and cond.get(c["id"], {}).get("action") not in ("fulfill", "reject")]
    return {
        "open_issues": len([f for f in issues if f["id"] not in reviewed]),
        "critical": len([f for f in flags if f["area"] == "authenticity"]),
        "over_policy": len([f for f in flags if f["id"].startswith("policy:")]),
        "unconfirmed_docs": len([d for d in low_conf if d not in review["confirmed_docs"] and d not in review["declined_docs"]]),
        "outstanding": len(outstanding),
        "conditions_sent": bool(review.get("approved")),
    }


def options(view: dict, review: dict) -> list[dict]:
    f = file_facts(view, review)
    suggested = SUGGESTED.get(view["recommendation"])
    if f["critical"]:
        suggested = "refer"
    out = []
    for d in DECISIONS:
        blocked = []
        if d["id"] in ("approve", "approve_conditions"):
            if f["critical"]:
                blocked.append("possible fraud is still on the file (refer or decline)")
            if f["open_issues"]:
                blocked.append(f"{f['open_issues']} issue{'s' * (f['open_issues'] != 1)} not reviewed")
            if f["unconfirmed_docs"]:
                blocked.append("hard-to-read document not checked")
        if d["id"] in ("approve", "approve_conditions") and f["over_policy"]:
            blocked.append("a ratio is over policy (refer or decline)")
        if d["id"] == "approve" and f["outstanding"]:
            blocked.append(f"{f['outstanding']} condition{'s' * (f['outstanding'] != 1)} outstanding (use Approve with conditions)")
        out.append({**d, "allowed": not blocked, "blocked": blocked, "suggested": d["id"] == suggested,
                    "reasons": REASONS.get(d["id"], [])})
    return out


def validate(decision: str, reasons: list[str], note: str | None, follow_up: str | None,
             view: dict, review: dict) -> str | None:
    """Returns an error message, or None if the decision can be recorded."""
    option = next((o for o in options(view, review) if o["id"] == decision), None)
    if option is None:
        return "Unknown decision"
    if not option["allowed"]:
        return f"{option['label']} isn't available: " + "; ".join(option["blocked"])
    if decision in REASONS and not reasons:
        return "Choose at least one reason"
    if decision == "refer" and not (note or "").strip():
        return "Add a note for the senior underwriter"
    if decision == "hold" and not follow_up:
        return "Set a follow-up date"
    return None
