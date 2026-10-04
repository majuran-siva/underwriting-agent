# Intent: Underwriting Review Agent (Leadership Demo)

Confirmed 2026-10-04.

- **Outcome:**
  - **Input:** An application package made of an application form (PDF) plus supporting documents, uploaded together.
  - **Output:** A completed underwriting review: extracted borrower data, ratio checks, document reconciliation, fraud flags, items that need attention, and suggested conditions.
- **User:** Underwriters at one Canadian lender. The underwriter makes the final decision.
- **Why now:** Reviewing a file takes days today. This shows leadership that it can take minutes.
- **What it checks:**
  - GDS, TDS and LTV, with the stress test, against policy
  - Down payment, income, debt and property risk
  - Consistency across documents
  - Signs of fake or altered documents
- **Success:** In the demo, leadership watches a familiar-looking application go in. Within minutes they see a review that catches the planted problems, with evidence for every flag.
- **Constraint:** Synthetic data only. No POS access. One lender's policy, without hardcoding it so tightly that adding lenders later is impossible.
- **Out of scope:**
  - Real borrower data
  - POS or LOS integration
  - A multi-lender setup
  - Automated approve or deny decisions
  - A polished intake form
