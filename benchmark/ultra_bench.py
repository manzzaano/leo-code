"""
ultra_bench.py — Benchmark ultraexigente: leo-code+KC-RAG vs full_ctx vs no_ctx

Modos:
  leo      : leo-code CLI con KC-RAG integrado (EL PRODUCTO)
  kc_api   : KC-RAG context + DeepSeek API directo (referencia interna)
  full_ctx : archivos fuente completos en contexto (simula opencode/Claude Code)
  no_ctx   : DeepSeek sin contexto (cota inferior)

Meta: leo >= full_ctx >> no_ctx en criteria score

Run:
  python -u benchmark/ultra_bench.py
  python -u benchmark/ultra_bench.py --quick   # 8 tareas rapidas
  python -u benchmark/ultra_bench.py --mode leo,full_ctx  # solo 2 modos
"""

import sys, os, json, time, httpx, statistics, subprocess, threading, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')

sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-core')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-code')
from kc_core.benchmark import score_answer, llm_judge as _judge
from openai import OpenAI

# ─── Config ────────────────────────────────────────────────────────────────────
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM          = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL        = "deepseek-chat"
TEMPERATURE  = 0.1
RUNS_PER_TASK = 1

SIDECAR   = "http://localhost:9898"
REPO      = r"C:\Users\Ismael\Desktop\RAG"
LEO_MODEL = "deepseek/deepseek-chat"
BUN       = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC   = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"

RUNS_DIR = Path(__file__).parent / "ultra_runs"
RUNS_DIR.mkdir(exist_ok=True)

SYSTEM_BASE = (
    "Eres un asistente experto en codigo Python. "
    "Responde en espanol. Se preciso y conciso. "
    "Cita valores exactos (numeros, nombres de variables, tipos) cuando los conozcas."
)

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
    "LEO_REPO_PATH": REPO,
}

# ─── 20 tareas ultraexigentes ───────────────────────────────────────────────────
# Cada tarea: query + criterios verificables + archivos relevantes para full_ctx
TASKS = [
    # ── Bloque 1: Valores exactos de config ──────────────────────────────────
    {
        "id": "C1", "type": "code_qa", "kc_task_type": "code_query",
        "query": "Cuales son los valores exactos de MAX_TRAVERSAL_DEPTH, MAX_SUBGRAPH_NODES y COMPRESS_THRESHOLD en config.py? Explica para que sirve cada uno.",
        "criterios": ["MAX_TRAVERSAL_DEPTH", "2", "MAX_SUBGRAPH_NODES", "20", "COMPRESS_THRESHOLD", "25"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\config.py"],
    },
    {
        "id": "C2", "type": "code_qa", "kc_task_type": "code_query",
        "query": "Que valores numericos exactos estan en CONFIDENCE_MAP en ingestion/pipeline.py? Que representa cada clave?",
        "criterios": ["HIGH", "0.95", "LOW", "0.60", "CONFIDENCE_MAP"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\ingestion\pipeline.py"],
    },
    {
        "id": "C3", "type": "code_qa", "kc_task_type": "code_query",
        "query": "Cuanto es CACHE_L2_TTL y CACHE_L3_TTL en config.py? En que unidades estan?",
        "criterios": ["CACHE_L2_TTL", "300", "CACHE_L3_TTL", "60", "segundos"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\config.py"],
    },
    {
        "id": "C4", "type": "code_qa", "kc_task_type": "code_query",
        "query": "Cual es el valor de MIN_GROUNDING_SCORE y ROUTER_CONFIDENCE_THRESHOLD en config.py?",
        "criterios": ["MIN_GROUNDING_SCORE", "0.70", "ROUTER_CONFIDENCE_THRESHOLD", "0.80"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\config.py"],
    },
    # ── Bloque 2: Algoritmos internos ────────────────────────────────────────
    {
        "id": "A1", "type": "code_qa", "kc_task_type": "code_query",
        "query": "En graph/traversal.py, la funcion bfs_subgraph ejecuta cuantas queries Cypher? Que devuelve cada una? Cita el comentario del codigo.",
        "criterios": ["2", "Q1", "Q2", "nodos", "aristas", "edges"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\graph\traversal.py"],
    },
    {
        "id": "A2", "type": "code_qa", "kc_task_type": "code_query",
        "query": "Como funciona _normalize_for_search en graph/traversal.py? Que transformaciones aplica exactamente al string de entrada?",
        "criterios": ["NFKD", "ascii", "lower", "unicodedata", "normalize"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\graph\traversal.py"],
    },
    {
        "id": "A3", "type": "code_qa", "kc_task_type": "code_query",
        "query": "En query/capa2.py, cuantos candidatos maximos usa retrieve_subgraph para hacer BFS? Que pasa si hay mas tokens en la query?",
        "criterios": ["3", "candidates[:3]", "candidatos", "BFS"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\capa2.py"],
    },
    {
        "id": "A4", "type": "code_qa", "kc_task_type": "code_query",
        "query": "En query/capa3.py, como separa la funcion compress los nodos precision_critical del resto? Que tratamiento diferente reciben?",
        "criterios": ["precision_critical", "precision_ctx", "JSON", "DATOS EXACTOS", "tripletas"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\capa3.py"],
    },
    {
        "id": "A5", "type": "code_qa", "kc_task_type": "code_query",
        "query": "En _to_lucene_query en graph/traversal.py, que caracteres especiales escapa con backslash? Que sufijo anade a cada token?",
        "criterios": ["re.sub", "backslash", "asterisco", "*", "escaped"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\graph\traversal.py"],
    },
    # ── Bloque 3: Flujo del pipeline ─────────────────────────────────────────
    {
        "id": "F1", "type": "flow_trace", "kc_task_type": "code_query",
        "query": "Traza el flujo completo de query/pipeline.py: en que orden se ejecutan las capas (0,2,3,4,5) y que hace cada una? Que pasa si capa0 resuelve la query?",
        "criterios": ["capa0", "try_resolve", "capa2", "capa3", "capa4", "capa5", "validate_query", "cache"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\pipeline.py"],
    },
    {
        "id": "F2", "type": "flow_trace", "kc_task_type": "code_query",
        "query": "En query/pipeline.py, la validacion de seguridad ocurre antes o despues de consultar la cache L2? Cual es el orden exacto de validate_query vs get_cached_result?",
        "criterios": ["validate_query", "get_cached_result", "antes", "primero"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\pipeline.py"],
    },
    {
        "id": "F3", "type": "flow_trace", "kc_task_type": "code_query",
        "query": "Que funciones importa query/pipeline.py del modulo query.router? Lista todas.",
        "criterios": ["route", "classify_intent", "route_parallel"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\pipeline.py"],
    },
    {
        "id": "F4", "type": "flow_trace", "kc_task_type": "code_query",
        "query": "En ingestion/pipeline.py, que tipo de entidad crea _extract_from_ast para una sentencia ast.Import? Que confianza le asigna?",
        "criterios": ["Modulo", "LOW", "0.60", "ast.Import", "IMPORTA"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\ingestion\pipeline.py"],
    },
    # ── Bloque 4: Cross-file y dependencias ──────────────────────────────────
    {
        "id": "X1", "type": "cross_file", "kc_task_type": "code_query",
        "query": "Que funciones exactas importa query/capa2.py de graph.traversal? Solo las que aparecen en el import.",
        "criterios": ["bfs_subgraph", "find_nodes_by_name", "graph.traversal"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\capa2.py", r"C:\Users\Ismael\Desktop\RAG\graph\traversal.py"],
    },
    {
        "id": "X2", "type": "cross_file", "kc_task_type": "code_query",
        "query": "Que paquetes del modulo security usa query/pipeline.py? Lista todos los imports del paquete security.",
        "criterios": ["sanitize", "audit", "validate_query", "log_query"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\pipeline.py"],
    },
    {
        "id": "X3", "type": "cross_file", "kc_task_type": "code_query",
        "query": "En query/capa3.py, de que modulo externo importa serialize_context? Escribe el import exacto.",
        "criterios": ["kc_core.context", "serialize_context", "from kc_core"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\capa3.py"],
    },
    # ── Bloque 5: Deteccion de bugs y edge cases ─────────────────────────────
    {
        "id": "B1", "type": "bug_detection", "kc_task_type": "code_query",
        "query": "En query/capa2.py, que ocurre si todos los tokens de la query son stop_words? Devuelve subgrafo vacio o hay algun fallback?",
        "criterios": ["candidates", "vacio", "empty", "lista vacia", "0", "stop_words"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\query\capa2.py"],
    },
    {
        "id": "B2", "type": "bug_detection", "kc_task_type": "code_query",
        "query": "En graph/traversal.py, que devuelve bfs_subgraph si node_rows esta vacio (el nodo inicial no existe)? Cual es el return exacto?",
        "criterios": ["nodes", "edges", "vacio", "empty", '{"nodes": [], "edges": []}'],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\graph\traversal.py"],
    },
    {
        "id": "B3", "type": "bug_detection", "kc_task_type": "code_query",
        "query": "En ingestion/pipeline.py, que hace _extract_from_ast si ast.parse lanza SyntaxError? Que devuelve la funcion en ese caso?",
        "criterios": ["SyntaxError", "entities", "relations", "vacio", "return", "except"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\ingestion\pipeline.py"],
    },
    {
        "id": "B4", "type": "bug_detection", "kc_task_type": "code_query",
        "query": "En _to_lucene_query de graph/traversal.py, que devuelve si el string de entrada esta vacio ('') o es solo espacios?",
        "criterios": ["*", "asterisco", "tokens", "split", "vacio"],
        "relevant_files": [r"C:\Users\Ismael\Desktop\RAG\graph\traversal.py"],
    },
]

# ─── Helpers de I/O ────────────────────────────────────────────────────────────

def _read_files(paths: list[str]) -> str:
    """Lee archivos reales para modo full_ctx. Simula lo que opencode haria."""
    parts = []
    for p in paths:
        try:
            content = Path(p).read_text(encoding="utf-8")
            parts.append(f"# === {Path(p).name} ===\n{content}")
        except Exception as e:
            parts.append(f"# === {Path(p).name} === ERROR: {e}")
    return "\n\n".join(parts)


def call_llm(system: str, user: str, run_id: str = "") -> dict:
    t0 = time.time()
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if run_id:
        (RUNS_DIR / f"{run_id}.json").write_text(
            json.dumps({"messages": msgs}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    try:
        resp = LLM.chat.completions.create(
            model=MODEL, messages=msgs, temperature=TEMPERATURE, max_tokens=1024,
        )
        return {
            "respuesta": resp.choices[0].message.content or "",
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
            "latency_s": round(time.time() - t0, 3),
        }
    except Exception as e:
        return {"respuesta": f"Error: {e}", "input_tokens": 0, "output_tokens": 0,
                "latency_s": round(time.time() - t0, 3)}


def get_kcrag_context(query: str, task_type: str, budget: int = 0) -> dict:
    try:
        r = httpx.post(f"{SIDECAR}/context", json={
            "query": query, "repo_path": REPO,
            "task_type": task_type, "budget_tokens": budget,
        }, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        return {"error": str(e)}


# ─── Streaming CLI runner (leo-code) ───────────────────────────────────────────

def _run_cli_streaming(cmd, cwd, env, timeout=150) -> str:
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=cwd, env=env,
    )
    lines = []
    done = threading.Event()

    def _reader():
        try:
            for raw in proc.stdout:
                lines.append(raw)
                # Stop only when the agent finishes (reason:stop), not on tool-call steps
                if b'"step_finish"' in raw and b'"reason":"stop"' in raw:
                    break
        finally:
            done.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    done.wait(timeout=timeout)
    proc.kill()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    return b"".join(lines).decode("utf-8", errors="replace")


def _parse_oc_json_output(stdout: str) -> tuple[str, int, int]:
    text = ""
    total_input = 0
    total_output = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            ev_type = ev.get("type", "")
            if ev_type == "text":
                part = ev.get("part", {})
                if isinstance(part, dict):
                    text += part.get("text", "")
            elif ev_type == "step_finish":
                toks = ev.get("part", {}).get("tokens", {})
                out = toks.get("output", 0) + toks.get("reasoning", 0)
                total_output += out
                total_input += toks.get("total", 0) - out
            elif ev_type == "assistant":
                for part in ev.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        text += part.get("text", "")
        except Exception:
            pass
    return text.strip(), total_input, total_output


def judge_fn(prompt: str) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=5,
    )
    return resp.choices[0].message.content or ""


# ─── Runners por modo ──────────────────────────────────────────────────────────

def run_leo(task: dict, task_idx: int) -> dict:
    t0 = time.time()
    stdout = _run_cli_streaming(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", task["query"], "--format", "json", "--model", LEO_MODEL,
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=150,
    )
    latency = round(time.time() - t0, 3)
    respuesta, in_tok, out_tok = _parse_oc_json_output(stdout)
    return {
        "respuesta": respuesta, "input_tokens": in_tok, "output_tokens": out_tok,
        "latency_s": latency, "context_tokens": -1, "mode": "leo",
    }


def run_kc_api(task: dict, task_idx: int) -> dict:
    ctx = get_kcrag_context(task["query"], task.get("kc_task_type", "auto"))
    sys_p = SYSTEM_BASE
    if ctx.get("context"):
        sys_p += f"\n\nContexto estructural KC-RAG:\n{ctx['context']}"
    r = call_llm(sys_p, task["query"], run_id=f"kc_t{task_idx+1}")
    r["context_tokens"] = ctx.get("tokens", 0)
    r["mode"] = "kc_api"
    return r


def run_full_ctx(task: dict, task_idx: int) -> dict:
    """Archivos fuente completos en contexto. Simula opencode/Claude Code con acceso a ficheros."""
    files_content = _read_files(task.get("relevant_files", []))
    sys_p = SYSTEM_BASE + (
        "\n\nTienes acceso completo a los archivos fuente del repositorio. "
        "Usa el codigo proporcionado para responder con precision."
    )
    user_q = f"{task['query']}\n\n<archivos_fuente>\n{files_content}\n</archivos_fuente>"
    r = call_llm(sys_p, user_q, run_id=f"full_t{task_idx+1}")
    r["context_tokens"] = len(files_content.split())
    r["mode"] = "full_ctx"
    return r


def run_no_ctx(task: dict, task_idx: int) -> dict:
    r = call_llm(SYSTEM_BASE, task["query"], run_id=f"noctx_t{task_idx+1}")
    r["context_tokens"] = 0
    r["mode"] = "no_ctx"
    return r


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_result(r: dict, criterios: list) -> dict:
    crit = score_answer(r["respuesta"], criterios)["score"]
    judge = _judge(r["respuesta"], criterios, judge_fn)
    return {**r, "criteria": crit, "judge": int(judge)}


# ─── Task runner ──────────────────────────────────────────────────────────────

def run_task(task: dict, task_idx: int, modes: list[str]) -> dict:
    runners = {
        "leo":      run_leo,
        "kc_api":   run_kc_api,
        "full_ctx": run_full_ctx,
        "no_ctx":   run_no_ctx,
    }
    results = {}
    active = {m: runners[m] for m in modes if m in runners}

    with ThreadPoolExecutor(max_workers=len(active)) as ex:
        futures = {ex.submit(fn, task, task_idx): m for m, fn in active.items()}
        for fut in as_completed(futures):
            m = futures[fut]
            try:
                raw = fut.result()
                results[m] = score_result(raw, task["criterios"])
            except Exception as e:
                results[m] = {
                    "respuesta": f"Error: {e}", "input_tokens": 0, "output_tokens": 0,
                    "latency_s": 0, "context_tokens": 0, "criteria": 0.0, "judge": 0,
                    "mode": m,
                }
    return {"task_id": task["id"], "type": task["type"], "query": task["query"], **results}


# ─── Metrics ──────────────────────────────────────────────────────────────────

def compute_metrics(results: list[dict], modes: list[str]) -> dict:
    n = len(results)
    metrics = {}
    for m in modes:
        crit_vals = [r[m]["criteria"] for r in results if m in r]
        judge_sum = sum(r[m]["judge"] for r in results if m in r)
        tok_sum   = sum(r[m]["input_tokens"] + r[m]["output_tokens"] for r in results if m in r)
        lat_sum   = sum(r[m]["latency_s"] for r in results if m in r)
        metrics[m] = {
            "avg_criteria": round(statistics.mean(crit_vals), 3) if crit_vals else 0,
            "judge_ok": judge_sum,
            "total_tokens": tok_sum,
            "avg_latency": round(lat_sum / n, 2) if n else 0,
        }
    return {"n_tasks": n, "modes": metrics}


def print_report(results: list[dict], m: dict, modes: list[str]):
    W = 110
    print("\n" + "=" * W)
    print("ULTRA BENCHMARK — leo+KC-RAG vs full_ctx (opencode) vs no_ctx")
    print(f"Model: {MODEL} | Temp: {TEMPERATURE} | Tasks: {m['n_tasks']}")
    print("=" * W)

    mm = m["modes"]
    col_w = 12

    header = f"{'Task':>5} {'Type':<14}"
    for mode in modes:
        header += f"  {mode[:col_w]:>{col_w}}"
    print(header)
    print("-" * W)

    for r in results:
        row = f"{r['task_id']:>5} {r['type']:<14}"
        for mode in modes:
            if mode in r:
                crit = r[mode]['criteria']
                j    = "J" if r[mode]['judge'] else "."
                tok  = r[mode]['input_tokens'] + r[mode]['output_tokens']
                row += f"  {crit:>4.0%} {j} {tok:>5}tok"
            else:
                row += f"  {'--':>{col_w}}"
        print(row)

    print("\n" + "=" * W)
    print(f"{'Metrica':<30}", end="")
    for mode in modes:
        print(f"  {mode:>{col_w}}", end="")
    print()
    print("-" * W)

    print(f"{'Criteria avg':30}", end="")
    for mode in modes:
        print(f"  {mm[mode]['avg_criteria']:>{col_w}.1%}", end="")
    print()

    print(f"{'Judge OK / {}'.format(m['n_tasks']):<30}", end="")
    for mode in modes:
        print(f"  {mm[mode]['judge_ok']:>{col_w}}", end="")
    print()

    print(f"{'Total tokens':30}", end="")
    for mode in modes:
        print(f"  {mm[mode]['total_tokens']:>{col_w},}", end="")
    print()

    print(f"{'Avg latency (s)':30}", end="")
    for mode in modes:
        print(f"  {mm[mode]['avg_latency']:>{col_w}.1f}", end="")
    print()

    print("\n--- Diagnosis ---")
    if "leo" in mm and "full_ctx" in mm:
        gap = mm["leo"]["avg_criteria"] - mm["full_ctx"]["avg_criteria"]
        if gap >= 0:
            print(f"[OK] leo KC-RAG >= full_ctx por {gap:+.1%}")
        elif gap > -0.05:
            print(f"[>>] leo KC-RAG casi iguala full_ctx: {gap:+.1%} — ajustar KC-RAG")
        else:
            print(f"[XX] leo KC-RAG por debajo de full_ctx: {gap:+.1%} — necesita mejoras")

    if "leo" in mm and "no_ctx" in mm:
        gain = mm["leo"]["avg_criteria"] - mm["no_ctx"]["avg_criteria"]
        print(f"     Gain vs no_ctx: {gain:+.1%}")

    if "full_ctx" in mm and "no_ctx" in mm:
        fc_gain = mm["full_ctx"]["avg_criteria"] - mm["no_ctx"]["avg_criteria"]
        print(f"     full_ctx vs no_ctx baseline: {fc_gain:+.1%}")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Solo primeras 8 tareas")
    parser.add_argument("--mode", default="leo,kc_api,full_ctx,no_ctx",
                        help="Modos separados por coma")
    parser.add_argument("--tasks", default="", help="IDs de tareas separados por coma (ej: C1,A1,F1)")
    args = parser.parse_args()

    modes = [m.strip() for m in args.mode.split(",")]
    tasks = TASKS

    if args.tasks:
        ids = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in ids]
    elif args.quick:
        tasks = tasks[:8]

    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    print(f"[{ts}] ULTRA BENCHMARK — {len(tasks)} tareas x {len(modes)} modos")
    print(f"Modos activos: {modes}")
    print(f"Repo: {REPO}")

    # Warmup KC-RAG
    if any(m in modes for m in ("leo", "kc_api")):
        try:
            h = httpx.get(f"{SIDECAR}/health", timeout=5)
            print(f"KC-RAG sidecar: {h.json()['status']}")
            w = httpx.post(f"{SIDECAR}/index",
                           json={"repo_path": REPO, "languages": "python,text"}, timeout=120)
            stats = w.json()
            print(f"[warmup] {stats.get('total_capsules', '?')} capsules indexadas")
        except Exception as e:
            print(f"WARN: KC-RAG no disponible ({e})")

    print(f"\nEjecutando {len(tasks)} tareas en paralelo...")
    task_results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=min(len(tasks), 6)) as ex:
        futures = {ex.submit(run_task, t, i, modes): i for i, t in enumerate(tasks)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                task_results[i] = fut.result()
                tid = tasks[i]["id"]
                r = task_results[i]
                parts = []
                for m in modes:
                    if m in r:
                        parts.append(f"{m}={r[m]['criteria']:.0%}")
                print(f"  [done] {tid}: {' | '.join(parts)}", flush=True)
            except Exception as e:
                print(f"  [ERROR] tarea {i}: {e}", flush=True)

    ordered = [task_results[i] for i in range(len(tasks)) if i in task_results]
    met = compute_metrics(ordered, modes)
    print_report(ordered, met, modes)

    out = Path(__file__).parent / f"ultra_results_{ts}.json"
    out.write_text(json.dumps({
        "run_timestamp": ts, "model": MODEL, "temperature": TEMPERATURE,
        "modes": modes, "n_tasks": len(tasks), "repo": REPO,
        "metrics": met, "results": ordered,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {out}")

    # Retorna el gap para goal tracking
    mm = met["modes"]
    if "leo" in mm and "full_ctx" in mm:
        gap = mm["leo"]["avg_criteria"] - mm["full_ctx"]["avg_criteria"]
        print(f"\nGAP leo vs full_ctx: {gap:+.1%} (meta: >= 0%)")
        return gap
    return None


if __name__ == "__main__":
    main()
