from datetime import date

from backend.catalog import load_catalog
from backend.db import SessionLocal
from backend.engine.tiers import gate_intent_confidence
from backend.graph.state import RequestState
from backend.llm.client import call_llm
from backend.llm.prompts import EXTRACT_INTENT_SYSTEM, build_extract_intent_prompt


def _askable_summary(svc: dict) -> str:
    askable = [f for f in svc.get("fields", []) if f.get("source") == "ask"]
    return ", ".join(
        f"{f['name']} ({f.get('prompt_hint', f.get('type', 'string'))})" for f in askable
    )


def _catalog_summary() -> str:
    catalog = load_catalog()
    return "\n".join(
        f"{svc['id']}: {svc['name']} (intent: {svc['intent']}) - {svc['description']}\n"
        f"    entity field names: {_askable_summary(svc)}"
        for svc in catalog.values()
        if svc.get("enabled")
    )


def run(state: RequestState) -> dict:
    """EXTRACT_INTENT (SPEC §13 #1). The decision record for this call is
    written by call_llm itself (stage=INTENT, actor=AI).
    """
    messages = state.get("messages", [])
    last_user_message = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
    )

    existing_intent = state.get("intent")
    existing_service_id = state.get("service_id")
    existing_entities = state.get("entities") or {}

    last_user_lower = last_user_message.lower().strip()
    greetings = ["hey", "hello", "hi", "hallo", "good morning", "good afternoon", "good evening", "hey there", "hi aura", "help"]
    if not existing_intent and (any(last_user_lower.startswith(g) or last_user_lower == g for g in greetings) or len(last_user_lower) < 4):
        return {
            "intent": "GREETING",
            "intent_confidence": 1.0,
            "service_id": None,
            "entities": existing_entities,
            "halt_reason": None,
            "missing_fields": [],
        }

    # Build conversation context string for full multi-turn memory
    convo_turns = []
    for m in messages:
        role = "Employee" if m.get("role") == "user" else "Assistant"
        content = m.get("content") or ""
        if content:
            convo_turns.append(f"{role}: {content}")
    
    full_message_prompt = (
        f"Conversation History:\n" + "\n".join(convo_turns) + f"\n\nLatest Employee Input:\n{last_user_message}"
        if len(convo_turns) > 1
        else last_user_message
    )

    session = SessionLocal()
    try:
        prompt = build_extract_intent_prompt(
            full_message_prompt, _catalog_summary(), date.today().isoformat()
        )
        result = call_llm(session, state["request_id"], "INTENT", prompt, EXTRACT_INTENT_SYSTEM)
    finally:
        session.close()

    confidence = result.get("confidence") or 0.0
    
    # If we already have an active transactional intent on this thread, preserve it unless overwritten with high confidence
    final_intent = result.get("intent")
    final_service = result.get("service_id")
    if existing_intent and existing_intent not in ("GREETING", "GENERAL_INQUIRY") and (not final_intent or confidence < 0.7):
        final_intent = existing_intent
        final_service = existing_service_id
        confidence = max(confidence, 0.95)

    gate = gate_intent_confidence(confidence)

    res = {
        "intent": final_intent,
        "intent_confidence": confidence,
        "service_id": final_service,
        "entities": {**existing_entities, **(result.get("entities") or {})},
        "halt_reason": gate.halt_reason,
    }
    if result.get("instruction_override_detected"):
        res["instruction_override_detected"] = True
    return res
