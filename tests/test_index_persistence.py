"""El índice en disco es JSON Lines (una cápsula por línea) dentro del gzip: se lee y se
escribe en streaming. Un único documento JSON obligaba a tener a la vez el texto
descomprimido, el dict parseado y las cápsulas, y orjson reserva ~12× la entrada para
parsearlo (medido en django: 113 MB de JSON → pico de 1,7 GB de memoria comprometida)."""

import gzip
import json

from leo_code.core.parser import Capsule
from leo_code.rag.indexer import Indexer


def _caps():
    return [
        Capsule(id="a", type="function", name="run", file_path="/r/m.py", start_line=1,
                end_line=3, language="python", signature="def run(x)",
                content="def run(x):\n    return 'ñ\\n' + x\n", docstring="Hace\nalgo",
                calls=["go"], called_by=["main"], imports=["os"],
                properties={"call_forms": [["go", ""]], "class": None}),
        Capsule(id="b", type="class", name="K", file_path="/r/k.py", start_line=5,
                end_line=9, language="python", signature="class K", content=""),
    ]


def _indexer(caps):
    idx = Indexer()
    idx._capsules = {c.id: c for c in caps}
    return idx


def test_roundtrip_keeps_every_field(tmp_path):
    p = tmp_path / "index.json.gz"
    _indexer(_caps()).save(str(p))
    idx = Indexer()
    idx.load(str(p))
    assert idx.get_capsules() == {c.id: c for c in _caps()}


def test_index_is_one_capsule_per_line(tmp_path):
    p = tmp_path / "index.json.gz"
    _indexer(_caps()).save(str(p))
    lines = gzip.decompress(p.read_bytes()).decode("utf-8").splitlines()
    assert [json.loads(l)["id"] for l in lines] == ["a", "b"]


def test_save_by_repo_keeps_only_that_repo(tmp_path):
    p = tmp_path / "index.json.gz"
    caps = _caps() + [Capsule(id="z", type="function", name="f", file_path="/otro/f.py",
                              start_line=1, end_line=1, language="python", signature="", content="")]
    _indexer(caps).save(str(p), repo="/r")
    idx = Indexer()
    idx.load(str(p))
    assert sorted(idx.get_capsules()) == ["a", "b"]


def test_legacy_single_document_still_loads(tmp_path):
    # índices escritos antes del cambio (TUI/agente usan kc_index.json.gz sin versión)
    p = tmp_path / "kc_index.json.gz"
    data = {c.id: {k: getattr(c, k) for k in c.__dataclass_fields__} for c in _caps()}
    p.write_bytes(gzip.compress(json.dumps(data, indent=2).encode("utf-8")))
    idx = Indexer()
    idx.load(str(p))
    assert idx.get_capsules() == {c.id: c for c in _caps()}


def test_merge_keeps_what_was_loaded(tmp_path):
    p = tmp_path / "index.json.gz"
    _indexer(_caps()[:1]).save(str(p))
    idx = _indexer(_caps()[1:])
    idx.load(str(p), merge=True)
    assert sorted(idx.get_capsules()) == ["a", "b"]
