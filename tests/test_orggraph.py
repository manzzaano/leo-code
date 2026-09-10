"""orggraph.py ya trae su propio self-check (_demo, con asserts) para validar
el trace cross-repo/cross-lenguaje sin red ni repos reales. Este test solo lo
engancha a pytest para que corra en CI en vez de depender de invocacion manual."""

from leo_code.core.orggraph import _demo


def test_orggraph_self_check_runs_clean(capsys):
    _demo()  # revienta con AssertionError si el trace cross-repo se rompe

    out = capsys.readouterr().out
    assert "self-check OK" in out
