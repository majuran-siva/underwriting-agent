"""Messages to the broker. Prototype only: they go to a simulated inbox, never to a real address.

Rule: the agent may send plain document requests on its own (missing or unreadable documents carry no
credit judgment). Everything else — income, debts, deposits, possible alteration, policy — goes out only
when the underwriter approves the full message.
"""
from __future__ import annotations

from underwriting.demo_cases import LENDER

AUTO_SEND_CHECKS = {"missing_document", "low_confidence"}


def _salutation(view: dict) -> str:
    names = " & ".join(b["name"] for b in view["application"]["borrowers"])
    return f"Re: {names} – {view['application']['property']['address']}"


def document_request(view: dict) -> dict | None:
    """The message the agent sends by itself as soon as the file is read, or None if nothing is missing."""
    items = [c for c in view["conditions"] if c["raised_by"] in AUTO_SEND_CHECKS]
    if not items:
        return None
    body = ["Hello,", "",
            f"We've started our review. To keep it moving, please send the following:", ""]
    body += [f"• {c['text']}" for c in items]
    body += ["", "Our underwriter will follow up with the full review shortly.", "", f"{LENDER} – Underwriting"]
    return {"subject": _salutation(view) + " – documents needed", "from": "Agent (automatic)",
            "body": "\n".join(body), "condition_ids": [c["id"] for c in items]}


def review_message(view: dict, condition_reviews: dict, already_requested: set[str]) -> dict:
    """The full conditions message the agent drafts for the underwriter to approve and send."""
    outstanding, standard = [], []
    for c in view["conditions"]:
        review = condition_reviews.get(c["id"], {})
        if review.get("action") == "reject":
            continue
        text = review.get("text") if review.get("action") == "edit" else c["text"]
        (standard if c["raised_by"] is None else outstanding).append((c["id"], text))

    lines = ["Hello,", "", "We've completed our first review of this file."]
    if outstanding:
        lines += ["", "Before we can proceed, we need:"]
        lines += [f"• {text}" + (" (requested earlier)" if cid in already_requested else "") for cid, text in outstanding]
    else:
        lines += ["", "No further documents are needed at this stage."]
    if standard:
        lines += ["", "Standard conditions before funding:"] + [f"• {text}" for _, text in standard]
    lines += ["", "Please reply with any questions.", "", f"{LENDER} – Underwriting"]
    return {"subject": _salutation(view) + " – conditions", "from": "Underwriter (approved)",
            "body": "\n".join(lines), "condition_ids": [cid for cid, _ in outstanding + standard]}
