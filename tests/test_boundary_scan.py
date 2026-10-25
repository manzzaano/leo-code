"""El escaneo de llamadas HTTP salta a las pistas en vez de probar el regex en cada
posición; debe encontrar exactamente lo mismo que `finditer` (chequeo (e) de la auditoría)."""

from leo_code.core.boundary import (_CLIENT_CALL, _CLIENT_HINTS, _SERVER_ROUTE,
                                    _hinted_finditer, _route_literals)

CASES = [
    "fetch('/api/a'); axios.get(\"/api/b\")",
    "x = FETCH(`/api/${id}`) + Http.post('/v1/x')",
    "fetch('http://h/api/c')",                      # la pista `http` dentro de una coincidencia
    "httprequest('/r'); request( '/s' )",            # pista que no casa seguida de una que sí
    "$.ajax('/j'); $.get('/k')",
    "no hay nada aquí",
    "İstanbul fetch('/u')",                          # lower() cambia la longitud: camino lento
]


def test_hinted_finditer_matches_finditer():
    for text in CASES:
        expected = [(m.start(), m.group(1)) for m in _CLIENT_CALL.finditer(text)]
        got = [(m.start(), m.group(1))
               for m in _hinted_finditer(_CLIENT_CALL, text, text.lower(), _CLIENT_HINTS)]
        assert got == expected, text


SERVER_CASES = [
    "@app.get('/api/a')\ndef a(): pass",
    "@router.POST(\"/x/{id}\") ; r.route('/y')",
    "@a.b.get('/no')  d.get('k')  @x_1.delete( '/z' )",   # `@a.b` no casa; `.get('/no')` sí
    "@.get('/w')",                                       # `@` sin palabra: solo casa `.get`
    "nada",
    "İ @app.put('/u')",
]


def test_route_literals_match_finditer_on_server_routes():
    # `_scan` solo usa el literal de la ruta (y `_norm` lo baja a minúsculas): buscar en
    # el texto ya en minúsculas, desde el `.`, da los mismos literales que el regex entero.
    for text in SERVER_CASES:
        expected = [m.group(1).lower() for m in _SERVER_ROUTE.finditer(text)]
        assert [r.lower() for r in _route_literals(text, text.lower())] == expected, text
