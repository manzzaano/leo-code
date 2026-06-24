"""Tests: scorer — TF-IDF identifier-aware, PageRank, greedy budget knapsack."""

from leo_code.core.parser import Capsule
from leo_code.rag.scorer import (
    pagerank,
    score_capsules,
    select_within_budget,
    tfidf_scores,
    tokenize,
)


def _cap(name, calls=None, ctype="function", docstring="", signature=""):
    return Capsule(
        id=name, type=ctype, name=name, file_path=f"{name}.py",
        start_line=1, end_line=3, language="python",
        signature=signature or f"def {name}()", content=f"def {name}(): pass",
        docstring=docstring, calls=calls or [],
        properties={},
    )


def test_tokenize_splits_identifiers():
    toks = tokenize("recalcularPlayerStats")
    assert "recalcular" in toks
    assert "player" in toks
    assert "stats" in toks
    # el identificador completo se preserva
    assert "recalcularplayerstats" in toks


def test_tokenize_snake_and_pascal():
    assert "parse" in tokenize("parse_ast_node")
    assert "ast" in tokenize("parse_ast_node")
    assert "xml" in tokenize("XMLParser")
    assert "parser" in tokenize("XMLParser")


def test_tfidf_ranks_matching_identifier_first():
    caps = [
        _cap("verifyUser", docstring="checks credentials"),
        _cap("hashPassword", docstring="hashes a secret"),
        _cap("renderTemplate", docstring="renders html"),
    ]
    scores = tfidf_scores(caps, "verify user")
    assert scores["verifyUser"] > scores["hashPassword"]
    assert scores["verifyUser"] > scores["renderTemplate"]


def test_tfidf_empty_query():
    caps = [_cap("foo")]
    assert tfidf_scores(caps, "") == {"foo": 0.0}


def test_pagerank_converges_and_ranks_hub():
    # a y b llaman a hub -> hub debe tener mayor rank
    caps = [
        _cap("hub"),
        _cap("a", calls=["hub"]),
        _cap("b", calls=["hub"]),
    ]
    pr = pagerank(caps)
    assert pr["hub"] > pr["a"]
    assert pr["hub"] > pr["b"]
    # suma ~1 (distribución de probabilidad)
    assert abs(sum(pr.values()) - 1.0) < 1e-3


def test_pagerank_empty():
    assert pagerank([]) == {}


def test_score_combines_and_boosts_code():
    # mismo texto en code y doc; query multi-término mantiene el coseno < 1
    # para que el clamp a 1.0 no empate. El +0.3 de código rompe el empate.
    code = _cap("alpha", docstring="target", ctype="function")
    doc = _cap("beta", docstring="target", ctype="document")
    final, struct, sem = score_capsules([code, doc], "target helper extra")
    assert sem["alpha"] == sem["beta"]          # mismo componente semántico
    assert final["alpha"] > final["beta"]        # el boost de código separa
    assert set(struct) == {"alpha", "beta"}


def test_select_respects_budget():
    caps = [_cap(f"f{i}", docstring=f"function number {i}") for i in range(20)]
    scores = {c.id: 1.0 - i * 0.01 for i, c in enumerate(caps)}
    selected, stats = select_within_budget(caps, scores, budget=40)
    assert stats["tokens_used"] <= 40
    assert stats["nodes_total"] == 20
    assert len(selected) == stats["nodes_selected"]
    # selecciona los de mayor score primero
    assert selected[0].id == "f0"


def test_select_neighbor_decay_boosts_connected():
    # target tiene score alto; helper bajo pero es vecino -> entra antes que un aislado igual de bajo
    target = _cap("target", calls=["helper"], docstring="aaa bbb ccc")
    helper = _cap("helper", docstring="ddd eee fff")
    isolated = _cap("isolated", docstring="ggg hhh iii")
    caps = [target, helper, isolated]
    scores = {"target": 0.9, "helper": 0.1, "isolated": 0.1}
    # budget para 2 nodos aprox
    selected, _ = select_within_budget(caps, scores, budget=30, neighbor_decay=0.7)
    ids = [c.id for c in selected]
    assert "target" in ids
    # helper recibe boost 0.9*0.7=0.63 > 0.1 de isolated -> se prefiere
    if len(ids) >= 2:
        assert "helper" in ids


def test_select_empty_or_zero_budget():
    assert select_within_budget([], {}, 100)[0] == []
    assert select_within_budget([_cap("f")], {"f": 1.0}, 0)[0] == []
