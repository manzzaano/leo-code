"""Tests: detección de tasks de amplitud (verbosity/effort off para review/arquitectura)."""

from leo_code.rag.agent.loop import _is_breadth


def test_breadth_tasks_by_type():
    assert _is_breadth("haz code review", "review")
    assert _is_breadth("analiza el diseno", "design_review")
    assert _is_breadth("explica para nuevo dev", "onboard")
    assert _is_breadth("revisa seguridad", "audit")


def test_breadth_by_signal_despite_misclassification():
    # el classifier mete arquitectura/trace en code_query → las señales lo rescatan
    assert _is_breadth("Explica la arquitectura del plugin system", "code_query")
    assert _is_breadth("Traza la cadena completa de dependencias desde X", "code_query")
    assert _is_breadth("Audita la seguridad de server.py", "search")


def test_narrow_tasks_not_breadth():
    assert not _is_breadth("Que hace la funcion detect_frameworks", "code_query")
    assert not _is_breadth("Escribe tests para compact_history", "test_gen")
    assert not _is_breadth("Modifica GoalRunner._plan", "code_edit")
    assert not _is_breadth("Encuentra funciones sin docstring", "search")
