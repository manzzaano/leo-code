"""Smoke test: extracción determinista de evidencia (sin LLM) encuentra nodos
mencionados en el texto y verify_grounding puntúa contra el subgrafo."""

from leo_code.core.evidence import extract_evidence, verify_grounding


def test_extract_evidence_finds_mentioned_node():
    nodes = [{"id": "n1", "name": "build_report", "type": "function"}]

    evidence, inferencias = extract_evidence(
        "La funcion build_report arma el reporte.", nodes
    )

    assert evidence[0]["node_id"] == "n1"
    assert inferencias == []


def test_extract_evidence_lists_unmentioned_as_inferencia():
    nodes = [{"id": "n1", "name": "build_report", "type": "function"}]

    evidence, inferencias = extract_evidence("Texto que no menciona nada relevante.", nodes)

    assert evidence == []
    assert len(inferencias) == 1


def test_verify_grounding_scores_partial_match():
    nodes = [{"id": "n1", "name": "a"}, {"id": "n2", "name": "b"}]
    evidence = [{"node_id": "n1", "relacion": "x", "valor": "a"}]

    result = verify_grounding(evidence, nodes)

    assert result["verified_claims"] == 1
    assert result["total_entities_in_context"] == 2
    assert result["score"] == 0.5
    assert result["low_confidence"] is True
