"""El servidor MCP rehace el grafo con `GraphQuery.update` tras una edición, no desde cero
(plan 2026-11-18, unidad 4): mismo resultado que en frío, sin `GraphQuery.__init__`, y bajo
el mismo lock que las consultas, porque `update` cambia el grafo en sitio y los handlers
corren en hilos (`asyncio.to_thread`)."""

import os
import time
from pathlib import Path

import pytest

from leo_code import engine
from leo_code.core.graphquery import GraphQuery
from leo_code.server import mcp_server


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    t = time.time() + 5                  # mtime posterior al último sync: lo re-parsea
    os.utime(p, (t, t))
    return p


def _snap(gq):
    ids = lambda d: {k: [c.id for c in v] for k, v in d.items()}
    return (ids(gq.by_name), ids(gq.callers), ids(gq._res), dict(gq._qref),
            {k: set(v) for k, v in gq._fams.items()})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "_indexer", None)
    for name in ("_structural_at", "_generation", "_synced_at", "_save_timers"):
        monkeypatch.setattr(engine, name, {})
    monkeypatch.setattr(engine, "_SAVE_DEBOUNCE_S", 0.0)
    monkeypatch.setattr(engine, "SEMANTIC", False)
    monkeypatch.setattr(mcp_server, "_gq_cache", {})
    monkeypatch.setattr(mcp_server, "_guard_cache", {})
    r = tmp_path / "app"
    _write(r / "svc" / "core.py", "def helper():\n    return 1\n\ndef other():\n    return 2\n")
    _write(r / "svc" / "use.py", "from core import helper\n\ndef run():\n    helper()\n")
    return r


def _edit(repo: Path, rel: str, body: str) -> None:
    _write(repo / rel, body)
    engine._structural_at[str(repo)] = 0.0        # saltar el throttle de resync


def _who(repo: Path, sym: str) -> str:
    return mcp_server._graph({"op": "who_calls", "symbol": sym, "repo_path": str(repo)})


def test_edit_updates_graph_without_rebuilding(repo, monkeypatch):
    assert "run" in _who(repo, "helper")
    _, gq = mcp_server._repo_graph(str(repo))
    inits = []
    real = GraphQuery.__init__
    monkeypatch.setattr(GraphQuery, "__init__", lambda self, *a, **k: inits.append(1) or real(self, *a, **k))

    _edit(repo, "svc/use.py", "from core import helper, other\n\ndef run():\n    helper()\n    other()\n")
    out = _who(repo, "other")
    assert "run" in out
    caps, gq2 = mcp_server._repo_graph(str(repo))
    assert gq2 is gq and inits == []
    assert _snap(gq2) == _snap(GraphQuery(caps))


def test_queries_and_update_run_under_the_same_lock(repo, monkeypatch):
    _who(repo, "helper")
    held = []
    lock = lambda: mcp_server._graph_lock(str(repo))
    real_update, real_who = GraphQuery.update, mcp_server._who_calls
    monkeypatch.setattr(GraphQuery, "update",
                        lambda self, *a: held.append(("update", lock().locked())) or real_update(self, *a))
    monkeypatch.setattr(mcp_server, "_who_calls",
                        lambda gq, s: held.append(("who", lock().locked())) or real_who(gq, s))
    _edit(repo, "svc/use.py", "from core import helper\n\ndef run():\n    helper()\n    helper()\n")
    _who(repo, "helper")
    assert held == [("update", True), ("who", True)]


def test_failed_update_falls_back_to_a_fresh_graph(repo, monkeypatch):
    _who(repo, "helper")

    def boom(self, *a):
        self.callers.clear()                      # a medias: el grafo queda roto
        raise RuntimeError("fallo a mitad")
    monkeypatch.setattr(GraphQuery, "update", boom)
    _edit(repo, "svc/use.py", "from core import other\n\ndef run():\n    other()\n")
    assert "run" in _who(repo, "other")
    caps, gq = mcp_server._repo_graph(str(repo))
    assert _snap(gq) == _snap(GraphQuery(caps))
