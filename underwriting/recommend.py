"""Rule-based recommended outcome. Deterministic so the same file always gets the same recommendation;
the LLM may explain it but never chooses it. The underwriter makes the decision."""
from underwriting.schemas import Area, Condition, ConditionStatus, Finding, Recommendation, Status


def recommend(findings: list[Finding], conditions: list[Condition]) -> tuple[Recommendation, list[str]]:
    hard_fails = [f for f in findings if f.status == Status.FAIL and not f.near_miss]
    if hard_fails:
        return Recommendation.DECLINE, [f"Fails policy: {f.check} ({f.message})" for f in hard_fails]

    referrals = [f for f in findings if f.status != Status.PASS and
                 (f.near_miss or f.needs_referral or f.area == Area.AUTHENTICITY)]
    if referrals:
        return Recommendation.REFER, [f"Needs underwriter judgment: {f.check} ({f.message})" for f in referrals]

    open_conditions = [c for c in conditions if c.status == ConditionStatus.OPEN and c.raised_by]
    attention = [f for f in findings if f.status == Status.ATTENTION]
    if open_conditions or attention:
        reasons = [f"Open condition: {c.text} (from {c.raised_by})" for c in open_conditions]
        reasons += [f"Attention: {f.check} ({f.message})" for f in attention
                    if not any(c.raised_by == f.check for c in open_conditions)]
        return Recommendation.APPROVE_WITH_CONDITIONS, reasons

    return Recommendation.APPROVE, ["All checks pass; only standard conditions remain"]
