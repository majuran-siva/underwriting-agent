# Tasks

Verify every task with `pytest -q` unless it says otherwise. Tests that call the LLM need `ANTHROPIC_API_KEY` set.

## Phase 1: Foundation (no LLM)

- [x] **Task 1: Scaffold, schemas, policy files** (M)
  - Accept: `requirements.txt`, `.gitignore` (incl. `cases/`, `.env`)/`.env.example`, `git init`; the schemas from the spec including `CaseRecord`; 4 policy YAMLs with the placeholder values and a `version` field each.
  - Verify: a test builds a sample Application and loads all the policy files.
  - Files: requirements.txt, underwriting/schemas.py, policy/*.yaml, tests/test_schemas.py
  - Depends: none

- [x] **Task 2: Ratio math (TDD)** (S)
  - Accept: semi-annual compounding payment, qualifying rate, GDS, TDS (including existing-property costs and the rental offset), LTV on lending value, minimum down payment.
  - Verify: hand-computed cases, plus boundaries at $500K, $1.5M, the 5.25% floor and 80% LTV.
  - Files: underwriting/ratios.py, tests/test_ratios.py
  - Depends: 1

- [x] **Task 3: Policy evaluation** (M)
  - Accept: evaluates the credit, product, insurer and regulatory layers → Findings with evidence; detects "near miss" within the exception margin.
  - Verify: a boundary test per rule; changing a YAML value flips the result.
  - Files: underwriting/policy.py, tests/test_policy.py
  - Depends: 2

- [ ] **Task 4: Recommendation rules** (S)
  - Accept: findings → Approve / Approve with conditions / Refer / Decline, following the spec table.
  - Verify: unit tests for each outcome.
  - Files: underwriting/recommend.py, tests/test_recommend.py
  - Depends: 1

### Checkpoint A: Foundation
- [ ] Tests pass. You check the ratio outputs against a calculator you trust.

## Phase 2: First vertical slice (case 01)

- [ ] **Task 5: Sample generator, clean case** (M)
  - Accept: `samples/01-clean/` with the application, pay stub, T4, NOA, employment letter, bank statements, credit report, appraisal (with marketability) and purchase agreement, plus expected.json.
  - Verify: open the PDFs; they look realistic and match expected.json.
  - Files: scripts/generate_samples.py, scripts/pdf_templates.py
  - Depends: 1

- [ ] **Task 6: Claude extraction** (M) ⚠ highest risk
  - Accept: each PDF → a typed model via `claude-opus-5-5`; cached per case in `cases/<id>/cache/`; documents processed in parallel; logs record no document content.
  - Verify: an `@llm` test checks case 01's extracted values against expected.json.
  - Files: underwriting/extract.py, underwriting/cache.py, tests/test_extract.py
  - Depends: 5

- [ ] **Task 7: Pipeline, case record, command line** (M)
  - Accept: `python -m underwriting.cli samples/01-clean` → `cases/01-clean/record.json` with the document hashes, extracted fields, ratios, policy versions, model and prompt version, findings, standard conditions and the recommendation "Approve with conditions"; `--purge` deletes a case.
  - Verify: an `@llm` golden test for case 01, plus a traceability test.
  - Files: underwriting/review.py, underwriting/case_record.py, underwriting/conditions.py, underwriting/cli.py, tests/test_golden.py
  - Depends: 3, 4, 6

### Checkpoint B: First slice
- [ ] Case 01 runs end to end in under 3 minutes. You review the report content before the checks are added.

## Phase 3: Borrower and property review

- [ ] **Task 8: Income reconciliation + case 02** (M)
  - Accept: income compared across documents; TDS recomputed at verified income; case 02 → Decline with evidence from both sources.
  - Files: underwriting/borrower.py, scripts/generate_samples.py, tests/test_borrower.py
  - Depends: 7

- [ ] **Task 9: Authenticity + case 03** (M)
  - Accept: pay stub YTD arithmetic, name/date/employer consistency in code, plus an LLM review note; case 03 → Refer.
  - Files: underwriting/authenticity.py, scripts/generate_samples.py, tests/test_authenticity.py
  - Depends: 7

- [ ] **Task 10: Credit and liabilities + case 04** (M)
  - Accept: score/delinquency/utilization checks; credit report and bank debits reconciled against declared debts; case 04 → Refer, TDS recalculated.
  - Files: underwriting/borrower.py, scripts/generate_samples.py, tests/test_borrower.py
  - Depends: 8

- [ ] **Task 11: Down payment, assets, unusual circumstances + case 05 (initial)** (M)
  - Accept: 90-day history, large-deposit detection, closing costs covered, NSF flags, LLM "unusual circumstances" note; case 05 → Approve with conditions, with a condition to explain the deposit.
  - Files: underwriting/borrower.py, scripts/generate_samples.py, tests/test_borrower.py
  - Depends: 8

- [ ] **Task 12: Self-employed, variable income, existing properties + case 06** (M)
  - Accept: 2-yr averages, declining trend flag, rental offset, existing mortgage in TDS; case 06 → Approve with conditions.
  - Files: underwriting/borrower.py, scripts/generate_samples.py, tests/test_borrower.py
  - Depends: 10

- [ ] **Task 13: Property review** (M)
  - Accept: lending value, property type rules, marketability flags, LTV tier, collateral verdict; present in all cases.
  - Verify: unit tests + golden cases still pass.
  - Files: underwriting/property.py, tests/test_property.py
  - Depends: 7

### Checkpoint C: Reviews complete
- [ ] Cases 01–06 pass their golden tests. You review every report.

## Phase 4: Exceptions and conditions

- [ ] **Task 14: Exception investigation + case 07** (M)
  - Accept: a near-miss triggers the 5-point investigation; ratios recomputed in code; LLM narrative; case 07 → Refer with an exception case showing the bonus brings TDS within policy.
  - Files: underwriting/exceptions.py, scripts/generate_samples.py, tests/test_exceptions.py
  - Depends: Checkpoint C

- [ ] **Task 15: Condition clearing (case 05 scene)** (S)
  - Accept: evaluating `followup/gift-letter.pdf` against the deposit condition → cleared, with evidence; the recommendation updates; the case record shows the condition raised → cleared and the clearing document.
  - Files: underwriting/conditions.py, scripts/generate_samples.py, tests/test_conditions.py
  - Depends: 11

- [ ] **Task 15b: Isolation and privacy tests** (S)
  - Accept: two-case test confirms no reads or writes outside `cases/<id>/` and no shared cache; log capture contains no synthetic PII from expected.json.
  - Files: tests/test_isolation.py, underwriting/logging.py
  - Depends: 7

### Checkpoint D: Logic complete
- [ ] All 7 golden cases pass, including the condition scene. Isolation and traceability tests pass.

## Phase 5: Demo

- [ ] **Task 16: HTML report** (M)
  - Accept: the spec's report sections; the "Recommended" banner; the exception case panel; the conditions list.
  - Verify: manual check of all 7 cases in the browser.
  - Files: app/templates/report.html, app/render.py, app/static/
  - Depends: Checkpoint D

- [ ] **Task 17: Upload app, decision buttons, condition upload** (M)
  - Accept: upload page with step progress; report page; underwriter decision buttons write the decision and a timestamp to the case record; upload a document against a condition; a "Review record" view shows the policy versions and documents used.
  - Verify: run all 7 cases plus the gift letter scene in the browser.
  - Files: app/main.py, app/templates/upload.html, app/templates/report.html
  - Depends: 16

- [ ] **Task 18: Hardening and rehearsal** (S)
  - Accept: each case correct in 5/5 runs; timing under 3 minutes recorded; README with demo script; works offline from cache.
  - Verify: a full rehearsal.
  - Files: README.md, tests/test_golden.py
  - Depends: 17

### Checkpoint E: Demo ready
- [ ] All spec success criteria met. Final walkthrough with you.
