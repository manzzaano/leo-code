"""Tools: herramientas del agente (read_file, write_file, replace_in_file, list_files, execute_command, run_tests, git_diff, search_code)."""

import subprocess
import sys
from pathlib import Path


class ToolRegistry:
    """Registro de herramientas disponibles para el agente."""

    def __init__(self):
        self._tools = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "replace_in_file": self.replace_in_file,
            "list_files": self.list_files,
            "execute_command": self.execute_command,
            "run_tests": self.run_tests,
            "git_diff": self.git_diff,
            "search_code": self.search_code,
            "find_symbol": self.find_symbol,
            "read_symbol": self.read_symbol,
            "who_calls": self.who_calls,
            "callees": self.callees,
            "impact": self.impact,
            "trace": self.trace,
            "where": self.where,
            "list_by_kind": self.list_by_kind,
            "retrieve_full": self.retrieve_full,
        }
        self._definitions: list[dict] = []  # extended by plugins
        self._capsules: dict = {}            # id -> Capsule (structural index)
        self._by_name: dict[str, list] = {}  # name -> [Capsule]
        self._callers: dict[str, list] = {}  # name -> [Capsule que lo llaman]
        self._gq = None                      # GraphQuery: cerebro determinista (con prueba)
        # CCR (compresión reversible): outputs grandes se truncan en el contexto
        # pero el original se guarda aquí; el modelo lo recupera con retrieve_full.
        self._ccr_store: dict[str, str] = {}
        self._ccr_seq = 0

    def store_full(self, text: str) -> str:
        """Guarda un output completo y devuelve su ref para retrieve_full."""
        ref = f"ccr{self._ccr_seq}"
        self._ccr_seq += 1
        self._ccr_store[ref] = text
        return ref

    def retrieve_full(self, args: dict, repo_path: str = ".") -> str:
        """Devuelve el output completo guardado bajo una ref (CCR)."""
        ref = (args.get("ref") or "").strip()
        full = self._ccr_store.get(ref)
        if full is None:
            return f"[ref CCR '{ref}' no encontrada]"
        return full

    def set_index(self, capsules: dict):
        """Conecta el índice estructural (capsules + grafo de llamadas) a las tools.

        Además cose las aristas cross-lenguaje (HTTP) y construye el GraphQuery: el
        cerebro determinista que responde trace/impact/who_calls/where con prueba
        citable y CERO LLM (las tools del agente lo usan en vez de grepear y alucinar).
        """
        self._capsules = capsules or {}
        self._by_name = {}
        self._callers = {}
        for c in self._capsules.values():
            self._by_name.setdefault(c.name, []).append(c)
        for c in self._capsules.values():
            for callee in (getattr(c, "calls", None) or []):
                self._callers.setdefault(callee, []).append(c)
        try:
            from leo_code.core.boundary import link_http_edges
            from leo_code.core.graphquery import GraphQuery
            link_http_edges(self._capsules)  # idempotente
            self._gq = GraphQuery(self._capsules)
        except Exception:
            self._gq = None

    def register(self, name: str, fn, definition: dict):
        self._tools[name] = fn
        self._definitions.append({"type": "function", "function": definition})

    def get_definitions(self) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": "read_file",
                "description": "Lee un archivo. Archivos grandes (>200 lineas) se capan: usa start_line/end_line para un rango, o read_symbol para una funcion concreta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Ruta relativa al archivo"},
                        "start_line": {"type": "integer", "description": "Linea inicial (opcional)"},
                        "end_line": {"type": "integer", "description": "Linea final (opcional)"},
                    },
                    "required": ["file_path"],
                },
            }},
            {"type": "function", "function": {
                "name": "write_file",
                "description": "Escribe contenido en un archivo (sobrescribe si existe, crea directorios si no existen)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Ruta relativa al archivo a escribir"},
                        "content": {"type": "string", "description": "Contenido completo del archivo"},
                    },
                    "required": ["file_path", "content"],
                },
            }},
            {"type": "function", "function": {
                "name": "replace_in_file",
                "description": "Reemplaza un fragmento exacto de texto en un archivo por otro. Usa old_string para identificar qué cambiar y new_string como reemplazo. Solo reemplaza la primera ocurrencia.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Ruta relativa al archivo"},
                        "old_string": {"type": "string", "description": "Texto exacto a reemplazar (debe ser único en el archivo)"},
                        "new_string": {"type": "string", "description": "Texto de reemplazo"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            }},
            {"type": "function", "function": {
                "name": "list_files",
                "description": "Lista archivos y directorios del repositorio. Usa depth para limitar profundidad y pattern para filtrar (ej. '*.py').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directorio a listar (relativo al repo, '.' por defecto)"},
                        "depth": {"type": "integer", "description": "Profundidad maxima (default 2)"},
                        "pattern": {"type": "string", "description": "Filtro glob (ej. '*.py', '**/*.md')"},
                    },
                },
            }},
            {"type": "function", "function": {
                "name": "execute_command",
                "description": "Ejecuta un comando en la terminal y retorna la salida",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Comando a ejecutar"},
                    },
                    "required": ["command"],
                },
            }},
            {"type": "function", "function": {
                "name": "run_tests",
                "description": "Ejecuta tests del repositorio (pytest). Opcionalmente filtra por archivo, directorio o keyword.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Archivo o directorio de tests (opcional, default: todo el repo)"},
                        "keyword": {"type": "string", "description": "Filtrar tests por keyword (ej. nombre de funcion)"},
                    },
                },
            }},
            {"type": "function", "function": {
                "name": "git_diff",
                "description": "Muestra los cambios (git diff) respecto al estado anterior",
                "parameters": {"type": "object", "properties": {}},
            }},
            {"type": "function", "function": {
                "name": "search_code",
                "description": "Busca un patron de texto en los archivos del repositorio. Devuelve lineas file:line coincidentes (no archivos enteros).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Patron a buscar"},
                    },
                    "required": ["pattern"],
                },
            }},
            {"type": "function", "function": {
                "name": "find_symbol",
                "description": "Busca simbolos (funciones, clases, metodos) por nombre o subcadena. Devuelve nombre, tipo, file:line y firma. Empieza SIEMPRE por aqui para localizar codigo.",
                "parameters": {
                    "type": "object",
                    "properties": {"pattern": {"type": "string", "description": "Nombre o subcadena del simbolo (ej. 'detect_frameworks')"}},
                    "required": ["pattern"],
                },
            }},
            {"type": "function", "function": {
                "name": "read_symbol",
                "description": "Devuelve el cuerpo completo de UN simbolo (firma + docstring + codigo), no el archivo entero. Usa esto en vez de read_file para leer una funcion/clase concreta.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nombre exacto del simbolo"}},
                    "required": ["name"],
                },
            }},
            {"type": "function", "function": {
                "name": "who_calls",
                "description": "DETERMINISTA, con PRUEBA (archivo:linea). Quien LLAMA a un simbolo. Preferelo a grep/search: no alucina.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nombre del simbolo"}},
                    "required": ["name"],
                },
            }},
            {"type": "function", "function": {
                "name": "callees",
                "description": "DETERMINISTA, con PRUEBA. A que simbolos LLAMA uno dado (dependencias directas).",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nombre del simbolo"}},
                    "required": ["name"],
                },
            }},
            {"type": "function", "function": {
                "name": "impact",
                "description": "DETERMINISTA, con PRUEBA. Que se ROMPE si cambias un simbolo (callers transitivos). Usalo ANTES de editar: es el grafo real, no una estimacion.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nombre del simbolo"}},
                    "required": ["name"],
                },
            }},
            {"type": "function", "function": {
                "name": "trace",
                "description": "DETERMINISTA, con PRUEBA. Camino de llamadas de src a dst (como fluye el control/dato de A a B), cruza archivos/repos/lenguajes. Cada salto citado. Para 'como llega X a Y'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Simbolo origen"},
                        "dst": {"type": "string", "description": "Simbolo destino"},
                    },
                    "required": ["src", "dst"],
                },
            }},
            {"type": "function", "function": {
                "name": "where",
                "description": "DETERMINISTA, con PRUEBA. Donde se define un simbolo (todas las definiciones), citado archivo:linea. Preferelo a grep.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Nombre del simbolo"}},
                    "required": ["name"],
                },
            }},
            {"type": "function", "function": {
                "name": "list_by_kind",
                "description": "Lista TODOS los simbolos de un tipo (endpoint, class, method, function, dataclass, model, test...). Usalo para preguntas agregadas: 'cuantos endpoints hay', 'lista las clases'.",
                "parameters": {
                    "type": "object",
                    "properties": {"kind": {"type": "string", "description": "Tipo: endpoint, class, method, function, dataclass, model, test, constant..."}},
                    "required": ["kind"],
                },
            }},
            {"type": "function", "function": {
                "name": "retrieve_full",
                "description": "Recupera el output COMPLETO de un tool anterior que se truncó en el contexto. Pasa la ref indicada en el mensaje '[truncado ... usa retrieve_full('ccrN')]'. Úsalo solo si necesitas el detalle que faltaba.",
                "parameters": {
                    "type": "object",
                    "properties": {"ref": {"type": "string", "description": "Ref CCR, p.ej. 'ccr0'"}},
                    "required": ["ref"],
                },
            }},
        ] + self._definitions

    def get_openai_definitions(self) -> list[dict]:
        return self.get_definitions()

    def execute(self, name: str, arguments: dict, repo_path: str = ".") -> str:
        tool_fn = self._tools.get(name)
        if tool_fn:
            return tool_fn(arguments, repo_path)
        return f"[Tool '{name}' no encontrada]"

    def read_file(self, args: dict, repo_path: str) -> str:
        path = Path(repo_path) / args.get("file_path", "")
        start = args.get("start_line")
        end = args.get("end_line")
        try:
            if path.is_dir():
                items = sorted(path.iterdir())[:50]
                listing = "\n".join(f"  {'📁' if p.is_dir() else '📄'} {p.name}" for p in items)
                return f"[{path} es un directorio. Usa list_files para explorar.]\nContenido:\n{listing}"
            lines = path.read_text(encoding="utf-8").split("\n")
            n = len(lines)
            if start is not None or end is not None:
                s = max(1, int(start or 1))
                e = min(n, int(end or n))
                body = "\n".join(f"{i}\t{lines[i-1]}" for i in range(s, e + 1))
                return f"[{path.name} lineas {s}-{e} de {n}]\n{body}"
            # ponytail: archivo grande inunda contexto; cap por lineas y empuja a read_symbol
            if n > 200:
                head = "\n".join(f"{i}\t{lines[i-1]}" for i in range(1, 201))
                return (f"[{path.name}: {n} lineas (grande). Mostrando 1-200. "
                        f"Usa read_symbol('nombre') para una funcion concreta o read_file con start_line/end_line.]\n{head}")
            return path.read_text(encoding="utf-8")
        except Exception as e:
            return f"[Error leyendo {path}: {e}]"

    def write_file(self, args: dict, repo_path: str) -> str:
        path = Path(repo_path) / args.get("file_path", "")
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"[Escrito: {path} ({len(content)} chars)]{_verify_py(path)}"
        except Exception as e:
            return f"[Error escribiendo {path}: {e}]"

    def replace_in_file(self, args: dict, repo_path: str) -> str:
        path = Path(repo_path) / args.get("file_path", "")
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        if not old:
            return "[Error: old_string vacio]"
        try:
            content = path.read_text(encoding="utf-8")
            count = content.count(old)
            if count == 0:
                return f"[Error: old_string no encontrado en {path}]"
            if count > 1:
                return f"[Error: old_string aparece {count} veces en {path}. Debe ser unico.]"
            content = content.replace(old, new, 1)
            path.write_text(content, encoding="utf-8")
            return f"[Reemplazado en {path}: {len(old)} → {len(new)} chars]{_verify_py(path)}"
        except Exception as e:
            return f"[Error en replace_in_file {path}: {e}]"

    def list_files(self, args: dict, repo_path: str) -> str:
        base = Path(repo_path) / args.get("path", ".")
        depth = args.get("depth", 2)
        pattern = args.get("pattern", "")
        try:
            if pattern:
                matches = sorted(base.rglob(pattern))
            else:
                matches = sorted(base.rglob("*"))
            return _render_file_tree(base, matches, depth)
        except Exception as e:
            return f"[Error listando {base}: {e}]"

    def execute_command(self, args: dict, repo_path: str) -> str:
        cmd = args.get("command", "")
        cwd = args.get("cwd", repo_path)
        if sys.platform == "win32":
            cmd = self._translate_windows(cmd)
        try:
            result = subprocess.run(cmd, shell=True, cwd=cwd,
                                     capture_output=True, text=True, timeout=60)
            output = (result.stdout + result.stderr).strip()
            return output if output else "[comando ejecutado sin salida]"
        except subprocess.TimeoutExpired:
            return f"[Timeout: {cmd[:100]}...]"
        except Exception as e:
            return f"[Error ejecutando '{cmd[:100]}...': {e}]"

    def run_tests(self, args: dict, repo_path: str) -> str:
        parts = ["pytest"]
        if keyword := args.get("keyword"):
            parts.append(f"-k {keyword}")
        if path := args.get("path"):
            parts.append(path)
        cmd = " ".join(parts)
        cwd = repo_path
        try:
            result = subprocess.run(cmd, shell=True, cwd=cwd,
                                     capture_output=True, text=True, timeout=120)
            output = (result.stdout + result.stderr).strip()
            return output if output else "[pytest sin salida]"
        except subprocess.TimeoutExpired:
            return f"[Timeout: pytest...]"
        except FileNotFoundError:
            return "[Error: pytest no instalado. pip install pytest]"
        except Exception as e:
            return f"[Error pytest: {e}]"

    @staticmethod
    def _translate_windows(cmd: str) -> str:
        c = cmd.strip()
        if c.startswith("mkdir -p "):
            path = c[9:].strip().strip('"')
            return f'New-Item -ItemType Directory -Path "{path}" -Force | Out-Null'
        if c.startswith("mkdir "):
            path = c[6:].strip().strip('"')
            return f'New-Item -ItemType Directory -Path "{path}" -Force | Out-Null'
        if c.startswith("rm -rf ") or c.startswith("rm -r "):
            parts = c.split(" ", 2)
            path = parts[-1].strip().strip('"') if len(parts) > 2 else ""
            return f'Remove-Item -LiteralPath "{path}" -Recurse -Force -ErrorAction SilentlyContinue' if path else c
        if c == "ls" or c.startswith("ls "):
            rest = c[3:] if len(c) > 2 else ""
            return f"Get-ChildItem {rest}".strip()
        if c.startswith("cat "):
            return f"Get-Content {c[4:]}"
        if c.startswith("touch "):
            path = c[6:].strip().strip('"')
            return f'New-Item -ItemType File -Path "{path}" -Force | Out-Null'
        if c.startswith("cp ") or c.startswith("copy "):
            parts = c.split(" ")
            if len(parts) >= 3:
                return f'Copy-Item "{parts[1]}" "{parts[2]}"'
        if c.startswith("mv "):
            parts = c.split(" ")
            if len(parts) >= 3:
                return f'Move-Item "{parts[1]}" "{parts[2]}"'
        if c.endswith("2>nul") or c.endswith("2>/dev/null") or "pytest" in c:
            return c
        return c

    def git_diff(self, args: dict, repo_path: str) -> str:
        try:
            result = subprocess.run("git diff", shell=True, cwd=repo_path,
                                     capture_output=True, text=True, timeout=30)
            return result.stdout or "[Sin cambios]"
        except Exception as e:
            return f"[Error git diff: {e}]"

    def search_code(self, args: dict, repo_path: str) -> str:
        pattern = args.get("pattern", "")
        search_path = Path(repo_path) / args.get("path", ".")
        try:
            result = subprocess.run(
                f'rg --line-number "{pattern}" "{search_path}"',
                shell=True, capture_output=True, text=True, timeout=30
            )
            return result.stdout or "[No encontrado]"
        except Exception:
            matches = []
            for p in search_path.rglob("*.py"):
                try:
                    for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
                        if pattern in line:
                            matches.append(f"{p}:{i}: {line.strip()[:120]}")
                except Exception:
                    continue
            return "\n".join(matches[:20]) or "[No encontrado]"

    # ---- Tools estructurales (sobre el indice de capsules + grafo de llamadas) ----

    def _rel(self, c) -> str:
        fp = getattr(c, "file_path", "") or ""
        return f"{Path(fp).name}:{getattr(c, 'start_line', 0)}"

    def find_symbol(self, args: dict, repo_path: str) -> str:
        pat = (args.get("pattern") or args.get("name") or args.get("query") or "").lower()
        if not pat:
            return "[Error: pattern vacio]"
        if not self._capsules:
            return "[Indice no disponible. Usa search_code/grep.]"
        exact, partial = [], []
        for c in self._capsules.values():
            nm = c.name.lower()
            if nm == pat:
                exact.append(c)
            elif pat in nm:
                partial.append(c)
        hits = (exact + partial)[:20]
        if not hits:
            return f"[Sin simbolos que coincidan con '{pat}'. Prueba search_code.]"
        return "\n".join(f"{c.name} ({c.type}) {self._rel(c)} — {c.signature or ''}".rstrip(" —") for c in hits)

    def _lookup(self, name: str):
        caps = self._by_name.get(name)
        if caps:
            return caps[0]
        # fallback: subcadena unica
        matches = [c for c in self._capsules.values() if name.lower() in c.name.lower()]
        return matches[0] if matches else None

    def read_symbol(self, args: dict, repo_path: str) -> str:
        name = args.get("name") or ""
        c = self._lookup(name)
        if not c:
            return f"[Simbolo '{name}' no encontrado. Usa find_symbol.]"
        parts = [f"# {c.name} ({c.type}) — {self._rel(c)}"]
        if c.signature:
            parts.append(c.signature)
        if c.docstring:
            parts.append(f'"""{c.docstring}"""')
        body = c.content or ""
        if len(body) > 2400:
            body = body[:2400] + "\n# ... [truncado, usa read_file con rango]"
        parts.append(body)
        return "\n".join(parts)

    def list_by_kind(self, args: dict, repo_path: str) -> str:
        kind = (args.get("kind") or "").lower()
        if not kind:
            return "[Error: kind vacio]"
        if not self._capsules:
            return "[Indice no disponible.]"
        hits = [c for c in self._capsules.values() if c.type.lower() == kind]
        if not hits:
            kinds = sorted({c.type for c in self._capsules.values()})
            return f"[Sin simbolos de tipo '{kind}'. Tipos disponibles: {', '.join(kinds)}]"
        hits.sort(key=lambda c: (c.file_path or "", c.start_line))
        lines = [f"{len(hits)} simbolos de tipo '{kind}':"]
        lines += [f"{c.name} {self._rel(c)}" for c in hits[:60]]
        if len(hits) > 60:
            lines.append(f"... (+{len(hits) - 60} mas)")
        return "\n".join(lines)

    # who_calls / callees / impact / trace / where → cerebro determinista (GraphQuery),
    # respuesta con PRUEBA citable (archivo:linea + arista) y cero alucinacion.
    def who_calls(self, args: dict, repo_path: str) -> str:
        if not self._gq:
            return "[Indice no disponible.]"
        return self._gq.who_calls(args.get("name") or args.get("symbol") or "", limit=20).render()

    def callees(self, args: dict, repo_path: str) -> str:
        if not self._gq:
            return "[Indice no disponible.]"
        return self._gq.callees(args.get("name") or args.get("symbol") or "", limit=20).render()

    def impact(self, args: dict, repo_path: str) -> str:
        if not self._gq:
            return "[Indice no disponible.]"
        return self._gq.impact(args.get("name") or args.get("symbol") or "", limit=30).render()

    def trace(self, args: dict, repo_path: str) -> str:
        """Camino de llamadas src→dst (como fluye de A a B), cruza archivos/repos/
        lenguajes, cada salto citado. Determinista, con prueba."""
        if not self._gq:
            return "[Indice no disponible.]"
        return self._gq.trace(args.get("src") or "", args.get("dst") or "").render()

    def where(self, args: dict, repo_path: str) -> str:
        """Donde se define un simbolo (todas las definiciones), citado archivo:linea."""
        if not self._gq:
            return "[Indice no disponible.]"
        return self._gq.where(args.get("name") or args.get("symbol") or "").render()


def _verify_py(path: Path) -> str:
    """Compila el archivo .py recién editado y reporta error de sintaxis al instante."""
    if path.suffix != ".py":
        return ""
    import py_compile
    try:
        py_compile.compile(str(path), doraise=True)
        return "\n[verify: compila OK]"
    except py_compile.PyCompileError as e:
        return f"\n[verify: SYNTAX ERROR — el cambio rompe el archivo: {str(e).strip()[:300]}]"
    except Exception:
        return ""


def _render_file_tree(base: Path, matches: list[Path], max_depth: int) -> str:
    """Render file tree with Rich Tree or fallback text."""
    try:
        from rich.tree import Tree
        tree = Tree(f"📁 {base.name or '.'}")
        nodes: dict[str, object] = {".": tree}
        count = 0
        for p in matches[:100]:
            if p.is_dir():
                continue
            rel = p.relative_to(base)
            if len(rel.parts) > max_depth:
                continue
            count += 1
            parent = tree
            for i, part in enumerate(rel.parts[:-1]):
                key = "/".join(rel.parts[:i + 1])
                if key not in nodes:
                    nodes[key] = parent.add(f"📁 {part}")
                parent = nodes[key]
            name = rel.parts[-1]
            size = p.stat().st_size
            suffix = f"  ({size} B)" if size < 1024 else f"  ({size // 1024} KB)"
            parent.add(f"📄 {name}{suffix}")
        if count == 0:
            return "[Directorio vacío]"
        return str(tree)
    except ImportError:
        lines = []
        count = 0
        for p in matches[:80]:
            if p.is_dir():
                continue
            rel = p.relative_to(base)
            if len(rel.parts) > max_depth:
                continue
            count += 1
            size = p.stat().st_size
            lines.append(f"  {rel} ({size} B)" if size < 1024 else f"  {rel} ({size // 1024} KB)")
        return "\n".join(lines) if lines else "[Directorio vacío]"
