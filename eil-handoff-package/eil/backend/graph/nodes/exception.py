import uuid

from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.graph.state import RequestState
from backend.models import ExceptionRecord

# SPEC gives no formula for risk_score/risk_band from a rule's severity.
# Mapped deterministically from the severity already authored on the rule.
_SEVERITY_RISK_SCORE = {"LOW": 25, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 100}


def _risk_band(risk_score: int) -> str:
    if risk_score >= 70:
        return "HIGH"
    if risk_score >= 40:
        return "MEDIUM"
    return "LOW"


def run(state: RequestState) -> dict:
    """Creates the Exception object (SPEC §4.7) for the exceptionable
    violation found in POLICY. RequestState.exception_draft is a single dict,
    so this handles the first (in Scenario A, the only) exceptionable
    violation.
    """
    rule_results = state.get("rule_results", [])
    violation = next(
        (r for r in rule_results if r.get("applicable") and not r.get("passed") and r.get("exceptionable")),
        None,
    )
    if violation is None:
        return {}

    risk_score = _SEVERITY_RISK_SCORE.get(violation.get("severity"), 50)
    actual, limit = violation.get("actual"), violation.get("limit")
    delta = actual - limit if isinstance(actual, (int, float)) and isinstance(limit, (int, float)) else None

    draft = {
        "id": f"EXC-{uuid.uuid4().hex[:8].upper()}",
        "request_id": state["request_id"],
        "violated_rule_id": violation["rule_id"],
        "clause_refs": [violation["clause_ref"]],
        "requested_value": actual,
        "policy_limit": limit,
        "delta": delta,
        "justification": None,
        "evidence": [],
        "risk_score": risk_score,
        "risk_band": _risk_band(risk_score),
        "compensating_controls": violation.get("compensating_controls", []),
        "approver_id": None,
        "status": "DRAFT",
        "expires_at": None,
        "review_due_at": None,
    }

    session = SessionLocal()
    try:
        session.add(ExceptionRecord(**draft))

        with record_decision(session, state["request_id"], "EXCEPTION", "RULE_ENGINE", violation["rule_id"]) as rec:
            rec.inputs_used = {"violation": violation}
            rec.clause_refs = [violation["clause_ref"]]
            rec.rule_fired = violation["rule_id"]
            rec.output = draft
            rec.rationale = f"Exception drafted for {violation['rule_id']} (risk={draft['risk_band']})"
    finally:
        session.close()

    return {"exception_draft": draft}
