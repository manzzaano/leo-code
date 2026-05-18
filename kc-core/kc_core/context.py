"""Serialización compacta de contexto para enviar al LLM."""


def serialize_context(nodes: list[dict], edges: list[dict] = None) -> str:
    """
    Formato compacto: 1 línea por entidad + sección de relaciones.
    [nombre|tipo] prop1=val1, prop2=val2
    ---
    [from]-[REL]-[to]

    Incluye campos de código Y de dominio (descripcion, precio, descuento…).
    Excluye embeddings, hashes y metadatos internos.
    """
    lines = []
    node_map = {n["id"]: n.get("name", n["id"]) for n in nodes}

    skip_keys = {
        "id", "status", "created_at", "updated_at", "source_doc_id", "source_hash",
        "aliases", "_depth", "precision_critical", "embedding",
    }

    # Campos objetivo: código (original) + dominio (nuevo)
    target_keys = {
        # Código
        "parametros", "lineas_aprox", "lineas", "module", "docstring", "tipo_retorno",
        "metodos_publicos", "metodos", "hereda_de", "path", "importado_por", "confidence",
        # Dominio
        "descripcion", "description", "precio", "precio_base", "precio_final",
        "descuento", "descuento_pct", "porcentaje", "valor", "valor_maximo",
        "tipo_condicion", "aplica_a", "requisitos", "restricciones",
        "edad_minima", "edad_maxima", "penalizacion", "penalizacion_max",
        "servicios", "categoria", "segmento", "permanencia",
    }

    for node in nodes:
        name = node.get("name", node.get("id", "?"))
        ntype = node.get("type", "")
        props: dict[str, str] = {}

        # 1. Campos del sub-dict "properties" (si existe)
        props_source = node.get("properties", {}) or {}
        for k, v in props_source.items():
            if v and k not in skip_keys:
                vshort = str(v).replace("\n", " ").strip()
                if len(vshort) > 120:
                    vshort = vshort[:117] + "..."
                props[k] = vshort

        # 2. Campos root-level en target_keys
        for k in target_keys:
            v = node.get(k)
            if v and k not in props:
                vshort = str(v).replace("\n", " ").strip()
                if len(vshort) > 120:
                    vshort = vshort[:117] + "..."
                props[k] = vshort

        props_str = ", ".join(f"{k}={v}" for k, v in props.items())
        line = f"[{name}|{ntype}]"
        if props_str:
            line += f" {props_str}"
        lines.append(line)

    if edges:
        lines.append("---")
        for edge in edges:
            from_name = node_map.get(edge["from"], edge["from"][:12])
            to_name = node_map.get(edge["to"], edge["to"][:12])
            lines.append(f"[{from_name}]-[{edge['type']}]-[{to_name}]")

    return "\n".join(lines)
