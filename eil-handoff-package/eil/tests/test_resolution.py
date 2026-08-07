import pytest

from backend.db import SessionLocal
from backend.engine.resolution import apply_resolution, resolve_cycle
from backend.models import DecisionRecord, RoutingRule
from backend.seed import seed


@pytest.fixture(scope="module", autouse=True)
def seeded_db():
    seed()


def test_svc_access_cycle_matches_expected_resolution():
    session = SessionLocal()
    try:
        resolution = resolve_cycle(session, "SVC-ACCESS")
    finally:
        session.close()

    assert resolution is not None
    assert resolution.service_id == "SVC-ACCESS"
    assert set(resolution.cycle) == {"DEPT-HR", "DEPT-SEC", "DEPT-DG", "DEPT-IT"}
    assert resolution.governing_clause == "POL-SEC-204§4.2"
    assert resolution.correct_approver_department_id == "DEPT-DG"
    assert resolution.correct_approver_employee_id == "EMP-203"
    assert set(resolution.edges_invalidated) == {"OWN-A03", "OWN-A04"}
    assert resolution.hr_approval_required is False


def test_svc_travel_has_no_cycle():
    session = SessionLocal()
    try:
        resolution = resolve_cycle(session, "SVC-TRAVEL")
    finally:
        session.close()

    assert resolution is None


def test_apply_resolution_writes_decision_records_and_proposed_routing_rule():
    session = SessionLocal()
    try:
        applied = apply_resolution(session, "SVC-ACCESS")

        assert applied is not None
        assert len(applied.decision_record_ids) == 12  # seeded BLOCKED SVC-ACCESS cohort

        for record_id in applied.decision_record_ids:
            record = session.get(DecisionRecord, record_id)
            assert record.stage == "RESOLUTION"
            assert record.clause_refs == ["POL-SEC-204§4.2"]
            assert set(record.output["edges_invalidated"]) == {"OWN-A03", "OWN-A04"}

        routing_rule = session.get(RoutingRule, applied.routing_rule_id)
        assert routing_rule.source == "PROPOSED"
        assert routing_rule.active is False
        assert routing_rule.target_department_id == "DEPT-DG"
    finally:
        session.close()
