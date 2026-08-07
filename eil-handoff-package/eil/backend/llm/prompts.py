import json

# Every prompt below returns strict JSON only. None of them may ask the model
# to decide an approver, an outcome, or a policy limit (SPEC §13) — the model
# extracts facts and narrates decisions the deterministic rule engine already made.

# ---------------------------------------------------------------------------
# 1. EXTRACT_INTENT
# In: message, service catalog summary
# Out: {intent, service_id, confidence, entities{}, ambiguity_note}
# ---------------------------------------------------------------------------

EXTRACT_INTENT_SYSTEM = (
    "You are the intent-extraction step of an enterprise service request system. "
    "You extract facts only. You never decide an outcome, an approver, or a policy "
    "limit — a separate deterministic rule engine does that. Respond with strict "
    "JSON only: no prose, no markdown code fences."
)


def build_extract_intent_prompt(
    message: str, service_catalog_summary: str, today: str = ""
) -> str:
    return (
        (f"Today's date is {today}.\n\n" if today else "")
        + "Available services, each shown with its canonical intent code:\n"
        f"{service_catalog_summary}\n\n"
        "Employee message:\n"
        f"{message}\n\n"
        "Extract the intent behind this message. Respond with JSON exactly matching "
        "this shape:\n"
        '{"intent": string, "service_id": string or null, "confidence": number between '
        '0 and 1, "entities": object of extracted slot values, "ambiguity_note": string '
        "or null}\n"
        "intent must be exactly the canonical intent code of the matched service (for "
        "example TRAVEL_BOOKING, LEAVE_REQUEST, ACCESS_REQUEST) — never a free-text "
        "description. Set both intent and service_id to null if no listed service "
        "matches. Do not invent a service_id or intent code that is not in the catalog "
        "above.\n"
        "entities must be keyed by exactly the entity field names listed for the matched "
        "service — do not invent, abbreviate or rename a key. Include a key only when the "
        "message actually supplies its value. Amounts must be plain numbers. Dates must be "
        "ISO (YYYY-MM-DD): resolve relative expressions such as \"next week\" or \"monday "
        "to friday\" against today's date, choosing the next such day in the future."
    )


# ---------------------------------------------------------------------------
# 2. GENERATE_CLARIFICATION
# In: missing_fields, field metadata, context already known
# Out: {question, fields_asked[]} — must ask only for genuinely missing fields
# ---------------------------------------------------------------------------

GENERATE_CLARIFICATION_SYSTEM = (
    "You are the clarification step of an enterprise service request system. You "
    "write one short question to collect missing information. You never decide an "
    "outcome, an approver, or a policy limit. Ask only about fields explicitly "
    "listed below as missing and askable — never ask about a field already known "
    "from context, and never ask about a field whose source is not 'ask'. Respond "
    "with strict JSON only."
)


def build_generate_clarification_prompt(
    missing_fields: list[str], field_metadata: list[dict], known_context: dict
) -> str:
    askable = [
        f for f in field_metadata if f.get("name") in missing_fields and f.get("source") == "ask"
    ]
    return (
        "Fields already known (do not ask about these again):\n"
        f"{json.dumps(known_context, indent=2, default=str, ensure_ascii=False)}\n\n"
        "Fields still missing and eligible to ask about (source: ask only):\n"
        f"{json.dumps(askable, indent=2, default=str, ensure_ascii=False)}\n\n"
        "Write one short, natural clarifying question covering only these missing "
        "fields. Respond with JSON exactly matching this shape:\n"
        '{"question": string, "fields_asked": array of field names this question covers}\n'
        "fields_asked must be a subset of the missing, askable field names listed above."
    )


# ---------------------------------------------------------------------------
# 3. EXPLAIN_DECISION
# In: decision records, clause texts
# Out: {explanation} — plain English, must cite clause refs, must not add rules
# ---------------------------------------------------------------------------

EXPLAIN_DECISION_SYSTEM = (
    "You are the explanation step of an enterprise service request system. You "
    "narrate a decision the deterministic rule engine already made. You never "
    "invent a rule, an approver, or a policy limit that is not already present in "
    "the decision records or clause texts given to you. Every claim must cite a "
    "clause reference from the material provided. Respond with strict JSON only."
)


def build_explain_decision_prompt(decision_records: list[dict], clause_texts: list[dict]) -> str:
    return (
        "Decision records (the rule engine's already-made decisions):\n"
        f"{json.dumps(decision_records, indent=2, default=str, ensure_ascii=False)}\n\n"
        "Clause texts (only cite these; do not invent a clause reference not listed "
        "here):\n"
        f"{json.dumps(clause_texts, indent=2, default=str, ensure_ascii=False)}\n\n"
        "Write a short, plain-English explanation of what happened and why, citing "
        "clause references inline (e.g. POL-TRV-101§5.3). Do not state or imply any "
        "rule, approver, or limit that is not already present in the material above. "
        'Respond with JSON exactly matching this shape: {"explanation": string}'
    )


# ---------------------------------------------------------------------------
# 4. NARRATE_RESOLUTION
# In: cycle, losing edges, precedence applied, proposed rule
# Out: {summary, recommendation}
# ---------------------------------------------------------------------------

NARRATE_RESOLUTION_SYSTEM = (
    "You are the resolution-narration step of an enterprise service request "
    "system. A deterministic algorithm has already found an approval-ownership "
    "cycle and resolved it using a fixed precedence ladder. You narrate that "
    "finding in plain English. You do not re-decide the governing approver, and "
    "you do not propose a different precedence rule than the one already applied. "
    "Respond with strict JSON only."
)


def build_narrate_resolution_prompt(
    cycle: list[str],
    losing_edges: list[dict],
    precedence_rule_applied: str,
    proposed_routing_rule: dict,
) -> str:
    path = " -> ".join(cycle + cycle[:1]) if cycle else ""
    return (
        f"Ownership cycle detected: {path}\n\n"
        "Losing edges (already decided, do not re-adjudicate):\n"
        f"{json.dumps(losing_edges, indent=2, default=str, ensure_ascii=False)}\n\n"
        f"Precedence rule already applied: {precedence_rule_applied}\n\n"
        "Proposed routing rule (already generated by the engine):\n"
        f"{json.dumps(proposed_routing_rule, indent=2, default=str, ensure_ascii=False)}\n\n"
        "Summarise this finding in plain English and recommend the one-click action "
        "a policy owner should take. Respond with JSON exactly matching this shape: "
        '{"summary": string, "recommendation": string}'
    )


# ---------------------------------------------------------------------------
# 5. COMPILE_POLICY (optional — the differentiator, SPEC §13 note)
# In: prose clause
# Out: {proposed_rules[]} in the SPEC §6 YAML schema — status PROPOSED,
#      requires human ratification before it can fire
# ---------------------------------------------------------------------------

COMPILE_POLICY_SYSTEM = (
    "You are the policy-compilation step of an enterprise service request "
    "system. You draft candidate machine-readable rules from a prose policy "
    "clause, in the exact schema the rule engine uses. Every rule you draft is a "
    "PROPOSAL ONLY: it cannot fire until a human policy owner ratifies it. You do "
    "not activate a rule, and you do not decide an approver as a matter of policy "
    "— you draft candidates for a human to review. Respond with strict JSON only."
)


def build_compile_policy_prompt(prose_clause: str) -> str:
    return (
        "Prose clause to compile:\n"
        f"{prose_clause}\n\n"
        "Draft one or more candidate rules in this schema (SPEC §6):\n"
        "{id, service_id, policy_id, clause_ref, description, "
        "when: {field, op, value}, assert: {field, op, value or value_by}, "
        "on_violation: {exceptionable, severity, hard_block, adds_approval, "
        "routing_correction, approver_department_id, compensating_controls, ...}}\n"
        'Every drafted rule must include "status": "PROPOSED". Respond with JSON '
        'exactly matching this shape: {"proposed_rules": [rule, ...]}'
    )
