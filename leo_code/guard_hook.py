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
import sys
import time
from pathlib import Path

# Presupuesto por edición. Se comprueba antes de cada paso caro: si ya se pasó, calla.
_DEADLINE_S = float(os.getenv("LEO_GUARD_DEADLINE_S", "2.0"))
# Techo por tamaño del índice comprimido: proxy medido de cuántos símbolos hay dentro
# (~216 KB ≈ 1.100 símbolos · ~7,9 MB ≈ 300.000). Cargar un índice de 300k cuesta ~3 s,
# que no se paga en cada edición. Leer el tamaño es un stat; contar símbolos exigiría
# descomprimirlo, que es justo lo que se quiere evitar.
_MAX_INDEX_MB = float(os.getenv("LEO_GUARD_MAX_INDEX_MB", "4"))
_MAX_SYMBOLS_REPORTED = 5   # más que esto es un muro de texto que el agente se salta
_MAX_SYMBOLS_REVIEWED = 3   # un Write toca muchos símbolos: se revisan los mayores

_TEST_MARKERS = ("/tests/", "/test/", "/__tests__/", "/spec/")


def _is_test_path(path: Path) -> bool:
    """Editar un test no rompe a nadie: es el caso más común y el más inútil de avisar."""
    posix = path.as_posix().lower()
    name = path.name.lower()
    return (any(m in posix for m in _TEST_MARKERS)
            or name.startswith("test_") or name.startswith("test.")
            or any(name.endswith(s) for s in ("_test.py", ".test.ts", ".test.tsx", ".test.js",
                                              ".spec.ts", ".spec.tsx", ".spec.js")))


def _is_test_cite(cite) -> bool:
    return (cite.type == "test" or (cite.name or "").lower().startswith("test_")
            or _is_test_path(Path(cite.file or "")))


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


def _report(caps: list, symbols: list) -> tuple[str, str] | None:
    """(contexto para el agente, línea para el humano), o None si no hay nada que avisar."""
    from leo_code.core.boundary import link_http_edges
    from leo_code.core.guardian import Guardian

    by_id = {c.id: c for c in caps}
    link_http_edges(by_id)   # un fetch del frontend también es un dependiente
    guard = Guardian(by_id)
    for cap in symbols:
        report = guard.review(cap.name)
        # Un test que depende del símbolo es cobertura, no riesgo — y nada cubre a un test,
        # así que sin este filtro TODOS salían marcados como "sin test". En un repo bien
        # cubierto eso es un aviso en cada edición apuntando a archivos de test: el ruido
        # que hace que el hook se apague el primer día.
        risky = [a for a in report.uncovered if not _is_test_cite(a.cite)]
        if not risky:
            continue
        shown = risky[:_MAX_SYMBOLS_REPORTED]
        rest = len(risky) - len(shown)
        lines = [f"leo-mcp: `{cap.name}` ({Path(cap.file_path).name}:{cap.start_line}) is used by "
                 f"{len(report.affected)} symbol(s); these have NO test covering them:"]
        lines += [f"  · {a.cite.name} ({a.cite.type}) @ {a.cite.file}:{a.cite.line}" for a in shown]
        if rest > 0:
            lines.append(f"  · …and {rest} more")
        lines.append("Check those call sites before you change the signature or the behaviour, "
                     "or cover them first. This comes from the static call graph: dependencies "
                     "through WebSockets, queues, subprocesses or string-built dispatch are not "
                     "in it, so this list can be incomplete.")
        human = (f"leo: {cap.name} → {len(report.affected)} dependents, "
                 f"{len(risky)} with no test")
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
    if not path.is_file() or _is_test_path(path):
        return None   # archivo nuevo (Write) o test: nada que romper

    from leo_code.rag.indexer import Indexer
    if path.suffix.lower() not in Indexer.CODE_EXTENSIONS:
        return None

    repo = os.path.abspath(os.getenv("LEO_REPO") or payload.get("cwd") or ".")
    try:
        path.relative_to(repo)
    except ValueError:
        return None   # fuera del repo indexado

    if time.monotonic() - started > _DEADLINE_S:
        return None
    caps = _load_caps(repo)
    if not caps:
        return None

    old = tool_input.get("old_string")
    line = _line_of(path, old) if old else None
    symbols = _symbols_at(caps, path, line)
    if not symbols or time.monotonic() - started > _DEADLINE_S:
        return None

    found = _report(caps, symbols)
    if found is None:
        return None
    context, human = found
    # Sin `permissionDecision`: esto informa, no decide.
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": context,
                                   "systemMessage": human}}


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
        payload = json.loads(sys.stdin.read() or "{}")
        out = run(payload, started)
        if out is not None:
            real_stdout.write(json.dumps(out))
    except Exception as e:
        # Un hook roto no puede frenar al agente. A stderr, que Claude Code manda al
        # log de debug sin interpretarlo como decisión.
        print(f"[leo-mcp] guard hook skipped: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        sys.stdout = real_stdout
    return 0


if __name__ == "__main__":
    sys.exit(main())
