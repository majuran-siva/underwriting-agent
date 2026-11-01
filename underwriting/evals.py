"""Eval: run the agent on every inbox file and compare the result with the answer set by hand for that file.

Expected values are written here on purpose rather than taken from the agent, so a change in behaviour fails.
Document reading is simulated in the prototype, so this tests the checks, math and rules, not reading accuracy.
"""
from __future__ import annotations

from underwriting import agent, decisions
from underwriting.demo_cases import CASES

EXPECTED = {
    "case01": {"recommendation": "approve", "gds": "24.85", "tds": "28.11", "ltv": "75.00", "issues": []},
    "case02": {"recommendation": "refer_for_review", "gds": "36.44", "tds": "44.91", "ltv": "75.00",
               "issues": ["large_deposit", "self_employed_average", "tds_limit", "undisclosed_debt"]},
    "case03": {"recommendation": "refer_for_review", "gds": "35.93", "tds": "45.65", "ltv": "78.85",
               "issues": ["low_confidence", "missing_document", "tds_limit", "undisclosed_debt"]},
    "case04": {"recommendation": "refer_for_review", "gds": "36.81", "tds": "36.81", "ltv": "75.00",
               "issues": ["income_mismatch"]},
    "case05": {"recommendation": "refer_for_review", "gds": "38.36", "tds": "39.26", "ltv": "76.92",
               "issues": ["hidden_instruction", "paystub_ytd", "pdf_edited"], "approval_blocked": True},
    "case06": {"recommendation": "approve_with_conditions", "gds": "28.49", "tds": "41.05", "ltv": "72.41",
               "issues": ["low_confidence", "missing_document", "self_employed_average"]},
}
RECOMMENDATION_LABELS = {"approve": "Approve", "approve_with_conditions": "Approve with conditions",
                         "refer_for_review": "Refer for review", "decline": "Decline"}


def _check(name: str, expected, actual) -> dict:
    return {"name": name, "expected": expected, "actual": actual, "passed": expected == actual}


def run_case(case: dict, expected: dict) -> dict:
    result = agent.run(case)
    ratios = result["ratios"]
    label = lambda rec: RECOMMENDATION_LABELS.get(rec, rec)
    checks = [
        _check("Recommendation", label(expected["recommendation"]), label(result["recommendation"])),
        _check("GDS", expected["gds"], str(ratios["gds_qualifying"])),
        _check("TDS", expected["tds"], str(ratios["tds_qualifying"])),
        _check("LTV", expected["ltv"], str(ratios["ltv"])),
        _check("Issues found, none invented", sorted(expected["issues"]), sorted({f["check"] for f in result["flags"]})),
    ]
    if "approval_blocked" in expected:
        review = {"flag_reviews": {}, "condition_reviews": {}, "confirmed_docs": [], "declined_docs": []}
        approve = next(o for o in decisions.options(result, review) if o["id"] == "approve")
        checks.append(_check("Approval blocked", expected["approval_blocked"], not approve["allowed"]))
    return {"id": case["id"], "app_no": case["pos"]["app_no"], "title": case["title"],
            "expected": label(expected["recommendation"]), "actual": label(result["recommendation"]),
            "checks": checks, "passed": all(c["passed"] for c in checks)}


def run_all() -> dict:
    files = [run_case(case, EXPECTED[case["id"]]) for case in CASES]
    checks = [c for f in files for c in f["checks"]]
    return {"files": files, "files_passed": sum(f["passed"] for f in files), "files_total": len(files),
            "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks)}
