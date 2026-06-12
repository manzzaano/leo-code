"""Serialize semantic clusters to hierarchical markdown, agnóstico y escalable."""

from leo_code.rag.semantic_clustering import SemanticCluster


def serialize_clusters(clusters: list[SemanticCluster], token_budget: int = 3000) -> str:
    """Convert clusters to hierarchical markdown, fixed params (agnóstico al repo).

    Estrategia simple y escalable: top N clusters, M nodes per cluster.
    Funciona igual en repos pequeños o gigantes.

    Args:
        clusters: List of SemanticCluster
        token_budget: Target token limit (rough: ~4 chars per token)

    Returns:
        Markdown string

    Fixed params (agnóstico):
    - Max 2 clusters (no más, no menos)
    - Max 4 nodes per cluster
    - Token budget: 2000 (strict)
    - Sort by size ascending for diversity
    """
    if not clusters:
        return ""

    lines = []
    char_budget = token_budget * 4  # Rough: 4 chars per token
    char_count = 0

    # Fixed: top 3 clusters (smallest first for diversity)
    max_clusters = 3
    max_nodes_per_cluster = 6

    # Sort by size ascending, take top 2
    relevant = sorted(clusters, key=lambda c: c.size)[:max_clusters]

    for cluster in relevant:
        # Cluster header
        header = f"# {cluster.label} ({cluster.size} items)\n\n"

        if char_count + len(header) > char_budget:
            break

        lines.append(header.rstrip())
        char_count += len(header)

        # Fixed: max 4 nodes per cluster
        for node in cluster.capsules[:max_nodes_per_cluster]:
            node_header = f"## {node.name} ({node.type})\n"

            if char_count + len(node_header) > char_budget:
                break

            lines.append(node_header.rstrip())
            char_count += len(node_header)

            # Graph edges (limited to 2 per type)
            if node.edges:
                calls = [e.target_id for e in node.edges if e.edge_type == "calls"][:2]
                imported_by = [e.source_id for e in node.edges if e.edge_type == "imported_by"][:2]

                if calls:
                    edge_line = f"**Calls:** {', '.join(calls)}\n"
                    if char_count + len(edge_line) <= char_budget:
                        lines.append(edge_line.rstrip())
                        char_count += len(edge_line)

                if imported_by:
                    edge_line = f"**Imported by:** {', '.join(imported_by)}\n"
                    if char_count + len(edge_line) <= char_budget:
                        lines.append(edge_line.rstrip())
                        char_count += len(edge_line)

            lines.append("")
            char_count += 1

    return "\n".join(lines)
