"""Benchmark v3 EXIGENTE: leo-code KC-RAG vs opencode CLI vs no_ctx.
15 tareas. Criterios de cuerpo de funcion, cross-module, constantes internas.
Imposible adivinar sin leer el codigo fuente.
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

DEEPSEEK_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
LLM           = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL         = "deepseek-chat"
TEMPERATURE   = 0.2
SIDECAR       = "http://localhost:9898"
BUN           = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC       = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"
LEO_REPO      = r"C:\Users\Ismael\Desktop\RAG"
WSL_REPO      = "/mnt/c/Users/Ismael/Desktop/RAG"
TIMEOUT_LEO   = 180
TIMEOUT_OC    = 180
RUNS_DIR      = Path(__file__).parent / "runs_pyrag_v3"
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
# Tareas v3: cuerpo de funcion, constantes internas, cross-module
# Cada criterio es un valor que SOLO aparece en el cuerpo del fichero (no firma)
# ---------------------------------------------------------------------------
TASKS = [
    {
        "id": "X1", "type": "cross_module",
        "query": "En query/pipeline.py, que dos funciones exactas importa del modulo security? Dame los nombres exactos de las funciones importadas de security.",
        "criterios": ["validate_query", "log_query", "security", "sanitize", "audit"],
        "ground_truth": "query/pipeline.py importa validate_query de security.sanitize y log_query de security.audit.",
    },
    {
        "id": "X2", "type": "constant",
        "query": "En ingestion/pipeline.py existe una constante llamada CONFIDENCE_MAP. Cuales son los dos pares clave-valor exactos? Dame los valores numericos.",
        "criterios": ["CONFIDENCE_MAP", "HIGH", "0.95", "LOW", "0.60"],
        "ground_truth": "CONFIDENCE_MAP = {'HIGH': 0.95, 'LOW': 0.60}",
    },
    {
        "id": "X3", "type": "prompt_content",
        "query": "En ingestion/extractor.py, CODE_EXTRACTION_PROMPT lista tipos de relacion validos. Cuales son exactamente los tipos de relacion validos para codigo Python?",
        "criterios": ["DEFINE", "LLAMA", "IMPORTA", "HEREDA", "USA", "RETORNA"],
        "ground_truth": "Tipos de relacion validos en CODE_EXTRACTION_PROMPT: DEFINE, LLAMA, IMPORTA, HEREDA, USA, RETORNA.",
    },
    {
        "id": "X4", "type": "logic_detail",
        "query": "En query/router.py, classify_intent() calcula confianza con una formula especifica. Si solo lookup_score > 0, cual es la formula exacta de confidence y cual es el maximo posible?",
        "criterios": ["0.60", "0.15", "min", "0.95", "lookup_score"],
        "ground_truth": "confidence = min(0.60 + lookup_score * 0.15, 0.95). Maximo posible es 0.95.",
    },
    {
        "id": "X5", "type": "hash_detail",
        "query": "En graph/nodes.py, la funcion privada _node_id() genera IDs de nodos. Que algoritmo de hash usa y cual es el formato exacto de la cadena de entrada?",
        "criterios": ["md5", "hashlib", "node_type", "lower", "strip"],
        "ground_truth": "Usa hashlib.md5() sobre f'{node_type}::{name.lower().strip()}' codificado en bytes.",
    },
    {
        "id": "X6", "type": "multi_func",
        "query": "En graph/vector_index.py hay exactamente 3 funciones publicas de busqueda vectorial. Cuales son sus nombres exactos y cual es el valor por defecto del parametro n_results?",
        "criterios": ["neo4j_vector_search", "chromadb_vector_search", "vector_search", "n_results", "5"],
        "ground_truth": "neo4j_vector_search(query, n_results=5), chromadb_vector_search(query, n_results=5), vector_search(query, n_results=5).",
    },
    {
        "id": "X7", "type": "cache_detail",
        "query": "En cache/redis_cache.py, cache_result() tiene un parametro opcional para el tiempo de vida. Cual es ese parametro, su valor por defecto y que constante de config usa si no se especifica?",
        "criterios": ["ttl", "None", "CACHE_L3_TTL", "cache_result", "setex"],
        "ground_truth": "cache_result(query, result, ttl=None). Si ttl es None usa config.CACHE_L3_TTL via client.setex().",
    },
    {
        "id": "X8", "type": "dict_fields",
        "query": "En security/audit.py, log_query() construye un diccionario entry que guarda en el log. Lista exactamente los campos del diccionario (claves exactas).",
        "criterios": ["ts", "source", "capa", "latency_s", "cache_hit", "grounding"],
        "ground_truth": "entry = {ts, source, query, capa, tokens, latency_s, cache_hit, grounding}.",
    },
    {
        "id": "X9", "type": "llm_params",
        "query": "En query/capa4.py, synthesize() llama al LLM con parametros especificos. Cuales son los valores exactos de temperature y max_tokens usados en esa llamada?",
        "criterios": ["0.1", "temperature", "512", "max_tokens", "SYSTEM_PROMPT"],
        "ground_truth": "synthesize() usa temperature=0.1 y max_tokens=512. El system message es SYSTEM_PROMPT.",
    },
    {
        "id": "X10", "type": "batch_funcs",
        "query": "En graph/nodes.py existen funciones para operaciones en batch. Cuales son sus nombres exactos y que tipo de parametro reciben?",
        "criterios": ["upsert_nodes_batch", "upsert_relations_batch", "list[dict]", "mark_orphans"],
        "ground_truth": "upsert_nodes_batch(nodes_data: list[dict]), upsert_relations_batch(relations_data: list[dict]), mark_orphans(source_doc_id: str).",
    },
    {
        "id": "X11", "type": "defaults_multi",
        "query": "En ingestion/pipeline.py, ingest_directory() tiene 3 parametros con sus valores por defecto. Cuales son los 3 parametros y sus defaults exactos?",
        "criterios": ["directory", "domain", "default", "recursive", "False"],
        "ground_truth": "ingest_directory(directory: str, domain: str='default', recursive: bool=False).",
    },
    {
        "id": "X12", "type": "return_type",
        "query": "En ingestion/consensus.py, dual_model_extract() retorna un tipo complejo con dos listas. Cual es la firma completa incluyendo parametros y tipo de retorno exacto?",
        "criterios": ["dual_model_extract", "text", "prompt", "None", "tuple", "list[dict]"],
        "ground_truth": "dual_model_extract(text: str, prompt: str=None) -> tuple[list[dict], list[dict]].",
    },
    {
        "id": "X13", "type": "prompt_restriction",
        "query": "En query/capa4.py existe SYSTEM_PROMPT para el LLM. Que formatos de respuesta prohibe explicitamente ese prompt?",
        "criterios": ["JSON", "listas", "numeradas", "plano", "conciso"],
        "ground_truth": "SYSTEM_PROMPT dice: No uses formato JSON ni listas numeradas. Responde en texto plano. Se conciso.",
    },
    {
        "id": "X14", "type": "reserved_set",
        "query": "En graph/nodes.py existe un set llamado _RESERVED con campos protegidos. Cuantos campos contiene y cuales son exactamente?",
        "criterios": ["_RESERVED", "source_doc_id", "source_hash", "status", "created_at", "updated_at"],
        "ground_truth": "_RESERVED = {'id','name','type','aliases','confidence','precision_critical','source_doc_id','source_hash','status','created_at','updated_at'}. 11 campos.",
    },
    {
        "id": "X15", "type": "param_detail",
        "query": "En graph/nodes.py, upsert_node() tiene un parametro aliases. Cual es su tipo exacto de anotacion y su valor por defecto? Tambien nombra el bool parametro que existe junto a aliases.",
        "criterios": ["aliases", "list[str]", "None", "precision_critical", "bool"],
        "ground_truth": "aliases: list[str]=None. El bool parametro es precision_critical: bool=False.",
    },
]

SYSTEM_INSTR = (
    "Eres experto en Python y sistemas de recuperacion de informacion. "
    "Responde en espanol. Da los nombres EXACTOS de funciones, parametros y valores. "
    "Si no tienes informacion especifica del codigo, di 'No tengo acceso a ese fichero'."
)

# ---------------------------------------------------------------------------
# Runner COMPLETO
# ---------------------------------------------------------------------------
def _run_complete(cmd, cwd, env, timeout=180) -> str:
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cwd, env=env,
            timeout=timeout,
        )
        return result.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b"").decode("utf-8", errors="replace")
    except Exception:
        return ""

def _parse_json_output(stdout: str) -> tuple[str, int, int]:
    text_parts = []
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
                    text_parts.append(part.get("text", ""))
            elif ev_type == "assistant":
                for part in ev.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
            elif ev_type == "step_finish":
                toks = ev.get("part", {}).get("tokens", {})
                out = toks.get("output", 0) + toks.get("reasoning", 0)
                inp = toks.get("total", 0) - out
                if inp > 0 or out > 0:
                    total_output += out
                    total_input  += inp
        except Exception:
            pass
    seen = set()
    unique_parts = []
    for part in text_parts:
        if part not in seen:
            seen.add(part)
            unique_parts.append(part)
    return "".join(unique_parts).strip(), total_input, total_output

def _judge_fn(prompt: str) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=5,
    )
    return resp.choices[0].message.content or ""

def judge_with_truth(answer: str, ground_truth: str, criterios: list[str]) -> bool:
    crit_str = ", ".join(criterios)
    prompt = (
        f"Evalua si la siguiente respuesta es correcta.\n\n"
        f"Ground truth:\n{ground_truth}\n\n"
        f"Criterios obligatorios (al menos 60% deben aparecer): {crit_str}\n\n"
        f"Respuesta:\n{answer[:3000]}\n\n"
        "Responde solo 'OK' si la respuesta es correcta. 'FAIL' en caso contrario."
    )
    return "OK" in _judge_fn(prompt).upper()

# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------
def run_leo(query: str, task_id: str) -> dict:
    t0 = time.time()
    stdout = _run_complete(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", query, "--format", "json", "--model", "deepseek/deepseek-chat",
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=TIMEOUT_LEO,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_json_output(stdout)
    if not respuesta and inp == 0:
        time.sleep(2)
        stdout2 = _run_complete(
            [BUN, "run", "--conditions=browser", "src/index.ts",
             "run", query, "--format", "json", "--model", "deepseek/deepseek-chat",
             "--dangerously-skip-permissions"],
            cwd=LEO_SRC, env=_BUN_ENV, timeout=TIMEOUT_LEO,
        )
        respuesta, inp, out = _parse_json_output(stdout2)
        latency = round(time.time() - t0, 3)
    (RUNS_DIR / f"leo_{task_id}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:500],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8")
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
    stdout = _run_complete(
        ["wsl", "-d", "Ubuntu", "bash", "-c", bash_cmd],
        cwd=None, env=env, timeout=TIMEOUT_OC,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_json_output(stdout)
    (RUNS_DIR / f"oc_{task_id}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:500],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8")
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
        inp, out = resp.usage.prompt_tokens, resp.usage.completion_tokens
    except Exception as e:
        answer, inp, out = f"Error: {e}", 0, 0
    return {"respuesta": answer, "input_tokens": inp, "output_tokens": out,
            "latency_s": round(time.time() - t0, 3)}

# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------
def run_task(task: dict) -> dict:
    query, crit, truth = task["query"], task["criterios"], task["ground_truth"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_leo = ex.submit(run_leo, query, task["id"])
        f_oc  = ex.submit(run_opencode_wsl, query, task["id"])
        f_nc  = ex.submit(run_no_ctx, query)
        r_leo, r_oc, r_nc = f_leo.result(), f_oc.result(), f_nc.result()

    def _score(r):
        ans = r["respuesta"]
        return {
            "tokens":   r["input_tokens"] + r["output_tokens"],
            "latency":  r["latency_s"],
            "criteria": score_answer(ans, crit)["score"] if ans else 0.0,
            "judge":    judge_with_truth(ans, truth, crit) if ans else False,
            "answer":   ans[:300],
        }
    return {"id": task["id"], "type": task["type"], "query": query,
            "leo": _score(r_leo), "opencode": _score(r_oc), "no_ctx": _score(r_nc)}

def compute_and_print(results: list[dict], label: str = "") -> dict:
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
    m_data = {
        "n_tasks": n, "total_tokens": total,
        "latency": {m: round(lat[m], 2) for m in modes},
        "avg_criteria": {m: round(avg_crit[m], 3) for m in modes},
        "judge_ok": judge,
        "leo_vs_oc_criteria":    round(avg_crit["leo"] - avg_crit["opencode"], 3),
        "leo_vs_noctx_criteria": round(avg_crit["leo"] - avg_crit["no_ctx"], 3),
        "leo_judge_vs_oc":       judge["leo"] - judge["opencode"],
        "leo_judge_vs_noctx":    judge["leo"] - judge["no_ctx"],
    }
    W = 119
    print("\n" + "=" * W)
    print(f"  BENCHMARK v3 EXIGENTE — leo-code KC-RAG vs opencode CLI  {label}")
    print(f"  Target: {LEO_REPO} | 15 tareas | Criterios: cuerpo func + cross-module")
    print("=" * W)
    tk, lk, ac, jk = m_data["total_tokens"], m_data["latency"], m_data["avg_criteria"], m_data["judge_ok"]
    print(f"\n  {'Metrica':<48} {'leo-code':>10} {'opencode':>10} {'no-ctx':>8}")
    print(f"  {'-'*78}")
    print(f"  {'Tokens totales':<48} {tk['leo']:>10,} {tk['opencode']:>10,} {tk['no_ctx']:>8,}")
    print(f"  {'Latencia total (s)':<48} {lk['leo']:>10.1f} {lk['opencode']:>10.1f} {lk['no_ctx']:>8.1f}")
    print(f"  {'Criteria avg':<48} {ac['leo']:>9.1%} {ac['opencode']:>10.1%} {ac['no_ctx']:>8.1%}")
    print(f"  {'LLM judge OK':<48} {jk['leo']:>9}/{n} {jk['opencode']:>9}/{n} {jk['no_ctx']:>6}/{n}")
    print(f"  {'Leo vs opencode (criteria)':<48} {m_data['leo_vs_oc_criteria']:>+10.1%}")
    print(f"  {'Leo vs no-ctx   (criteria)':<48} {m_data['leo_vs_noctx_criteria']:>+10.1%}")
    print(f"  {'Leo vs opencode (judge)':<48} {m_data['leo_judge_vs_oc']:>+10}")
    print()
    print(f"  {'ID':<6} {'Tipo':<16} {'Pregunta':<40} {'LEOc':>5} {'OCc':>5} {'NCc':>5} {'LEOj':>5} {'OCj':>5} {'LEOtok':>8} {'OCtok':>8}")
    print(f"  {'-'*107}")
    for r in results:
        qshort = r["query"][:38]
        lc = f"{r['leo']['criteria']:.0%}"
        oc = f"{r['opencode']['criteria']:.0%}"
        nc = f"{r['no_ctx']['criteria']:.0%}"
        lj = "OK" if r["leo"]["judge"] else "--"
        oj = "OK" if r["opencode"]["judge"] else "--"
        print(f"  {r['id']:<6} {r['type']:<16} {qshort:<40} {lc:>5} {oc:>5} {nc:>5} {lj:>5} {oj:>5} {r['leo']['tokens']:>8,} {r['opencode']['tokens']:>8,}")
    print()
    leo_wins_oc   = m_data["leo_vs_oc_criteria"] > 0
    leo_wins_nc   = m_data["leo_vs_noctx_criteria"] > 0
    leo_judge_win = m_data["leo_judge_vs_oc"] >= 0
    print(f"  --- Resultado ---")
    print(f"  Leo > opencode criteria: {'SI' if leo_wins_oc else 'NO'} ({m_data['leo_vs_oc_criteria']:+.1%})")
    print(f"  Leo > no-ctx criteria:   {'SI' if leo_wins_nc else 'NO'} ({m_data['leo_vs_noctx_criteria']:+.1%})")
    print(f"  Leo >= opencode judge:   {'SI' if leo_judge_win else 'NO'} ({m_data['leo_judge_vs_oc']:+d}/15)")
    all_win = leo_wins_oc and leo_wins_nc and leo_judge_win
    print(f"  LEO GANA TODO:           {'[WIN]' if all_win else '[FAIL]'}")
    return {**m_data, "tasks": results, "leo_wins_all": all_win}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    print(f"\n[{ts}] Python RAG Benchmark v3: {len(TASKS)} tareas | leo-code vs opencode")
    print(f"  15 tareas de alta exigencia: cuerpo de funcion, cross-module, constantes")
    print(f"  Target: {LEO_REPO}")

    try:
        r = httpx.get(f"{SIDECAR}/health", timeout=5).json()
        print(f"  KC-RAG sidecar: {r}")
    except Exception as e:
        print(f"  KC-RAG ERROR: {e}")
        sys.exit(1)
    try:
        ri = httpx.post(f"{SIDECAR}/index", json={"repo_path": LEO_REPO}, timeout=60).json()
        print(f"  [index] KC-RAG: {ri}")
    except Exception as e:
        print(f"  [index] ERROR: {e}")

    import subprocess as _sp
    try:
        ov = _sp.run(["wsl", "-d", "Ubuntu", "opencode", "--version"],
                     capture_output=True, text=True, timeout=10).stdout.strip()
        print(f"  opencode WSL: {ov}")
    except Exception as e:
        print(f"  opencode WSL: ERROR {e}")

    print(f"\n  [Benchmark] {len(TASKS)} tareas x 3 modos en paralelo (subprocess.run, timeout=180s)...")
    results = []
    with ThreadPoolExecutor(max_workers=len(TASKS)) as ex:
        futs = {ex.submit(run_task, t): t for t in TASKS}
        for fut in as_completed(futs):
            r = fut.result()
            lj = "OK" if r["leo"]["judge"] else "--"
            oj = "OK" if r["opencode"]["judge"] else "--"
            print(f"  [done] {r['id']} ({r['type']}) leo={r['leo']['criteria']:.0%}({lj},{r['leo']['tokens']}tok) oc={r['opencode']['criteria']:.0%}({oj},{r['opencode']['tokens']}tok)")
            results.append(r)
    results.sort(key=lambda r: r["id"])

    m = compute_and_print(results, label=f"[{ts}]")
    out_path = Path(__file__).parent / "pyrag_v3_results.json"
    out_path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out_path}")
    print(f"  LEO_WINS_ALL: {m['leo_wins_all']}")
    return m

if __name__ == "__main__":
    m = main()
    sys.exit(0 if m["leo_wins_all"] else 1)
