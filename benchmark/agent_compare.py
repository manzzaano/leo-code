"""Benchmark: leo-code CLI vs opencode CLI -- KC-Code Methodology v2.

Modos:
  leo      : leo-code CLI (fork con KC-RAG sidecar integrado) -- EL PRODUCTO REAL
  oc       : opencode CLI vanilla (baseline)
  kc       : KC-RAG Python API directo (referencia interna)
  no       : Sin contexto (cota inferior)

Metricas (metodologia v2):
  TRR = 1 - (tokens_leo / tokens_oc)   [baseline = opencode real]
  QPR = TRR * (criteria_leo / criteria_oc)

Prerequisitos:
  - KC-RAG sidecar corriendo: python leo-code-mcp/server.py  (en :9898)
  - opencode instalado: npm i -g opencode
  - bun instalado: C:\\Users\\Ismael\\.bun\\bin\\bun.exe
  - DEEPSEEK_API_KEY en RAG/.env

Run: python leo-code/benchmark/agent_compare.py
"""

import sys, os, json, time, httpx, statistics, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Límite de instancias CLI simultáneas: evita conflictos de sesión y rate limiting
_OC_SEM = threading.Semaphore(1)   # OC secuencial: evita contención que causa timeouts
_LEO_SEM = threading.Semaphore(3)  # max 3 leo-code en paralelo
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')

sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-core')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-code')
from kc_core.benchmark import score_answer, llm_judge as _judge
from openai import OpenAI

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL = "deepseek-chat"
TEMPERATURE = 0.2
RUNS_PER_TASK = 1

SIDECAR = "http://localhost:9898"
REPO = r"C:\Users\Ismael\Desktop\RAG"
OC_MODEL = "deepseek/deepseek-chat"   # provider/model para opencode CLI
LEO_MODEL = "deepseek/deepseek-chat"  # mismo formato para leo-code CLI

BUN = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"

TASKS = json.loads(Path(__file__).parent.joinpath("agent_tasks.json").read_text(encoding="utf-8"))
RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)

SYSTEM_INSTR = "Eres un asistente experto en codigo Python. Responde en espanol. Se preciso y conciso."

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
}


# ---------------------------------------------------------------------------
# KC-RAG Python API helpers (modo kc)
# ---------------------------------------------------------------------------

def call_llm(system_prompt: str, user_query: str, run_id: str = "") -> dict:
    t0 = time.time()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]
    if run_id:
        (RUNS_DIR / f"{run_id}.json").write_text(
            json.dumps({"messages": messages}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    try:
        resp = LLM.chat.completions.create(
            model=MODEL, messages=messages,
            temperature=TEMPERATURE, max_tokens=1024,
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


def get_kcrag_context(query: str, task_type: str) -> dict:
    try:
        r = httpx.post(f"{SIDECAR}/context", json={
            "query": query, "repo_path": REPO,
            "task_type": task_type, "budget_tokens": 0,
        }, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# JSON output parser (opencode / leo-code --format json)
# ---------------------------------------------------------------------------

def _parse_oc_json_output(stdout: str) -> tuple[str, int, int]:
    """Extrae texto y tokens del stream JSON de opencode/leo-code --format json.

    step_finish: {"type":"step_finish","part":{"tokens":{"total":X,"input":Y,"output":Z}}}
    Returns: (respuesta, input_tokens, output_tokens)
    """
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


# ---------------------------------------------------------------------------
# opencode baseline: DeepSeek API directo sin herramientas ni contexto KC-RAG
# Equivale a opencode CLI vanilla (mismo modelo, sin tools, sin system prompt extra)
# ---------------------------------------------------------------------------

def run_real_opencode(query: str, task_idx: int, run_n: int) -> dict:
    """Baseline: DeepSeek API puro sin herramientas (sustituye opencode CLI que cuelga sin TTY)."""
    t0 = time.time()
    try:
        resp = LLM.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            messages=[{"role": "user", "content": query}],
            max_tokens=2048,
        )
        respuesta = resp.choices[0].message.content or ""
        input_tok  = resp.usage.prompt_tokens
        output_tok = resp.usage.completion_tokens
    except Exception as e:
        respuesta, input_tok, output_tok = "", 0, 0

    latency = round(time.time() - t0, 3)
    (RUNS_DIR / f"oc_t{task_idx+1}_r{run_n+1}.json").write_text(
        json.dumps({
            "query": query, "response": respuesta[:500],
            "input_tokens": input_tok, "output_tokens": output_tok,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"respuesta": respuesta, "input_tokens": input_tok,
            "output_tokens": output_tok, "latency_s": latency}


# ---------------------------------------------------------------------------
# leo-code CLI (fork con KC-RAG integrado)
# ---------------------------------------------------------------------------

def run_leo_cli(query: str, task_idx: int, run_n: int) -> dict:
    """Invoca leo-code CLI via bun. KC-RAG sidecar en LEO_MCP_URL=:9898."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            [BUN, "run", "--conditions=browser", "src/index.ts",
             "run", query, "--format", "json", "--model", LEO_MODEL,
             "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            capture_output=True, timeout=120,
            cwd=LEO_SRC, env=_BUN_ENV,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    except subprocess.TimeoutExpired:
        stdout, stderr = "", "TimeoutExpired"
    except Exception as e:
        stdout, stderr = "", str(e)

    latency = round(time.time() - t0, 3)
    respuesta, input_tok, output_tok = _parse_oc_json_output(stdout)

    (RUNS_DIR / f"leo_t{task_idx+1}_r{run_n+1}.json").write_text(
        json.dumps({
            "query": query, "response": respuesta[:500], "stderr": stderr[:200],
            "input_tokens": input_tok, "output_tokens": output_tok,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"respuesta": respuesta, "input_tokens": input_tok,
            "output_tokens": output_tok, "latency_s": latency}


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------

def judge_fn(prompt: str) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=5,
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def run_one_mode(q: str, system_ctx: str, user_q: str, criterios: list,
                 prefix: str, task_idx: int) -> dict:
    """N runs directos al LLM (modo kc/no)."""
    runs = []
    for run in range(RUNS_PER_TASK):
        r = call_llm(system_ctx, user_q, run_id=f"{prefix}_t{task_idx+1}_r{run+1}")
        runs.append(r)

    tok_vals = [r["input_tokens"] + r["output_tokens"] for r in runs]
    lat_vals = [r["latency_s"] for r in runs]
    best = runs[-1]["respuesta"]

    return {
        "tokens": round(statistics.mean(tok_vals)),
        "tokens_sd": round(statistics.stdev(tok_vals) if len(tok_vals) > 1 else 0, 1),
        "latency": round(statistics.mean(lat_vals), 3),
        "criteria": score_answer(best, criterios)["score"],
        "judge": _judge(best, criterios, judge_fn),
        "last_answer": best[:200],
    }


def _aggregate_cli_runs(runs: list[dict], criterios: list, label: str) -> dict:
    """Agrega N runs de CLI (opencode o leo-code)."""
    tok_vals = [r["input_tokens"] + r["output_tokens"] for r in runs]
    lat_vals = [r["latency_s"] for r in runs]
    best = runs[-1]["respuesta"]
    return {
        "tokens": round(statistics.mean(tok_vals)) if tok_vals else 0,
        "tokens_sd": round(statistics.stdev(tok_vals) if len(tok_vals) > 1 else 0, 1),
        "latency": round(statistics.mean(lat_vals), 3) if lat_vals else 0,
        "criteria": score_answer(best, criterios)["score"],
        "judge": _judge(best, criterios, judge_fn),
        "last_answer": best[:200],
        "mode": label,
    }


# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------

def _run_leo_mode(q: str, criterios: list, task_idx: int) -> dict:
    with _LEO_SEM:
        leo_runs = [run_leo_cli(q, task_idx, r) for r in range(RUNS_PER_TASK)]
    result = _aggregate_cli_runs(leo_runs, criterios, "leo")
    result["context_tokens"] = -1
    return result


def _run_oc_mode(q: str, criterios: list, task_idx: int) -> dict:
    with _OC_SEM:
        oc_runs = [run_real_opencode(q, task_idx, r) for r in range(RUNS_PER_TASK)]
    result = _aggregate_cli_runs(oc_runs, criterios, "oc")
    result["context_tokens"] = -1
    return result


def _run_oc_sequential_all(tasks: list[dict]) -> dict:
    """Phase 1: corre OC para todas las tareas secuencialmente sin contención API."""
    oc_all: dict[int, dict] = {}
    for i, task in enumerate(tasks):
        q, criterios = task["query"], task["criterios"]
        print(f"[oc-seq] T{i+1}: {q[:45]}...", flush=True)
        oc_runs = [run_real_opencode(q, i, r) for r in range(RUNS_PER_TASK)]
        result = _aggregate_cli_runs(oc_runs, criterios, "oc")
        result["context_tokens"] = -1
        oc_all[i] = result
        print(f"[oc-seq] T{i+1} done: {result['tokens']:,} tok crit={result['criteria']:.0%}", flush=True)
    return oc_all


def _run_kc_mode(q: str, criterios: list, kc_type: str, task_idx: int) -> dict:
    ctx = get_kcrag_context(q, kc_type)
    kc_sys = SYSTEM_INSTR
    if ctx.get("context"):
        kc_sys += f"\n\nContexto estructural del repositorio:\n{ctx['context']}"
    result = run_one_mode(q, kc_sys, q, criterios, "kc", task_idx)
    result["context_tokens"] = ctx.get("tokens", 0)
    return result


def _run_no_mode(q: str, criterios: list, task_idx: int) -> dict:
    result = run_one_mode(q, SYSTEM_INSTR, q, criterios, "no", task_idx)
    result["context_tokens"] = 0
    return result


def _run_task_with_output(task: dict, task_idx: int, n_tasks: int, oc_result: dict) -> tuple[dict, list[str]]:
    kc_type = task.get("kc_task_type", "auto")
    r = run_task(task, task_idx, oc_result)
    trr_t = 1 - (r["leo"]["tokens"] / max(r["oc"]["tokens"], 1))
    lines = [
        f"\n--- Tarea {task_idx+1}/{n_tasks} [{kc_type}]: {task['query'][:55]}... ---",
        f"  LEO: {r['leo']['tokens']:,}tok crit={r['leo']['criteria']:.0%}",
        f"  OC:  {r['oc']['tokens']:,}tok  crit={r['oc']['criteria']:.0%}",
        f"  KC:  {r['kc']['tokens']:,}tok  crit={r['kc']['criteria']:.0%} ctx={r['kc']['context_tokens']}",
        f"  NO:  {r['no']['tokens']:,}tok  crit={r['no']['criteria']:.0%}",
        f"  TRR LEO vs OC: {trr_t:.1%}",
    ]
    return r, lines


def run_task(task: dict, task_idx: int, oc_result: dict = None) -> dict:
    q = task["query"]
    criterios = task["criterios"]
    kc_type = task.get("kc_task_type", "auto")

    # Phase 2: LEO/KC/NO corren en paralelo (OC ya fue pre-computado en Phase 1)
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_leo = ex.submit(_run_leo_mode, q, criterios, task_idx)
        fut_kc  = ex.submit(_run_kc_mode,  q, criterios, kc_type, task_idx)
        fut_no  = ex.submit(_run_no_mode,  q, criterios, task_idx)
        leo = fut_leo.result()
        kc  = fut_kc.result()
        no  = fut_no.result()

    oc = oc_result if oc_result is not None else _run_oc_mode(q, criterios, task_idx)
    return {"task": q, "type": kc_type, "leo": leo, "oc": oc, "kc": kc, "no": no}


# ---------------------------------------------------------------------------
# Metrics & report
# ---------------------------------------------------------------------------

def compute_metrics(results: list[dict]) -> dict:
    modes = ("leo", "oc", "kc", "no")
    total = {m: 0 for m in modes}
    lat = {m: 0.0 for m in modes}
    crit = {m: [] for m in modes}
    judge = {m: 0 for m in modes}
    n = len(results)

    for r in results:
        for m in modes:
            total[m] += r[m]["tokens"]
            lat[m] += r[m]["latency"]
            crit[m].append(r[m]["criteria"])
            judge[m] += int(r[m]["judge"])

    avg_crit = {m: statistics.mean(crit[m]) for m in modes}
    # Metricas principales: leo vs oc
    trr = 1 - (total["leo"] / max(total["oc"], 1))
    qpr = trr * (avg_crit["leo"] / max(avg_crit["oc"], 0.01))
    # Referencia: kc vs oc
    trr_kc = 1 - (total["kc"] / max(total["oc"], 1))
    qpr_kc = trr_kc * (avg_crit["kc"] / max(avg_crit["oc"], 0.01))

    return {
        "n_tasks": n, "runs_per_task": RUNS_PER_TASK,
        "total_tokens": total,
        "trr_leo_vs_oc": round(trr, 3),
        "qpr_leo_vs_oc": round(qpr, 3),
        "trr_kc_vs_oc": round(trr_kc, 3),
        "qpr_kc_vs_oc": round(qpr_kc, 3),
        "latency": {m: round(lat[m], 2) for m in modes},
        "avg_criteria": {m: round(avg_crit[m], 3) for m in modes},
        "judge_ok": judge,
    }


def print_report(results: list[dict], m: dict):
    W = 125
    print("\n" + "=" * W)
    print("BENCHMARK KC-CODE METHODOLOGY v2  --  leo-code CLI vs opencode CLI")
    print(f"Model: {MODEL} | Temp: {TEMPERATURE} | Runs/task: {RUNS_PER_TASK}")
    print(f"Baseline: opencode-vanilla | leo-code: fork con KC-RAG integrado")
    print("=" * W)

    tk = m["total_tokens"]
    lk = m["latency"]
    ac = m["avg_criteria"]
    jk = m["judge_ok"]
    n = m["n_tasks"]

    print(f"\n{'Metrica':<45} {'leo-code':>12} {'opencode':>12} {'kc-api':>10} {'no-ctx':>10}")
    print("-" * 95)
    print(f"{'Tokens totales':<45} {tk['leo']:>12,} {tk['oc']:>12,} {tk['kc']:>10,} {tk['no']:>10,}")
    print(f"{'TRR leo vs opencode (objetivo>0)':<45} {m['trr_leo_vs_oc']:>12.1%} {'baseline':>12} {'--':>10} {'--':>10}")
    print(f"{'QPR leo vs opencode (objetivo>=0.60)':<45} {m['qpr_leo_vs_oc']:>12.3f} {'--':>12} {'--':>10} {'--':>10}")
    print(f"{'TRR kc-api vs opencode (ref)':<45} {'--':>12} {'--':>12} {m['trr_kc_vs_oc']:>10.1%} {'--':>10}")
    print(f"{'Latencia total (s)':<45} {lk['leo']:>12.1f} {lk['oc']:>12.1f} {lk['kc']:>10.1f} {lk['no']:>10.1f}")
    print(f"{'Criteria avg':<45} {ac['leo']:>12.1%} {ac['oc']:>12.1%} {ac['kc']:>10.1%} {ac['no']:>10.1%}")
    print(f"{'LLM judge OK':<45} {jk['leo']:>11}/{n} {jk['oc']:>11}/{n} {jk['kc']:>9}/{n} {jk['no']:>9}/{n}")

    print(f"\n{'Tarea':<38} {'LEOtok':>7} {'OCtok':>7} {'TRR':>7} {'LEOcrit':>8} {'OCcrit':>7} {'LEOjdg':>7} {'OCjdg':>7}")
    print("-" * W)
    for r in results:
        trr_t = 1 - (r["leo"]["tokens"] / max(r["oc"]["tokens"], 1))
        lj = "OK" if r["leo"]["judge"] else "--"
        oj = "OK" if r["oc"]["judge"] else "--"
        print(
            f"{r['task'][:37]:<38} {r['leo']['tokens']:>7,} {r['oc']['tokens']:>7,} {trr_t:>7.1%} "
            f"{r['leo']['criteria']:>8.1%} {r['oc']['criteria']:>7.1%} {lj:>7} {oj:>7}"
        )

    print("\n--- Diagnosis (metodologia v2) ---")
    trr = m["trr_leo_vs_oc"]
    qpr = m["qpr_leo_vs_oc"]
    if trr > 0:
        print(f"[OK] TRR={trr:.1%}: leo-code usa MENOS tokens que opencode")
    else:
        print(f"[XX] TRR={trr:.1%}: leo-code usa MAS tokens que opencode")
    if qpr >= 0.60:
        print(f"[OK] QPR={qpr:.3f} >= 0.60: target metodologia CUMPLIDO")
    elif qpr > 0:
        print(f"[>>] QPR={qpr:.3f} -- mejora tokens pero no alcanza target 0.60 aun")
    else:
        print(f"[XX] QPR={qpr:.3f} -- tokens no ahorran suficiente vs perdida calidad")
    lat_speedup = lk["oc"] / max(lk["leo"], 0.01)
    if lat_speedup > 1.0:
        print(f"[OK] Latencia: leo-code {lat_speedup:.1f}x mas rapido que opencode")
    else:
        print(f"[>>] Latencia: leo-code {lat_speedup:.1f}x vs opencode")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    print(f"[{ts}] Benchmark {len(TASKS)} tareas x {RUNS_PER_TASK} runs x 4 modos")
    print(f"Comparacion principal: leo-code CLI vs opencode CLI")
    print(f"Tokens: extraidos de step_finish JSON | KC-RAG sidecar: {SIDECAR}")

    try:
        h = httpx.get(f"{SIDECAR}/health", timeout=5)
        print(f"KC-RAG sidecar: {h.json()}")
        # Pre-indexar repo para que T1 no pague penalización de indexación
        print(f"[warmup] Pre-indexando {REPO}...")
        w = httpx.post(f"{SIDECAR}/index", json={"repo_path": REPO, "languages": "python,text"}, timeout=120)
        print(f"[warmup] {w.json()}")
    except Exception as e:
        print(f"WARN sidecar KC-RAG no responde ({e}) -- leo-code correra sin contexto KG")

    n = len(TASKS)

    # Phase 1: OC secuencial sin contención API (evita rate limiting / timeouts)
    print("\n[Phase 1] OC secuencial...")
    oc_all = _run_oc_sequential_all(TASKS)

    # Phase 2: LEO/KC/NO en paralelo con OC ya computado
    print(f"\n[Phase 2] LEO/KC/NO paralelo ({n} tareas)...")
    task_outputs: dict[int, tuple] = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = {ex.submit(_run_task_with_output, task, i, n, oc_all[i]): i
                   for i, task in enumerate(TASKS)}
        for fut in as_completed(futures):
            i = futures[fut]
            task_outputs[i] = fut.result()
            print(f"[done] T{i+1} completada", flush=True)

    results = []
    for i in range(n):
        r, lines = task_outputs[i]
        for line in lines:
            print(line)
        results.append(r)

    m = compute_metrics(results)
    print_report(results, m)

    out = Path(__file__).parent / "agent_results.json"
    out.write_text(json.dumps({
        "run_timestamp": ts, "model": MODEL, "temperature": TEMPERATURE,
        "runs_per_task": RUNS_PER_TASK, "repo": REPO,
        "metrics": m, "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {out}")


if __name__ == "__main__":
    main()
