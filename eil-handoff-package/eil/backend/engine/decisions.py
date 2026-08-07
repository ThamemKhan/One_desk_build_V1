import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy.orm import Session

from backend.models import DecisionRecord


@dataclass
class DecisionContext:
    request_id: str
    stage: str
    actor: str
    actor_id: str
    inputs_used: dict = field(default_factory=dict)
    rule_fired: str | None = None
    clause_refs: list = field(default_factory=list)
    policy_versions: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    confidence: float | None = None
    rationale: str = ""


@contextmanager
def record_decision(
    session: Session, request_id: str, stage: str, actor: str, actor_id: str
) -> Iterator[DecisionContext]:
    """Append-only writer for a decision_records row (SPEC §4.6).

    Usage:
        with record_decision(session, request_id, "POLICY", "RULE_ENGINE", "engine.rules") as rec:
            rec.inputs_used = {"payload": payload}
            rec.clause_refs = [...]
            rec.output = {...}

    latency_ms is captured automatically from time spent inside the block.
    """
    ctx = DecisionContext(request_id=request_id, stage=stage, actor=actor, actor_id=actor_id)
    start = time.perf_counter()
    try:
        yield ctx
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        session.add(
            DecisionRecord(
                id=str(uuid.uuid4()),
                request_id=ctx.request_id,
                stage=ctx.stage,
                actor=ctx.actor,
                actor_id=ctx.actor_id,
                inputs_used=ctx.inputs_used,
                rule_fired=ctx.rule_fired,
                clause_refs=ctx.clause_refs,
                policy_versions=ctx.policy_versions,
                output=ctx.output,
                confidence=ctx.confidence,
                rationale=ctx.rationale,
                latency_ms=latency_ms,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
