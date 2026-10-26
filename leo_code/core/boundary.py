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


def _scan(capsules: dict) -> tuple[dict[str, list], list[tuple]]:
    """Una sola pasada: rutas de servidor y llamadas de cliente.

    Recorrer las cápsulas dos veces significaba bajar a minúsculas y volver a tocar
    todo el texto dos veces; aquí cada cápsula se lee una vez.
    """
    routes: dict[str, list] = {}
    clients: list[tuple] = []
    for c in capsules.values():
        content = getattr(c, "content", "") or ""
        # El parser AST de Python deja los decoradores FUERA de content/signature, en
        # properties["decorators"] ("app.get('/api/x')"): sin mirarlos, ninguna ruta
        # FastAPI/Flask de un repo real se cosía (medido en NEXUS, 2026-09-15).
        props = getattr(c, "properties", None) or {}
        deco = str(props.get("decorators", ""))
        sig = getattr(c, "signature", "") or ""
        server_text = " ".join((content, sig, deco))
        low = server_text.lower()
        for r in _route_literals(server_text, low):
            routes.setdefault(_norm(r), []).append(c)
        if any(h in low for h in _CLIENT_HINTS):
            # low empieza por content.lower() si lower() no cambió longitudes
            aligned = low[:len(content)] if len(low) == len(server_text) else content.lower()
            for m in _hinted_finditer(_CLIENT_CALL, content, aligned, _CLIENT_HINTS):
                url = m.group(1)
                if url.startswith(("/", "http")) or "/" in url:
                    clients.append((c, _norm(url)))
    return routes, clients


def _server_routes(capsules: dict) -> dict[str, list]:
    """plantilla_ruta -> [cápsulas endpoint que la sirven]."""
    return _scan(capsules)[0]


def _client_calls(capsules: dict) -> list[tuple]:
    """[(cápsula_cliente, plantilla_ruta)] de cada llamada HTTP saliente."""
    return _scan(capsules)[1]


def link_http_edges(capsules: dict) -> int:
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
