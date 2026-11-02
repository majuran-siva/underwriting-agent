# ClearLine

A prototype agent for Canadian mortgage underwriters. It does the first review of a broker's file and drafts a complete conditions list, which is everything the broker must provide. The underwriter reviews the work and makes every decision.

**The agent decides what to look at. Fixed code decides the numbers. The underwriter decides the outcome.**

All data is synthetic, and the lender, Maple Ridge Mortgage Co., is fictional. This is a capstone prototype, not financial advice or a production system.

## What it does

1. Takes a loan file from a simulated broker inbox on the Demo Dashboard.
2. Identifies the documents and marks anything missing or hard to read.
3. Cross-checks income, debts and deposits, and flags what doesn't match.
4. Calculates GDS, TDS and LTV against lender policy using fixed, tested code.
5. Drafts one broker email with the full review and conditions.
6. Blocks decisions the file can't support, and leaves every decision and send to the underwriter.

The Eval page runs all six sample files against a hand-set answer key and shows the reviewer's verdict for each.

## Limits

- **Reading is simulated.** Sample files carry a marker linked to prepared figures, so accuracy on real documents is untested.
- **No live AI model is connected.** The agent's steps and findings come from fixed code and prepared data.
- **No real systems are connected.** Emails go to a simulated inbox, and there is no sign-in.
- **State is in memory and shared.** Everyone using a running copy sees the same session, and it resets on restart.
- **Figures in the project documents are estimates** that still need to be validated with lenders.

## Run it locally

Requires Python 3.12.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
```

Then open http://localhost:8000.

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

## Host it

`render.yaml` describes a free web service for [Render](https://render.com). In Render, choose **New › Blueprint** and connect this repository. GitHub Pages can't run this app, because it needs a Python server.

## Project documents

- [PRD](PRD-underwriting-package-agent.md)
- [Design partner plan](design-partner-plan.md)
