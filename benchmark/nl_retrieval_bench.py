"""Calidad de get_context con preguntas en lenguaje natural — determinista, cero LLM.

mcp_client_bench solo prueba consultas que NOMBRAN el símbolo; esto mide lo que pregunta
un agente de verdad ("how does X decide Y"). Cada pregunta tiene sus símbolos correctos
sobre este repo; acierto = alguno sale entre los 5 primeros del contexto devuelto.

Las 10 últimas (HOLDOUT) se escribieron a la vez que el resto y no se miran al ajustar
el retrieval: si dev sube y holdout no, el ajuste es sobreajuste a estas preguntas.

Uso:  python benchmark/nl_retrieval_bench.py [-v]
Sale !=0 si el acierto@5 total < UMBRAL.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LEO_SEMANTIC", "0")

UMBRAL = 0.60  # 27/10: 67% (dev 13/20, holdout 7/10); antes del arreglo 20%
TOP = 5

DEV = [
    ("how does the guard hook decide to stay silent before an edit", {"run", "_report"}),
    ("where is the index written to disk", {"_write_index", "flush_index", "_save_index_to_disk", "save"}),
    ("how are short acronyms in the query filtered", {"discriminant_short_words"}),
    ("what does the MCP server do at startup", {"_warmup", "_preload_native"}),
    ("how does trace cross from a frontend fetch to a backend route", {"link_http_edges"}),
    ("what happens when get_context finds no matching symbol", {"_get_context"}),
    ("how is the token budget chosen for a task type", {"get_budget", "classify_task"}),
    ("how does init write the mcp config for cursor", {"cmd_init", "_write_json"}),
    ("how are callers of a method found in the call graph", {"who_calls", "_callers_of"}),
    ("how are python imports resolved to their definitions", {"_bind_module", "_bind_targets", "resolve", "_resolve"}),
    ("how is the method resolution order computed for self calls", {"_mro", "_dispatch"}),
    ("which files are skipped when indexing", {"_is_junk", "_should_skip", "_discover_files"}),
    ("how does the file watcher reindex only changed files", {"watch", "sync", "mark_dirty", "take_dirty"}),
    ("how is the BM25 score computed", {"get_scores", "_compute_idf"}),
    ("how are capsules ranked with pagerank", {"pagerank", "score_capsules"}),
    ("how does the compressor fit symbols into the token budget", {"compress", "select_within_budget"}),
    ("how does doctor check the installation", {"cmd_doctor"}),
    ("how is the uv cache directory detected", {"_uv_cache_dir", "_ephemeral"}),
    ("how does guardian find which dependents have no tests", {"is_covered", "test_closure", "review", "uncovered"}),
    ("how are typescript functions extracted with tree-sitter", {"extract_from_tree_sitter"}),
]
HOLDOUT = [
    ("where are the http server routes collected", {"_server_routes"}),
    ("how does the cli detect the changed symbols in a git diff", {"changed_symbols", "review_diff", "git_diff"}),
    ("how is the index protected against two processes writing at once", {"_acquire_file_lock"}),
    ("how is the language of a file detected", {"detect_language"}),
    ("how are web frameworks detected in a project", {"detect_frameworks"}),
    ("how is the call graph built from parsed files", {"build_call_graph", "_rebuild_call_graph"}),
    ("what is the path to the cached index of a repo", {"repo_index_path", "_default_cache_dir"}),
    ("how does the server warn about very large repos", {"_warn_if_huge"}),
    ("how does impact compute transitive dependents", {"impact"}),
    ("how are local variable types inferred for method calls", {"_local_types", "_typed"}),
]

# Cabeceras de símbolo del compressor: "[nombre|tipo] ruta" y "## nombre (TIPO)".
_HEAD = re.compile(r"^\[([^\]|]+)\|(\w+)\]|^## (\S+) \((\w+)\)", re.M)


def symbols(text: str) -> list[tuple[str, str]]:
    """(nombre sin clase, tipo) en orden de aparición, sin repetidos."""
    out, seen = [], set()
    for m in _HEAD.finditer(text):
        name, kind = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        bare = name.split(".")[-1]
        if bare not in seen:
            seen.add(bare)
            out.append((bare, kind.lower()))
    return out


def run(verbose: bool = False) -> dict:
    from leo_code.server.mcp_server import _get_context
    repo = str(ROOT)
    res = {}
    for split, cases in (("dev", DEV), ("holdout", HOLDOUT)):
        hits = test_first = 0
        for q, gold in cases:
            syms = symbols(_get_context({"query": q, "repo_path": repo}))
            top = [n for n, _ in syms[:TOP]]
            ok = bool(gold & set(top))
            hits += ok
            test_first += bool(syms) and syms[0][1] == "test"
            if verbose:
                print(f"  {'OK  ' if ok else 'MISS'} [{split}] {q}\n        top: {', '.join(top)}")
        res[split] = {"hit": hits, "n": len(cases), "test_first": test_first}
    return res


if __name__ == "__main__":
    r = run("-v" in sys.argv)
    total = sum(v["hit"] for v in r.values()) / sum(v["n"] for v in r.values())
    for k, v in r.items():
        print(f"{k:8} acierto@{TOP} {v['hit']}/{v['n']} · test en cabeza {v['test_first']}/{v['n']}")
    print(f"total    {total:.0%} (umbral {UMBRAL:.0%})")
    sys.exit(0 if total >= UMBRAL else 1)
