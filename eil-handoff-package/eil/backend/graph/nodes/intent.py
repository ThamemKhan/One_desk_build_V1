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

    last_user_lower = last_user_message.lower().strip()
    greetings = ["hey", "hello", "hi", "hallo", "good morning", "good afternoon", "good evening", "hey there", "hi aura", "help"]
    if any(last_user_lower.startswith(g) or last_user_lower == g for g in greetings) or len(last_user_lower) < 4:
        return {
            "intent": "GREETING",
            "intent_confidence": 1.0,
            "service_id": None,
            "entities": state.get("entities", {}),
            "halt_reason": None,
            "missing_fields": [],
        }

    session = SessionLocal()
    try:
        prompt = build_extract_intent_prompt(
            last_user_message, _catalog_summary(), date.today().isoformat()
        )
        result = call_llm(session, state["request_id"], "INTENT", prompt, EXTRACT_INTENT_SYSTEM)
    finally:
        session.close()

    confidence = result.get("confidence") or 0.0
    gate = gate_intent_confidence(confidence)

    return {
        "intent": result.get("intent"),
        "intent_confidence": confidence,
        "service_id": result.get("service_id"),
        "entities": {**state.get("entities", {}), **(result.get("entities") or {})},
        # Always emit halt_reason, including None. Graph state persists across
        # turns on the same thread_id, so a halt set by an earlier low-confidence
        # message would otherwise stick permanently and bounce every later turn
        # to communicate — however confident the new message is.
        "halt_reason": gate.halt_reason,
    }
