from typing import Iterable

import networkx as nx


def build_graph(edges: Iterable) -> nx.MultiDiGraph:
    """Builds the ownership graph from ownership_edges rows (SPEC §7.1).

    Nodes are department ids. Each ownership_edges row becomes one directed
    edge source_department_id -> asserts_approver_department_id, carrying
    {edge_id, service_id, clause_ref, note} as edge data. A MultiDiGraph is
    used because the same department pair can carry edges for different
    services.
    """
    graph = nx.MultiDiGraph()
    for edge in edges:
        graph.add_edge(
            edge.source_department_id,
            edge.asserts_approver_department_id,
            key=edge.id,
            edge_id=edge.id,
            service_id=edge.service_id,
            clause_ref=edge.clause_ref,
            note=edge.note,
        )
    return graph


def subgraph_for_service(graph: nx.MultiDiGraph, service_id: str) -> nx.DiGraph:
    """A plain DiGraph containing only the edges tagged with one service_id."""
    sub = nx.DiGraph()
    for source, target, data in graph.edges(data=True):
        if data["service_id"] == service_id:
            sub.add_edge(source, target, **data)
    return sub


def find_cycles(graph: nx.MultiDiGraph, service_id: str) -> list[list[str]]:
    """Deterministic cycle detection for one service (SPEC §7.2). No LLM."""
    sub = subgraph_for_service(graph, service_id)
    return list(nx.simple_cycles(sub))
