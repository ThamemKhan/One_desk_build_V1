from typing import TypedDict


class RequestState(TypedDict, total=False):
    request_id: str
    employee_id: str
    channel: str
    messages: list[dict]  # {role, content}
    intent: str | None
    intent_confidence: float
    service_id: str | None
    entities: dict  # extracted slot values
    context: dict  # employee, manager, balances, history
    missing_fields: list[str]
    clause_hits: list[dict]  # {clause_ref, score, text}
    rule_results: list[dict]  # {rule_id, passed, actual, limit, clause_ref}
    exception_draft: dict | None
    tier: int
    route: dict | None  # {department_id, approver_id, reason, clause_ref}
    approvals: list[dict]
    outcome: str | None
    explanation: str | None
    halt_reason: str | None  # set when escalating to human
    instruction_override_detected: bool

