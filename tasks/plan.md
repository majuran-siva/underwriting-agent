# Implementation Plan: Underwriting Review Agent (Leadership Demo)

Spec: [../SPEC.md](../SPEC.md). Tasks: [todo.md](todo.md).

## Overview
A Python pipeline turns an application package (an application PDF plus supporting PDFs) into a review report. Claude extracts the documents into typed data. Deterministic code computes the ratios and checks policy. Reconciliation and authenticity checks add findings that cite their evidence. A small FastAPI app shows the upload, the progress and the report to a non-technical audience.

## Architecture Decisions
- **Pipeline:** extract → compute → check → assemble. Each stage is a plain function over Pydantic models and returns `Finding`s. The stages can be tested on their own.
- **Math is code only.** `ratios.py` has no LLM dependency. Money is `Decimal`. Payments use semi-annual compounding.
- **Policy from YAML.** `policy.py` reads `policy/lender_policy.yaml`. There are no thresholds in code.
- **Extraction is cached per case.** Results are saved under `cases/<id>/cache/` so demo reruns are fast and repeatable. The cache is never shared across cases (see the spec's data handling section).
- **Case record is the only persistent state.** `case_record.py` owns `cases/<id>/record.json`; nothing else persists.
- **Ground truth from the generator.** `generate_samples.py` writes the PDFs and an `expected.json` listing the planted issues. The golden tests compare against that file.
- **Vertical first.** The clean case runs end to end through the command line before any fraud checks are built.

- **Recommendation is rule-based.** `recommend.py` maps findings to the 4-step outcome, so results are repeatable. The LLM only explains.
- **Exceptions recompute in code.** The exception investigation reuses `ratios.py`. The LLM writes the narrative only.

## Phases
1. **Foundation:** Tasks 1–4. Schemas, ratios, layered policy, recommendation rules. No LLM.
2. **First slice:** Tasks 5–7. Case 01 runs end to end from the command line. This retires the extraction risk early.
3. **Borrower and property review:** Tasks 8–13, cases 02–06.
4. **Exceptions and conditions:** Tasks 14–15. Case 07 and the gift letter scene.
5. **Demo:** Tasks 16–18. Report, app, rehearsal.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Claude misreads a value in a PDF | High | Generated PDFs are clean text; the report shows the extracted data for the underwriter to confirm; golden tests check extraction against `expected.json`; caching keeps the demo repeatable |
| A detection is inconsistent between runs | High | Run the check in code wherever possible (YTD arithmetic, amount matching); the LLM only adds explanation; run each case 5 times before the demo |
| Over 3 minutes per case | Med | Extract documents in parallel; cache results; time it in Task 14 |
| Placeholder policy numbers are wrong | Med | Unit tests cite their source rule; values live only in YAML |
| An API key ends up in git | Med | `.env` + `.gitignore` from Task 1 |

## Open Questions
None.
