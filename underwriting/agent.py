"""Prototype agent: works one loan file from intake to a draft conditions list.

It decides which checks the file needs from what is in it (salaried vs self-employed, rental property,
condo), follows leads across documents, and hands the numbers to the deterministic ratio and policy code.
It never decides the outcome or sends anything: the underwriter reviews, edits and approves.

Document reading is simulated: documents arrive already extracted (underwriting/demo_cases.py). Everything
after that is the real logic.
"""
from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import yaml

from underwriting.demo_cases import LENDER
from underwriting.policy import Policy, evaluate, load_policy
from underwriting.recommend import recommend
from underwriting.schemas import Application, Area, Condition, Evidence, Finding, Status

TEMPLATES = yaml.safe_load((Path(__file__).parent.parent / "policy" / "condition_templates.yaml").read_text())
LOW_CONFIDENCE = 0.80
INCOME_VARIANCE_PCT = Decimal("10")
YTD_TOLERANCE = Decimal("1.00")
EXPECTED_INCOME_DEPOSITS = ("payroll", "transfer from business account", "rent")
DOC_NAMES = {
    "pay_stub": "recent pay stub", "employment_letter": "employment letter", "t4": "2025 T4",
    "noa": "2025 Notice of Assessment", "t1_general": "T1 General (2 most recent years)",
    "business_registration": "business registration or articles of incorporation",
    "bank_statement": "90-day bank statement", "credit_bureau": "credit bureau report",
    "purchase_agreement": "signed agreement of purchase and sale", "appraisal": "appraisal report",
    "property_tax": "property tax bill", "condo_fees": "condo status certificate", "id": "government photo ID",
    "lease": "lease for the rental property", "mortgage_statement": "mortgage statement for the rental property",
}


def _d(value) -> Decimal:
    return Decimal(str(value))


def _fmt(value) -> str:
    return f"{_d(value):,.2f}"


class _Run:
    def __init__(self, case: dict, overrides: dict, dismissed: set[str], policy: Policy):
        self.case, self.overrides, self.dismissed, self.policy = case, overrides, dismissed, policy
        self.app = copy.deepcopy(case["application"])
        self.docs = case["documents"]
        self.steps: list[dict] = []
        self.flags: list[dict] = []
        self.inputs: list[dict] = []

    # --- helpers ---

    def step(self, text: str, kind: str = "step", detail: str = ""):
        self.steps.append({"text": text, "kind": kind, "detail": detail})

    def flag(self, flag_id: str, check: str, severity: str, title: str, detail: str, evidence: list[dict],
             area: Area = Area.BORROWER, escalate_to: str | None = None, condition_vars: dict | None = None):
        self.flags.append({"id": flag_id, "check": check, "severity": severity, "area": area.value, "title": title,
                           "detail": detail, "evidence": evidence, "escalate_to": escalate_to,
                           "condition_vars": condition_vars or {}, "dismissed": flag_id in self.dismissed})
        self.step(title, "flag", detail)

    def of_type(self, doc_type: str, name: str | None = None) -> list[dict]:
        return [d for d in self.docs if d["type"] == doc_type
                and (name is None or d["fields"].get("name") in (None, name))]

    def ev(self, d: dict, field: str, value=None) -> dict:
        return {"doc_id": d["id"], "doc": d["label"], "file": d["filename"], "page": d["page"], "field": field,
                "value": str(value if value is not None else d["fields"].get(field))}

    def add_input(self, key: str, label: str, agent_value: Decimal, basis: str, evidence: list[dict]) -> Decimal:
        override = self.overrides.get(key)
        value = _d(override["value"]) if override else agent_value
        self.inputs.append({"key": key, "label": label, "agent_value": str(agent_value), "value": str(value),
                            "basis": basis, "evidence": evidence, "override": override})
        return value

    # --- the work ---

    def intake(self):
        files = {d["filename"] for d in self.docs}
        combined = sorted({d["filename"] for d in self.docs if sum(x["filename"] == d["filename"] for x in self.docs) > 1})
        self.step(f"Received {len(files)} files from the broker submission",
                  detail=", ".join(sorted(files)))
        if combined:
            self.step(f"Split combined PDFs into separate documents: {', '.join(combined)}")
        self.step(f"Classified {len(self.docs)} documents",
                  detail="; ".join(f"{d['label']} ({d['filename']} p.{d['page']})" for d in self.docs))

    def check_required_documents(self):
        required: list[tuple[str, str | None]] = [("bank_statement", None), ("credit_bureau", None),
                                                  ("purchase_agreement", None), ("appraisal", None),
                                                  ("property_tax", None)]
        for b in self.app["borrowers"]:
            required.append(("id", b["name"]))
            kinds = {i["type"] for i in b["incomes"]}
            if "salary" in kinds:
                required += [(t, b["name"]) for t in ("pay_stub", "employment_letter", "t4", "noa")]
            if "self_employed" in kinds:
                required += [("t1_general", b["name"]), ("noa", b["name"]), ("business_registration", None)]
        if self.app["property"]["type"] == "condo":
            required.append(("condo_fees", None))
        if any(p.get("monthly_rental_income") for p in self.app.get("existing_properties", [])):
            required += [("lease", None), ("mortgage_statement", None)]

        reasons = []
        if any("self_employed" in {i["type"] for i in b["incomes"]} for b in self.app["borrowers"]):
            reasons.append("self-employed income → needs 2 years of T1s, NOA and business registration")
        if self.app["property"]["type"] == "condo":
            reasons.append("condo → needs condo fees")
        if self.app.get("existing_properties"):
            reasons.append("owns a rental → needs lease and mortgage statement")
        self.step("Built the document checklist for this file", "decision",
                  "; ".join(reasons) or "salaried borrower(s), freehold property → standard checklist")

        for doc_type, name in required:
            if not self.of_type(doc_type, name if doc_type not in ("id",) else None) or (
                    doc_type == "id" and not any(d["fields"].get("name") == name for d in self.of_type("id"))):
                document = DOC_NAMES[doc_type] + (f" for {name}" if name else "")
                self.flag(f"missing:{doc_type}:{name or ''}", "missing_document", "condition",
                          f"Missing document: {document}",
                          "Required for this file type and not found in the submission. Reported as missing, not estimated.",
                          [], condition_vars={"document": document})

        for d in self.docs:
            if d["confidence"] < LOW_CONFIDENCE:
                self.flag(f"low_confidence:{d['id']}", "low_confidence", "condition",
                          f"Low-confidence read: {d['label']}",
                          f"Read confidence {int(d['confidence'] * 100)}%. {d.get('quality_note', '')} "
                          "Values from this page must be confirmed by the underwriter.",
                          [self.ev(d, "page", f"p.{d['page']}")], condition_vars={"document": d["label"]})

    def verify_income(self):
        for bi, b in enumerate(self.app["borrowers"]):
            for ii, inc in enumerate(b["incomes"]):
                key, stated = f"income:{bi}:{ii}", _d(inc["annual_amount"])
                if inc["type"] == "salary":
                    self._salaried(b, inc, key, stated)
                elif inc["type"] == "self_employed":
                    self._self_employed(b, inc, key, stated)

    def _salaried(self, b, inc, key, stated):
        name = b["name"]
        stubs, t4s, noas = self.of_type("pay_stub", name), self.of_type("t4", name), self.of_type("noa", name)
        self.step(f"{name}: salaried → reconciling pay stub, employment letter, T4 and NOA", "decision")
        sources, evidence = [], []
        if stubs:
            s = stubs[0]
            gross = _d(s["fields"]["gross_per_period"])
            annualized = gross * 26
            sources.append(("pay stub (annualized)", annualized))
            evidence.append(self.ev(s, "gross_per_period"))
            expected_ytd = gross * s["fields"]["periods_to_date"]
            ytd = _d(s["fields"]["ytd_gross"])
            if abs(ytd - expected_ytd) > YTD_TOLERANCE:
                self.flag(f"paystub_ytd:{s['id']}", "paystub_ytd", "refer",
                          f"Possible document alteration: pay stub YTD doesn't add up ({name})",
                          f"YTD gross ${_fmt(ytd)} vs ${_fmt(gross)} × {s['fields']['periods_to_date']} periods = "
                          f"${_fmt(expected_ytd)} (difference ${_fmt(ytd - expected_ytd)}).",
                          [self.ev(s, "ytd_gross"), self.ev(s, "gross_per_period"), self.ev(s, "periods_to_date")],
                          area=Area.AUTHENTICITY, escalate_to="Fraud / risk team",
                          condition_vars={"employer": inc.get("employer")})
            meta = s.get("pdf_metadata")
            if meta and meta["modified"] > meta["created"]:
                self.flag(f"pdf_edited:{s['id']}", "pdf_edited", "refer",
                          f"Possible document alteration: pay stub PDF was edited ({name})",
                          f"Created {meta['created']}, modified {meta['modified']} with \"{meta['producer']}\".",
                          [self.ev(s, "pdf_metadata", f"{meta['producer']}, modified {meta['modified']}")],
                          area=Area.AUTHENTICITY, escalate_to="Fraud / risk team",
                          condition_vars={"employer": inc.get("employer")})
        if t4s:
            sources.append(("2025 T4", _d(t4s[0]["fields"]["box_14_employment_income"])))
            evidence.append(self.ev(t4s[0], "box_14_employment_income"))
        if noas:
            sources.append(("2025 NOA", _d(noas[0]["fields"]["line_15000_total_income"])))
            evidence.append(self.ev(noas[0], "line_15000_total_income"))

        values = [v for _, v in sources]
        if len(values) > 1 and (max(values) - min(values)) / max(values) * 100 > INCOME_VARIANCE_PCT:
            listing = ", ".join(f"{label} ${_fmt(v)}" for label, v in sources)
            self.flag(f"income_mismatch:{key}", "income_mismatch", "refer",
                      f"Income sources don't agree ({name})",
                      f"{listing}. Spread is more than {INCOME_VARIANCE_PCT}%. The agent does not choose which is "
                      "correct: ratios use the stated income, and the lowest verified figure is shown for comparison.",
                      evidence, condition_vars={"stated": _fmt(stated), "employer": inc.get("employer"),
                                                "t4": _fmt(sources[1][1]) if len(sources) > 1 else "n/a",
                                                "noa": _fmt(sources[2][1]) if len(sources) > 2 else "n/a"})
            self.lowest_verified = (key, min(values))
        elif values:
            self.step(f"{name}: income consistent across {len(values)} sources", "check",
                      ", ".join(f"{label} ${_fmt(v)}" for label, v in sources))
        self.add_input(key, f"{name} – salary (annual)", stated, "Stated income, checked against pay stub, T4 and NOA",
                       evidence)

    def _self_employed(self, b, inc, key, stated):
        name = b["name"]
        t1s = sorted(self.of_type("t1_general", name), key=lambda d: d["fields"]["year"])
        self.step(f"{name}: self-employed → running 2-year T1 income average instead of pay stub checks", "decision")
        if len(t1s) < 2:
            self.add_input(key, f"{name} – self-employed (annual)", stated, "Stated income; T1s incomplete", [])
            return
        totals = [_d(t["fields"]["line_15000_total_income"]) for t in t1s[-2:]]
        average = sum(totals) / 2
        evidence = [self.ev(t, "line_15000_total_income") for t in t1s[-2:]]
        trend = "rising" if totals[1] >= totals[0] else "declining"
        qualifying = min(stated, average)
        self.step(f"{name}: 2-year average ${_fmt(average)} ({trend})", "check",
                  f"{t1s[-2]['fields']['year']}: ${_fmt(totals[0])}, {t1s[-1]['fields']['year']}: ${_fmt(totals[1])}")
        if stated > average:
            self.flag(f"self_employed_average:{key}", "self_employed_average", "condition",
                      f"Qualified on 2-year average, below stated income ({name})",
                      f"Stated ${_fmt(stated)} vs 2-year T1 average ${_fmt(average)}. Policy uses the lower figure.",
                      evidence, condition_vars={"average": _fmt(average), "stated": _fmt(stated)})
        self.add_input(key, f"{name} – self-employed (annual)", qualifying,
                       "Lower of stated income and 2-year T1 average", evidence)

    def verify_bank_and_down_payment(self):
        threshold = _d(self.policy.credit["large_deposit_threshold"])
        has_gift_letter = bool(self.of_type("gift_letter"))
        for d in self.of_type("bank_statement"):
            self.step(f"Traced {len(d['fields'].get('deposits', []))} deposits in {d['label']}", "check",
                      f"Large-deposit threshold ${_fmt(threshold)} (credit policy)")
            if d.get("hidden_text"):
                self.flag(f"hidden_instruction:{d['id']}", "hidden_instruction", "refer",
                          "Hidden instruction-like text found in a document",
                          f"{d['label']} contains hidden text addressed to the reviewer: \"{d['hidden_text']}\". "
                          "Treated as document content, not as an instruction; all checks still ran.",
                          [self.ev(d, "hidden_text", d["hidden_text"])], area=Area.AUTHENTICITY,
                          escalate_to="Fraud / risk team")
            for dep in d["fields"].get("deposits", []):
                amount = _d(dep["amount"])
                expected = any(k in dep["description"].lower() for k in EXPECTED_INCOME_DEPOSITS)
                if amount > threshold and not expected:
                    if has_gift_letter:
                        self.step(f"${_fmt(amount)} deposit on {dep['date']} matched to gift letter", "check")
                        continue
                    self.step(f"${_fmt(amount)} deposit on {dep['date']} isn't income → looked for a gift letter → none found",
                              "decision")
                    self.flag(f"large_deposit:{d['id']}:{dep['date']}", "large_deposit", "condition",
                              f"Unexplained ${_fmt(amount)} deposit",
                              f"{dep['date']}: \"{dep['description']}\". Not payroll or business income, and no gift "
                              "letter in the file. Source of funds must be documented (FINTRAC).",
                              [self.ev(d, "deposits", f"{dep['date']} ${_fmt(amount)} {dep['description']}")],
                              condition_vars={"amount": _fmt(amount), "date": dep["date"],
                                              "description": dep["description"]})

    def reconcile_debts(self):
        declared = {l["lender"] for l in self.app.get("liabilities", [])}
        existing_mortgages = sum(1 for p in self.app.get("existing_properties", []) if _d(p["mortgage_balance"]) > 0)
        for bureau in self.of_type("credit_bureau"):
            lines = bureau["fields"]["tradelines"]
            self.step(f"Compared {len(lines)} bureau tradelines with {len(declared)} declared debts", "check")
            for t in lines:
                if t["lender"] in declared or (t["type"] == "mortgage" and existing_mortgages):
                    continue
                corroboration = [self.ev(bank, "withdrawals", f"{w['date']} ${w['amount']} {w['description']}")
                                 for bank in self.of_type("bank_statement")
                                 for w in bank["fields"].get("withdrawals", []) if t["lender"] in w["description"]]
                self.flag(f"undisclosed_debt:{t['lender']}", "undisclosed_debt", "refer",
                          f"Debt on the bureau not declared on the application: {t['lender']}",
                          f"{t['type'].replace('_', ' ')}, balance ${_fmt(t['balance'])}, ${_fmt(t['monthly_payment'])}/month"
                          + (f"; also seen as {len(corroboration)} payments in the bank statement" if corroboration else "")
                          + ". Added to TDS.",
                          [self.ev(bureau, "tradelines", f"{t['lender']} ${t['monthly_payment']}/mo")] + corroboration,
                          condition_vars={"lender": t["lender"], "type": t["type"].replace("_", " "),
                                          "balance": _fmt(t["balance"]), "payment": _fmt(t["monthly_payment"])})
                if f"undisclosed_debt:{t['lender']}" not in self.dismissed:
                    self.app.setdefault("liabilities", []).append(
                        {"type": t["type"], "lender": t["lender"], "balance": t["balance"],
                         "monthly_payment": t["monthly_payment"], "source": "bureau"})

    def build_application(self) -> Application:
        app = copy.deepcopy(self.app)
        for inp in self.inputs:
            if inp["key"].startswith("income:"):
                _, bi, ii = inp["key"].split(":")
                app["borrowers"][int(bi)]["incomes"][int(ii)]["annual_amount"] = inp["value"]
        for li, l in enumerate(app.get("liabilities", [])):
            src = "bureau (undisclosed)" if l.get("source") == "bureau" else "application"
            l["monthly_payment"] = str(self.add_input(f"debt:{l['lender']}", f"{l['lender']} – monthly payment",
                                                      _d(l["monthly_payment"]), f"From the {src}", []))
        for pi, p in enumerate(app.get("existing_properties", [])):
            if _d(p["monthly_rental_income"]):
                leases = self.of_type("lease")
                p["monthly_rental_income"] = str(self.add_input(
                    f"rent:{pi}", f"Rental income – {p['address']} (monthly)", _d(p["monthly_rental_income"]),
                    f"Lease; {self.policy.credit['rental_income_offset_pct']}% counted per policy",
                    [self.ev(leases[0], "monthly_rent")] if leases else []))
        for b in app["borrowers"]:
            for inc in b["incomes"]:
                inc.pop("employer", None)
        return Application.model_validate(app)


def _findings_from_flags(flags: list[dict]) -> list[Finding]:
    findings = []
    for f in flags:
        if f["dismissed"]:
            continue
        findings.append(Finding(area=Area(f["area"]), check=f["check"], status=Status.ATTENTION, message=f["title"],
                                evidence=[Evidence(doc=e["doc"], field=e["field"], value=e["value"]) for e in f["evidence"]],
                                needs_referral=f["severity"] == "refer"))
    return findings


def _conditions(flags: list[dict], policy_findings: list[Finding]) -> list[dict]:
    conditions = [{"id": s["id"], "text": s["text"].format(lender=LENDER), "trigger": "Standard condition",
                   "flag_id": None, "raised_by": None} for s in TEMPLATES["standard"]]
    for n, f in enumerate([f for f in flags if not f["dismissed"]], start=1):
        template = TEMPLATES["by_check"].get(f["check"])
        if template:
            conditions.append({"id": f"C{n}", "text": template.format(**f["condition_vars"]), "trigger": f["title"],
                               "flag_id": f["id"], "raised_by": f["check"]})
    for p in policy_findings:
        if p.status == Status.FAIL:
            conditions.append({"id": f"P-{p.check}", "flag_id": f"policy:{p.check}", "raised_by": p.check,
                               "trigger": f"Policy: {p.message}",
                               "text": f"{p.message}: requires an approved policy exception or a restructured deal "
                                       "(debt payoff, larger down payment or added income)."})
    return conditions


def run(case: dict, overrides: dict | None = None, dismissed: set[str] | None = None,
        policy: Policy | None = None) -> dict:
    """Works the file and returns everything the review screen shows. Pure: same inputs, same output."""
    policy = policy or load_policy()
    w = _Run(case, overrides or {}, dismissed or set(), policy)
    w.lowest_verified = None
    w.intake()
    w.check_required_documents()
    w.verify_income()
    w.verify_bank_and_down_payment()
    w.reconcile_debts()

    app = w.build_application()
    ratios, policy_findings = evaluate(app, policy)
    w.step(f"Calculated ratios at the qualifying rate {ratios['qualifying_rate']}% (fixed calculation code)", "calc",
           f"GDS {ratios['gds_qualifying']}%, TDS {ratios['tds_qualifying']}%, LTV {ratios['ltv']}%")
    for p in policy_findings:
        if p.status == Status.FAIL:
            w.flag(f"policy:{p.check}", p.check, "refer" if p.near_miss else "decline",
                   f"Policy limit exceeded: {p.message}",
                   "Within the exception margin: needs senior underwriter approval." if p.near_miss
                   else "Outside the exception margin.",
                   [{"doc_id": None, "doc": "Calculation", "file": "policy/credit_policy.yaml", "page": None,
                     "field": e.field, "value": e.value} for e in p.evidence],
                   area=Area.POLICY, escalate_to="Senior underwriter")

    comparison = None
    if w.lowest_verified:
        key, low = w.lowest_verified
        alt_overrides = {**(overrides or {}), key: {"value": str(low)}}
        alt_app = _Run(case, alt_overrides, dismissed or set(), policy)
        alt_app.lowest_verified = None
        alt_app.verify_income(); alt_app.reconcile_debts()
        alt_ratios, _ = evaluate(alt_app.build_application(), policy)
        comparison = {"label": f"At lowest verified income (${_fmt(low)})",
                      "gds": str(alt_ratios["gds_qualifying"]), "tds": str(alt_ratios["tds_qualifying"])}

    findings = [f for f in policy_findings if f.status != Status.FAIL or f"policy:{f.check}" not in w.dismissed]
    findings += _findings_from_flags([f for f in w.flags if not f["id"].startswith("policy:")])
    conditions = _conditions(w.flags, [f for f in policy_findings if f"policy:{f.check}" not in w.dismissed])
    recommendation, reasons = recommend(findings, [Condition(id=c["id"], text=c["text"], raised_by=c["raised_by"])
                                                   for c in conditions])
    w.step(f"Drafted {len(conditions)} conditions and a recommendation for the underwriter", "step")

    return {
        "case_id": case["id"], "title": case["title"], "summary": case["summary"], "pos": case.get("pos"),
        "application": case["application"], "documents": case["documents"],
        "steps": w.steps, "flags": w.flags, "inputs": w.inputs,
        "extracted": [{"doc_id": d["id"], "doc": d["label"], "file": d["filename"], "page": d["page"],
                       "confidence": d["confidence"], "field": k, "value": v}
                      for d in case["documents"] for k, v in d["fields"].items() if not isinstance(v, (list, dict))],
        "ratios": {k: str(v) for k, v in ratios.items()}, "comparison": comparison,
        "limits": {"gds": policy.credit["gds_max_pct"], "tds": policy.credit["tds_max_pct"]},
        "policy_findings": [p.model_dump(mode="json") for p in policy_findings],
        "policy_versions": [ref.model_dump() for ref in policy.refs()],
        "conditions": conditions,
        "recommendation": recommendation.value, "recommendation_reasons": reasons,
    }
