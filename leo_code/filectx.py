"""Vista comprimida de UN archivo, para el plugin de opencode (C v4).

`python -m leo_code.filectx <archivo> [--repo .]` imprime las cápsulas del
archivo (firma + docstring + cuerpo con cap) en vez del contenido crudo. El
plugin sustituye el output del `read` nativo por esto: el agente conserva su
flujo (cero turnos extra, cero vetos) y paga ~una fracción del archivo.

Solo índice estructural: sin embeddings ni torch — arranque en frío rápido.
Exit 3 = archivo sin cápsulas (el plugin deja pasar el read crudo).
"""

import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--body-chars", type=int, default=1200)
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    target = os.path.abspath(os.path.join(repo, a.file) if not os.path.isabs(a.file) else a.file)
    # stdout real solo para el resultado (UTF-8): el indexer hace print() de
    # progreso y contaminaria lo que el plugin inyecta como output del read.
    import io
    real_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr
    # _CACHE_DIR del engine es relativa al CWD: situarse en el repo ANTES de importar.
    os.chdir(repo)
    from leo_code.engine import _get_indexer, _load_index_from_disk, _indexed_repos, _index_lock

    with _index_lock:
        _load_index_from_disk()
        if repo not in _indexed_repos:
            _get_indexer().build(repo)
            _indexed_repos.add(repo)

    caps = [c for c in _get_indexer().get_capsules().values()
            if os.path.abspath(c.file_path) == target]
    if not caps:
        sys.exit(3)
    caps.sort(key=lambda c: c.start_line)

    rel = os.path.relpath(target, repo).replace("\\", "/")
    out = [f"[leo-code] {rel} COMPRIMIDO ({len(caps)} simbolos, del AST). "
           "Cuerpos largos truncados: para lineas exactas usa read con offset/limit."]
    for c in caps:
        out.append(f"\n## {c.name} ({c.type}) L{c.start_line}-{c.end_line}")
        if c.signature:
            out.append(c.signature)
        if c.docstring:
            out.append(f'"""{c.docstring[:300]}"""')
        body = c.content or ""
        if len(body) <= a.body_chars:
            if body.strip():
                out.append(body)
        else:
            out.append(body[: a.body_chars]
                       + f"\n# ... [truncado; read offset={c.start_line} limit={c.end_line - c.start_line + 1} para el resto]")
    real_stdout.write("\n".join(out))
    real_stdout.flush()


if __name__ == "__main__":
    main()
