"""Extracción determinista de evidencia desde texto de respuesta.

Escanea la respuesta buscando nombres de entidad del subgrafo.
Cero dependencia del LLM para la trazabilidad.
"""


def extract_evidence(respuesta: str, nodes: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Encuentra qué entidades del subgrafo se mencionan en la respuesta.
    Retorna (evidence, inferencias).
    """
    text = respuesta.lower()
    node_names = {}
    for n in nodes:
        name = n.get("name", "")
        if name and len(name) >= 2:
            node_names[name.lower()] = n

    found = {}
    for name_lower, node in sorted(node_names.items(), key=lambda x: -len(x[0])):
        if name_lower in text:
            found[name_lower] = node

    evidence = [
        {
            "nombre": node["name"],
            "node_id": node["id"],
            "relacion": "mencionado_en_respuesta",
            "valor": node.get("name", ""),
        }
        for node in found.values()
    ]

    inferencias = [
        f"[no citado en respuesta] {n.get('name', '?')} ({n.get('type', '?')})"
        for n in nodes
        if n.get("name", "").lower() not in found
    ]

    return evidence, inferencias


def verify_grounding(evidence: list[dict], nodes: list[dict]) -> dict:
    """Verifica que los node_ids en evidence existan en el subgrafo."""
    node_map = {n["id"]: n for n in nodes}
    verified = []
    inferencias = []

    for claim in evidence:
        nid = claim.get("node_id", "")
        if nid and nid in node_map:
            verified.append(claim)
        else:
            inferencias.append(
                f"[node_id no encontrado: {nid}] {claim.get('relacion', '')}: {claim.get('valor', '')}"
            )

    total = len(nodes)
    score = len(verified) / total if total > 0 else 0.0

    return {
        "evidence": verified,
        "inferencias": inferencias,
        "score": round(score, 3),
        "verified_claims": len(verified),
        "total_entities_in_context": total,
        "low_confidence": score < 0.70,
    }
