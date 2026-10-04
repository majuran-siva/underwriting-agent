# Spec: Underwriting Review Agent (Leadership Demo)

Status: APPROVED 2026-10-04, revised 2026-10-04 (full underwriting scope). Intent: [docs/intent/underwriting-agent.md](docs/intent/underwriting-agent.md)

## Objective

Build an AI agent that takes a synthetic mortgage application package and, in a few minutes, does the underwriter's review work:
- reviews the **borrower**
- reviews the **property**
- applies the **lender's policies**
- investigates **exceptions**
- produces the **conditions** needed before funding

It ends with a **recommended** outcome. The underwriter makes the decision.

**Audience for v1:** the lender's leadership team, in a live demo on the presenter's laptop.

**User stories**
- As an underwriter, I upload an application package and get one review report. It sorts every finding into ✅ Checks out, ⚠️ Needs attention, or ❌ Fails policy, and every flag cites its evidence: which document, what value, compared against what.
- As an underwriter, I see a recommended outcome with the reasons, then I click my own decision.
- As an underwriter, when a file narrowly misses policy, I see the exception case already investigated: other income, liabilities that could be excluded, compensating strengths, alternative products, and whether policy allows an exception.
- As an underwriter, I upload a follow-up document against an open condition, and the agent tells me whether it satisfies the condition.
- As a leadership viewer, I watch a familiar-looking application go in and a completed review come out, and I see the agent catch problems planted in the file.

**Input: the application package**
```
samples/<case-id>/
├── mortgage-application.pdf   # human-readable, like a broker submission summary
├── docs/                      # paystub, T4, NOA, employment letter, bank statements, credit report,
│                              # appraisal, purchase agreement, mortgage statements for existing
│                              # properties, gift letter / T1 Generals (as applicable)
└── followup/                  # (case 05 only) documents uploaded later to clear a condition
```

## What the agent does

### 1. Borrower review
Establishes whether the borrower can reasonably service the mortgage.
| Area | Checks |
|---|---|
| Income and employment | Salary compared across the pay stub, employment letter, T4 and NOA; tenure and probation; employer consistency |
| Variable / self-employed income | Bonus, commission and overtime use a 2-year average; self-employed income uses the 2-year NOA average; flag declining trends |
| Credit history and liabilities | Score, delinquencies, utilization; credit-report tradelines and bank-statement debits reconciled against declared debts |
| Debt service | GDS and TDS at both the contract rate and the qualifying (stress-test) rate |
| Down payment and source of funds | Minimum down payment tier; 90-day history; large deposits explained; gift letter if gifted |
| Assets and bank statements | Declared assets verified; closing costs (1.5% of price) covered; NSF and overdraft flags |
| Existing properties and mortgages | Their payments, taxes and heat go into TDS; rental income offset per policy |
| Unusual circumstances | LLM-written notes on anything unusual: recent job change, gaps, unusual transfers, and so on |

### 2. Property review
Evaluates the collateral risk.
| Area | Checks |
|---|---|
| Value / appraisal | Appraised value vs purchase price; lending value = lower of the two |
| Property type | Allowed types per product (e.g. condo minimum size, no rural acreage over the policy limit) |
| Location and marketability | Appraisal's marketability rating, days on market, rural or single-industry town flags |
| LTV | Loan ÷ lending value; tier → insured or conventional |
| Collateral verdict | Summary of whether the property provides sufficient security |

### 3. Policy application
Each layer is a separate YAML file under `policy/`, and the code holds no thresholds:
- `credit_policy.yaml`: lender credit policy and risk appetite (minimum score, GDS/TDS limits, exception authority)
- `products.yaml`: product rules (e.g. 5-yr fixed, 5-yr variable; amortization; LTV caps)
- `insurers.yaml`: CMHC / Sagen / Canada Guaranty requirements, applied when LTV > 80%
- `regulatory.yaml`: B-20 qualifying rate, minimum down payment tiers

**Recommended outcome, on a 4-step scale** (it is always labelled "Recommended"):
| Recommendation | When |
|---|---|
| Approve | All checks pass, no conditions beyond the standard ones |
| Approve with conditions | Passes policy, with open conditions |
| Refer for review | An exception case, an authenticity flag, or anything else that needs a human judgment |
| Decline | A hard policy failure with no viable exception path |

Below the recommendation, the underwriter clicks their own decision from the same four options. That decision is saved with the review.

### 4. Exception investigation
When a rule fails within a configurable margin (e.g. TDS within 2 points of the limit), the agent works through:
1. Additional verifiable income in the documents (e.g. a bonus in the T4 that wasn't declared)
2. Liabilities that could be excluded (e.g. a loan paid off before closing, with evidence)
3. Compensating strengths (score ≥ 760, liquid assets ≥ 6 months of payments, long tenure, low LTV)
4. Alternative products that fit (e.g. a longer amortization, a different product)
5. Whether policy allows an exception, and at what approval authority

The output is an **exception case**: the gap, what was found under each point, and the recomputed ratios where something changed. The ratios are recomputed in code. The LLM writes the narrative.

### 5. Conditions
Every finding that needs follow-up produces a condition tied to that finding, e.g. "Explain $25,000 deposit on Aug 22", "Provide 2023 and 2024 T1 Generals". Standard conditions are always included: confirmation of employment, insurance binder, and solicitor's instructions.

**Clearing a condition (one scripted scene, case 05):** the underwriter uploads a gift letter against the "Explain deposit" condition. The agent checks it: donor, relationship, amount matches the deposit, non-repayable. The condition turns ✅ and the recommendation updates. No full condition-tracking workflow.

## Output: the review report
Shown as an HTML page and saved as JSON:
1. **Recommended outcome** with reasons, and the underwriter's decision buttons
2. **Extracted application data**, for the underwriter to confirm
3. **Borrower review** findings
4. **Property review** findings
5. **Ratios:** GDS, TDS, LTV at the contract and qualifying rates, with inputs and formulas shown
6. **Policy checks**, by layer
7. **Exception case**, when there is one
8. **Authenticity and fraud flags**
9. **Conditions**, open or cleared

## Case record and data handling

**The agent's only persistent memory is a case-level review record** for the single application being assessed. It's stored at `cases/<case-id>/record.json`, alongside that case's extraction cache. It contains:
- case ID and review timestamps
- documents reviewed (filename + SHA-256 hash)
- extracted fields and calculated ratios
- policy and product versions used (each `policy/*.yaml` has a `version` field; the record stores the version and file hash)
- model ID and prompt version
- findings, with evidence references (document + field)
- conditions raised and cleared, with the clearing document
- the agent's recommendation, labelled "Recommended"
- the underwriter's final decision, with a timestamp

This makes every finding, condition and recommendation traceable back to its inputs and rules.

**No reusable borrower memory:**
- Nothing from one case is read while assessing another. No cross-case cache, index, embeddings or "similar cases" lookup.
- The extraction cache is per case (`cases/<case-id>/cache/`), not global. A file hash only ever matches within its own case.
- Prompts contain only the current case's documents plus fixed instructions. Any examples in prompts are hand-written and contain no case data.
- No borrower data in application logs (names, contact details, account numbers, SIN or other government IDs, credit details, income, transactions, document text). Logs record case ID, stage, timings and counts only.
- No borrower data used for training. API inputs are processed for the request only. In production, use a zero-data-retention agreement with the provider.
- The agent's behaviour comes only from code, prompts and policy files, which are versioned in git. It never changes based on previous cases.

**Prototype vs production:** in the prototype, all data is synthetic, and `cases/` exists only to support the demo and review of each case (`python -m underwriting.cli --purge <case-id>` deletes one). In production, case records would be access-controlled to authorized underwriting users and governed by the lender's retention, privacy and security requirements. That is out of scope here.

## Key design decisions
- **Calculations and policy rules live in deterministic code. The LLM does extraction and judgment.** The LLM reads documents into typed data and writes the narratives, the exception reasoning and the fraud reasoning. Python computes every ratio and evaluates every threshold, and unit tests cover it. A wrong ratio in front of leadership kills trust.
- **Policy is configuration.** A second lender later means another `policy/` folder, not a rewrite.
- **The recommendation comes from rules.** The outcome is derived in code from the findings, so it's repeatable. The LLM explains the outcome but doesn't choose it.

## Domain rules for v1 (standard Canadian placeholders)

| Rule | Value |
|---|---|
| Qualifying rate (stress test) | max(contract + 2%, 5.25%) |
| GDS / TDS max | 39% / 44% |
| GDS housing costs | principal and interest + property tax + heat (default $100/mo) + 50% of condo fees |
| Min down payment | 5% of the first $500K, 10% of $500K–$1.5M; 20% at or above $1.5M |
| Insured | LTV > 80%; max amortization 30 years (first-time buyer or new build), otherwise 25 |
| Conventional | LTV ≤ 80%; max amortization 30 years |
| Min credit score | 680 (insured: 600 for at least one borrower) |
| Variable / self-employed income | 2-year average |
| Rental income offset | 50% of gross rent added to income |
| Income docs: salaried | pay stub (≤30 days old) + employment letter |
| Down payment proof | 90-day bank history; gift letter if gifted |
| Exception margin | within 2 points of the GDS/TDS limit → exception investigation |

Canadian mortgage payments compound semi-annually. The payment math has to use that, and tests must cover it.

## Demo cases (synthetic)

| Case | Planted issue | Expected recommendation |
|---|---|---|
| `01-clean` | none | Approve (standard conditions only) |
| `02-inflated-income` | application says $92K, NOA says $68K | Decline: TDS fails at verified income, no exception path |
| `03-tampered-paystub` | YTD gross doesn't equal per-period gross × pay periods | Refer for review: authenticity flag |
| `04-hidden-debt` | $650/mo car payment in bank statements and credit report, not declared | Refer for review: undisclosed liability, TDS recalculated |
| `05-unexplained-deposit` | $25K deposit 40 days before closing, no gift letter | Approve with conditions → condition cleared after the gift letter upload |
| `06-self-employed` | stated income above the 2-yr NOA average; declining trend; owns a rental property | Approve with conditions: qualified on the 2-yr average, rental offset applied, financials condition |
| `07-exception` | strong borrower (score 810, 9 years' tenure, large savings), TDS 45.2% vs 44% | Refer for review, with an exception case: undeclared bonus in the T4 brings TDS within policy |

Every package includes a synthetic credit report and an appraisal with marketability data. A script generates the cases and writes an `expected.json` per case, so the planted issues are reproducible and tested.

## Tech Stack
- Python 3.12 (via uv; system Python is 3.9), Pydantic v2, FastAPI + uvicorn
- Claude (`claude-opus-5-5`) via the `anthropic` Python SDK; PDFs sent as document inputs; structured output into Pydantic models
- `reportlab` to generate the synthetic PDFs
- pytest

## Commands
```
Setup:    uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
Samples:  python -m scripts.generate_samples
Review:   python -m underwriting.cli samples/07-exception
Demo app: uvicorn app.main:app --reload
Test:     pytest -q
```

## Project Structure
```
underwriting/
  schemas.py         # Pydantic: Application, Borrower, Income, Liability, Asset, Property,
                     #   Finding, Evidence, ExceptionCase, Condition, Recommendation, Review
  extract.py         # LLM: PDF → typed data (per-case cache)
  ratios.py          # deterministic payment / GDS / TDS / LTV / stress test
  policy.py          # loads policy/*.yaml, evaluates rules → Findings
  borrower.py        # income, credit, liabilities, assets, down payment checks → Findings
  property.py        # appraisal, type, marketability, LTV, collateral → Findings
  authenticity.py    # deterministic tamper checks + LLM review → Findings
  exceptions.py      # exception investigation → ExceptionCase
  conditions.py      # findings → Conditions; evaluate a follow-up doc against a condition
  recommend.py       # findings → Recommendation (rule-based)
  review.py          # orchestrates the pipeline → Review
  case_record.py     # writes and reads cases/<case-id>/record.json; purge
  cli.py
policy/              # credit_policy, products, insurers, regulatory .yaml
app/                 # FastAPI: upload, progress, report, decision, condition upload
scripts/generate_samples.py
samples/
cases/               # per-case review records + caches (gitignored)
tests/
```

## Code Style
Small pure functions, typed throughout, every finding carries its evidence:
```python
def gds(monthly_pi: Decimal, property_tax: Decimal, heat: Decimal,
        condo_fees: Decimal, gross_monthly_income: Decimal) -> Decimal:
    housing = monthly_pi + property_tax + heat + condo_fees * Decimal("0.5")
    return (housing / gross_monthly_income * 100).quantize(Decimal("0.01"))

Finding(
    area=Area.BORROWER,
    check="income_reconciliation",
    status=Status.FAIL,
    message="Stated income exceeds NOA-verified income by 35%",
    evidence=[Evidence(doc="application", field="annual_income", value="92,000"),
              Evidence(doc="noa_2024.pdf", field="line_15000", value="68,000")],
)
```
Money is `Decimal`, never float. snake_case.

## Testing Strategy
- **Unit (pytest):** ratios, policy, recommendation rules and exception recomputation, with hand-computed values. A boundary test for every threshold.
- **Golden-case:** each of the 7 cases runs end to end and is checked against `expected.json`: the recommendation and the planted finding. Tests that need the LLM are marked `@pytest.mark.llm` and skipped without an API key.
- **Isolation:** a test runs two cases and asserts no file outside `cases/<id>/` is read or written during a review, that the caches don't overlap, and that captured logs contain none of the synthetic PII values from `expected.json`.
- **Traceability:** a test asserts every finding's evidence points to a document listed in the record, and that the record contains the policy versions and the decision.
- **Manual:** a full demo rehearsal in the browser, including the condition-clearing scene.

## Boundaries
- **Always:**
  - Keep the math deterministic and tested.
  - Every finding has evidence.
  - Use synthetic data only.
  - The outcome is labelled "Recommended", and the decision is the underwriter's click.
  - Every review writes a complete case record.
- **Ask first:**
  - Adding dependencies.
  - Changing policy defaults.
  - Changing the report structure.
  - Expanding condition management beyond the scripted scene.
- **Never:**
  - Real borrower data.
  - Committing API keys.
  - LLM-computed ratios.
  - An LLM choosing the recommendation.
  - The system recording a decision the underwriter didn't click.
  - Cross-case memory of any kind.
  - Borrower data in logs.
  - Committing `cases/`.

## Success Criteria
1. All 7 cases produce the expected recommendation and planted finding, with correct evidence, 5 runs out of 5.
2. Ratios, including exception recomputations, match hand calculations (unit tests pass).
3. Upload to finished report takes under 3 minutes per case.
4. Case 07 shows a complete exception case covering all five investigation points.
5. Case 05's condition clears after the gift letter upload, and the recommendation updates.
6. A non-technical viewer can follow the flow; no JSON or terminal is shown.
7. Changing a value in `policy/*.yaml` changes the outcome without any code change.
8. Every case has a record from which each finding, condition and the recommendation can be traced to its documents and policy versions; isolation and log tests pass.

## Out of Scope
- Real data
- POS or LOS integration
- Multi-lender setup
- Full condition-tracking workflow
- Funding
- Hosting or auth

## Open Questions
None.
