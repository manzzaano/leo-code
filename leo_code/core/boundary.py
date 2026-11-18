"""Boundary — aristas CROSS-LENGUAJE en el grafo: cose el límite HTTP/RPC.

El AST de cada lenguaje no sabe que `fetch('/api/users')` en un componente React
llama al `@app.get('/api/users')` de un servicio FastAPI: son procesos y lenguajes
distintos. Este resolver extrae las rutas de ambos lados y añade la arista que falta,
para que `trace(boton_react, columna_db)` cruce los 6 servicios.

Se integra reusando el grafo existente: a la cápsula cliente se le añade el NOMBRE
de la cápsula-endpoint a su lista `calls`, así GraphQuery la recorre como una arista
normal. Determinista, sin LLM.

Cubre los patrones HTTP comunes (fetch/axios/.get/.post/@app/@router/
@route/Flask). El techo: rutas construidas dinámicamente por concatenación a runtime
no se resuelven; ampliar el matcher si un repo real lo necesita.

Self-check:  python -m leo_code.core.boundary
"""

from __future__ import annotations

import re

# Rutas de servidor: @app.get("/x"), @router.post('/x'), @app.route("/x"), .get("/x")
_SERVER_ROUTE = re.compile(
    r"""(?:@\w+\.(?:get|post|put|patch|delete|route)|\.(?:get|post|put|patch|delete|route))\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
# El mismo regex desde el `.`, para el texto ya en minúsculas: toda coincidencia de
# `@app.get(...)` contiene la de `.get(...)` con el mismo literal, y `_scan` solo usa el
# literal (que `_norm` baja a minúsculas). Una pasada en C en vez de 6 `find` por cápsula.
_SERVER_ROUTE_LOW = re.compile(
    r"""\.(?:get|post|put|patch|delete|route)\s*\(\s*['"]([^'"]+)['"]""")
# Llamadas cliente: fetch("/x"), axios.get('/x'), http.post(`/x`), request("/x")
_CLIENT_CALL = re.compile(
    r"""(?:fetch|axios|http|request|\$\.(?:ajax|get|post))(?:\.\w+)?\s*\(\s*[`'"]([^`'"]+)[`'"]""",
    re.IGNORECASE,
)


def _norm(route: str) -> str:
    """Normaliza una ruta a una plantilla comparable entre lenguajes.

    /api/users/{id}  ·  /api/users/:id  ·  /api/users/${id}  ·  /api/users/123
        → /api/users/*
    """
    r = route.strip()
    r = r.split("?")[0]                                   # quita querystring
    r = re.sub(r"https?://[^/]+", "", r)                  # quita host
    r = re.sub(r"\$\{[^}]+\}", "*", r)                    # template literal JS ${id}
    r = re.sub(r"\{[^}]+\}", "*", r)                      # path param FastAPI {id}
    r = re.sub(r":[A-Za-z_]\w*", "*", r)                  # path param Express :id
    r = re.sub(r"/\d+(?=/|$)", "/*", r)                   # segmento numérico literal
    r = "/" + r.strip("/")                                # normaliza slashes
    return r.lower()


# Prefiltros: TODA coincidencia posible de los dos regex contiene uno de estos
# literales (son el primer término de cada alternativa), así que un `in` sobre el texto
# ya en minúsculas descarta sin perder ni un match —los regex siguen siendo la única
# fuente de verdad, solo se les ahorra el 99% de las cápsulas—. Medido a 300k símbolos:
# escanear todo con el regex cliente costaba 3.629 ms; con prefiltro, 225 ms.
_CLIENT_HINTS = ("fetch", "axios", "http", "request", "$.")


def _route_literals(text: str, low: str):
    """Literales de ruta de servidor en `text` (`low` = text.lower()), en minúsculas salvo
    en el camino lento. Medido en django: _scan bajó de 6,0 a 3,6 µs/símbolo."""
    if len(low) != len(text):               # lower() cambió longitudes (Unicode): camino lento
        return [m.group(1) for m in _SERVER_ROUTE.finditer(text)]
    return _SERVER_ROUTE_LOW.findall(low)


# A (16/11): en código, `.get('/x')` solo es una RUTA si el receptor es un decorador o un
# objeto servidor; `axios.get('/x')`, `requests.get`, `client.get` son clientes (antes dos
# componentes que pedían la misma ruta quedaban unidos entre sí). En `decorators` (Python)
# cualquier `.get('/x')` es ruta. ponytail: lista corta de nombres de servidor; ampliar si
# un repo real llama al suyo de otra forma.
_SERVER_RECV = frozenset(("app", "router", "server", "blueprint", "bp"))
_RECV_BEFORE = re.compile(r"(@?)([\w$]+)$")
_SERVER_DEF_BEFORE = re.compile(
    r"(?:@[\w.$]*|\b(?:app|router|server|blueprint|bp))\.(?:get|post|put|patch|delete|route)\s*\(\s*$")
# C+D: un literal de ruta como argumento de CUALQUIER llamada es un cliente si casa con una
# ruta del servidor: los envoltorios (`get<Stats>("/api/stats")` en NEXUS) llaman a fetch
# por dentro con una variable. Admite `${BASE}/x` y `BASE + "/x"` delante del literal.
_PATH_LIT = re.compile(r"""[`'"](?:\$\{[^}`]*\})?((?:/|https?://)[^`'"\s]*)[`'"]""")
_CALL_BEFORE = re.compile(
    r"""[\w$]\s*(?:<[^<>()]*(?:<[^<>()]*>)?[^<>()]*>)?\s*\(\s*(?:[\w.$]+\s*\+\s*)?$""")
_PATH_HINTS = ("'/", '"/', "`/", "`${", "http")


def _server_literals(low: str, end: int) -> list[str]:
    """Rutas de servidor en `low[:end]` (en minúsculas): `@x.get('/r')` o
    `app|router|server|blueprint|bp.get('/r')`."""
    out = []
    for m in _SERVER_ROUTE_LOW.finditer(low, 0, end):
        r = _RECV_BEFORE.search(low, max(0, m.start() - 40), m.start())
        if r and (r.group(1) or r.group(2) in _SERVER_RECV):
            out.append(m.group(1))
    return out


def _literal_calls(content: str) -> list[str]:
    """Rutas literales pasadas a una llamada que no define una ruta de servidor."""
    out = []
    for m in _PATH_LIT.finditer(content):
        before = content[max(0, m.start() - 120):m.start()]
        if _CALL_BEFORE.search(before) and not _SERVER_DEF_BEFORE.search(before.lower()):
            out.append(m.group(1))
    return out


def _innermost(eps: list) -> list:
    """B: una ruta es de la def más interna, no de la clase que contiene su decorador."""
    def inside(o, e):
        return (o is not e and o.file_path == e.file_path
                and (e.start_line or 0) <= (o.start_line or 0) and (o.end_line or 0) <= (e.end_line or 0)
                and (o.start_line, o.end_line) != (e.start_line, e.end_line))
    return [e for e in eps if not any(inside(o, e) for o in eps)] if len(eps) > 1 else eps


def _hinted_finditer(rx, text: str, low: str, hints):
    """= rx.finditer(text) cuando toda coincidencia EMPIEZA por una pista: prueba el regex
    solo ahí (`low` = text.lower()), no en cada posición. Medido en django: el regex
    cliente costaba 9,7 µs/símbolo de la reconstrucción."""
    if len(low) != len(text):               # lower() cambió longitudes (Unicode): camino lento
        yield from rx.finditer(text)
        return
    starts = set()
    for h in hints:
        i = low.find(h)
        while i != -1:
            starts.add(i)
            i = low.find(h, i + 1)
    end = 0
    for i in sorted(starts):
        if i < end:                         # dentro de la coincidencia anterior: finditer no solapa
            continue
        m = rx.match(text, i)
        if m:
            yield m
            end = max(m.end(), i + 1)


def _scan_one(c) -> tuple:
    """Lo que una cápsula aporta a la frontera HTTP: (rutas de servidor, URLs de cliente,
    ¿puede llevar literales de ruta?). Solo depende de la propia cápsula."""
    content = getattr(c, "content", "") or ""
    # El parser AST de Python deja los decoradores FUERA de content/signature, en
    # properties["decorators"] ("app.get('/api/x')"): sin mirarlos, ninguna ruta
    # FastAPI/Flask de un repo real se cosía (medido en NEXUS, 2026-09-15).
    props = getattr(c, "properties", None) or {}
    deco = str(props.get("decorators", ""))
    sig = getattr(c, "signature", "") or ""
    server_text = " ".join((content, sig, deco))
    low = server_text.lower()
    if len(low) == len(server_text):     # sin copiar: content+sig es el prefijo de low
        code_low, code_end = low, len(content) + 1 + len(sig)
    else:
        code_low = " ".join((content, sig)).lower(); code_end = len(code_low)
    found = _route_literals(deco, deco.lower()) if deco else []
    found += _server_literals(code_low, code_end)
    routes = [_norm(r) for r in dict.fromkeys(found)]
    urls = []
    if any(h in low for h in _CLIENT_HINTS):
        # low empieza por content.lower() si lower() no cambió longitudes
        aligned = low[:len(content)] if len(low) == len(server_text) else content.lower()
        for m in _hinted_finditer(_CLIENT_CALL, content, aligned, _CLIENT_HINTS):
            url = m.group(1)
            if url.startswith(("/", "http")) or "/" in url:
                urls.append(_norm(url))
    literal = ("/" in content or "http" in content) and any(h in content for h in _PATH_HINTS)
    if not (routes or urls or literal):
        return _NOTHING
    return tuple(routes), tuple(urls), literal


# Casi ninguna cápsula aporta nada (django: todas). Una constante compartida y no una tupla
# por cápsula: 74k contenedores nuevos que sigue el GC subían el resto de la reconstrucción.
_NOTHING = ()


def _scan(capsules: dict) -> tuple[dict[str, list], list[tuple]]:
    """Una sola pasada: rutas de servidor y llamadas de cliente.

    Lo de cada cápsula se guarda en ella (`_http_scan`): `sync` sustituye las cápsulas de
    los archivos cambiados por objetos nuevos, así que tras una edición solo se escanean
    esas y el resultado viejo se va con su cápsula. En django eran 6,2 µs/símbolo de los
    12,8 de reconstruir el grafo, con 0 aristas HTTP.
    """
    routes: dict[str, list] = {}
    clients: list[tuple] = []
    seen: set = set()
    literal: list = []                   # cápsulas con literales de ruta, para el final

    def add(c, t):
        if (c.id, t) not in seen:
            seen.add((c.id, t)); clients.append((c, t))
    for c in capsules.values():
        hit = c._http_scan
        if hit is None:
            hit = c._http_scan = _scan_one(c)
        if hit is _NOTHING:
            continue
        found, urls, lit = hit
        for t in found:
            routes.setdefault(t, []).append(c)
        for t in urls:
            add(c, t)
        if lit:
            literal.append(c)
    # Sin rutas de servidor ningún literal puede coser (sympy, scipy): no se buscan. Si se
    # buscan, se guardan en la cápsula como lo demás (True = aún sin buscar).
    for c in literal if routes else ():
        found, urls, lit = c._http_scan
        if lit is True:
            # `x.split("/")` coserían con la ruta raíz de todo backend
            lit = tuple(t for t in map(_norm, _literal_calls(c.content)) if t != "/")
            c._http_scan = (found, urls, lit)
        for t in lit:
            add(c, t)
    routes = {t: _innermost(eps) for t, eps in routes.items()}
    return routes, clients


def _server_routes(capsules: dict) -> dict[str, list]:
    """plantilla_ruta -> [cápsulas endpoint que la sirven]."""
    return _scan(capsules)[0]


def _client_calls(capsules: dict) -> list[tuple]:
    """[(cápsula_cliente, plantilla_ruta)] de cada llamada HTTP saliente."""
    return _scan(capsules)[1]


def link_http_edges(capsules: dict, touched: set | None = None) -> int:
    """Añade aristas cliente→endpoint donde la ruta casa. Devuelve nº de aristas.

    Muta las cápsulas cliente: añade el nombre del endpoint a `calls` (+ registra la
    arista cross-lenguaje en properties['xlang_calls'] para poder citarla como prueba).
    """
    routes, clients = _scan(capsules)
    if not routes:
        return 0
    added = 0
    for client, tmpl in clients:
        targets = routes.get(tmpl)
        if not targets:
            continue
        for ep in targets:
            if ep.id == client.id:
                continue
            if ep.name not in client.calls:
                client.calls.append(ep.name)
                if touched is not None:      # ids mutados en sitio: GraphQuery.update los re-resuelve
                    touched.add(client.id)
                client.properties.setdefault("xlang_calls", []).append(
                    {"to": ep.name, "route": tmpl, "to_file": ep.file_path})
                added += 1
    return added


# ----------------------------------------------------------------------------
def _demo():
    """Self-check: un fetch React debe quedar conectado a un endpoint FastAPI."""
    from leo_code.core.parser import Capsule
    from leo_code.core.graphquery import GraphQuery

    def cap(name, content, file, t="function", calls=None):
        return Capsule(id=name, type=t, name=name, file_path=file, start_line=1,
                       end_line=9, language="ts" if file.endswith("tsx") else "python",
                       signature="", content=content, calls=calls or [])

    caps = {c.name: c for c in [
        cap("UserButton", "function UserButton(){ return fetch('/api/users/${id}') }", "ui.tsx", "component"),
        cap("get_user", "@app.get('/api/users/{id}')\ndef get_user(id): return query_user(id)",
            "api.py", "endpoint", calls=["query_user"]),
        cap("query_user", "def query_user(id): return db.execute('select * from users')",
            "db.py", calls=["execute"]),
    ]}
    # antes de coser: no hay camino del botón al endpoint (lenguajes distintos)
    assert not GraphQuery(caps).trace("UserButton", "get_user").found

    n = link_http_edges(caps)
    assert n == 1, f"esperaba 1 arista cross-lenguaje, hubo {n}"

    # después: el trace cruza ui.tsx → api.py → db.py
    tr = GraphQuery(caps).trace("UserButton", "query_user")
    path = [c.name for c in tr.cites]
    assert path == ["UserButton", "get_user", "query_user"], path
    files = [c.file for c in tr.cites]
    assert "ui.tsx" in files and "api.py" in files and "db.py" in files, files

    # la prueba registra la arista cross-lenguaje
    assert caps["UserButton"].properties["xlang_calls"][0]["route"] == "/api/users/*"

    print("boundary self-check OK — frontera HTTP cosida")
    print(tr.render())


if __name__ == "__main__":
    from leo_code.logging_config import utf8_console
    utf8_console()
    _demo()
