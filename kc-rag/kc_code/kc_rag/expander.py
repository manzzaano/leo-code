"""Expander: BFS sobre grafo de dependencias para expandir top-50 a ~150 candidatas.

Usa kc_core.graph.bfs_subgraph para el traversal estructural.
"""

from kc_core.parser import Capsule

_edges_cache: tuple[int, list[dict]] = (0, [])


def _build_edges(nodes: list[Capsule], nodes_by_id: dict[str, Capsule]) -> list[dict]:
    global _edges_cache
    nodes_id = id(nodes)
    if _edges_cache[0] == nodes_id:
        return _edges_cache[1]
    name_to_id = {c.name: c.id for c in nodes}
    edges = []
    for c in nodes:
        for call_name in c.calls:
            target_id = name_to_id.get(call_name)
            if target_id:
                edges.append({"from": c.id, "type": "LLAMA", "to": target_id})
    _edges_cache = (nodes_id, edges)
    return edges


def expand(
    capsules: dict[str, Capsule],
    seed_ids: list[str],
    max_depth: int = 2,
    max_candidates: int = 200,
) -> list[Capsule]:
    """
    Expande un conjunto semilla de cápsulas vía BFS sobre sus dependencias.
    Retorna lista de cápsulas topológicamente conectadas.
    """
    nodes = list(capsules.values())
    nodes_by_id = {c.id: c for c in nodes}
    edges = _build_edges(nodes, nodes_by_id)

    from kc_core.graph import bfs_subgraph
    visited_ids = set()
    all_capsules: dict[str, Capsule] = {}

    for seed_id in seed_ids:
        if seed_id not in nodes_by_id:
            continue
        graph_nodes = {n.id: {"id": n.id, "name": n.name, "type": n.type,
                               "signature": n.signature, "file_path": n.file_path}
                       for n in nodes}
        bfs_nodes, bfs_edges = bfs_subgraph(seed_id, graph_nodes, edges, max_depth=max_depth)
        for n in bfs_nodes:
            nid = n["id"]
            if nid in nodes_by_id and nid not in visited_ids:
                visited_ids.add(nid)
                all_capsules[nid] = nodes_by_id[nid]
        if len(all_capsules) >= max_candidates:
            break

    return list(all_capsules.values())
