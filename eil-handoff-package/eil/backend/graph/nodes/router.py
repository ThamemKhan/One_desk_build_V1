from dataclasses import dataclass

from backend.catalog import load_catalog
from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.engine.tiers import compute_tier
from backend.graph.state import RequestState
from backend.models import Department


@dataclass
class _RuleResultView:
    """compute_tier expects RuleResult-shaped attributes; rule_results on
    state are plain dicts (JSON-serialisable), so adapt rather than duplicate
    the tiering logic here.
    """

    applicable: bool
    passed: bool
    hard_block: bool
    tier_override: int | None
    exceptionable: bool
    adds_approval: bool


def run(state: RequestState) -> dict:
    service_id = state["service_id"]
    rule_results = state.get("rule_results", [])

    catalog = load_catalog()
    service = catalog.get(service_id, {})
    base_tier = service.get("base_tier", 1)

    views = [
        _RuleResultView(
            applicable=r.get("applicable", False),
            passed=r.get("passed", True),
            hard_block=r.get("hard_block", False),
            tier_override=r.get("tier_override"),
            exceptionable=r.get("exceptionable", False),
            adds_approval=r.get("adds_approval", False),
        )
        for r in rule_results
    ]
    tier = compute_tier(base_tier, views)

    department_id = service.get("owning_department_id")
    reason = "Default service ownership"
    clause_ref = None

    routing_correction = next(
        (
            r
            for r in rule_results
            if r.get("applicable") and not r.get("passed") and r.get("routing_correction")
        ),
        None,
    )
    if routing_correction and routing_correction.get("approver_department_id"):
        department_id = routing_correction["approver_department_id"]
        reason = routing_correction.get("message") or f"Routing correction: {routing_correction['rule_id']}"
        clause_ref = routing_correction.get("approver_clause_ref") or routing_correction.get("clause_ref")

    session = SessionLocal()
    try:
        approvals: list[dict] = []
        if tier >= 2:
            department = session.get(Department, department_id) if department_id else None
            approvals.append(
                {
                    "department_id": department_id,
                    "approver_id": department.head_employee_id if department else None,
                    "sequence": 1,
                    "reason": reason,
                    "clause_ref": clause_ref,
                    "status": "PENDING",
                }
            )

            for result in rule_results:
                if result.get("applicable") and not result.get("passed") and result.get("adds_approval"):
                    extra_dept_id = result.get("approver_department_id")
                    if not extra_dept_id or extra_dept_id == department_id:
                        continue
                    extra_dept = session.get(Department, extra_dept_id)
                    approvals.append(
                        {
                            "department_id": extra_dept_id,
                            "approver_id": extra_dept.head_employee_id if extra_dept else None,
                            "sequence": len(approvals) + 1,
                            "reason": result.get("message") or f"{result['rule_id']} requires additional approval",
                            "clause_ref": result.get("approver_clause_ref"),
                            "status": "PENDING",
                        }
                    )

        route = {
            "department_id": department_id,
            "approver_id": approvals[0]["approver_id"] if approvals else None,
            "reason": reason,
            "clause_ref": clause_ref,
        }

        with record_decision(session, state["request_id"], "ROUTE", "RULE_ENGINE", "engine.router") as rec:
            rec.inputs_used = {"service_id": service_id, "tier": tier}
            rec.output = {"route": route, "approvals": approvals, "tier": tier}
            rec.rationale = f"Routed to {department_id} at tier {tier}"
    finally:
        session.close()

    return {"tier": tier, "route": route, "approvals": approvals}
