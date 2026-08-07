from typing import Any

from pydantic import BaseModel


class Persona(BaseModel):
    id: str
    name: str
    title: str
    department_id: str
    roles: list[str]


class ChatRequest(BaseModel):
    message: str
    employee_id: str | None = None
    request_id: str | None = None


class DecisionRecordOut(BaseModel):
    id: str
    request_id: str
    stage: str
    actor: str
    actor_id: str
    inputs_used: dict = {}
    rule_fired: str | None = None
    clause_refs: list = []
    policy_versions: dict = {}
    output: dict = {}
    confidence: float | None = None
    rationale: str = ""
    latency_ms: int = 0
    created_at: Any = None


class ChatResponse(BaseModel):
    reply: str
    request_id: str
    state: dict
    decision_records: list[DecisionRecordOut] = []


class RequestOut(BaseModel):
    id: str
    employee_id: str
    service_id: str
    intent: str
    status: str
    channel: str
    payload: dict = {}
    missing_fields: list = []
    assigned_department_id: str | None = None
    pending_approver_id: str | None = None
    tier: int
    thread_id: str | None = None
    created_at: Any = None
    updated_at: Any = None
    closed_at: Any = None
    stuck_reason_code: str | None = None


class TimelineEntry(BaseModel):
    stage: str
    actor: str
    actor_id: str
    rationale: str
    clause_refs: list = []
    policy_versions: dict = {}
    latency_ms: int = 0
    created_at: Any = None


class ClauseOut(BaseModel):
    id: str
    policy_id: str
    ref: str
    heading: str
    text: str


class RequestDetail(BaseModel):
    request: RequestOut
    timeline: list[TimelineEntry] = []
    decision_records: list[DecisionRecordOut] = []
    clauses: list[ClauseOut] = []


class ApprovalDecision(BaseModel):
    approver_id: str | None = None
    comment: str | None = None


class StuckItem(BaseModel):
    request: RequestOut
    stuck_reason_code: str | None = None
    diagnosis: dict | None = None


class ResolutionOut(BaseModel):
    service_id: str
    cycle: list[str] = []
    cycle_edge_ids: list[str] = []
    governing_clause: str
    governing_policy_id: str
    governing_policy_version: str
    correct_approver_department_id: str
    correct_approver_employee_id: str | None = None
    losing_edge_ids: list[str] = []
    edges_invalidated: list[str] = []
    precedence_rule_applied: str
    governing_reason: str
    hr_approval_required: bool
    narration: dict | None = None
    proposed_routing_rule_id: str | None = None
    affected_request_ids: list[str] = []


class RoutingRuleOut(BaseModel):
    id: str
    service_id: str
    condition: dict = {}
    target_department_id: str
    active: bool
    source: str
    proposed_by_resolution_id: str | None = None


class PolicyOut(BaseModel):
    id: str
    title: str
    owner_department_id: str
    policy_class: str
    version: str
    effective_date: str
    supersedes: list = []


class PolicyDetail(PolicyOut):
    body_md: str
    clauses: list[ClauseOut] = []


class CompilePolicyRequest(BaseModel):
    prose: str


class CompilePolicyResponse(BaseModel):
    proposed_rules: list[dict] = []
    note: str


class ExceptionOut(BaseModel):
    id: str
    request_id: str
    violated_rule_id: str
    clause_refs: list = []
    requested_value: float | None = None
    policy_limit: float | None = None
    delta: float | None = None
    justification: str | None = None
    evidence: list = []
    risk_score: int
    risk_band: str
    compensating_controls: list = []
    approver_id: str | None = None
    status: str
    expires_at: Any = None
    review_due_at: Any = None


class ReloadResponse(BaseModel):
    services: list[str]
    enabled: list[str]
    rules_loaded: int
    clauses_indexed: int
