"""guard_hook — aviso antes de romper: el agente va a editar, leo mira quién depende.

Hook `PreToolUse` de Claude Code sobre Edit|Write. Si el símbolo que se va a tocar
tiene dependientes SIN test, se lo dice al agente (`additionalContext`) y al humano
(`systemMessage`). En cualquier otro caso no dice nada.

Invierte la iniciativa del producto: no espera a que el agente se acuerde de preguntar
—medido, lo hace 0,5-1,1 veces por tarea—, y habla en el único instante donde el dato
decide algo.

Reglas duras, todas con test:
  · NUNCA escribe `permissionDecision`: no puede bloquear una edición.
  · NUNCA sale con código != 0: un fallo del hook no puede frenar al agente.
  · NUNCA indexa: sin índice en caché, silencio (construirlo dentro de una edición
    costaría segundos).
  · Índice por encima del umbral → silencio: a 300k símbolos cargarlo cuesta ~3 s.

Contrato: lee el JSON del hook por stdin, escribe JSON por stdout. Se prueba así.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Presupuesto por edición. Se comprueba antes de cada paso caro: si ya se pasó, calla.
_DEADLINE_S = float(os.getenv("LEO_GUARD_DEADLINE_S", "2.0"))
# Techo por tamaño del índice comprimido: proxy de cuántos símbolos hay dentro. Medido el
# 17/11: ~6,5k símbolos/MB (leo-code 0,4 MB ≈ 1,8k · django 11 MB ≈ 72k), y con django el
# hook entero (cargar + informe) cuesta 5,8 s. A 2 MB (~13k símbolos) sale ~1 s. Leer el
# tamaño es un stat; contar símbolos exigiría descomprimirlo, justo lo que se evita.
_MAX_INDEX_MB = float(os.getenv("LEO_GUARD_MAX_INDEX_MB", "2"))
_MAX_SYMBOLS_REPORTED = 5   # más que esto es un muro de texto que el agente se salta
_MAX_SYMBOLS_REVIEWED = 3   # un Write toca muchos símbolos: se revisan los mayores

_TEST_MARKERS = ("/tests/", "/test/", "/__tests__/", "/spec/")
# Revisión #16: sin `_test.go`, Go no tenía ningún test y nada quedaba cubierto.
_TEST_SUFFIXES = ("_test.py", "_test.go", "_test.rb", "_spec.rb") + tuple(
    f".{kind}.{ext}" for kind in ("test", "spec")
    for ext in ("ts", "tsx", "js", "jsx", "mjs", "cjs"))
_JAVA_TEST = re.compile(r"[a-z0-9]Tests?\.java$")


def _is_test_path(path: Path) -> bool:
    """Editar un test no rompe a nadie: es el caso más común y el más inútil de avisar."""
    posix = "/" + path.as_posix().lower()   # "/" delante: `tests/x.py` relativo también
    name = path.name.lower()
    return (any(m in posix for m in _TEST_MARKERS)
            or name.startswith("test_") or name.startswith("test.")
            or name in ("tests.py", "conftest.py")
            or name.endswith(_TEST_SUFFIXES)
            # Java: FooTest.java / FooTests.java, en mayúscula (Latest.java no es un test)
            or bool(_JAVA_TEST.search(path.name)))


def _line_of(path: Path, needle: str) -> int | None:
    """Línea (1-based) donde empieza `needle` en el archivo.

    En PreToolUse el archivo todavía tiene el contenido VIEJO, así que el `old_string`
    del Edit se encuentra tal cual.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    idx = text.find(needle)
    if idx < 0:
        return None
    return text.count("\n", 0, idx) + 1


def _symbols_at(caps: list, path: Path, line: int | None) -> list:
    """Cápsulas afectadas: la que contiene `line`, o todas las del archivo si no hay línea.

    Con anidamiento (método dentro de clase) gana la más pequeña: es la que se edita.
    """
    target = str(path)
    in_file = [c for c in caps
               if os.path.normcase(c.file_path or "") == os.path.normcase(target)]
    if line is None:
        # Write reemplaza el archivo entero: los símbolos más grandes primero, que son
        # los que arrastran más dependientes.
        in_file.sort(key=lambda c: (c.end_line or 0) - (c.start_line or 0), reverse=True)
        return in_file[:_MAX_SYMBOLS_REVIEWED]
    holding = [c for c in in_file
               if (c.start_line or 0) <= line <= (c.end_line or 0)]
    holding.sort(key=lambda c: (c.end_line or 0) - (c.start_line or 0))
    return holding[:1]


def _load_caps(repo: str) -> list:
    """Cápsulas del repo desde el índice YA persistido. Nunca indexa."""
    from leo_code import engine
    from leo_code.rag.indexer import Indexer

    path = engine.repo_index_path(repo)
    if not path.exists():
        return []
    if path.stat().st_size > _MAX_INDEX_MB * 1024 * 1024:
        return []
    idx = Indexer(hygiene=True)
    idx.load(str(path))
    return engine._repo_caps(idx, repo)


def _rel(path: str, repo: str | None) -> str:
    """Ruta relativa al repo con `/`, como cita el server MCP; absoluta si no se puede."""
    try:
        return Path(os.path.relpath(path, repo)).as_posix() if repo else path
    except ValueError:                       # otra unidad en Windows
        return path


def _fresh(caps: list, path: Path, index_mtime: float) -> list:
    """Si `path` cambió después de escribirse el índice, sus símbolos se vuelven a parsear
    (un archivo: milisegundos). Con las líneas viejas el hook culpaba al símbolo que ANTES
    estaba en esa línea: el server escribe el índice 3 s después del último cambio, y sin
    server no lo escribe en toda la sesión."""
    try:
        if path.stat().st_mtime <= index_mtime:
            return caps
        from leo_code.core.parser import extract_from_file
        from leo_code.rag.indexer import Indexer
        new = extract_from_file(str(path), Indexer.CODE_EXTENSIONS[path.suffix.lower()])
    except Exception:
        return caps            # no se pudo re-parsear: mejor el índice que nada
    target = os.path.normcase(str(path))
    return [c for c in caps if os.path.normcase(c.file_path or "") != target] + new


def _late(started: float | None) -> bool:
    return started is not None and time.monotonic() - started > _DEADLINE_S


def _report(caps: list, symbols: list, repo: str | None = None,
            started: float | None = None) -> tuple[str, str] | None:
    """(contexto para el agente, línea para el humano), o None si no hay nada que avisar.

    Revisión #14 (16/11): avisa solo si algún llamador DIRECTO (resuelto por definición,
    sin homónimas de otros archivos) no está cubierto por un test. Contar dependientes
    transitivos avisaba en el 72% de las ediciones de leo-code: casi todo acaba en un
    `main` sin test. El total transitivo va como cifra, no como motivo."""
    from leo_code.core.boundary import link_http_edges
    from leo_code.core.graphquery import _qual
    from leo_code.core.guardian import Guardian

    by_id = {c.id: c for c in caps}
    link_http_edges(by_id)   # un fetch del frontend también es un dependiente
    if _late(started):       # el plazo se mira entre las fases caras, no solo antes
        return None
    guard = Guardian(by_id, repo)
    if _late(started):
        return None
    for cap in symbols:
        risky = {c.id: c for c in guard.gq.callers_of_def(cap)
                 if not guard._is_test(c, guard._root) and not guard.is_covered(c)}
        if not risky:
            continue
        risky = sorted(risky.values(), key=lambda c: (c.file_path or "", c.start_line or 0))
        rel, name = _rel(cap.file_path, repo), _qual(cap)
        total = len(guard.review(f"{rel}:{name}").affected)
        shown = risky[:_MAX_SYMBOLS_REPORTED]
        rest = len(risky) - len(shown)
        lines = [f"leo-mcp: `{name}` ({rel}:{cap.start_line}) has {len(risky)} direct caller(s) "
                 f"with NO test covering them ({total} dependent(s) in total):"]
        lines += [f"  · {_qual(c)} ({c.type}) @ {_rel(c.file_path, repo)}:{c.start_line}"
                  for c in shown]
        if rest > 0:
            lines.append(f"  · …and {rest} more")
        lines.append("Check those call sites before you change the signature or the behaviour, "
                     "or cover them first. This comes from the static call graph: dependencies "
                     "through WebSockets, queues, subprocesses or string-built dispatch are not "
                     "in it, so this list can be incomplete.")
        human = f"leo: {name} → {len(risky)} direct caller(s) with no test ({total} dependents)"
        return "\n".join(lines), human
    return None


def run(payload: dict, started: float) -> dict | None:
    """El JSON a escribir, o None para callar. Sin efectos: así se puede testear directo."""
    if payload.get("tool_name") not in ("Edit", "Write"):
        return None
    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if not path.is_file():
        return None   # archivo nuevo (Write): nada que romper

    from leo_code.rag.indexer import Indexer
    if path.suffix.lower() not in Indexer.CODE_EXTENSIONS:
        return None

    repo = os.path.abspath(os.getenv("LEO_REPO") or payload.get("cwd") or ".")
    if os.name == "nt":
        # Windows no distingue mayúsculas: `c:/users/...` es el mismo repo, pero el índice
        # va por la ruta exacta. realpath devuelve la grafía real del disco.
        repo, path = os.path.realpath(repo), Path(os.path.realpath(path))
    rel = Path(_rel(str(path), repo))
    if rel.is_absolute() or rel.parts[:1] == ("..",):
        return None   # fuera del repo indexado
    if _is_test_path(rel):
        return None   # un test: nada que romper (ruta en el repo: el repo puede vivir bajo `test/`)

    if time.monotonic() - started > _DEADLINE_S:
        return None
    caps = _load_caps(repo)
    if not caps:
        return None
    from leo_code import engine
    caps = _fresh(caps, path, engine.repo_index_path(repo).stat().st_mtime)

    old = tool_input.get("old_string")
    line = _line_of(path, old) if old else None
    symbols = _symbols_at(caps, path, line)
    if not symbols or time.monotonic() - started > _DEADLINE_S:
        return None

    found = _report(caps, symbols, repo, started)
    if found is None:
        return None
    context, human = found
    # Sin `permissionDecision`: esto informa, no decide. `systemMessage` es campo
    # universal, en el nivel superior: dentro de hookSpecificOutput no se le muestra a
    # la persona (docs de hooks de Claude Code).
    return {"systemMessage": human,
            "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": context}}


def read_payload() -> dict:
    """El JSON del hook. Claude Code lo manda en UTF-8; en Windows `sys.stdin` lo
    decodifica como cp1252 y una ruta con tilde llegaba deformada (hook mudo). Se leen
    los bytes."""
    data = sys.stdin.buffer.read().decode("utf-8", "replace")
    return json.loads(data or "{}")


def main(argv: list[str] | None = None) -> int:
    """Entrypoint del hook. Devuelve 0 SIEMPRE: ver la cabecera del módulo."""
    started = time.monotonic()
    if os.getenv("LEO_GUARD_HOOK") == "0":
        return 0
    # stdout es el canal del JSON del hook, y el indexer imprime ("[indexer] loaded: …")
    # al cargar el índice. Claude Code solo interpreta stdout si EMPIEZA por `{`: una línea
    # del indexer delante y el aviso se descarta en silencio. Todo print se desvía a stderr
    # y el JSON se escribe en el stdout real. Mismo reparto que en el server MCP.
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        out = run(read_payload(), started)
        if out is not None:
            real_stdout.write(json.dumps(out))
    except BaseException as e:   # también SystemExit(2): en Claude Code exit 2 BLOQUEA
        # Un hook roto no puede frenar al agente. A stderr, que Claude Code manda al
        # log de debug sin interpretarlo como decisión.
        print(f"[leo-mcp] guard hook skipped: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        sys.stdout = real_stdout
    return 0


if __name__ == "__main__":
    sys.exit(main())
