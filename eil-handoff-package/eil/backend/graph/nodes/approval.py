from datetime import datetime, timezone

from langgraph.types import interrupt

from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.graph.state import RequestState
from backend.models import Approval as ApprovalModel


def run(state: RequestState) -> dict:
    """Uses LangGraph interrupt() so the graph checkpoints to SQLite and
    resumes when a human posts a decision (SPEC §5) — this is how approvals
    survive a process restart.

    Resolves exactly ONE pending approval per invocation, then relies on a
    self-loop conditional edge (see build.py) to come back for the next one.
    A node that calls interrupt() more than once replays everything before
    the still-pending interrupt on every resume — including side effects —
    so any DB write made for an already-resolved approval would re-run (and
    collide on its primary key) every time a later approval in the same
    sequence resumes. One interrupt per invocation avoids that entirely.
    """
    approvals = state.get("approvals", [])
    pending = next((a for a in approvals if a.get("status") == "PENDING"), None)
    if pending is None:
        return {}

    decision = interrupt(
        {
            "request_id": state["request_id"],
            "department_id": pending.get("department_id"),
            "approver_id": pending.get("approver_id"),
            "sequence": pending.get("sequence"),
            "reason": pending.get("reason"),
            "clause_ref": pending.get("clause_ref"),
        }
    )

    status = decision.get("status", "REJECTED")
    comment = decision.get("comment")
    decided_by = decision.get("approver_id") or pending.get("approver_id") or "unknown"

    updated_approval = {
        **pending,
        "status": status,
        "comment": comment,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    updated_approvals = [
        updated_approval if a.get("sequence") == pending.get("sequence") else a for a in approvals
    ]

    session = SessionLocal()
    try:
        with record_decision(session, state["request_id"], "APPROVAL", "HUMAN", decided_by) as rec:
            rec.inputs_used = {"approval": pending}
            rec.clause_refs = [pending["clause_ref"]] if pending.get("clause_ref") else []
            rec.output = updated_approval
            rec.rationale = comment or f"{status} by {decided_by}"

        session.add(
            ApprovalModel(
                id=f"APR-{state['request_id']}-{pending.get('sequence', 1)}",
                request_id=state["request_id"],
                approver_id=decided_by,
                sequence=pending.get("sequence", 1),
                reason=pending.get("reason"),
                required_by_clause_ref=pending.get("clause_ref"),
                status=status,
                decided_at=datetime.now(timezone.utc),
                comment=comment,
            )
        )
        session.commit()
    finally:
        session.close()

    result: dict = {"approvals": updated_approvals}
    if status == "REJECTED":
        result["outcome"] = "REJECTED"
    elif not any(a.get("status") == "PENDING" for a in updated_approvals):
        result["outcome"] = "APPROVED"
    return result
