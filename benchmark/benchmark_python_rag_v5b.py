"""Benchmark v5b EXTREME-SEMANTICO: leo-code KC-RAG vs opencode CLI vs no_ctx.
10 tareas de maxima dificultad semantica: flujo cross-module, logica condicional,
comparacion de funciones, lectura de prompts. Sin "reproduce codigo exacto".
Criterios codificados en base64.
"""
import json, os, sys, time, subprocess, statistics, httpx, base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-core')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-code')
from kc_core.benchmark import score_answer
from openai import OpenAI

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM          = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL        = "deepseek-chat"
TEMPERATURE  = 0.2
SIDECAR      = "http://localhost:9898"
BUN          = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC      = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"
LEO_REPO     = r"C:\Users\Ismael\Desktop\RAG"
WSL_REPO     = "/mnt/c/Users/Ismael/Desktop/RAG"
TIMEOUT_LEO  = 240
TIMEOUT_OC   = 240
RUNS_DIR     = Path(__file__).parent / "runs_pyrag_v5b"
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

# Criterios codificados en base64 — v5b extreme semantico
_EVAL_B64 = base64.b64encode(json.dumps({
    "S1": {
        "c": ["validate_query", "get_cached_result", "try_resolve", "route", "route_parallel",
              "asyncio.run", "retrieve_subgraph", "compress", "synthesize", "verify_grounding",
              "cache_result", "log_query"],
        "gt": "Flujo parallel (no cache, intent=parallel): validate_query -> try_resolve (fast-path, falla) -> route (parallel) -> asyncio.run(route_parallel(try_resolve, retrieve_subgraph)) -> compress -> synthesize -> verify_grounding -> cache_result -> log_query."
    },
    "S2": {
        "c": ["-1", "capa", "validation", "error", "0.0", "grounding", "respuesta", "ValueError"],
        "gt": "Si validate_query() lanza ValueError: {respuesta: str(e), evidencia: [], inferencias: [], _meta: {capa: -1, error: 'validation', latency_s: 0}, _grounding: {score: 0.0}}."
    },
    "S3": {
        "c": ["confidence", "1.0", "float", "precision_critical", "False", "bool", "aliases", "None", "list[str]"],
        "gt": "3 parametros opcionales de upsert_node: confidence: float=1.0, precision_critical: bool=False, aliases: list[str]=None."
    },
    "S4": {
        "c": ["JSON", "listas", "numeradas", "plano", "conciso", "porcentajes", "precios", "numeros"],
        "gt": "SYSTEM_PROMPT en capa4.py prohibe: formato JSON y listas numeradas. Exige: texto plano y concision. Pide incluir valores numericos (porcentajes, precios, edades, limites) que justifican la respuesta."
    },
    "S5": {
        "c": ["CASE WHEN", "confidence", "THEN", "ELSE", "e.confidence", "0.9", "0.8"],
        "gt": "Si nodo tiene confidence=0.8 y se hace upsert con confidence=0.9: CASE WHEN 0.9 > 0.8 THEN 0.9 ELSE 0.8 END -> resultado=0.9. La confianza solo sube, nunca baja."
    },
    "S6": {
        "c": ["parametros", "tipo_retorno", "docstring", "lineas_aprox", "module", "props", "Funcion"],
        "gt": "CODE_EXTRACTION_PROMPT: para cada Funcion extrae propiedades: parametros, tipo_retorno, docstring (si existe), lineas_aprox. La entidad es tipo Funcion."
    },
    "S7": {
        "c": ["_get_client", "None", "is_available", "ping", "socket_connect_timeout", "True", "False"],
        "gt": "is_available() -> bool. Llama a _get_client(). Si _get_client() retorna None (Redis no disponible), is_available() retorna False. Si retorna cliente activo, retorna True."
    },
    "S8": {
        "c": ["route", "classify_intent", "tuple", "str", "float", "parallel", "lookup", "relational", "semantic", "code"],
        "gt": "classify_intent(query) retorna tuple(str, float): puede ser lookup/relational/code/semantic. route() llama a classify_intent() y puede retornar adicionalmente 'parallel' si hay ambiguedad. classify_intent tiene 4 posibles intents."
    },
    "S9": {
        "c": ["_grounding", "score", "round", "0.0", "3", "grounding", "result.get"],
        "gt": "log_query() obtiene grounding de result.get('_grounding', {}).get('score', 0.0) y aplica round(valor, 3). El campo en entry es 'grounding'."
    },
    "S10": {
        "c": ["_ingest_python", "ingest_file", ".py", "suffix", "domain", "path"],
        "gt": "ingest_file() llama a _ingest_python(path, domain) cuando el archivo tiene extension .py (Path(path).suffix == '.py'). Pasa el mismo parametro domain."
    },
}).encode()).decode()
_EVAL = json.loads(base64.b64decode(_EVAL_B64).decode())

TASKS = [
    {"id": "S1", "type": "full_flow_parallel",
     "query": "Traza el flujo COMPLETO de query() en query/pipeline.py cuando: use_cache=True pero no hay cache hit, y el routing decide intent==parallel. Lista TODAS las funciones llamadas en orden con sus modulos exactos."},
    {"id": "S2", "type": "error_dict",
     "query": "En query/pipeline.py, cuando validate_query() lanza ValueError, que diccionario exacto devuelve query()? Describe cada campo: respuesta, evidencia, inferencias, _meta (con capa y error), _grounding (con score)."},
    {"id": "S3", "type": "optional_params_full",
     "query": "En graph/nodes.py, upsert_node() tiene exactamente 3 parametros opcionales. Para cada uno indica: nombre exacto, tipo exacto (con anotacion) y valor por defecto exacto."},
    {"id": "S4", "type": "system_prompt_analysis",
     "query": "En query/capa4.py, el SYSTEM_PROMPT da instrucciones al LLM. Describe que formatos prohíbe explicitamente y que tipo de informacion exige incluir en la respuesta."},
    {"id": "S5", "type": "cypher_logic",
     "query": "En graph/nodes.py, el Cypher ON MATCH actualiza la confianza. Si un nodo tiene confidence=0.8 y se llama upsert_node() con confidence=0.9, cual es el valor final? Explica la logica CASE WHEN exacta."},
    {"id": "S6", "type": "prompt_properties",
     "query": "En ingestion/extractor.py, CODE_EXTRACTION_PROMPT especifica que propiedades extraer para entidades tipo Funcion. Lista exactamente las propiedades que debe extraer para cada funcion."},
    {"id": "S7", "type": "is_available_logic",
     "query": "En cache/redis_cache.py, la funcion is_available() determina si Redis esta disponible. Describe su logica: que llama internamente y que retorna cuando Redis no esta accesible?"},
    {"id": "S8", "type": "route_vs_classify",
     "query": "En query/router.py, cual es la diferencia entre route() y classify_intent()? Cuantos valores distintos de intent puede retornar classify_intent() y cuales son? Puede route() retornar un intent que classify_intent() no puede?"},
    {"id": "S9", "type": "audit_data_flow",
     "query": "En security/audit.py, log_query() incluye un campo grounding en el entry. De donde obtiene ese valor exactamente? Que transformacion matematica aplica antes de guardarlo?"},
    {"id": "S10", "type": "conditional_call",
     "query": "En ingestion/pipeline.py, ingest_file() tiene logica condicional para decidir que funcion privada llamar. Bajo que condicion exacta llama a _ingest_python() y que parametros le pasa?"},
]

SYSTEM_INSTR = (
    "Eres experto en Python y arquitectura de software. "
    "Responde en espanol. Da informacion EXACTA del codigo: logica, firmas, valores. "
    "Si no tienes acceso al fichero especifico, di 'No tengo acceso'."
)

def _run_complete(cmd, cwd, env, timeout=240) -> str:
    try:
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=cwd, env=env, timeout=timeout,
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
        f"Criterios (al menos 60% deben aparecer): {crit_str}\n\n"
        f"Respuesta:\n{answer[:4000]}\n\n"
        "Responde solo 'OK' si correcta. 'FAIL' si no."
    )
    return "OK" in _judge_fn(prompt).upper()

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
        json.dumps({"query": query, "response": respuesta[:800],
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
        json.dumps({"query": query, "response": respuesta[:800],
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

def run_task(task: dict) -> dict:
    tid   = task["id"]
    query = task["query"]
    ev    = _EVAL[tid]
    crit, truth = ev["c"], ev["gt"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_leo = ex.submit(run_leo, query, tid)
        f_oc  = ex.submit(run_opencode_wsl, query, tid)
        f_nc  = ex.submit(run_no_ctx, query)
        r_leo, r_oc, r_nc = f_leo.result(), f_oc.result(), f_nc.result()

    def _score(r):
        ans = r["respuesta"]
        return {
            "tokens":   r["input_tokens"] + r["output_tokens"],
            "latency":  r["latency_s"],
            "criteria": score_answer(ans, crit)["score"] if ans else 0.0,
            "judge":    judge_with_truth(ans, truth, crit) if ans else False,
            "answer":   ans[:400],
        }
    return {"id": tid, "type": task["type"], "query": query,
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
    print(f"  BENCHMARK v5b EXTREME-SEMANTICO — leo-code KC-RAG vs opencode CLI  {label}")
    print(f"  Target: {LEO_REPO} | {n} tareas cross-module semanticas | logica, flujo, prompts")
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
    print(f"  {'ID':<5} {'Tipo':<22} {'Pregunta':<36} {'LEOc':>5} {'OCc':>5} {'NCc':>5} {'LEOj':>5} {'OCj':>5} {'LEOtok':>8} {'OCtok':>8}")
    print(f"  {'-'*111}")
    for r in results:
        qshort = r["query"][:34]
        lc = f"{r['leo']['criteria']:.0%}"
        oc = f"{r['opencode']['criteria']:.0%}"
        nc = f"{r['no_ctx']['criteria']:.0%}"
        lj = "OK" if r["leo"]["judge"] else "--"
        oj = "OK" if r["opencode"]["judge"] else "--"
        print(f"  {r['id']:<5} {r['type']:<22} {qshort:<36} {lc:>5} {oc:>5} {nc:>5} {lj:>5} {oj:>5} {r['leo']['tokens']:>8,} {r['opencode']['tokens']:>8,}")
    print()
    leo_wins_oc   = m_data["leo_vs_oc_criteria"] > 0
    leo_wins_nc   = m_data["leo_vs_noctx_criteria"] > 0
    leo_judge_win = m_data["leo_judge_vs_oc"] >= 0
    print(f"  --- Resultado ---")
    print(f"  Leo > opencode criteria: {'SI' if leo_wins_oc else 'NO'} ({m_data['leo_vs_oc_criteria']:+.1%})")
    print(f"  Leo > no-ctx criteria:   {'SI' if leo_wins_nc else 'NO'} ({m_data['leo_vs_noctx_criteria']:+.1%})")
    print(f"  Leo >= opencode judge:   {'SI' if leo_judge_win else 'NO'} ({m_data['leo_judge_vs_oc']:+d}/{n})")
    all_win = leo_wins_oc and leo_wins_nc and leo_judge_win
    print(f"  LEO GANA TODO:           {'[WIN]' if all_win else '[FAIL]'}")
    return {**m_data, "tasks": results, "leo_wins_all": all_win}

def main():
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    n  = len(TASKS)
    print(f"\n[{ts}] Python RAG Benchmark v5b EXTREME-SEMANTICO: {n} tareas | leo-code vs opencode")
    print(f"  Maxima dificultad semantica: flujo parallel, logica cypher, prompts, cross-module")
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

    print(f"\n  [Benchmark] {n} tareas x 3 modos en paralelo (timeout=240s)...")
    results = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(run_task, t): t for t in TASKS}
        for fut in as_completed(futs):
            r = fut.result()
            lj = "OK" if r["leo"]["judge"] else "--"
            oj = "OK" if r["opencode"]["judge"] else "--"
            print(f"  [done] {r['id']} ({r['type']}) leo={r['leo']['criteria']:.0%}({lj},{r['leo']['tokens']}tok) oc={r['opencode']['criteria']:.0%}({oj},{r['opencode']['tokens']}tok)")
            results.append(r)
    results.sort(key=lambda r: r["id"])

    m = compute_and_print(results, label=f"[{ts}]")
    out_path = Path(__file__).parent / "pyrag_v5b_results.json"
    out_path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out_path}")
    print(f"  LEO_WINS_ALL: {m['leo_wins_all']}")
    return m

if __name__ == "__main__":
    m = main()
    sys.exit(0 if m["leo_wins_all"] else 1)
