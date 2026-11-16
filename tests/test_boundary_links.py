"""Aristas HTTP cliente → endpoint: lo que se cose y lo que no (revisión #13, 16/11).
Medido en NEXUS: 39 rutas y 0 clientes, porque el frontend llama por un envoltorio."""

from leo_code.core.boundary import link_http_edges
from leo_code.core.parser import Capsule


def cap(name, content, file, t="function", start=1, end=9, deco=None):
    return Capsule(id=f"{file}:{name}", type=t, name=name, file_path=file, start_line=start,
                   end_line=end, language="python" if file.endswith(".py") else "typescript",
                   signature="", content=content, calls=[],
                   properties={"decorators": deco} if deco else {})


def edges(caps):
    link_http_edges(caps)
    return sorted((c.name, x["to"]) for c in caps.values()
                  for x in (c.properties or {}).get("xlang_calls", []))


def by_id(*cs):
    return {c.id: c for c in cs}


def test_two_axios_clients_are_not_each_others_endpoint():
    """A: `axios.get('/x')` es un cliente, no una ruta de servidor."""
    caps = by_id(cap("ListA", "function ListA(){ return axios.get('/api/users') }", "a.tsx"),
                 cap("ListB", "function ListB(){ return axios.get('/api/users') }", "b.tsx"),
                 cap("users", "def users(): ...", "api.py", "endpoint", deco="app.get('/api/users')"))
    assert edges(caps) == [("ListA", "users"), ("ListB", "users")]


def test_express_and_flask_style_routes_still_count():
    caps = by_id(cap("routes", "app.get('/api/a', listA)\nrouter.post('/api/b', makeB)", "server.js", "module"),
                 cap("Page", "function Page(){ fetch('/api/a'); fetch('/api/b') }", "page.tsx"))
    assert edges(caps) == [("Page", "routes")]


def test_route_counts_once_on_the_method_not_its_class():
    """B: la clase contiene el decorador de su método; la ruta es del método."""
    caps = by_id(cap("Api", "class Api:\n    @router.get('/api/jobs')\n    def jobs(self): ...", "api.py",
                     "class", start=1, end=3),
                 cap("jobs", "def jobs(self): ...", "api.py", "method", start=2, end=3,
                     deco="router.get('/api/jobs')"),
                 cap("Jobs", "function Jobs(){ return fetch('/api/jobs') }", "jobs.tsx"))
    assert edges(caps) == [("Jobs", "jobs")]


def test_wrapper_call_with_a_route_literal_is_a_client():
    """C: NEXUS `get<Stats>("/api/stats")` (lib/api.ts) envuelve fetch(BASE + path)."""
    caps = by_id(cap("api", 'export const api = {\n  stats: () => get<Stats>("/api/stats"),\n'
                            '  jobs: () => get<Job[]>("/api/jobs"),\n}', "lib/api.ts", "variable"),
                 cap("stats", "def stats(): ...", "main.py", "endpoint", deco="app.get('/api/stats')"),
                 cap("jobs", "def jobs(): ...", "main.py", "endpoint", deco="app.get('/api/jobs')"))
    assert edges(caps) == [("api", "jobs"), ("api", "stats")]


def test_literal_outside_a_call_or_without_route_is_not_an_edge():
    caps = by_id(cap("c", 'const p = "/api/stats"; go("/api/none")', "c.ts"),
                 cap("stats", "def stats(): ...", "main.py", "endpoint", deco="app.get('/api/stats')"))
    assert edges(caps) == []


def test_base_url_variable_before_the_path():
    """D: `${API_URL}/api/x` y `BASE + "/api/x"` van a la misma ruta."""
    caps = by_id(cap("A", "function A(){ return fetch(`${API_URL}/api/users`) }", "a.tsx"),
                 cap("B", 'function B(){ return fetch(BASE + "/api/users") }', "b.tsx"),
                 cap("users", "def users(): ...", "api.py", "endpoint", deco="app.get('/api/users')"))
    assert edges(caps) == [("A", "users"), ("B", "users")]


def test_word_ending_in_app_is_not_a_server():
    """`myapp.get('/x')` no es `app.get`: el nombre del servidor se casa entero, así que
    es un cliente más de la ruta."""
    caps = by_id(cap("A", "function A(){ return myapp.get('/api/users') }", "a.tsx"),
                 cap("users", "def users(): ...", "api.py", "endpoint", deco="app.get('/api/users')"))
    assert edges(caps) == [("A", "users")]


def test_a_route_definition_is_not_a_client_of_another_backend():
    """`app.get('/api/a', h)` DEFINE la ruta: no es cliente del `/api/a` de otro servicio."""
    caps = by_id(cap("routes", "app.get('/api/a', listA)", "server.js", "module"),
                 cap("list_a", "def list_a(): ...", "api.py", "endpoint", deco="app.get('/api/a')"))
    assert edges(caps) == []
