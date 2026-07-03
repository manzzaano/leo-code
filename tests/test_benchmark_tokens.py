"""El benchmark reporta el coste REAL del runner ([LEO_TOKENS=N] por stderr),
no la estimación len//4 de solo-salida. Fallback si el marcador no llegó."""

from benchmark.run_real import parse_leo_tokens


def test_usa_total_tokens_real_del_marcador():
    stderr = "[indexer] 10 archivos\n[LEO_TOKENS=12345]\n"
    assert parse_leo_tokens(stderr, "x" * 400) == 12345


def test_fallback_len_4_sin_marcador():
    assert parse_leo_tokens("[indexer] log sin marcador", "x" * 400) == 100


def test_fallback_con_stderr_vacio_o_none():
    assert parse_leo_tokens("", "x" * 40) == 10
    assert parse_leo_tokens(None, "x" * 40) == 10
