"""Bench DETERMINISTA de eficiencia de tokens — la métrica del objetivo, sin LLM/API.

Mide la promesa central de leo-code como MOTOR DE CONTEXTO: para responder una
tarea sobre un símbolo, un agente sin leo (Claude Code, opencode, …) lee el
ARCHIVO COMPLETO; leo le da el subgrafo comprimido. Esto cuantifica:

    reduction = 1 - tokens(contexto_leo) / tokens(archivo_completo)
    recall    = el símbolo objetivo sigue presente en el contexto comprimido

Reemplaza el baseline HARDCODEADO (metrics.BASELINE_TOKENS_PER_QUERY = 20000) por
medición real. Determinista al 100% (usa el compresor real con selección
estructural de candidatos — cero embeddings, cero varianza), así sirve de
regression guard en CI igual que retrieval_bench.py.

ponytail: selección de candidatos solo-estructural (archivo nombrado + vecinos de
grafo a 1 salto). Es el lower-bound honesto y reproducible; el endpoint /context
real añade semántica (Qdrant+BM25+scorer) que solo puede SUBIR el recall. Si
quieres medir fidelidad exacta al server, levanta el sidecar y mide /context.

Uso:  python benchmark/token_efficiency.py [--repo .]
Sale con código !=0 si reduction < UMBRAL_RED o recall < UMBRAL_REC (test CI).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code.core.tokens import count_tokens
from leo_code.rag.classifier import classify_task, get_budget
from leo_code.rag.compressor import compress

UMBRAL_RED = 0.80   # reducción media mínima vs leer el archivo completo
UMBRAL_REC = 0.90   # fracción de tareas cuyo símbolo objetivo sobrevive

# (task_id, archivo_objetivo relativo al repo, símbolo objetivo que DEBE sobrevivir)
TARGETS = [
    ("t1_code_query", "leo_code/core/parser.py",            "detect_frameworks"),
    ("t2_debug",      "leo_code/rag/compressor.py",         "compress"),
    ("t3_test_gen",   "leo_code/session/compactor.py",      "compact_history"),
    ("t4_refactor",   "leo_code/core/parser.py",            "detect_frameworks"),
    ("t6_code_gen",   "leo_code/server/server.py",          "get_context"),
    ("t7_code_edit",  "leo_code/rag/agent/goal.py",         "_plan"),
    ("t8_review",     "leo_code/rag/compressor.py",         "compress"),
    ("t9_optimize",   "leo_code/core/parser_generic.py",    "_find_block_end"),
    ("t10_audit",     "leo_code/server/server.py",          "get_context"),
    ("t14_cross_file","leo_code/rag/agent/loop.py",         "stream_run"),
]


def _select_candidates(caps: list, target_file: str, target_sym: str) -> tuple[list, list]:
    """Candidatos solo-estructural: cápsulas del archivo nombrado + vecinos de grafo.

    El símbolo objetivo lidera (compress usa la primera cápsula como target).
    """
    tf = target_file.replace("\\", "/")
    file_caps = [c for c in caps if (c.file_path or "").replace("\\", "/").endswith(tf)]

    # El símbolo objetivo primero; luego el resto del archivo.
    file_caps.sort(key=lambda c: (c.name != target_sym, c.start_line))

    # Expansión de grafo a 1 salto: callees + callers del objetivo.
    neighbor_names: set[str] = set()
    for c in file_caps:
        neighbor_names |= set(c.calls or []) | set(c.called_by or [])
    file_paths = {c.file_path for c in file_caps}
    neighbors = [c for c in caps
                 if c.name in neighbor_names and c.file_path not in file_paths]

    top = file_caps + neighbors
    return top, caps


def _baseline_multi(caps: list, top: list, repo: str) -> int:
    """Tokens que un agente sin leo consume al seguir el subgrafo: el archivo
    objetivo + los archivos de sus vecinos directos (callees/callers). Es lo que
    Claude Code/opencode abren para razonar sobre dependencias — el baseline
    realista del objetivo, frente al cual leo compite vía MCP.
    """
    files = {c.file_path for c in top if c.file_path}
    total = 0
    for fp in files:
        p = Path(fp)
        if not p.is_absolute():
            p = Path(repo) / fp
        if p.exists():
            total += count_tokens(p.read_text(encoding='utf-8', errors='replace'))
    return total


def _body_coverage(top: list, target_sym: str, context: str) -> float:
    """Fracción de líneas no triviales del CUERPO del símbolo objetivo presentes en
    el contexto. Guard anti-gaming: si una futura optimización recorta tokens
    tirando el cuerpo que responde la pregunta, esto cae aunque el nombre siga.
    """
    target = next((c for c in top if c.name == target_sym and c.content), None)
    if not target or not target.content:
        return 1.0  # nada que cubrir
    lines = [ln.strip() for ln in target.content.splitlines() if len(ln.strip()) > 8]
    if not lines:
        return 1.0
    hit = sum(1 for ln in lines if ln in context)
    return hit / len(lines)


def run(repo: str = ".") -> tuple[float, float]:
    from leo_code.rag.indexer import Indexer

    idx = Indexer()
    idx.build(repo, verbose=False)
    caps = list(idx.get_capsules().values())

    red_single, red_multi, recalls, bodies = [], [], [], []
    print(f"{'task':<16} {'1file':>8} {'multi':>8} {'leo':>7} {'red1':>6} {'redN':>6} {'rec':>5} {'body':>5}")
    print("-" * 70)
    for task_id, target_file, target_sym in TARGETS:
        fpath = Path(repo) / target_file
        if not fpath.exists():
            print(f"{task_id:<16} (archivo no encontrado: {target_file})")
            continue
        base1 = count_tokens(fpath.read_text(encoding='utf-8', errors='replace'))

        query = f"¿Qué hace {target_sym} en {target_file}?"  # query reproducible
        task_type = classify_task(query)
        budget = get_budget(query)
        top, allc = _select_candidates(caps, target_file, target_sym)
        context = compress(top, allc, budget_tokens=budget, task_type=task_type, query=query)
        leo = count_tokens(context)
        baseN = _baseline_multi(caps, top, repo) or base1

        r1 = 1 - leo / base1 if base1 else 0.0
        rN = 1 - leo / baseN if baseN else 0.0
        recall = target_sym in context
        body_cov = _body_coverage(top, target_sym, context)  # guard anti-gaming
        red_single.append(r1)
        red_multi.append(rN)
        recalls.append(1.0 if recall else 0.0)
        bodies.append(body_cov)
        print(f"{task_id:<16} {base1:>8,} {baseN:>8,} {leo:>7,} {r1:>5.0%} {rN:>5.0%} "
              f"{'✓' if recall else '✗':>5} {body_cov:>4.0%}")

    avg1 = sum(red_single) / len(red_single) if red_single else 0.0
    avgN = sum(red_multi) / len(red_multi) if red_multi else 0.0
    avg_rec = sum(recalls) / len(recalls) if recalls else 0.0
    avg_body = sum(bodies) / len(bodies) if bodies else 0.0
    print("-" * 70)
    print(f"{'MEDIA':<16} {'':>8} {'':>8} {'':>7} {avg1:>5.0%} {avgN:>5.0%} {avg_rec:>4.0%} {avg_body:>4.0%}")
    print(f"\nReducción vs 1 archivo (conservador): {avg1:.1%}")
    print(f"Reducción vs multi-archivo (realista): {avgN:.1%}  (umbral {UMBRAL_RED:.0%})")
    print(f"Recall símbolo objetivo:               {avg_rec:.1%}  (umbral {UMBRAL_REC:.0%})")
    print(f"Cobertura de cuerpo (precisión):       {avg_body:.1%}  (guard anti-gaming)")
    # El guard CI usa el baseline realista multi-archivo (el del objetivo).
    return avgN, avg_rec


if __name__ == "__main__":
    repo = "."
    if "--repo" in sys.argv:
        repo = sys.argv[sys.argv.index("--repo") + 1]
    red, rec = run(repo)
    sys.exit(0 if (red >= UMBRAL_RED and rec >= UMBRAL_REC) else 1)
