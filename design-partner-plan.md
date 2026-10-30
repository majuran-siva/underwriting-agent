# Phase 0 Design-Partner Plan: Underwriting Package Agent

**Date:** 2026-10-29 · **Duration:** 6 weeks · **Links to:** [PRD](PRD-underwriting-package-agent.md) §9 Phase 0

## 1. Objectives

What we need to learn, and the evidence that would change our plan:

| # | Question | Kill / pivot signal |
|---|----------|---------------------|
| Q1 | Is elapsed time driven by conditions and document chasing, rather than by the decision itself? | Underwriters say the decision itself is the bottleneck → reposition toward judgment support |
| Q2 | How much hands-on time per file goes to re-keying and reconciling? | < 25% of time → the value prop is too thin |
| Q3 | **Would underwriters trust extracted numbers enough to stop re-verifying them?** (riskiest assumption) | Most say "I'd still check every number" even at 95%+ accuracy |
| Q4 | Are our default B-lender policy thresholds realistic? | Wide variance → the policy config UX becomes P0 and onboarding cost goes up |
| Q5 | Who buys, what's the budget, and what does security/model-risk review require? | No budget owner, or a > 12-month procurement cycle at MFCs |
| Q6 | Will a lender share anonymized files and commit to a pilot? | 0 of 5 willing → find another route to data (ex-underwriters, synthetic files) |

**Phase exit criteria:** 2+ lenders confirm the problem and sign an LOI (letter of intent) or pilot agreement; we hold ≥ 20 anonymized files for evaluation.

## 2. Who to Recruit

**Target: 3–5 design partners plus 2–3 paid advisors.**

| Profile | Count | Why |
|---|---|---|
| Underwriter / senior underwriter at an MFC or B-lender | 6–10 interviews | Day-to-day workflow, trust threshold |
| Head of underwriting / VP credit | 3–5 | Buyer, budget, metrics |
| Ex-underwriter (now consulting or retired) | 2–3 paid advisors | Fast access to file patterns and policy norms; can help create realistic synthetic files |
| Mortgage broker who works with B-lenders | 2–3 | The other side of the conditions cycle; quantifies delay |
| Compliance / risk at an MFC | 1–2 | FINTRAC, model-risk, data-sharing constraints |

**Target organisations (types):** non-bank MFCs, alternative lenders, B-side trust companies, larger credit unions with B-programs, mortgage investment corporations (MICs) for the private end. Prioritise Ontario and BC (highest B volume).

**Channels**
- LinkedIn search: "Underwriter" + "MFC / alternative lending / B lending"; warm intros first
- CMBA, Mortgage Professionals Canada, and provincial broker associations
- Mortgage industry events (e.g., CMP/Mortgage Professionals Canada conferences)
- Mortgage fintech communities, plus angels and operators with lender networks
- Paid expert networks for ex-underwriters ($150–300/hr)

**Outreach message (draft)**
> Hi [Name]. I'm building a tool that helps B-lender underwriters get from submission to a complete conditions list in minutes instead of days, with every number traced back to source documents. I'm not selling anything yet; I'm trying to understand how underwriting actually works at MFCs. Would you be open to a 30-minute conversation? Happy to share what we learn across lenders, or to compensate your time.

**Incentive for design partners:** free pilot, influence over the roadmap, preferred pricing, an anonymized benchmark of their turnaround vs. peers.

## 3. Research Activities

### Weeks 1–2: Discovery interviews (30–45 min)
**Underwriter guide**
1. Walk me through the last file you decisioned, from when it landed to final approval.
2. Where did the time go? Which parts were waiting, and which were you working?
3. What do you re-key or reconcile by hand? Which documents are the worst?
4. How many condition rounds does a typical file have? What triggers them?
5. Tell me about a file that went wrong: fraud, missed debt, bad income.
6. How do you assess stated income or self-employed income? What's "reasonable"?
7. *(Trust)* If a tool extracted every number and showed you the source page, what would you still check yourself? What would make you stop checking?
8. What are your actual policy limits (ratios, LTV, credit floor, property restrictions)?
9. What tools do you use today (LOS, spreadsheets, OCR, bureau tools)?

**Head of underwriting guide** (adds)
- What do you measure underwriters on? What are the current numbers?
- What would a 50% cut in hands-on time be worth (headcount, volume, broker share)?
- What would security, compliance or a funder require before you'd pilot an AI tool?
- Who signs off on a purchase like this, and how have similar tools been bought?

**Broker guide**
- Typical B-lender turnaround? How often do you lose a deal or switch lenders over speed?
- Which conditions come back most often?

### Weeks 2–4: Contextual observation (2–3 sessions)
Shadow an underwriter (screen share) working 2–3 real files. Time each step: reading, re-keying, calculating, writing conditions, writing the memo, waiting. This produces the **baseline time study** for PRD metrics G1–G2.

### Weeks 3–5: Concierge trust test
Without building the product, use rough extraction (an LLM plus manual QA) to produce an "underwriting package" for 5–10 anonymized files per partner. Package: extracted fields with citations, ratios, flags, draft conditions, memo.
- Underwriters review it and **mark every value they'd re-verify, and why**
- Compare our draft conditions with their actual conditions (missed and extra)
- Ask them to rate the memo (1–5) on usefulness and accuracy

### Weeks 4–6: Policy & commercial validation
- Collect policy guidelines (redacted if needed) from 3+ lenders → calibrate default profile thresholds
- Pilot conversation: scope, data agreement, success metrics, pricing signal (per-file vs. per-seat)

## 4. Data & Legal

- **Mutual NDA** before any file is shared.
- **Data-sharing agreement:** purpose limitation, Canadian storage, deletion at the end of the study, no model training without explicit consent. Aligned with PIPEDA.
- **Anonymization protocol:** lenders redact names, SINs, account numbers and addresses (or we provide a redaction tool or checklist); keep amounts, dates and document structure.
- **Fallback if no real files:** ex-underwriter advisors build 20–30 realistic synthetic files covering typical B scenarios (self-employed, consumer proposal, rental, gifted down payment, large deposits, falsified pay stub).

## 5. Synthesis & Decision

- Tag every interview against Q1–Q6. Track how many participants confirm or contradict each one.
- **Trust score:** % of extracted values underwriters said they'd accept without re-checking (target ≥ 70% at this stage).
- **Condition match:** recall of our draft conditions vs. actual (target ≥ 80% in the concierge test).
- **Policy variance table:** min, median and max of each threshold across lenders → update PRD R5 defaults.

**Week 6 decision meeting:** go / pivot / stop on Phase 1, with a recommended first pilot lender.

## 6. Timeline

| Week | Activities | Output |
|---|---|---|
| 1 | Outreach (40+ contacts), first interviews, advisors engaged | Interview schedule |
| 2 | Interviews continue; NDAs; first observation | Early themes |
| 3 | Observation sessions; files received; concierge packages built | Baseline time study |
| 4 | Concierge reviews; policy collection | Trust & condition-match data |
| 5 | Remaining reviews; commercial and pilot conversations | Policy variance table |
| 6 | Synthesis; LOIs; decision | Research readout + go/no-go |

## 7. Budget (rough)

| Item | Estimate (CAD) |
|---|---|
| Paid advisors (2–3 × ~10 hrs) | $4–8K |
| Interview incentives (gift cards / donations) | $1–2K |
| Expert-network fees | $2–4K |
| LLM/API + secure storage for concierge test | < $1K |
| Legal (NDA / data-sharing templates) | $2–5K |
| **Total** | **~$10–20K** |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Lenders won't share real files | Synthetic files from advisors; offer on-prem or lender-run redaction |
| Only friendly or small lenders respond | Mix in 1–2 larger MFCs; weight buyer interviews |
| "Interesting" but no commitment | Ask for a concrete next step every time: files, an observation session, an intro to the decision maker |
| Concierge test overstates product quality | Log every manual correction; report raw vs. corrected accuracy |
