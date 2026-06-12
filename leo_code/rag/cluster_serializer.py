"""Serialize semantic clusters to hierarchical markdown, dynamic by token budget."""

from leo_code.rag.semantic_clustering import SemanticCluster


def serialize_clusters(clusters: list[SemanticCluster], token_budget: int = 4000) -> str:
    """Convert clusters to hierarchical markdown, limited by token budget.

    Agnóstico al tamaño del repo: itera clusters hasta llenar presupuesto.
    Descarta outliers y maximiza diversidad.

    Args:
        clusters: List of SemanticCluster
        token_budget: Target token limit (rough: ~4 chars per token)

    Returns:
        Markdown string

    Strategy:
    - Discard outlier clusters (> 150 items) from loose DBSCAN
    - Sort by size ascending (small clusters first for diversity)
    - Serialize nodes within each cluster until budget exhausted
    - Scales automatically: small repos get many clusters, large repos get few
    """
    if not clusters:
        return ""

    lines = []
    char_budget = token_budget * 4  # Rough: 4 chars per token
    char_count = 0

    # Include all clusters (don't filter outliers — token budget is the limit)
    # Sort by size ascending (small clusters first for diversity)
    relevant = sorted(clusters, key=lambda c: c.size)

    for cluster in relevant:
        # Cluster header
        header = f"# {cluster.label} ({cluster.size} items)\n\n"

        if char_count + len(header) > char_budget:
            # Budget exhausted
            break

        lines.append(header.rstrip())
        char_count += len(header)

        # Nodes in cluster: limit based on available space, but cap at 8
        remaining_budget = char_budget - char_count
        avg_node_size = 200  # Rough estimate
        max_nodes = min(8, max(1, remaining_budget // avg_node_size))

        for node in cluster.capsules[:max_nodes]:
            node_header = f"## {node.name} ({node.type})\n"

            if char_count + len(node_header) > char_budget:
                break

            lines.append(node_header.rstrip())
            char_count += len(node_header)

            # Graph edges
            if node.edges:
                calls = [e.target_id for e in node.edges if e.edge_type == "calls"][:3]
                imported_by = [e.source_id for e in node.edges if e.edge_type == "imported_by"][:3]

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
