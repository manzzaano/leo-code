"""Tests: BM25 sparse retrieval."""

from leo_code.core.parser import Capsule
from leo_code.rag.bm25 import BM25Index


def _capsules():
    return [
        Capsule(id="1", type="function", name="greet", file_path="a.py",
                start_line=1, end_line=3, language="python",
                signature="def greet(name: str) -> str", content="",
                docstring="Say hello", calls=[], properties={}),
        Capsule(id="2", type="function", name="process", file_path="b.py",
                start_line=1, end_line=5, language="python",
                signature="def process(data: dict) -> dict", content="",
                docstring="Process input data and return result", calls=[], properties={}),
        Capsule(id="3", type="class", name="UserService", file_path="c.py",
                start_line=1, end_line=10, language="python",
                signature="class UserService", content="",
                docstring="Handles user operations", calls=[], properties={}),
    ]


def test_bm25_add_and_search():
    idx = BM25Index()
    idx.add(_capsules())
    results = idx.search("greet hello", top_k=5)
    assert len(results) > 0
    assert results[0].capsule_id == "1"  # mejor match para "greet hello"


def test_bm25_search_no_match():
    idx = BM25Index()
    idx.add(_capsules())
    results = idx.search("zzz_nonexistent_word")
    assert results == []


def test_bm25_empty():
    idx = BM25Index()
    assert idx.search("anything") == []


def test_bm25_process_match():
    idx = BM25Index()
    idx.add(_capsules())
    results = idx.search("process data input")
    assert len(results) > 0
    assert results[0].capsule_id == "2"
