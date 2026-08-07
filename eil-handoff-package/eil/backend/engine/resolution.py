import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy.orm import Session

from backend.catalog import load_catalog
from backend.engine.decisions import record_decision
from backend.engine.ownership import build_graph, find_cycles
from backend.models import Clause, DecisionRecord, Department, OwnershipEdge, Policy, Request, RoutingRule

OWNERSHIP_MATRIX_PATH = (
    Path(__file__).resolve().parent.parent.parent / "seed" / "ownership_matrix.yaml"
)

_matrix = yaml.safe_load(OWNERSHIP_MATRIX_PATH.read_text(encoding="utf-8"))
POLICY_CLASS_ORDER: list[str] = _matrix["precedence"]["policy_class_order"]

RESOLUTION_ACTOR_ID = "ownership_resolution"


@dataclass
class CycleResolution:
    service_id: str
    cycle: list[str]
    cycle_edge_ids: list[str]
    winning_edge_id: str
    governing_clause: str
    governing_policy_id: str
    governing_policy_version: str
    correct_approver_department_id: str
    correct_approver_employee_id: str | None
    losing_edge_ids: list[str]
    edges_invalidated: list[str]
    precedence_rule_applied: str
    governing_reason: str
    hr_approval_required: bool


@dataclass
class AppliedResolution:
    resolution: CycleResolution
    decision_record_ids: list[str]
    routing_rule_id: str
    affected_request_ids: list[str]


def _policy_class_rank(policy_class: str) -> int:
    try:
        return POLICY_CLASS_ORDER.index(policy_class)
    except ValueError:
        return len(POLICY_CLASS_ORDER)


def _specificity_score(session: Session, policy_id: str) -> int:
    """Fewer SVC- tags on the policy's clauses means a more specific policy."""
    clause = session.query(Clause).filter_by(policy_id=policy_id).first()
    tags = clause.tags if clause else []
    svc_tags = [t for t in tags if str(t).startswith("SVC-")]
    return -len(svc_tags)


def _cycle_edges(
    edges: list[OwnershipEdge], cycle: list[str], service_id: str
) -> list[OwnershipEdge]:
    pairs = list(zip(cycle, cycle[1:] + cycle[:1]))
    result = []
    for source, target in pairs:
        match = next(
            e
            for e in edges
            if e.service_id == service_id
            and e.source_department_id == source
            and e.asserts_approver_department_id == target
        )
        result.append(match)
    return result


def _select_winner(
    session: Session, candidates: list[OwnershipEdge]
) -> tuple[OwnershipEdge, Policy, str]:
    """Precedence ladder (SPEC §7.3): policy_class -> explicit supersession
    -> recency -> specificity. Returns (winning_edge, winning_policy, rule_applied).
    """
    enriched = [(e, session.get(Policy, e.clause_ref.split("§")[0])) for e in candidates]

    best_rank = min(_policy_class_rank(p.policy_class) for _, p in enriched)
    tier1 = [(e, p) for e, p in enriched if _policy_class_rank(p.policy_class) == best_rank]
    if len(tier1) == 1:
        edge, policy = tier1[0]
        return edge, policy, "policy_class"

    clause_refs = [e.clause_ref for e, _ in tier1]
    scored = []
    for edge, policy in tier1:
        other_refs = [r for r in clause_refs if r != edge.clause_ref]
        score = sum(1 for r in other_refs if r in (policy.supersedes or []))
        scored.append((edge, policy, score))
    best_supersede = max(s for _, _, s in scored)
    tier2 = [(e, p) for e, p, s in scored if s == best_supersede] if best_supersede > 0 else tier1
    if len(tier2) == 1:
        edge, policy = tier2[0]
        return edge, policy, "explicit_supersession"

    best_date = max(date.fromisoformat(p.effective_date) for _, p in tier2)
    tier3 = [(e, p) for e, p in tier2 if date.fromisoformat(p.effective_date) == best_date]
    if len(tier3) == 1:
        edge, policy = tier3[0]
        return edge, policy, "effective_date_desc"

    scored_specificity = [(e, p, _specificity_score(session, p.id)) for e, p in tier3]
    best_spec = max(s for _, _, s in scored_specificity)
    tier4 = [(e, p) for e, p, s in scored_specificity if s == best_spec]
    edge, policy = tier4[0]
    return edge, policy, "service_specificity"


def resolve_cycle(session: Session, service_id: str) -> Optional[CycleResolution]:
    """Detects and resolves the approval-ownership cycle for one service, if any.

    Pure computation — no decision record is written here. No LLM anywhere
    in this function (SPEC §7.2/§7.3: deterministic, not LLM).
    """
    edges = session.query(OwnershipEdge).filter_by(service_id=service_id).all()
    graph = build_graph(edges)
    cycles = find_cycles(graph, service_id)
    if not cycles:
        return None
    cycle = cycles[0]

    cycle_edges = _cycle_edges(edges, cycle, service_id)
    winner_edge, winner_policy, precedence_rule = _select_winner(session, cycle_edges)

    losing_edges = [e for e in cycle_edges if e.id != winner_edge.id]
    invalidated = [e for e in losing_edges if e.clause_ref in (winner_policy.supersedes or [])]

    approver_department = session.get(Department, winner_edge.asserts_approver_department_id)
    correct_approver_employee_id = (
        approver_department.head_employee_id if approver_department else None
    )

    hr_approval_required = winner_edge.asserts_approver_department_id == "DEPT-HR"

    reason = (
        f"{winner_policy.id} is a {winner_policy.policy_class}-class policy "
        f"(precedence rule: {precedence_rule}), version {winner_policy.version}, "
        f"effective {winner_policy.effective_date}."
    )
    if invalidated:
        reason += (
            " It explicitly supersedes "
            + ", ".join(e.clause_ref for e in invalidated)
            + ", which continued the delegation chain."
        )
    reason += (
        f" Governing clause {winner_edge.clause_ref} assigns approval to "
        f"{winner_edge.asserts_approver_department_id}."
    )

    return CycleResolution(
        service_id=service_id,
        cycle=cycle,
        cycle_edge_ids=[e.id for e in cycle_edges],
        winning_edge_id=winner_edge.id,
        governing_clause=winner_edge.clause_ref,
        governing_policy_id=winner_policy.id,
        governing_policy_version=winner_policy.version,
        correct_approver_department_id=winner_edge.asserts_approver_department_id,
        correct_approver_employee_id=correct_approver_employee_id,
        losing_edge_ids=[e.id for e in losing_edges],
        edges_invalidated=[e.id for e in invalidated],
        precedence_rule_applied=precedence_rule,
        governing_reason=reason,
        hr_approval_required=hr_approval_required,
    )


def apply_resolution(session: Session, service_id: str) -> Optional[AppliedResolution]:
    """Resolves the cycle, writes one RESOLUTION decision record per affected
    (stuck) request, and creates a single PROPOSED routing_rule (SPEC §7.3/§7.4).
    """
    resolution = resolve_cycle(session, service_id)
    if resolution is None:
        return None

    affected_requests = (
        session.query(Request)
        .filter(Request.service_id == service_id)
        .filter(Request.stuck_reason_code.isnot(None))
        .all()
    )

    routing_rule_id = str(uuid.uuid4())
    decision_record_ids: list[str] = []

    for request in affected_requests:
        with record_decision(
            session,
            request_id=request.id,
            stage="RESOLUTION",
            actor="RULE_ENGINE",
            actor_id=RESOLUTION_ACTOR_ID,
        ) as rec:
            rec.inputs_used = {"service_id": service_id, "cycle": resolution.cycle}
            rec.clause_refs = [resolution.governing_clause]
            rec.policy_versions = {resolution.governing_policy_id: resolution.governing_policy_version}
            rec.rationale = resolution.governing_reason
            rec.output = {
                "cycle": resolution.cycle,
                "losing_edges": resolution.losing_edge_ids,
                "edges_invalidated": resolution.edges_invalidated,
                "precedence_rule_applied": resolution.precedence_rule_applied,
                "correct_approver_department_id": resolution.correct_approver_department_id,
                "correct_approver_employee_id": resolution.correct_approver_employee_id,
                "hr_approval_required": resolution.hr_approval_required,
                "proposed_routing_rule_id": routing_rule_id,
            }
        latest = (
            session.query(DecisionRecord)
            .filter_by(request_id=request.id, stage="RESOLUTION")
            .order_by(DecisionRecord.created_at.desc())
            .first()
        )
        decision_record_ids.append(latest.id)

    session.add(
        RoutingRule(
            id=routing_rule_id,
            service_id=service_id,
            condition={"service_id": service_id},
            target_department_id=resolution.correct_approver_department_id,
            active=False,
            source="PROPOSED",
            proposed_by_resolution_id=decision_record_ids[0] if decision_record_ids else None,
        )
    )
    session.commit()

    return AppliedResolution(
        resolution=resolution,
        decision_record_ids=decision_record_ids,
        routing_rule_id=routing_rule_id,
        affected_request_ids=[r.id for r in affected_requests],
    )


def detect_bottlenecks(session: Session) -> list[dict]:
    """SPEC §7.4: requests per service stuck > SLA, reassignment counts, and
    the most common wrong first queue, aggregated over requests + decision_records.
    """
    catalog = load_catalog()
    now = datetime.utcnow()

    stuck_requests = session.query(Request).filter(Request.stuck_reason_code.isnot(None)).all()
    by_service: dict[str, list[Request]] = defaultdict(list)
    for request in stuck_requests:
        by_service[request.service_id].append(request)

    results = []
    for service_id, requests in by_service.items():
        sla_hours = catalog.get(service_id, {}).get("sla_hours")
        over_sla = [
            r
            for r in requests
            if sla_hours is not None and (now - r.created_at).total_seconds() / 3600 > sla_hours
        ]

        request_ids = [r.id for r in requests]
        route_records = (
            session.query(DecisionRecord)
            .filter(DecisionRecord.stage == "ROUTE")
            .filter(DecisionRecord.request_id.in_(request_ids))
            .order_by(DecisionRecord.created_at)
            .all()
        )
        reassignment_counts = Counter(record.request_id for record in route_records)

        first_department_by_request: dict[str, str] = {}
        for record in route_records:
            department_id = (record.output or {}).get("department_id")
            if department_id:
                first_department_by_request.setdefault(record.request_id, department_id)
        first_queue_counts = Counter(first_department_by_request.values())

        results.append(
            {
                "service_id": service_id,
                "stuck_count": len(requests),
                "stuck_over_sla_count": len(over_sla),
                "reassignment_counts": dict(reassignment_counts),
                "most_common_wrong_first_queue": (
                    first_queue_counts.most_common(1)[0][0] if first_queue_counts else None
                ),
            }
        )

    return sorted(results, key=lambda r: r["stuck_count"], reverse=True)
