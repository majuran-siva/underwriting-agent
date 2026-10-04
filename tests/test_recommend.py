from underwriting.recommend import recommend
from underwriting.schemas import Area, Condition, Finding, Recommendation, Status


def f(status=Status.PASS, area=Area.POLICY, check="x", near_miss=False, needs_referral=False):
    return Finding(area=area, check=check, status=status, message=check,
                   near_miss=near_miss, needs_referral=needs_referral)


STANDARD = [Condition(id="S1", text="Confirmation of employment")]
FROM_FINDING = Condition(id="C1", text="Explain deposit", raised_by="large_deposit")


def test_all_pass_with_only_standard_conditions_is_approve():
    rec, reasons = recommend([f(), f()], STANDARD)
    assert rec == Recommendation.APPROVE and reasons


def test_open_finding_condition_is_approve_with_conditions():
    rec, reasons = recommend([f(), f(Status.ATTENTION, Area.BORROWER, "large_deposit")], STANDARD + [FROM_FINDING])
    assert rec == Recommendation.APPROVE_WITH_CONDITIONS
    assert any("large_deposit" in r for r in reasons)


def test_cleared_condition_no_longer_counts():
    cleared = FROM_FINDING.model_copy(update={"status": "cleared"})
    rec, _ = recommend([f()], STANDARD + [cleared])
    assert rec == Recommendation.APPROVE


def test_near_miss_is_refer():
    rec, reasons = recommend([f(Status.FAIL, check="tds_limit", near_miss=True)], STANDARD)
    assert rec == Recommendation.REFER and any("tds_limit" in r for r in reasons)


def test_authenticity_flag_is_refer():
    rec, _ = recommend([f(Status.ATTENTION, Area.AUTHENTICITY, "paystub_ytd")], STANDARD)
    assert rec == Recommendation.REFER


def test_needs_referral_is_refer():
    rec, _ = recommend([f(Status.ATTENTION, Area.BORROWER, "undisclosed_liability", needs_referral=True)], STANDARD)
    assert rec == Recommendation.REFER


def test_hard_fail_is_decline_and_outranks_refer():
    findings = [f(Status.FAIL, check="tds_limit"), f(Status.ATTENTION, Area.AUTHENTICITY, "paystub_ytd")]
    rec, reasons = recommend(findings, STANDARD)
    assert rec == Recommendation.DECLINE and any("tds_limit" in r for r in reasons)
