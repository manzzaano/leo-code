"""Tests: classifier — clasificación de tipos de tarea."""

from leo_code.rag.classifier import classify_task, needs_code_context, get_budget


def test_classify_code_query():
    assert classify_task("qué hace la función process_payment") == "code_query"
    assert classify_task("explain how the auth module works") == "code_query"


def test_classify_debug():
    assert classify_task("hay un bug en login") == "debug"
    assert classify_task("por qué falla el endpoint /users") == "debug"
    assert classify_task("fix the crash in payment handler") == "debug"


def test_classify_test_gen():
    assert classify_task("escribe tests para UserService") == "test_gen"
    assert classify_task("genera unit tests para la función calculate_tax") == "test_gen"


def test_classify_refactor():
    assert classify_task("refactoriza el módulo de auth") == "refactor"
    assert classify_task("extrae la lógica de validación") == "refactor"


def test_classify_search():
    assert classify_task("busca todas las funciones sin docstring") == "search"
    assert classify_task("cuántas clases heredan de BaseModel") == "search"


def test_classify_review():
    assert classify_task("haz code review de auth.py") == "review"
    assert classify_task("revisa este código") == "review"


def test_classify_optimize():
    assert classify_task("optimiza el loop de parse_large_file") == "optimize"
    assert classify_task("mejora la performance de la query") == "optimize"


def test_classify_audit():
    assert classify_task("audita la seguridad del endpoint /login") == "audit"
    assert classify_task("hay una vulnerabilidad sql injection aqui") == "audit"


def test_classify_onboard():
    assert classify_task("explicame la estructura del proyecto") == "onboard"
    assert classify_task("cómo empezar con este repo") == "onboard"


def test_classify_code_gen():
    assert classify_task("crea un nuevo endpoint para export") == "code_gen"
    assert classify_task("añade una función de logging") == "code_gen"


def test_needs_code_context():
    assert needs_code_context("qué hace retrieve_subgraph")
    assert needs_code_context("explain the parser module")
    assert not needs_code_context("hola cómo estás")


def test_get_budget():
    assert get_budget("bug en auth") >= 2500
    assert get_budget("qué hace X") == 1500
    assert get_budget("busca todas las funciones") == 500
    assert get_budget("crea un nuevo archivo") == 800
