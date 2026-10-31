"""Messages to the broker. Prototype only: they go to a simulated inbox, never to a real address.

Rule: the agent drafts, the underwriter sends. As soon as the file is read the agent drafts a plain
document request (missing or unreadable documents) so it can go out early; the full conditions message
follows once the underwriter has reviewed the issues. Nothing is sent without the underwriter clicking Send.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from underwriting.demo_cases import LENDER

DOCUMENT_REQUEST_CHECKS = {"missing_document", "low_confidence"}


def _addresses(view: dict) -> dict:
    pos = view.get("pos") or {}
    return {"to": f"{pos.get('broker', 'Broker')} <{pos.get('email', 'broker@example.com')}>",
            "from": f"{LENDER} Underwriting <underwriting@mapleridge-mortgage.example>"}


def _salutation(view: dict) -> str:
    names = " & ".join(b["name"] for b in view["application"]["borrowers"])
    return f"Re: {names} – {view['application']['property']['address']}"


def document_request(view: dict) -> dict | None:
    """Draft request for missing or unreadable documents, ready as soon as the file is read; None if none."""
    items = [c for c in view["conditions"] if c["raised_by"] in DOCUMENT_REQUEST_CHECKS]
    if not items:
        return None
    body = [_hello(view), "",
            f"We've started our review. To keep it moving, please send the following:", ""]
    body += [f"• {c['text']}" for c in items]
    body += ["", "Our underwriter will follow up with the full review shortly.", "", f"{LENDER} – Underwriting"]
    return {"subject": _salutation(view) + " – documents needed", "kind": "document_request", **_addresses(view),
            "body": "\n".join(body), "condition_ids": [c["id"] for c in items]}


def _money(value) -> str:
    return f"${Decimal(str(value)):,.0f}"


def _date(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%b %-d, %Y") if value else "Not provided"


def review_report(view: dict, condition_reviews: dict, already_requested: set[str]) -> list[dict]:
    """Broker-facing review report: facts, qualification, documents and conditions.

    Deliberately leaves out internal material: the agent's recommendation, suspected alteration or other
    referral notes, and anything the underwriter rejected. The conditions carry what the broker must act on.
    """
    app, loan, prop, r, limits = view["application"], view["application"]["loan"], view["application"]["property"], \
        view["ratios"], view["limits"]
    aps = next((d["fields"] for d in view["documents"] if d["type"] == "purchase_agreement"), {})
    down_pct = Decimal(str(loan["down_payment"])) / Decimal(str(prop["purchase_price"])) * 100

    outstanding, standard, satisfied = [], [], []
    for c in view["conditions"]:
        review = condition_reviews.get(c["id"], {})
        if review.get("action") == "reject":
            continue
        text = review.get("text") or c["text"]
        item = {"id": c["id"], "text": text, "requested_earlier": c["id"] in already_requested}
        if review.get("action") == "fulfill":
            satisfied.append(item)
        else:
            (standard if c["raised_by"] is None else outstanding).append(item)

    def ratio(label, key, limit):
        value = Decimal(r[key])
        return {"label": label, "value": f"{value}%", "note": f"limit {limit}%",
                "status": "ok" if value <= Decimal(str(limit)) else "over"}

    income = [{"label": i["label"], "value": _money(i["value"]), "note": i["basis"]}
              for i in view["inputs"] if i["key"].startswith(("income:", "rent:"))]
    debts = [{"label": i["label"].replace(" – monthly payment", ""), "value": _money(i["value"]) + "/mo",
              "note": "Not on the application; reported on the credit bureau" if "bureau" in i["basis"] else "Declared on the application"}
             for i in view["inputs"] if i["key"].startswith("debt:")]
    missing = [f["condition_vars"]["document"] for f in view["flags"]
               if f["check"] in DOCUMENT_REQUEST_CHECKS and not f["dismissed"]]

    return [
        {"title": "File summary", "rows": [
            {"label": "Borrower(s)", "value": " & ".join(b["name"] for b in app["borrowers"])},
            {"label": "Property", "value": f"{prop['address']} ({prop['type'].replace('_', ' ')})"},
            {"label": "Purchase price", "value": _money(prop["purchase_price"])},
            {"label": "Loan amount", "value": _money(loan["amount"])},
            {"label": "Down payment", "value": _money(loan["down_payment"]), "note": f"{down_pct:.0f}% of price"},
            {"label": "Product", "value": f"{loan['product']} at {loan['contract_rate']}%",
             "note": f"{loan['term_years']}-yr term, {loan['amortization_years']}-yr amortization"},
            {"label": "Closing date", "value": _date(aps.get("closing_date"))}]},
        {"title": "Qualification", "note": f"Stress-tested at the qualifying rate of {r['qualifying_rate']}%.", "rows": [
            ratio("GDS", "gds_qualifying", limits["gds"]), ratio("TDS", "tds_qualifying", limits["tds"]),
            ratio("LTV", "ltv", 80)]},
        {"title": "Income used to qualify", "rows": income},
        {"title": "Debts included", "rows": debts or [{"label": "None", "value": "–"}]},
        {"title": "Documents", "rows": [
            {"label": "Received", "value": f"{len(view['documents'])} documents",
             "note": ", ".join(d["label"] for d in view["documents"])},
            *[{"label": "Outstanding", "value": m, "status": "over"} for m in missing]]},
        {"title": "Conditions before approval", "items": outstanding,
         "empty": "None. Only the standard conditions below remain."},
        {"title": "Conditions before funding", "items": standard},
        *([{"title": "Conditions satisfied", "items": satisfied}] if satisfied else []),
    ]


def _report_text(report: list[dict]) -> list[str]:
    lines = []
    for section in report:
        lines += ["", section["title"].upper(), "-" * len(section["title"])]
        if section.get("note"):
            lines.append(section["note"])
        for row in section.get("rows", []):
            flag = {"ok": " ✓", "over": " ✗"}.get(row.get("status"), "")
            lines.append(f"{row['label']}: {row['value']}{flag}" + (f" ({row['note']})" if row.get("note") else ""))
        if "items" in section:
            if not section["items"]:
                lines.append(section.get("empty", "None."))
            lines += [f"{n}. {item['text']}" + (" (requested earlier)" if item["requested_earlier"] else "")
                      for n, item in enumerate(section["items"], start=1)]
    return lines


def _hello(view: dict) -> str:
    return f"Hello {(view.get('pos') or {}).get('broker', '').split(' ')[0]},".replace(" ,", ",")


def review_message(view: dict, condition_reviews: dict, already_requested: set[str], status: str | None = None,
                   intro: list[str] | None = None, subject: str = "review and conditions", kind: str = "conditions") -> dict:
    """The conditions email with the full review report, drafted for the underwriter to send."""
    report = review_report(view, condition_reviews, already_requested)
    section = {s["title"]: s for s in report}
    outstanding = section["Conditions before approval"]["items"]
    status = status or (f"Under review – {len(outstanding)} condition{'s' * (len(outstanding) != 1)} to satisfy before approval"
                        if outstanding else "Review complete – standard conditions only")
    lines = [_hello(view), "", *(intro or ["We've completed our first review of this file. The full review and our conditions are below."]),
             "", f"Status: {status}"]
    lines += _report_text(report)
    lines += ["", "Please send the outstanding items in one package where possible, and reply with any questions.",
              "", f"{LENDER} – Underwriting"]
    return {"subject": _salutation(view) + f" – {subject}", "kind": kind, "status": status,
            **_addresses(view),
            "report": report, "body": "\n".join(lines),
            "condition_ids": [i["id"] for s in report if "items" in s and s["title"] != "Conditions satisfied"
                              for i in s["items"]]}


def _letter(view: dict, subject: str, kind: str, status: str, lines: list[str]) -> dict:
    body = [_hello(view), "", *lines, "", "Please reply with any questions.", "", f"{LENDER} – Underwriting"]
    return {"subject": _salutation(view) + f" – {subject}", "kind": kind, "status": status, **_addresses(view),
            "body": "\n".join(body), "condition_ids": []}


def decision_message(view: dict, decision: dict, condition_reviews: dict, already_requested: set[str],
                     decline_wording: dict[str, str]) -> dict:
    """The broker email for a recorded decision. Drafted only; the underwriter previews and sends it."""
    kind, note = decision["type"], (decision.get("note") or "").strip()
    if kind in ("approve", "approve_conditions"):
        msg = review_message(view, condition_reviews, already_requested, kind="decision", subject="commitment",
                             status="Approved" if kind == "approve" else "Approved with conditions",
                             intro=["Good news: this file is approved. Our commitment, the review and the conditions are below."])
        return msg
    if kind == "counter_offer":
        t, r, loan = decision["terms"], view["ratios"], view["application"]["loan"]
        offer = [f"Loan amount: ${float(t.get('amount') or loan['amount']):,.0f}",
                 f"Amortization: {t.get('amortization') or loan['amortization_years']} years",
                 f"GDS {r['gds_qualifying']}% · TDS {r['tds_qualifying']}% at the qualifying rate of {r['qualifying_rate']}%"]
        return review_message(view, condition_reviews, already_requested, kind="decision", subject="counter-offer",
                              status="Counter-offer", intro=["We can't approve the file as submitted, but we can offer the following:",
                                                             "", *[f"• {o}" for o in offer], *(["", note] if note else []),
                                                             "", "If the borrower accepts, the conditions below apply."])
    if kind == "refer":
        return review_message(view, condition_reviews, already_requested, kind="decision", subject="file under senior review",
                              status="Under senior review",
                              intro=["This file has been passed to a senior underwriter for a final decision. "
                                     "We'll follow up shortly; in the meantime the review and outstanding items are below."])
    if kind == "hold":
        return _letter(view, "file on hold", "decision", "On hold",
                       ["This file is on hold while we wait for the following:", "",
                        *[f"• {r}" for r in decision["reasons"]], *(["", note] if note else []),
                        "", f"We'll revisit it on {decision['follow_up']}."])
    if kind == "decline":
        return _letter(view, "decision", "decision", "Declined",
                       ["After reviewing this file we're unable to approve it.", "",
                        *[f"• {decline_wording.get(r, r)}" for r in decision["reasons"]],
                        "", "We'd be happy to look at a restructured application."])
    return _letter(view, "application withdrawn", "decision", "Withdrawn",
                   ["As requested, we've closed this application as withdrawn. No further action is needed."])
