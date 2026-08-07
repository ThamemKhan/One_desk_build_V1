from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    department_id: Mapped[str] = mapped_column(String, ForeignKey("departments.id"))
    manager_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("employees.id"), nullable=True
    )
    location: Mapped[str] = mapped_column(String)
    city_tier: Mapped[int] = mapped_column(Integer)
    cost_center: Mapped[str] = mapped_column(String)
    grade: Mapped[str] = mapped_column(String)
    leave_balance_days: Mapped[float] = mapped_column(Float)
    roles: Mapped[list] = mapped_column(JSON)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    head_employee_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    owner_department_id: Mapped[str] = mapped_column(String, ForeignKey("departments.id"))
    policy_class: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    effective_date: Mapped[str] = mapped_column(String)
    supersedes: Mapped[list] = mapped_column(JSON)
    body_md: Mapped[str] = mapped_column(String)


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String, ForeignKey("policies.id"))
    ref: Mapped[str] = mapped_column(String)
    heading: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    tags: Mapped[list] = mapped_column(JSON)


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String, ForeignKey("employees.id"))
    service_id: Mapped[str] = mapped_column(String)
    intent: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    missing_fields: Mapped[list] = mapped_column(JSON)
    assigned_department_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pending_approver_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tier: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stuck_reason_code: Mapped[str | None] = mapped_column(String, nullable=True)


class DecisionRecord(Base):
    __tablename__ = "decision_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.id"))
    stage: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    inputs_used: Mapped[dict] = mapped_column(JSON)
    rule_fired: Mapped[str | None] = mapped_column(String, nullable=True)
    clause_refs: Mapped[list] = mapped_column(JSON)
    policy_versions: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ExceptionRecord(Base):
    __tablename__ = "exceptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.id"))
    violated_rule_id: Mapped[str] = mapped_column(String)
    clause_refs: Mapped[list] = mapped_column(JSON)
    requested_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    policy_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    justification: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON)
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_band: Mapped[str] = mapped_column(String)
    compensating_controls: Mapped[list] = mapped_column(JSON)
    approver_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OwnershipEdge(Base):
    __tablename__ = "ownership_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_department_id: Mapped[str] = mapped_column(String, ForeignKey("departments.id"))
    service_id: Mapped[str] = mapped_column(String)
    asserts_approver_department_id: Mapped[str] = mapped_column(
        String, ForeignKey("departments.id")
    )
    clause_ref: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    service_id: Mapped[str] = mapped_column(String)
    condition: Mapped[dict] = mapped_column(JSON)
    target_department_id: Mapped[str] = mapped_column(String, ForeignKey("departments.id"))
    active: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String)
    proposed_by_resolution_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, ForeignKey("requests.id"))
    approver_id: Mapped[str] = mapped_column(String, ForeignKey("employees.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    required_by_clause_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
