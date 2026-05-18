"""Grafo de dependencias: BFS traversal, filtro de relaciones, búsqueda."""

from collections import deque
from typing import Optional


def bfs_subgraph(
    start_node_id: str,
    graph: dict[str, dict],
    edges: list[dict],
    max_depth: int = 2,
) -> tuple[list[dict], list[dict]]:
    """
    BFS desde start_node_id. Retorna (nodes, edges).
    Edges espera [{"from": id, "to": id, "type": str, "properties": dict}].
    """
    node_index = {n["id"]: n for n in graph.values()} if isinstance(graph, dict) else {n["id"]: n for n in graph}
    visited_nodes = set()
    visited_edges = set()
    nodes = []
    result_edges = []

    edge_index = {}
    for e in edges:
        key = f"{e['from']}::{e['type']}::{e['to']}"
        edge_index.setdefault(e["from"], []).append(e)

    queue = deque([(start_node_id, 0)])
    visited_nodes.add(start_node_id)

    while queue:
        current_id, depth = queue.popleft()

        node = node_index.get(current_id)
        if node:
            nodes.append(node)

        if depth >= max_depth:
            continue

        for edge in edge_index.get(current_id, []):
            edge_key = f"{edge['from']}::{edge['type']}::{edge['to']}"
            if edge_key not in visited_edges:
                visited_edges.add(edge_key)
                result_edges.append(edge)
            neighbor = edge["to"]
            if neighbor not in visited_nodes:
                visited_nodes.add(neighbor)
                queue.append((neighbor, depth + 1))

    return nodes, result_edges


def find_nodes_by_name(nodes: list[dict], name: str, limit: int = 5) -> list[dict]:
    """Busca nodos cuyo nombre contenga 'name' (case-insensitive)."""
    name_lower = name.lower()
    matches = []
    for n in nodes:
        n_name = n.get("name", "").lower()
        if name_lower in n_name:
            matches.append(n)
            if len(matches) >= limit:
                break
    return matches


_RELATION_PATTERNS = {
    "llama": "LLAMA", "llamar": "LLAMA",
    "importa": "IMPORTA", "importar": "IMPORTA", "imports": "IMPORTA",
    "define": "DEFINE", "definir": "DEFINE", "definidas": "DEFINE",
    "hereda": "HEREDA", "heredar": "HEREDA",
    "usa": "USA", "usar": "USA",
}


def detect_relation_filter(query: str) -> Optional[set[str]]:
    """Detecta tipos de relación mencionados en la query."""
    q = query.lower()
    found = set()
    for keyword, rel_type in _RELATION_PATTERNS.items():
        if keyword in q:
            found.add(rel_type)
    return found if found else None


def filter_by_relation(
    edges: list[dict],
    nodes_map: dict[str, dict],
    start_ids: set[str],
    rel_types: set[str],
) -> tuple[dict[str, dict], list[dict]]:
    """Filtra aristas por tipo y mantiene solo nodos conectados."""
    filtered_edges = [e for e in edges if e["type"] in rel_types]
    connected = set(start_ids)
    for e in filtered_edges:
        connected.add(e["from"])
        connected.add(e["to"])
    filtered_nodes = {nid: n for nid, n in nodes_map.items() if nid in connected}
    return filtered_nodes, filtered_edges
