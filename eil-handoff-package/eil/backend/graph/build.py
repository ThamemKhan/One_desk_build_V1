from langgraph.graph import END, StateGraph

from backend.graph.nodes import approval, clarifier, communicate, context, exception, guardrails, intent, policy, router
from backend.graph.state import RequestState

CHECKPOINT_DB_PATH = "checkpoints.sqlite"


def _route_after_guardrails(state: RequestState) -> str:
    if state.get("halt_reason"):
        return "node_communicate"
    return "node_intent"


def _route_after_clarifier(state: RequestState) -> str:
    if state.get("halt_reason"):
        return "node_communicate"
    if state.get("missing_fields"):
        return END
    return "node_policy"


def _route_after_policy(state: RequestState) -> str:
    if state.get("halt_reason"):
        return "node_communicate"
    violated = [r for r in state.get("rule_results", []) if r.get("applicable") and not r.get("passed")]
    if any(r.get("hard_block") for r in violated):
        return "node_communicate"
    if any(r.get("exceptionable") for r in violated):
        return "node_exception"
    return "node_router"


def _route_after_router(state: RequestState) -> str:
    return "node_approval" if state.get("tier", 0) >= 2 else "node_communicate"


def _route_after_approval(state: RequestState) -> str:
    approvals = state.get("approvals", [])
    if any(a.get("status") == "PENDING" for a in approvals) and not any(
        a.get("status") == "REJECTED" for a in approvals
    ):
        return "node_approval"
    return "node_communicate"


def build_graph(checkpointer):
    """Assembles the LangGraph per SPEC §5. Conditional edges only — no node
    calls another node directly. `resolution` is not part of this graph; it
    runs off-graph as a service over the stuck-request queue (SPEC §5, §7.4).
    """
    graph = StateGraph(RequestState)
    graph.add_node("node_guardrails", guardrails.run)
    graph.add_node("node_intent", intent.run)
    graph.add_node("node_context", context.run)
    graph.add_node("node_clarifier", clarifier.run)
    graph.add_node("node_policy", policy.run)
    graph.add_node("node_exception", exception.run)
    graph.add_node("node_router", router.run)
    graph.add_node("node_approval", approval.run)
    graph.add_node("node_communicate", communicate.run)

    graph.set_entry_point("node_guardrails")
    graph.add_conditional_edges(
        "node_guardrails", _route_after_guardrails, {"node_communicate": "node_communicate", "node_intent": "node_intent"}
    )
    graph.add_edge("node_intent", "node_context")
    graph.add_edge("node_context", "node_clarifier")

    graph.add_conditional_edges(
        "node_clarifier", _route_after_clarifier, {"node_communicate": "node_communicate", END: END, "node_policy": "node_policy"}
    )
    graph.add_conditional_edges(
        "node_policy", _route_after_policy, {"node_communicate": "node_communicate", "node_exception": "node_exception", "node_router": "node_router"}
    )
    graph.add_edge("node_exception", "node_router")
    graph.add_conditional_edges(
        "node_router", _route_after_router, {"node_communicate": "node_communicate", "node_approval": "node_approval"}
    )
    graph.add_conditional_edges(
        "node_approval", _route_after_approval, {"node_approval": "node_approval", "node_communicate": "node_communicate"}
    )
    graph.add_edge("node_communicate", END)

    return graph.compile(checkpointer=checkpointer)
