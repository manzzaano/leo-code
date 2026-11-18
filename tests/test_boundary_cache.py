"""El escaneo HTTP de una cápsula se guarda en ella: tras una edición solo se escanean
las cápsulas nuevas (django: 6,2 µs/símbolo de 12,8 se iban en reescanear todo)."""

from leo_code.core import boundary
from leo_code.core.boundary import _scan, link_http_edges
from leo_code.core.parser import Capsule


def cap(name, content, file, deco=None):
    return Capsule(id=f"{file}:{name}", type="function", name=name, file_path=file, start_line=1,
                   end_line=9, language="python" if file.endswith(".py") else "typescript",
                   signature="", content=content, calls=[],
                   properties={"decorators": deco} if deco else {})


def _repo():
    return {c.id: c for c in (
        cap("get_user", "def get_user(): return db.user()", "api.py", deco="app.get('/api/user')"),
        cap("list_items", "def list_items(): ...", "api.py", deco="router.get('/api/items/{id}')"),
        cap("load", "const r = await fetch('/api/user')", "web/user.ts"),
        cap("item", "return axios.get(`/api/items/${id}`)", "web/item.ts"),
        cap("wrap", "return get<T>('/api/user')", "web/lib.ts"),
        cap("nada", "x = a.split('/')", "util.py"),
    )}


def _count(monkeypatch):
    n = []
    real = boundary._server_literals
    monkeypatch.setattr(boundary, "_server_literals", lambda *a: (n.append(1), real(*a))[1])
    return n


def _edges(caps):
    return sorted((c.name, x["to"]) for c in caps.values()
                  for x in (c.properties or {}).get("xlang_calls", []))


def test_segunda_pasada_sin_cambios_no_reescanea(monkeypatch):
    caps = _repo()
    n = _count(monkeypatch)
    link_http_edges(caps)
    first = len(n)
    assert first == len(caps)
    link_http_edges(caps)
    assert len(n) == first, "las cápsulas ya escaneadas no se vuelven a leer"


def test_capsula_sustituida_se_reescanea_y_cambia_el_grafo(monkeypatch):
    caps = _repo()
    link_http_edges(caps)
    assert ("load", "get_user") in _edges(caps)
    # sync sustituye la cápsula por un objeto nuevo (no la muta)
    new = cap("load", "const r = await fetch('/api/items/7')", "web/user.ts")
    caps[new.id] = new
    n = _count(monkeypatch)
    link_http_edges(caps)
    assert len(n) == 1, "solo la cápsula nueva"
    assert ("load", "list_items") in _edges(caps)


def test_varias_pasadas_dan_las_mismas_aristas_que_una():
    once = _repo()
    link_http_edges(once)
    many = _repo()
    for _ in range(3):
        link_http_edges(many)
    assert _edges(many) == _edges(once)
    assert {c.id: c.calls for c in many.values()} == {c.id: c.calls for c in once.values()}


def test_con_cache_el_escaneo_es_identico_al_de_cero():
    """Mismas rutas (y en el mismo orden) y mismos clientes que escaneando de cero."""
    caps = _repo()
    _scan(caps)                                  # llena la caché
    cached = _scan(caps)
    fresh = _scan(_repo())                       # objetos nuevos: sin caché
    as_ids = lambda r: ({t: [c.id for c in eps] for t, eps in r[0].items()},
                        [(c.id, t) for c, t in r[1]])
    assert as_ids(cached) == as_ids(fresh)
    assert list(cached[0]) == list(fresh[0])


def test_la_cache_no_cambia_la_igualdad_ni_lo_que_se_guarda():
    a, b = _repo(), _repo()
    link_http_edges(a)
    link_http_edges(b)
    _scan(a)
    assert a == b


def test_los_literales_de_ruta_tambien_se_guardan(monkeypatch):
    """Con rutas en el repo se buscan literales en las cápsulas candidatas (django: 4.062)."""
    caps = _repo()
    link_http_edges(caps)
    assert ("wrap", "get_user") in _edges(caps)   # cliente por literal: get<T>('/api/user')
    n = []
    real = boundary._literal_calls
    monkeypatch.setattr(boundary, "_literal_calls", lambda *a: (n.append(1), real(*a))[1])
    link_http_edges(caps)
    assert n == []
