"""BM25 propio sin numpy: mismas puntuaciones que rank_bm25.BM25Okapi (el que se usaba)."""

import pytest

from leo_code.rag.bm25 import BM25Index, code_tokens
from leo_code.core.parser import Capsule

rank_bm25 = pytest.importorskip("rank_bm25")  # oráculo, solo en el extra dev

DOCS = [
    ("a", "compute_context", "Build the compressed context for a question"),
    ("b", "who_calls", "Direct callers of a symbol"),
    ("c", "impact", "Everything that depends on a symbol transitively"),
    ("d", "trace", "Call path between two symbols"),
    ("e", "guard", "Impact plus which dependents have no tests"),
    ("f", "symbol_symbol", "symbol symbol symbol"),
]


def _caps():
    return [Capsule(id=i, type="function", name=n, file_path=f"m/{n}.py", start_line=1,
                    end_line=2, language="python", signature=f"def {n}()", content="",
                    docstring=d)
            for i, n, d in DOCS]


@pytest.mark.parametrize("query", ["callers of symbol", "symbol", "compressed context",
                                   "tests dependents impact", "nothing matches xyz"])
def test_puntuaciones_identicas_a_bm25okapi(query):
    idx = BM25Index()
    idx.add(_caps())
    ours = idx._index.get_scores(code_tokens(query))
    ref = rank_bm25.BM25Okapi(idx._tokenized).get_scores(code_tokens(query))
    assert list(ours) == [float(x) for x in ref]
