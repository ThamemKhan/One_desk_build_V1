from backend.catalog import load_catalog
from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.graph.state import RequestState
from backend.llm.client import call_llm
from backend.llm.prompts import GENERATE_CLARIFICATION_SYSTEM, build_generate_clarification_prompt


def _missing_ask_fields(service_id: str, entities: dict) -> tuple[list[str], list[dict]]:
    catalog = load_catalog()
    service = catalog.get(service_id, {})
    fields = service.get("fields", [])
    askable = [f for f in fields if f.get("source") == "ask"]
    missing = [
        f["name"] for f in askable if entities.get(f["name"]) is None and not f.get("optional", False)
    ]
    return missing, fields


def run(state: RequestState) -> dict:
    """GENERATE_CLARIFICATION (SPEC §13 #2) — asks only about fields with
    source: ask that are still missing from entities already known.
    """
    if state.get("halt_reason"):
        return {}

    service_id = state.get("service_id")
    entities = state.get("entities", {})

    if not service_id:
        # Intent confidence landed in the DISAMBIGUATE band or no service
        # matched — nothing to check missing fields against yet.
        return {"missing_fields": ["service_id"]}

    missing, fields = _missing_ask_fields(service_id, entities)

    session = SessionLocal()
    try:
        if not missing:
            with record_decision(session, state["request_id"], "CLARIFY", "RULE_ENGINE", "clarifier") as rec:
                rec.inputs_used = {"service_id": service_id, "entities": entities}
                rec.output = {"missing_fields": []}
                rec.rationale = "All askable fields already known; proceeding to policy."
            return {"missing_fields": []}

        prompt = build_generate_clarification_prompt(missing, fields, entities)
        result = call_llm(session, state["request_id"], "CLARIFY", prompt, GENERATE_CLARIFICATION_SYSTEM)
    finally:
        session.close()

    question = result.get("question", "")
    messages = state.get("messages", []) + [{"role": "assistant", "content": question}]
    return {"missing_fields": missing, "messages": messages}
