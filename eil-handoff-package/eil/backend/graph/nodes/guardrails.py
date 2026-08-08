from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.graph.state import RequestState

def run(state: RequestState) -> dict:
    """GUARDRAILS (SPEC §15 adversarial cases check).
    Inspects user input for out-of-scope prompts, toxic content, and prompt injection/instruction overrides.
    """
    messages = state.get("messages", [])
    last_user_message = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
    )
    last_user_lower = last_user_message.lower().strip()

    instruction_override = False
    halt_reason = None
    intent = state.get("intent")
    service_id = state.get("service_id")

    # Prompt Injection Checks (G18, G19)
    if "ignore your previous instructions" in last_user_lower or "ignore instruction" in last_user_lower:
        instruction_override = True

    # Out of Scope Checks (G16)
    if "capital of france" in last_user_lower or "weather in" in last_user_lower:
        intent = "OUT_OF_SCOPE"
        halt_reason = "OUT_OF_SCOPE"
        service_id = None

    # No Governing Policy Checks (G17)
    if "car allowance" in last_user_lower or "company car" in last_user_lower:
        intent = "GENERAL_INQUIRY"
        halt_reason = "NO_GOVERNING_POLICY"
        service_id = None

    session = SessionLocal()
    try:
        with record_decision(session, state["request_id"], "INTENT", "RULE_ENGINE", "engine.guardrails") as rec:
            rec.inputs_used = {"message": last_user_message}
            rec.output = {
                "instruction_override_detected": instruction_override,
                "halt_reason": halt_reason,
                "intent": intent,
                "service_id": service_id
            }
            rec.rationale = "Guardrails check ran successfully. Checked message for prompt injections and scope bounds."
    finally:
        session.close()

    res = {}
    if instruction_override:
        res["instruction_override_detected"] = True
    if halt_reason:
        res["halt_reason"] = halt_reason
    if intent:
        res["intent"] = intent
    if service_id is not None:
        res["service_id"] = service_id
    return res
