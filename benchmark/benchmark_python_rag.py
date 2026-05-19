"""Benchmark justo: leo-code CLI (KC-RAG Python) vs opencode CLI (WSL) vs no_ctx.
Target: C:\\Users\\Ismael\\Desktop\\RAG (Python codebase, 509+ KC-RAG capsules).
KC-RAG indexa Python. opencode lee ficheros via WSL. Mismo repo, mismas tareas.
"""
import json, os, sys, time, threading, subprocess, statistics, httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-core')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-code')
from kc_core.benchmark import score_answer
from openai import OpenAI

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL         = "deepseek-chat"
TEMPERATURE   = 0.2
SIDECAR       = "http://localhost:9898"
BUN           = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC       = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"
LEO_REPO      = r"C:\Users\Ismael\Desktop\RAG"   # Python repo: KC-RAG funciona aqui
WSL_REPO      = "/mnt/c/Users/Ismael/Desktop/RAG"
TIMEOUT_LEO   = 150
TIMEOUT_OC    = 180
RUNS_DIR      = Path(__file__).parent / "runs_pyrag"
RUNS_DIR.mkdir(exist_ok=True)

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
    "LEO_REPO_PATH": LEO_REPO,
}
_WSL_ENV = {
    **os.environ,
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "WSLENV": "DEEPSEEK_API_KEY/u:OC_QUERY/u",
}

# ---------------------------------------------------------------------------
# Tareas: codigo Python especifico del repo RAG
# Criterios = palabras que SOLO aparecen si el agente leyó el código real.
# Ground truth basado en el código fuente observado.
# ---------------------------------------------------------------------------
TASKS = [
    {
        "id": "P1", "type": "code_query",
        "query": "¿Qué parámetros exactos acepta la función bfs_subgraph() en graph/traversal.py y cuáles son sus tipos y valores por defecto?",
        "criterios": ["start_node_id", "max_depth", "dict"],
        "ground_truth": "bfs_subgraph(start_node_id: str, max_depth: int=None) -> dict. Parámetro start_node_id: str obligatorio, max_depth: int opcional (None por defecto).",
    },
    {
        "id": "P2", "type": "code_query",
        "query": "¿Qué retorna compress() en query/capa3.py y cuáles son los tipos de sus parámetros y retorno?",
        "criterios": ["compress", "tuple", "bool", "subgraph"],
        "ground_truth": "compress(subgraph: dict) -> tuple[str, bool]. Recibe subgraph (dict) y retorna una tupla: (texto_comprimido: str, fue_truncado: bool).",
    },
    {
        "id": "P3", "type": "code_query",
        "query": "¿Cuál es la firma completa de synthesize() en query/capa4.py incluyendo todos sus parámetros?",
        "criterios": ["synthesize", "context", "subgraph", "dict", "query"],
        "ground_truth": "synthesize(query: str, context: str, subgraph: dict=None) -> dict. Parámetros: query obligatorio, context obligatorio, subgraph opcional.",
    },
    {
        "id": "P4", "type": "search",
        "query": "¿Qué funciones existen en graph/traversal.py que buscan nodos por nombre o tipo?",
        "criterios": ["find_nodes_by_name", "find_nodes_by_type", "limit", "list"],
        "ground_truth": "find_nodes_by_name(name: str, limit: int=5) -> list[dict] y find_nodes_by_type(node_type: str, limit: int=20) -> list[dict].",
    },
    {
        "id": "P5", "type": "code_query",
        "query": "¿Qué hace classify_intent() en query/router.py y qué tipo retorna exactamente?",
        "criterios": ["classify_intent", "tuple", "float", "intent"],
        "ground_truth": "classify_intent(query: str) -> tuple[str, float]. Clasifica la intención de la query y retorna una tupla (tipo_intención, confianza_float).",
    },
    {
        "id": "P6", "type": "search",
        "query": "¿Qué funciones de graph/nodes.py tienen operaciones en batch (batch operations)?",
        "criterios": ["upsert_nodes_batch", "upsert_relations_batch", "list", "batch"],
        "ground_truth": "upsert_nodes_batch(nodes_data: list[dict]) -> list[str] y upsert_relations_batch(relations_data: list[dict]).",
    },
    {
        "id": "P7", "type": "no_code",
        "query": "Según la documentación del sistema, ¿cuáles son exactamente las condiciones C01 y C05 para obtener descuentos?",
        "criterios": ["C01", "domiciliado", "C05", "fidelizacion"],
        "ground_truth": "C01: pago domiciliado en cuenta bancaria. C05: fidelización del cliente (más de 3 años de antigüedad).",
    },
    {
        "id": "P8", "type": "refactor",
        "query": "¿Qué funciones en graph/traversal.py dependen directamente de Neo4j (llaman a run_query o run_write) y cuáles son independientes?",
        "criterios": ["run_query", "bfs_subgraph", "find_nodes", "_normalize"],
        "ground_truth": "Dependen de Neo4j: bfs_subgraph (via run_query), find_nodes_by_name (via run_query), find_nodes_by_type (via run_query). Independientes: _normalize_for_search, _to_lucene_query.",
    },
]

SYSTEM_INSTR = "Eres experto en Python y sistemas de recuperacion de informacion. Responde en español. Se preciso y usa los nombres exactos del codigo."

# ---------------------------------------------------------------------------
# Streaming helper
# ---------------------------------------------------------------------------
def _run_cli_streaming(cmd, cwd, env, timeout=120) -> str:
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
                if b'"step_finish"' in raw and b'"total"' in raw:
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
    total_input = total_output = 0
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
                total_input  += toks.get("total", 0) - out
            elif ev_type == "assistant":
                for part in ev.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        text += part.get("text", "")
        except Exception:
            pass
    return text.strip(), total_input, total_output

# ---------------------------------------------------------------------------
# Judge LLM
# ---------------------------------------------------------------------------
def _judge_fn(prompt: str) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=5,
    )
    return resp.choices[0].message.content or ""

def judge_with_truth(answer: str, ground_truth: str, criterios: list[str]) -> bool:
    crit_str = ", ".join(criterios)
    prompt = (
        f"Evalua si la siguiente respuesta cubre los puntos clave.\n\n"
        f"Ground truth:\n{ground_truth}\n\n"
        f"Criterios obligatorios (al menos 60% deben aparecer): {crit_str}\n\n"
        f"Respuesta del agente:\n{answer[:3000]}\n\n"
        "Responde solo 'OK' si la respuesta cubre los criterios y es consistente "
        "con el ground truth. Responde 'FAIL' en caso contrario."
    )
    return "OK" in _judge_fn(prompt).upper()

# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------
def run_leo(query: str, task_id: str) -> dict:
    t0 = time.time()
    stdout = _run_cli_streaming(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", query, "--format", "json", "--model", "deepseek/deepseek-chat",
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=TIMEOUT_LEO,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_oc_json_output(stdout)
    (RUNS_DIR / f"leo_{task_id}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:500],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"respuesta": respuesta, "input_tokens": inp, "output_tokens": out, "latency_s": latency}

def run_opencode_wsl(query: str, task_id: str) -> dict:
    t0 = time.time()
    env = {**_WSL_ENV, "OC_QUERY": query}
    bash_cmd = (
        f'cd "{WSL_REPO}" && '
        'opencode run "$OC_QUERY" '
        '--format json '
        '--model deepseek/deepseek-chat '
        '--dangerously-skip-permissions 2>/dev/null'
    )
    stdout = _run_cli_streaming(
        ["wsl", "-d", "Ubuntu", "bash", "-c", bash_cmd],
        cwd=None, env=env, timeout=TIMEOUT_OC,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_oc_json_output(stdout)
    (RUNS_DIR / f"oc_{task_id}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:500],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"respuesta": respuesta, "input_tokens": inp, "output_tokens": out, "latency_s": latency}

def run_no_ctx(query: str) -> dict:
    t0 = time.time()
    try:
        resp = LLM.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTR},
                {"role": "user", "content": query},
            ],
            temperature=TEMPERATURE, max_tokens=1024,
        )
        answer = resp.choices[0].message.content or ""
        inp  = resp.usage.prompt_tokens
        out  = resp.usage.completion_tokens
    except Exception as e:
        answer, inp, out = f"Error: {e}", 0, 0
    return {"respuesta": answer, "input_tokens": inp, "output_tokens": out,
            "latency_s": round(time.time() - t0, 3)}

# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------
def run_task(task: dict) -> dict:
    query  = task["query"]
    crit   = task["criterios"]
    truth  = task["ground_truth"]

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_leo = ex.submit(run_leo, query, task["id"])
        f_oc  = ex.submit(run_opencode_wsl, query, task["id"])
        f_nc  = ex.submit(run_no_ctx, query)
        r_leo = f_leo.result()
        r_oc  = f_oc.result()
        r_nc  = f_nc.result()

    def _score(r):
        ans = r["respuesta"]
        crit_score = score_answer(ans, crit)["score"] if ans else 0.0
        return {
            "tokens":   r["input_tokens"] + r["output_tokens"],
            "latency":  r["latency_s"],
            "criteria": crit_score,
            "judge":    judge_with_truth(ans, truth, crit) if ans else False,
            "answer":   ans[:300],
        }

    return {
        "id":       task["id"],
        "type":     task["type"],
        "query":    query,
        "leo":      _score(r_leo),
        "opencode": _score(r_oc),
        "no_ctx":   _score(r_nc),
    }

# ---------------------------------------------------------------------------
# Metrics & report
# ---------------------------------------------------------------------------
def compute_metrics(results: list[dict]) -> dict:
    modes = ("leo", "opencode", "no_ctx")
    total = {m: 0 for m in modes}
    lat   = {m: 0.0 for m in modes}
    crit  = {m: [] for m in modes}
    judge = {m: 0 for m in modes}
    n     = len(results)
    for r in results:
        for m in modes:
            total[m] += r[m]["tokens"]
            lat[m]   += r[m]["latency"]
            crit[m].append(r[m]["criteria"])
            judge[m] += int(r[m]["judge"])
    avg_crit = {m: statistics.mean(crit[m]) for m in modes}
    return {
        "n_tasks": n,
        "total_tokens": total,
        "latency": {m: round(lat[m], 2) for m in modes},
        "avg_criteria": {m: round(avg_crit[m], 3) for m in modes},
        "judge_ok": judge,
        "leo_vs_oc_criteria":   round(avg_crit["leo"] - avg_crit["opencode"], 3),
        "leo_vs_noctx_criteria":round(avg_crit["leo"] - avg_crit["no_ctx"], 3),
        "leo_judge_vs_oc":      judge["leo"] - judge["opencode"],
    }

def print_report(results: list[dict], m: dict, run_label: str = ""):
    W = 115
    label = f"BENCHMARK: leo-code (KC-RAG Python) vs opencode CLI  {run_label}"
    print("\n" + "=" * W)
    print(f"  {label}")
    print(f"  Target: {LEO_REPO} | Model: {MODEL} | Temp: {TEMPERATURE}")
    print("=" * W)

    tk, lk, ac, jk, n = m["total_tokens"], m["latency"], m["avg_criteria"], m["judge_ok"], m["n_tasks"]

    print(f"\n  {'Metrica':<45} {'leo-code':>10} {'opencode':>10} {'no-ctx':>8}")
    print(f"  {'-'*75}")
    print(f"  {'Tokens totales':<45} {tk['leo']:>10,} {tk['opencode']:>10,} {tk['no_ctx']:>8,}")
    print(f"  {'Latencia total (s)':<45} {lk['leo']:>10.1f} {lk['opencode']:>10.1f} {lk['no_ctx']:>8.1f}")
    print(f"  {'Criteria avg (keyword match)':<45} {ac['leo']:>10.1%} {ac['opencode']:>10.1%} {ac['no_ctx']:>8.1%}")
    print(f"  {'LLM judge OK':<45} {jk['leo']:>9}/{n} {jk['opencode']:>9}/{n} {jk['no_ctx']:>7}/{n}")
    print(f"  {'Leo vs opencode (criteria delta)':<45} {m['leo_vs_oc_criteria']:>+10.1%}")
    print(f"  {'Leo vs no-ctx   (criteria delta)':<45} {m['leo_vs_noctx_criteria']:>+10.1%}")
    print(f"  {'Leo vs opencode (judge delta)':<45} {m['leo_judge_vs_oc']:>+10d}")

    print(f"\n  {'ID':<5} {'Tipo':<14} {'Tarea':<32} {'LEOc':>6} {'OCc':>6} {'NCc':>5} {'LEOj':>5} {'OCj':>5} {'LEOtok':>7} {'OCtok':>7}")
    print(f"  {'-'*W}")
    for r in results:
        leo_j = "OK" if r["leo"]["judge"] else "--"
        oc_j  = "OK" if r["opencode"]["judge"] else "--"
        print(
            f"  {r['id']:<5} {r['type']:<14} {r['query'][:31]:<32} "
            f"{r['leo']['criteria']:>5.0%} {r['opencode']['criteria']:>5.0%} "
            f"{r['no_ctx']['criteria']:>4.0%} "
            f"{leo_j:>5} {oc_j:>5} "
            f"{r['leo']['tokens']:>7,} {r['opencode']['tokens']:>7,}"
        )

    print(f"\n  --- Diagnostico ---")
    lvo = m["leo_vs_oc_criteria"]
    lvj = m["leo_judge_vs_oc"]
    criteria_win = lvo > 0
    judge_win    = lvj >= 0
    all_win      = criteria_win and judge_win
    if all_win:
        print(f"  [WIN] leo-code supera opencode: criteria {lvo:+.1%}, judge {'+' if lvj>=0 else ''}{lvj}/{n}")
    elif criteria_win:
        print(f"  [>>] leo gana criteria {lvo:+.1%} pero judge empatado/perdido ({lvj:+d}/{n})")
    else:
        print(f"  [XX] opencode gana: criteria {lvo:+.1%}, judge {lvj:+d}/{n}")

    if ac["leo"] >= 0.70:
        print(f"  [OK] Leo criteria {ac['leo']:.0%} >= objetivo 70%")
    else:
        print(f"  [>>] Leo criteria {ac['leo']:.0%} -- objetivo 70%")

    return all_win

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    n  = len(TASKS)
    print(f"\n[{ts}] Python RAG Benchmark: {n} tareas | leo-code vs opencode")
    print(f"Target: {LEO_REPO}")
    print(f"Modelo: {MODEL} | Temperatura: {TEMPERATURE}")

    # KC-RAG: asegurar que el repo Python esta indexado
    try:
        h = httpx.get(f"{SIDECAR}/health", timeout=5)
        print(f"KC-RAG sidecar: {h.json()}")
        r = httpx.post(f"{SIDECAR}/index",
                       json={"repo_path": LEO_REPO, "languages": "python,text"},
                       timeout=120)
        idx_result = r.json()
        print(f"[index] KC-RAG Python: {idx_result}")
        if idx_result.get("capsules", 0) == 0:
            print("WARN: 0 capsules indexadas -- KC-RAG sin contexto")
    except Exception as e:
        print(f"WARN sidecar KC-RAG no responde ({e})")

    # Verificar opencode en WSL
    try:
        r = subprocess.run(
            ["wsl", "-d", "Ubuntu", "bash", "-c", "opencode --version 2>/dev/null || echo NOTFOUND"],
            capture_output=True, text=True, timeout=15
        )
        print(f"opencode WSL: {r.stdout.strip()}")
    except Exception as e:
        print(f"WARN WSL opencode: {e}")

    print(f"\n[Benchmark] {n} tareas x 3 modos en paralelo...")
    task_outputs: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = {ex.submit(run_task, task): i for i, task in enumerate(TASKS)}
        for fut in as_completed(futures):
            i = futures[fut]
            r = fut.result()
            task_outputs[i] = r
            leo_c = r["leo"]["criteria"]
            oc_c  = r["opencode"]["criteria"]
            leo_j = "OK" if r["leo"]["judge"] else "--"
            oc_j  = "OK" if r["opencode"]["judge"] else "--"
            print(f"[done] {r['id']} ({r['type']}) -- leo={leo_c:.0%}({leo_j}) oc={oc_c:.0%}({oc_j})", flush=True)

    results = [task_outputs[i] for i in range(n)]
    m = compute_metrics(results)
    all_win = print_report(results, m, run_label=f"[{ts}]")

    out = Path(__file__).parent / "pyrag_results.json"
    out.write_text(json.dumps({
        "run_timestamp": ts,
        "model": MODEL,
        "temperature": TEMPERATURE,
        "target_repo": LEO_REPO,
        "all_win": all_win,
        "metrics": m,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {out}")
    print(f"LEO_WINS_ALL: {all_win}")
    return all_win

if __name__ == "__main__":
    main()
