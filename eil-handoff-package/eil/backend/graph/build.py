from langgraph.graph import END, StateGraph

from backend.graph.nodes import approval, clarifier, communicate, context, exception, guardrails, intent, policy, router
from backend.graph.state import RequestState

CHECKPOINT_DB_PATH = "checkpoints.sqlite"


def _route_after_guardrails(state: RequestState) -> str:
    if state.get("halt_reason"):
        return "communicate"
    return "intent"


def _route_after_clarifier(state: RequestState) -> str:
    if state.get("halt_reason"):
        return "communicate"
    if state.get("missing_fields"):
        return END
    return "policy"



def _route_after_policy(state: RequestState) -> str:
    if state.get("halt_reason"):
        return "communicate"
    violated = [r for r in state.get("rule_results", []) if r.get("applicable") and not r.get("passed")]
    if any(r.get("hard_block") for r in violated):
        return "communicate"
    if any(r.get("exceptionable") for r in violated):
        return "exception"
    return "router"


def _route_after_router(state: RequestState) -> str:
    return "approval" if state.get("tier", 0) >= 2 else "communicate"


def _route_after_approval(state: RequestState) -> str:
    approvals = state.get("approvals", [])
    if any(a.get("status") == "PENDING" for a in approvals) and not any(
        a.get("status") == "REJECTED" for a in approvals
    ):
        return "approval"
    return "communicate"


def build_graph(checkpointer):
    """Assembles the LangGraph per SPEC §5. Conditional edges only — no node
    calls another node directly. `resolution` is not part of this graph; it
    runs off-graph as a service over the stuck-request queue (SPEC §5, §7.4).
    """
    graph = StateGraph(RequestState)
    graph.add_node("guardrails", guardrails.run)
    graph.add_node("intent", intent.run)
    graph.add_node("context", context.run)
    graph.add_node("clarifier", clarifier.run)
    graph.add_node("policy", policy.run)
    graph.add_node("exception", exception.run)
    graph.add_node("router", router.run)
    graph.add_node("approval", approval.run)
    graph.add_node("communicate", communicate.run)

    graph.set_entry_point("guardrails")
    graph.add_conditional_edges(
        "guardrails", _route_after_guardrails, {"communicate": "communicate", "intent": "intent"}
    )
    graph.add_edge("intent", "context")
    graph.add_edge("context", "clarifier")

    graph.add_conditional_edges(
        "clarifier", _route_after_clarifier, {"communicate": "communicate", END: END, "policy": "policy"}
    )
    graph.add_conditional_edges(
        "policy", _route_after_policy, {"communicate": "communicate", "exception": "exception", "router": "router"}
    )
    graph.add_edge("exception", "router")
    graph.add_conditional_edges(
        "router", _route_after_router, {"communicate": "communicate", "approval": "approval"}
    )
    graph.add_conditional_edges(
        "approval", _route_after_approval, {"approval": "approval", "communicate": "communicate"}
    )
    graph.add_edge("communicate", END)

    return graph.compile(checkpointer=checkpointer)
