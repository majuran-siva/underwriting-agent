# PRD: Underwriting Package Agent (B-Lenders & MFCs, Canada)

**Status:** Draft v0.1 · **Date:** 2026-10-29 · **Author:** Majuran Sivarajah
**Phase:** v1 — Decision support (human approves every decision)

---

## 1. Problem Statement

Underwriters at Canadian B-lenders and mortgage finance companies (MFCs) spend most of their time on a file **re-keying documents, reconciling income across sources, and chasing missing items**, not on the credit decision itself. A clean file takes ~20 minutes of real judgment but **2–5 days** of elapsed time, driven by incomplete submissions and multiple rounds of conditions with the broker. In B-lending, where files are messier (self-employed, stated income, credit events) and competition for broker deals is won on turnaround speed, slow first responses cost lenders deals and cap how many files each underwriter can handle.

*Evidence status:* hypothesis from domain knowledge. It must be validated in design-partner interviews (see §9).

## 2. Goals

| # | Goal | Type | Target (v1) |
|---|------|------|-------------|
| G1 | Cut **time to first conditions** from submission | User / Business | < 15 min (vs. ~1–2 days baseline) |
| G2 | Cut **underwriter hands-on time per file** | User | −50% on standard B-files |
| G3 | Cut **condition cycles per file** (broker back-and-forth) | Business | −30% |
| G4 | Make every number **traceable to source** to stand up to audit and model-risk review | Compliance | 100% of computed values cited |
| G5 | Extraction accurate enough that underwriters **stop re-keying** | Trust | ≥ 95% field-level accuracy; < 10% override rate |

## 3. Non-Goals

1. **Autonomous approve/decline.** Credit authority stays with humans. It's a regulatory (OSFI E-23 / lender model-risk) and trust barrier; we'll revisit after a proven track record.
2. **LOS integrations (Filogix, Newton Velocity, Lendesk).** Depends on which design partner we land; v1 is upload in, PDF/JSON out.
3. **Pricing / rate setting / fee recommendations.** A separate risk-pricing problem with different stakeholders.
4. **Insured deals and mortgage insurer submission (CMHC / Sagen / Canada Guaranty).** Outside the B-lender wedge.
5. **Borrower- or broker-facing UI.** The customer is the lender's underwriting team only.

## 4. Personas

- **B-Lender Underwriter.** Works a queue of 8–15 files/day, accountable for decision quality and QA findings.
- **Senior Underwriter / Credit Manager.** Owns lender policy, handles exceptions and escalations, signs off above authority limits.
- **Head of Underwriting / Credit Risk.** Buyer; cares about throughput, defect rate, and audit defensibility.
- **Compliance / Audit.** Needs FINTRAC records and decision rationale.

## 5. User Stories

**Underwriter**
1. As an underwriter, I want every document in a new file automatically classified and extracted so that I don't re-key income, debts or property details.
2. As an underwriter, I want income cross-checked across pay stubs, T4s, NOAs, T1s and bank deposits, with discrepancies flagged, so that I catch misrepresentation without manual reconciliation.
3. As an underwriter, I want GDS, TDS, LTV and the stress test calculated against my lender's policy so that I see policy fit at a glance.
4. As an underwriter, I want a draft conditions list in my lender's wording within minutes of submission so that the broker can start gathering documents immediately.
5. As an underwriter, I want a draft underwriting memo (borrower story, credit narrative, income reasonableness, exit strategy, risks), with every claim linked to its source page, so that I can review and sign instead of write.
6. As an underwriter, I want to override any extracted value or flag, with a reason, so that the file reflects my judgment and the system learns where it's wrong.
7. As an underwriter, when a document is unreadable, unsupported or missing, I want it clearly marked rather than silently skipped, so that I never treat an incomplete analysis as complete.

**Credit Manager**
8. As a credit manager, I want to edit policy thresholds (ratios, LTV by property type and region, credit floors, income treatment) without engineering help so that the tool reflects our policy.
9. As a credit manager, I want policy exceptions surfaced with the rule, threshold and actual value so that I can approve or decline exceptions quickly.

**Compliance**
10. As a compliance officer, I want a complete, immutable audit trail of inputs, extracted values, rules fired, overrides and the final human decision, so that we can answer regulator and funder audits.

## 6. Requirements

### P0: Must-Have

**R1. Document ingestion & classification**
Accept PDF/image uploads (single or bulk) and classify them as: pay stub, employment letter, T4, NOA, T1 General, financial statements, bank statement, gift letter, purchase agreement, appraisal, mortgage statement, property tax bill, credit bureau report, ID.
- [ ] Classification accuracy ≥ 97% on the test set
- [ ] Unknown or low-confidence documents routed to a "needs review" bin, never dropped
- [ ] Handles multi-document PDFs (splits by page ranges)

**R2. Field extraction with citations**
Extract the key fields per document type (e.g., NOA line 15000 / 23600, T4 box 14, bank deposits, appraised value, property tax, condo fees, bureau score and tradelines).
- [ ] Every value links to its source document, page and region
- [ ] Each value carries a confidence score; low-confidence values are highlighted
- [ ] ≥ 95% field-level accuracy on the design-partner file set

**R3. Cross-document verification & fraud flags**
- [ ] Income reconciled across available sources; variance > configurable % is flagged
- [ ] Name, address, SIN-last-3 and employer consistent across documents
- [ ] 90-day bank statement trace: large or unexplained deposits flagged (threshold configurable)
- [ ] Document integrity signals (e.g., edited PDF metadata, font inconsistencies, YTD math errors on pay stubs)
- [ ] Debts on the bureau that are missing from the application, and vice versa

**R4. Ratio, LTV & stress-test engine**
- [ ] GDS/TDS computed per standard Canadian method (P&I, property tax, heating, 50% condo fees; all other debts for TDS; configurable revolving-debt payment %)
- [ ] Qualifying rate = max(contract + 2%, 5.25%), toggleable per lender (on by default)
- [ ] LTV and combined LTV (where there's a second mortgage)
- [ ] Rental income treatment: offset or add-back, configurable %
- [ ] Deterministic code, no LLM arithmetic; unit-tested against reference calculations

**R5. Configurable policy profile**
Ship a default "Canadian B-lender" profile; every threshold is editable by credit managers.
- [ ] Default values: GDS/TDS max 50/50, credit floor 550, max LTV 80% (urban) / 65–75% (rural, small condo), self-employed history ≥ 1 yr, stated-income reasonableness required
- [ ] Hard regulatory rules (FINTRAC, 80% uninsured LTV for federally regulated lenders) are non-editable, or require explicit compliance acknowledgement to change
- [ ] Profile changes are versioned; each file records the profile version it was evaluated against

**R6. Draft conditions list**
- [ ] Generated within 15 minutes of complete upload
- [ ] Each condition tied to its trigger (missing document, discrepancy, policy exception)
- [ ] Editable, with export to PDF/text for sending to the broker
- [ ] Supports lender-specific condition templates/wording

**R7. Underwriting memo (decision support)**
Sections: deal summary, borrower story ("why B, how out"), income analysis and reasonableness, credit narrative, collateral, ratios vs. policy, exceptions, risks and mitigants, suggested recommendation.
- [ ] Every factual claim cites a source document
- [ ] Recommendation clearly labelled advisory; final decision recorded by a named human
- [ ] No claim without a source; when information is missing, the memo says so

**R8. Human review & override**
- [ ] Underwriter can accept, edit or reject any extracted value, flag or condition
- [ ] Overrides require a reason code and are logged

**R9. FINTRAC & compliance capture**
- [ ] KYC identity verification fields captured; source-of-funds documented
- [ ] PEP/sanctions screening hook (integration with a third-party provider)
- [ ] Record retention aligned with FINTRAC requirements (5 years)

**R10. Audit trail & security**
- [ ] Immutable log: inputs, model/prompt versions, extracted values, rules fired, overrides, decision
- [ ] Data residency in Canada; encryption at rest and in transit; role-based access
- [ ] PIPEDA-compliant handling of personal information; borrower data not used to train models without consent

### P1: Nice-to-Have

- **R11. Stated-income reasonableness benchmark.** Compare declared income with industry, occupation and region benchmarks (e.g., StatCan data).
- **R12. Exit-strategy assessment.** Estimate the path to A-lender eligibility (credit rehab time, income documentation gap, equity).
- **R13. Missing-document requests.** Generate a broker-ready checklist as soon as gaps are detected, before full review.
- **R14. Queue triage.** Rank incoming files by completeness and complexity so underwriters pick up ready files first.
- **R15. Accuracy dashboard.** Override rates by field and document type, to guide model improvement.

### P2: Future Considerations (design for, don't build)

- **LOS integrations**: keep the internal data model mappable to the MISMO/Filogix field structure.
- **Autonomous approval for low-risk files** (e.g., LTV < 65%, clean verification): keep the decision log structured enough to backtest.
- **Insured and A-lender profiles**: the policy engine must support multiple profiles per tenant.
- **Bureau and bank data APIs** (Equifax/TransUnion direct, Flinks/Plaid-style bank data), replacing PDF bank statements.
- **Post-funding QA sampling** using the same verification engine.

## 7. Success Metrics

**Leading indicators (measured weekly during pilot)**
| Metric | Success | Stretch | Measured by |
|---|---|---|---|
| Time from complete upload to draft conditions | < 15 min | < 5 min | System timestamps |
| Underwriter hands-on time per file | −40% | −60% | Time study vs. baseline (same underwriters, matched files) |
| Field-level override rate | < 10% | < 5% | Override log |
| Missed-condition rate vs. senior underwriter review | < 5% | < 2% | Blind dual review of 20-file sample |
| Underwriter adoption (files run through agent / total) | 70% | 90% | Usage logs |

**Lagging indicators (60–90 days)**
| Metric | Success | Measured by |
|---|---|---|
| Condition cycles per file | −30% | LOS / pilot tracking |
| Files closed per underwriter per week | +30% | Lender ops data |
| QA / audit defect rate | No increase (target −20%) | Lender QA reports |
| Broker-reported turnaround satisfaction | Measurable improvement | Lender's broker survey |

## 8. Open Questions

| Question | Owner | Blocking? |
|---|---|---|
| Which LOS do target MFCs use, and does upload-and-export suffice for a pilot? | Stakeholder / design partners | Yes (pilot design) |
| Do non-OSFI MFCs see model-risk governance (E-23-style) as mandatory through their funders or securitization buyers? | Legal / design partners | Yes |
| Can we get anonymized real files for training and evaluation, and under what data agreement? | Legal | Yes |
| Hosting model: our Canadian cloud tenant vs. the lender's environment? | Engineering / security | Yes (architecture) |
| Which PEP/sanctions and ID-verification providers to integrate first? | Engineering | No |
| Are default B-lender thresholds representative? Validate with 3+ lenders. | Stakeholder | No |
| LLM choice and deployment (data residency, zero-retention terms) | Engineering | Yes |
| How do we evaluate memo quality objectively (rubric, senior UW scoring)? | Data / design partners | No |

## 9. Timeline & Phasing

**Phase 0: Validate (weeks 0–6)**
Recruit 3–5 B-lender/MFC underwriters as design partners or paid advisors. Collect and anonymize ~20–50 files. Baseline time studies.
*Exit criteria:* 2+ lenders confirm the problem and agree to a pilot.

**Phase 1: Trust prototype (weeks 6–14)**
R1–R4 and R8 on the design-partner file set; offline, upload-based.
*Exit criteria:* ≥ 95% field accuracy, < 10% override rate, and underwriters say they'd stop re-keying.

**Phase 2: Pilot MVP (weeks 14–26)**
Add R5–R7, R9–R10. Live pilot with one lender on real incoming volume, human sign-off on 100% of files.
*Exit criteria:* G1–G3 met; security review passed; paid conversion.

**Phase 3: Expand**
P1 features, first LOS integration, second lender.

**Dependencies:** access to real files (legal agreement), a Canadian-hosted LLM deployment, a credit bureau report format sample, a PEP/sanctions vendor.

---

### Parking Lot
Broker-side lender matching · pricing engine · A-lender/insured expansion · autonomous approvals · post-funding QA product.
