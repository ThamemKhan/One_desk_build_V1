from datetime import date

from backend.catalog import load_catalog
from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.graph.state import RequestState
from backend.models import Department, Employee


def _employee_context(session, employee_id: str) -> dict:
    employee = session.get(Employee, employee_id)
    if employee is None:
        return {}
    manager = session.get(Employee, employee.manager_id) if employee.manager_id else None
    department = session.get(Department, employee.department_id)
    return {
        "employee": {
            "id": employee.id,
            "name": employee.name,
            "grade": employee.grade,
            "department_id": employee.department_id,
            "manager_id": employee.manager_id,
            "location": employee.location,
            "city_tier": employee.city_tier,
            "cost_center": employee.cost_center,
            "leave_balance_days": employee.leave_balance_days,
            "roles": employee.roles,
        },
        "manager": {"id": manager.id, "name": manager.name} if manager else None,
        "department": (
            {"id": department.id, "name": department.name, "head_employee_id": department.head_employee_id}
            if department
            else None
        ),
    }


def _resolve_context_fields(fields: list[dict], context: dict) -> dict:
    """Generically resolves every `source: context` field via its `from:`
    dotted path (e.g. employee.grade). SPEC assigns no generic evaluator for
    `source: derived` fields (free-text rule expressions in the service YAML)
    to any file — those are hand-computed per service below, scoped to only
    what a seeded demo scenario actually needs.
    """
    resolved = {}
    for field in fields:
        if field.get("source") != "context":
            continue
        path = field.get("from", "")
        if path == "session.employee_id":
            resolved[field["name"]] = context.get("employee", {}).get("id")
            continue
        section, _, attr = path.partition(".")
        section_value = context.get(section)
        if isinstance(section_value, dict):
            resolved[field["name"]] = section_value.get(attr)
    return resolved


def _derive_travel_fields(entities: dict, context: dict, service: dict) -> dict:
    """SVC-TRAVEL's derived fields (seed/services/SVC-TRAVEL.yaml), scoped to
    what Scenario A needs: destination_city_tier, nights, travel_cost_estimate,
    total_estimated_cost, trip_type, booking_status.
    """
    derived: dict = {}
    reference = service.get("reference_data", {})
    tier1_cities = reference.get("tier1_cities", [])
    destination_city = entities.get("destination_city")
    if destination_city:
        derived["destination_city_tier"] = 1 if destination_city in tier1_cities else 2
        derived["trip_type"] = "DOMESTIC"  # no international destinations in this seed

    start_date = entities.get("start_date")
    end_date = entities.get("end_date")
    if start_date and end_date:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        derived["nights"] = (end - start).days
        derived["days_until_departure"] = (start - date.today()).days

    origin_city = context.get("employee", {}).get("location")
    fare_table = reference.get("fare_table", {})
    travel_cost_estimate = fare_table.get(f"{origin_city}->{destination_city}", fare_table.get("default", 0))
    derived["travel_cost_estimate"] = travel_cost_estimate

    hotel_rate = entities.get("hotel_rate_per_night")
    if hotel_rate is not None and derived.get("nights") is not None:
        derived["total_estimated_cost"] = hotel_rate * derived["nights"] + travel_cost_estimate

    derived["booking_status"] = "NOT_BOOKED"
    return derived


_DERIVERS = {
    "SVC-TRAVEL": _derive_travel_fields,
}


def run(state: RequestState) -> dict:
    session = SessionLocal()
    try:
        with record_decision(session, state["request_id"], "CONTEXT", "RULE_ENGINE", "context_loader") as rec:
            rec.inputs_used = {"employee_id": state.get("employee_id")}
            context = _employee_context(session, state["employee_id"])

            service_id = state.get("service_id")
            entities = dict(state.get("entities", {}))
            if service_id:
                catalog = load_catalog()
                service = catalog.get(service_id, {})
                fields = service.get("fields", [])
                context_values = _resolve_context_fields(fields, context)
                entities.update({k: v for k, v in context_values.items() if v is not None})
                deriver = _DERIVERS.get(service_id)
                if deriver:
                    derived_values = deriver(entities, context, service)
                    entities.update({k: v for k, v in derived_values.items() if v is not None})

            rec.output = {"context_keys": list(context.keys()), "entities": entities}
    finally:
        session.close()

    return {"context": context, "entities": entities}
