from dataclasses import asdict

from backend.db import SessionLocal
from backend.engine.decisions import record_decision
from backend.engine.rules import evaluate
from backend.graph.state import RequestState
from backend.rag.index import build_index
from backend.rag.retrieve import retrieve


def run(state: RequestState) -> dict:
    """Retrieval feeds explanation only; the rule engine produces the decision
    (SPEC §2/§9). If retrieval finds no governing clause for this service,
    halt and escalate rather than let the model improvise policy (SPEC §8).
    """
    service_id = state["service_id"]
    entities = state.get("entities", {})
    context = state.get("context", {})

    session = SessionLocal()
    try:
        index = build_index(session)
        clause_hits = retrieve(index, state.get("intent") or "", service_id, top_k=5)

        if not clause_hits:
            with record_decision(session, state["request_id"], "POLICY", "RULE_ENGINE", "rag.retrieve") as rec:
                rec.inputs_used = {"service_id": service_id}
                rec.output = {"clause_hits": []}
                rec.rationale = "No governing clause retrieved for this service."
            return {"clause_hits": [], "halt_reason": "NO_GOVERNING_POLICY"}

        rule_results = evaluate(service_id, entities, context)
        rule_result_dicts = [asdict(r) for r in rule_results]
        violated = [r for r in rule_result_dicts if r["applicable"] and not r["passed"]]

        tier = None
        if any(r.get("hard_block") for r in violated):
            from backend.catalog import load_catalog
            catalog = load_catalog()
            service = catalog.get(service_id, {})
            base_tier = service.get("base_tier", 1)
            tier = base_tier
            for r in violated:
                if r.get("hard_block"):
                    tier = max(tier, r.get("tier_override") or 4)

        with record_decision(session, state["request_id"], "POLICY", "RULE_ENGINE", "engine.rules") as rec:
            rec.inputs_used = {"service_id": service_id, "payload": entities}
            rec.clause_refs = [hit["clause_ref"] for hit in clause_hits]
            rec.output = {"rule_results": rule_result_dicts}
            rec.rationale = f"{len(violated)} rule(s) violated" if violated else "All applicable rules passed"
    finally:
        session.close()

    res = {"clause_hits": clause_hits, "rule_results": rule_result_dicts}
    if tier is not None:
        res["tier"] = tier
    return res
