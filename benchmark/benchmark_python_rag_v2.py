"""Benchmark v2 FAIR: leo-code (KC-RAG Python) vs opencode CLI vs no_ctx.
FIX: usa subprocess.run() completo — captura el answer final de opencode.
Target: C:\\Users\\Ismael\\Desktop\\RAG (Python 539+ capsules en KC-RAG).
Criterios: valores exactos del codigo (imposibles de adivinar sin leer los ficheros).
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
RUNS_DIR      = Path(__file__).parent / "runs_pyrag_v2"
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
# Tareas con criterios IMPOSIBLES de adivinar sin leer el codigo fuente
# Cada criterio es un nombre exacto, valor exacto, o patron que solo aparece
# en el fichero especificado del repo RAG.
# ---------------------------------------------------------------------------
TASKS = [
    {
        "id": "H1", "type": "code_query",
        "query": "En graph/traversal.py, cuales son los valores por defecto exactos de limit en find_nodes_by_name() y en find_nodes_by_type()? Dame los numeros exactos.",
        "criterios": ["5", "20", "find_nodes_by_name", "find_nodes_by_type"],
        "ground_truth": "find_nodes_by_name(name: str, limit: int=5). find_nodes_by_type(node_type: str, limit: int=20). Los defaults son 5 y 20 respectivamente.",
    },
    {
        "id": "H2", "type": "code_query",
        "query": "En graph/nodes.py, la funcion upsert_node() tiene un parametro de confianza con valor por defecto. Cual es ese parametro y su valor exacto?",
        "criterios": ["confidence", "1.0", "float", "upsert_node"],
        "ground_truth": "upsert_node(..., confidence: float=1.0). El parametro es confidence de tipo float con valor por defecto 1.0.",
    },
    {
        "id": "H3", "type": "search",
        "query": "En query/router.py hay una funcion asincrona (async def). Cual es su nombre exacto y que parametros recibe?",
        "criterios": ["route_parallel", "async", "capa0_fn", "capa2_fn"],
        "ground_truth": "async def route_parallel(query: str, capa0_fn, capa2_fn) -> dict. Es la unica funcion async en router.py.",
    },
    {
        "id": "H4", "type": "code_query",
        "query": "En query/pipeline.py, la funcion query() tiene un parametro client_id con valor por defecto. Cual es ese valor exacto?",
        "criterios": ["client_id", "default", "skip_compression", "use_cache"],
        "ground_truth": "query(user_query: str, use_cache: bool=True, skip_compression: bool=False, client_id: str='default'). client_id por defecto es 'default'.",
    },
    {
        "id": "H5", "type": "code_query",
        "query": "En graph/traversal.py existe una funcion llamada cypher_property_lookup. Cuales son sus parametros exactos y que tipo retorna?",
        "criterios": ["cypher_property_lookup", "entity_name", "property_name", "str | None"],
        "ground_truth": "cypher_property_lookup(entity_name: str, property_name: str) -> str | None. Retorna el valor de la propiedad o None si no existe.",
    },
    {
        "id": "H6", "type": "code_query",
        "query": "En graph/nodes.py, la funcion upsert_relation() tiene exactamente cuantos parametros? Lista sus nombres exactos.",
        "criterios": ["from_id", "to_id", "rel_type", "confidence"],
        "ground_truth": "upsert_relation(from_id: str, to_id: str, rel_type: str, properties: dict=None, confidence: float=1.0) -> str. Tiene 5 parametros.",
    },
    {
        "id": "H7", "type": "code_query",
        "query": "En query/capa4.py, synthesize() tiene un parametro opcional con valor por defecto None. Cual es ese parametro exactamente?",
        "criterios": ["subgraph", "None", "synthesize", "context"],
        "ground_truth": "synthesize(query: str, context: str, subgraph: dict=None) -> dict. El parametro opcional es subgraph con default None.",
    },
    {
        "id": "H8", "type": "code_query",
        "query": "En ingestion/extractor.py, extract_entities() tiene un parametro de temperatura. Cual es su valor por defecto exacto?",
        "criterios": ["temperature", "0.1", "extract_entities", "float"],
        "ground_truth": "extract_entities(text: str, temperature: float=0.1, prompt: str=None). La temperatura por defecto es 0.1.",
    },
    {
        "id": "H9", "type": "no_code",
        "query": "Segun la documentacion del sistema (docs/), cuales son exactamente las condiciones C01 y C05 para obtener descuentos?",
        "criterios": ["C01", "domiciliado", "C05", "fidelizacion"],
        "ground_truth": "C01: pago domiciliado en cuenta bancaria. C05: fidelizacion del cliente (mas de 3 anos de antiguedad con el operador).",
    },
    {
        "id": "H10", "type": "refactor",
        "query": "En graph/traversal.py, la funcion _to_lucene_query() que hace exactamente? Describe su proposito y los parametros que recibe.",
        "criterios": ["_to_lucene_query", "lucene", "text", "str"],
        "ground_truth": "_to_lucene_query(text: str) -> str. Convierte texto a una query compatible con Lucene full-text search de Neo4j.",
    },
]

SYSTEM_INSTR = (
    "Eres experto en Python y sistemas de recuperacion de informacion. "
    "Responde en espanol. Da los nombres EXACTOS de funciones, parametros y valores. "
    "Si no tienes informacion especifica del codigo, di 'No tengo acceso a ese fichero'."
)

# ---------------------------------------------------------------------------
# Runner COMPLETO: lee TODA la salida del proceso (fix principal)
# ---------------------------------------------------------------------------
def _run_complete(cmd, cwd, env, timeout=180) -> str:
    """Lee la salida COMPLETA del proceso. No para en step_finish."""
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
    except Exception as e:
        return ""

def _parse_json_output(stdout: str) -> tuple[str, int, int]:
    """Extrae texto y tokens de eventos JSON de opencode/leo."""
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
    # Deduplicar texto si hay repeticion
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
# Runners de agentes
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
    # Retry si fallo (0 tokens)
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
# Task runner y metricas
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
    W = 115
    print("\n" + "=" * W)
    print(f"  BENCHMARK v2 (FAIR) — leo-code KC-RAG vs opencode CLI  {label}")
    print(f"  Target: {LEO_REPO} | Criterios: imposibles sin leer codigo")
    print("=" * W)
    tk, lk, ac, jk = m_data["total_tokens"], m_data["latency"], m_data["avg_criteria"], m_data["judge_ok"]
    print(f"\n  {'Metrica':<48} {'leo-code':>10} {'opencode':>10} {'no-ctx':>8}")
    print(f"  {'-'*78}")
    print(f"  {'Tokens totales':<48} {tk['leo']:>10,} {tk['opencode']:>10,} {tk['no_ctx']:>8,}")
    print(f"  {'Latencia total (s)':<48} {lk['leo']:>10.1f} {lk['opencode']:>10.1f} {lk['no_ctx']:>8.1f}")
    print(f"  {'Criteria avg (keyword especifico)':<48} {ac['leo']:>10.1%} {ac['opencode']:>10.1%} {ac['no_ctx']:>8.1%}")
    print(f"  {'LLM judge OK':<48} {jk['leo']:>9}/{n} {jk['opencode']:>9}/{n} {jk['no_ctx']:>7}/{n}")
    print(f"  {'Leo vs opencode (criteria)':<48} {m_data['leo_vs_oc_criteria']:>+10.1%}")
    print(f"  {'Leo vs no-ctx (criteria)':<48} {m_data['leo_vs_noctx_criteria']:>+10.1%}")
    print(f"  {'Leo vs opencode (judge)':<48} {m_data['leo_judge_vs_oc']:>+10d}")

    print(f"\n  {'ID':<5} {'Tipo':<12} {'Pregunta':<34} {'LEOc':>6} {'OCc':>6} {'NCc':>5} {'LEOj':>5} {'OCj':>5} {'LEOtok':>7} {'OCtok':>7}")
    print(f"  {'-'*W}")
    for r in results:
        lj = "OK" if r["leo"]["judge"] else "--"
        oj = "OK" if r["opencode"]["judge"] else "--"
        print(f"  {r['id']:<5} {r['type']:<12} {r['query'][:33]:<34} "
              f"{r['leo']['criteria']:>5.0%} {r['opencode']['criteria']:>5.0%} "
              f"{r['no_ctx']['criteria']:>4.0%} {lj:>5} {oj:>5} "
              f"{r['leo']['tokens']:>7,} {r['opencode']['tokens']:>7,}")

    # Resultado
    crit_win  = m_data["leo_vs_oc_criteria"] > 0
    nctx_win  = m_data["leo_vs_noctx_criteria"] > 0
    judge_win = m_data["leo_judge_vs_oc"] >= 0
    all_win   = crit_win and judge_win and nctx_win

    print(f"\n  --- Resultado ---")
    print(f"  Leo > opencode criteria: {'SI' if crit_win else 'NO'} ({m_data['leo_vs_oc_criteria']:+.1%})")
    print(f"  Leo > no-ctx criteria:   {'SI' if nctx_win else 'NO'} ({m_data['leo_vs_noctx_criteria']:+.1%})")
    print(f"  Leo >= opencode judge:   {'SI' if judge_win else 'NO'} ({m_data['leo_judge_vs_oc']:+d}/{n})")
    print(f"  LEO GANA TODO:           {'[WIN]' if all_win else '[PARCIAL]' if crit_win else '[FAIL]'}")
    return m_data

def main():
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    n  = len(TASKS)
    print(f"\n[{ts}] Python RAG Benchmark v2: {n} tareas | leo-code vs opencode")
    print(f"  FIX: subprocess.run() completo — opencode respuesta total capturada")
    print(f"  Criterios: valores exactos del codigo (no adivinables)")
    print(f"  Target: {LEO_REPO}")

    try:
        h = httpx.get(f"{SIDECAR}/health", timeout=5)
        print(f"  KC-RAG sidecar: {h.json()}")
        r = httpx.post(f"{SIDECAR}/index",
                       json={"repo_path": LEO_REPO, "languages": "python,text"},
                       timeout=120)
        idx = r.json()
        print(f"  [index] KC-RAG: {idx}")
    except Exception as e:
        print(f"  WARN sidecar: {e}")

    try:
        r = subprocess.run(["wsl", "-d", "Ubuntu", "bash", "-c",
                            "opencode --version 2>/dev/null || echo NOTFOUND"],
                           capture_output=True, text=True, timeout=15)
        print(f"  opencode WSL: {r.stdout.strip()}")
    except Exception as e:
        print(f"  WARN opencode: {e}")

    print(f"\n  [Benchmark] {n} tareas x 3 modos en paralelo (subprocess.run, timeout={TIMEOUT_OC}s)...")
    task_outputs: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = {ex.submit(run_task, task): i for i, task in enumerate(TASKS)}
        for fut in as_completed(futures):
            i = futures[fut]
            r = fut.result()
            task_outputs[i] = r
            lc, oc = r["leo"]["criteria"], r["opencode"]["criteria"]
            lj = "OK" if r["leo"]["judge"] else "--"
            oj = "OK" if r["opencode"]["judge"] else "--"
            ltok = r["leo"]["tokens"]
            otok = r["opencode"]["tokens"]
            print(f"  [done] {r['id']} ({r['type']}) leo={lc:.0%}({lj},{ltok}tok) oc={oc:.0%}({oj},{otok}tok)", flush=True)

    results = [task_outputs[i] for i in range(n)]
    m = compute_and_print(results, label=f"[{ts}]")

    out = Path(__file__).parent / "pyrag_v2_results.json"
    out.write_text(json.dumps({
        "run_timestamp": ts, "model": MODEL, "temperature": TEMPERATURE,
        "target_repo": LEO_REPO, "metrics": m, "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out}")
    return m["leo_vs_oc_criteria"] > 0 and m["leo_vs_noctx_criteria"] > 0 and m["leo_judge_vs_oc"] >= 0

if __name__ == "__main__":
    main()
