from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.graph.state import RequestState
from backend.llm.client import call_llm
from backend.llm.prompts import EXPLAIN_DECISION_SYSTEM, build_explain_decision_prompt
from backend.models import DecisionRecord

# Stages whose records carry the substance of the decision. COMMUNICATE is
# excluded so a re-run never narrates its own previous narration.
_NARRATABLE_STAGES = ("INTENT", "CONTEXT", "CLARIFY", "POLICY", "EXCEPTION", "ROUTE", "APPROVAL")


def _compute_outcome(state: RequestState) -> str | None:
    """Deterministic (SPEC §2 / invariant 1) — the LLM narrates this, never sets it.

    approval.py already sets APPROVED/REJECTED for the human-authorized paths;
    this fills in the two paths that reach communicate without passing through
    an approval: a hard block, and a tier <= 1 auto-execute (SPEC §8, §11).
    """
    if state.get("outcome"):
        return state["outcome"]
    if state.get("halt_reason"):
        return None  # escalated to a human; no outcome has been decided
    violated = [r for r in state.get("rule_results", []) if r.get("applicable") and not r.get("passed")]
    if any(r.get("hard_block") for r in violated):
        return "REJECTED"
    if state.get("route") and not any(a.get("status") == "PENDING" for a in state.get("approvals", [])):
        if state.get("tier", 0) <= 1:
            return "AUTO_APPROVED"
    return None


def _fallback_explanation(state: RequestState, outcome: str | None) -> str:
    """Used when the narration call fails. The decision is already made and
    recorded by this point, so a gateway problem must not fail the request —
    it only costs us the prose.
    """
    violated = [r for r in state.get("rule_results", []) if r.get("applicable") and not r.get("passed")]
    parts: list[str] = []

    if state.get("halt_reason"):
        parts.append(f"Escalated to a human service desk ({state['halt_reason']}).")
    elif outcome == "REJECTED":
        parts.append("This request cannot proceed.")
    elif outcome == "AUTO_APPROVED":
        parts.append("Approved automatically — within policy and low risk.")
    elif outcome == "APPROVED":
        parts.append("All required approvals are complete.")

    for r in violated:
        cite = f" ({r['clause_ref']})" if r.get("clause_ref") else ""
        parts.append(f"{r['rule_id']}: requested {r.get('actual')} against limit {r.get('limit')}{cite}.")

    pending = [a for a in state.get("approvals", []) if a.get("status") == "PENDING"]
    for a in pending:
        cite = f" ({a['clause_ref']})" if a.get("clause_ref") else ""
        parts.append(f"Awaiting approval from {a.get('department_id')}: {a.get('reason')}{cite}.")

    return " ".join(parts) or "Request recorded."


def run(state: RequestState) -> dict:
    """EXPLAIN_DECISION (SPEC §13 #3) — narrates in plain English what the rule
    engine already decided, citing only clauses already retrieved for this
    request. It must not introduce a rule, approver or limit of its own.
    """
    outcome = _compute_outcome(state)
    clause_texts = [
        {"clause_ref": hit["clause_ref"], "text": hit.get("text", "")}
        for hit in state.get("clause_hits", [])
    ]

    session = SessionLocal()
    try:
        rows = (
            session.query(DecisionRecord)
            .filter(DecisionRecord.request_id == state["request_id"])
            .filter(DecisionRecord.stage.in_(_NARRATABLE_STAGES))
            .order_by(DecisionRecord.created_at)
            .all()
        )
        records = [
            {
                "stage": r.stage,
                "actor": r.actor,
                "rule_fired": r.rule_fired,
                "clause_refs": r.clause_refs,
                "rationale": r.rationale,
                "output": r.output,
            }
            for r in rows
        ]

        prompt = build_explain_decision_prompt(records, clause_texts)
        try:
            result = call_llm(
                session, state["request_id"], "COMMUNICATE", prompt, EXPLAIN_DECISION_SYSTEM
            )
            explanation = (result.get("explanation") or "").strip() or _fallback_explanation(state, outcome)
        except Exception as exc:
            explanation = _fallback_explanation(state, outcome)
            with record_decision(
                session, state["request_id"], "COMMUNICATE", "RULE_ENGINE", "communicate.fallback"
            ) as rec:
                rec.inputs_used = {"error": f"{type(exc).__name__}: {exc}"}
                rec.output = {"explanation": explanation}
                rec.rationale = "Narration call failed; fell back to a deterministic summary."

        with record_decision(
            session, state["request_id"], "COMMUNICATE", "RULE_ENGINE", "communicate"
        ) as rec:
            rec.inputs_used = {"outcome": outcome, "halt_reason": state.get("halt_reason")}
            rec.clause_refs = [c["clause_ref"] for c in clause_texts]
            rec.output = {"outcome": outcome, "explanation": explanation}
            rec.rationale = f"Communicated outcome: {outcome or state.get('halt_reason') or 'IN_PROGRESS'}"
    finally:
        session.close()

    update: dict = {
        "explanation": explanation,
        "messages": state.get("messages", []) + [{"role": "assistant", "content": explanation}],
    }
    if outcome:
        update["outcome"] = outcome
    return update
