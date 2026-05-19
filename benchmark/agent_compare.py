"""Benchmark Q&A: leo-code CLI con KC-RAG en tareas de repositorio real.

Modos:
  leo    : leo-code CLI (KC-RAG + DeepSeek) -- EL PRODUCTO
  kc_api : KC-RAG + DeepSeek API directo (referencia interna de eficiencia)
  no_ctx : DeepSeek API sin contexto (cota inferior)

Referencia externa: Claude Code (Sonnet 4.5) ~87.6% SWE-bench / 97.6% HumanEval.
Para benchmark EvalPlus público ver: benchmark/evalplus_bench.py

Prerequisitos:
  - KC-RAG sidecar corriendo: python -m leo_mcp.server  (en :9898)
  - bun instalado: C:\\Users\\Ismael\\.bun\\bin\\bun.exe
  - DEEPSEEK_API_KEY en RAG/.env

Run: python -u benchmark/agent_compare.py
"""

import sys, os, json, time, httpx, statistics, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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

SIDECAR   = "http://localhost:9898"
REPO      = r"C:\Users\Ismael\Desktop\RAG"
LEO_MODEL = "deepseek/deepseek-chat"

BUN     = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"

TASKS    = json.loads(Path(__file__).parent.joinpath("agent_tasks.json").read_text(encoding="utf-8"))
RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)

SYSTEM_INSTR = "Eres un asistente experto en codigo Python. Responde en espanol. Se preciso y conciso."

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
    "LEO_REPO_PATH": REPO,
}


# ---------------------------------------------------------------------------
# Streaming subprocess helper (resuelve el proceso colgado en Windows)
# ---------------------------------------------------------------------------

def _run_cli_streaming(cmd, cwd, env, timeout=120) -> str:
    """Lee stdout hasta detectar step_finish o timeout, luego mata el proceso.

    Usa thread lector para que el timeout funcione incluso si el proceso no escribe nada
    (el loop `for raw in proc.stdout` bloquea indefinidamente sin output en Windows).
    """
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
                # Stop only when agent finishes (reason:stop), not on tool-call steps
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


# ---------------------------------------------------------------------------
# KC-RAG Python API helpers (modo kc_api)
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
# leo-code CLI (fork con KC-RAG integrado)
# ---------------------------------------------------------------------------

def run_leo_cli(query: str, task_idx: int, run_n: int) -> dict:
    """Invoca leo-code CLI via bun con streaming. KC-RAG sidecar en LEO_MCP_URL=:9898."""
    t0 = time.time()
    stdout = _run_cli_streaming(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", query, "--format", "json", "--model", LEO_MODEL,
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=120,
    )
    latency = round(time.time() - t0, 3)
    respuesta, input_tok, output_tok = _parse_oc_json_output(stdout)
    (RUNS_DIR / f"leo_t{task_idx+1}_r{run_n+1}.json").write_text(
        json.dumps({
            "query": query, "response": respuesta[:500],
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
    """N runs directos al LLM (modo kc_api/no_ctx)."""
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
# Task runners (un modo por función)
# ---------------------------------------------------------------------------

def _run_leo_mode(q: str, criterios: list, task_idx: int) -> dict:
    runs = [run_leo_cli(q, task_idx, r) for r in range(RUNS_PER_TASK)]
    result = _aggregate_cli_runs(runs, criterios, "leo")
    result["context_tokens"] = -1
    return result



def _run_kc_api_mode(q: str, criterios: list, kc_type: str, task_idx: int) -> dict:
    ctx = get_kcrag_context(q, kc_type)
    kc_sys = SYSTEM_INSTR
    if ctx.get("context"):
        kc_sys += f"\n\nContexto estructural del repositorio:\n{ctx['context']}"
    result = run_one_mode(q, kc_sys, q, criterios, "kc_api", task_idx)
    result["context_tokens"] = ctx.get("tokens", 0)
    return result


def _run_no_ctx_mode(q: str, criterios: list, task_idx: int) -> dict:
    result = run_one_mode(q, SYSTEM_INSTR, q, criterios, "no_ctx", task_idx)
    result["context_tokens"] = 0
    return result


def _run_task_with_output(task: dict, task_idx: int, n_tasks: int) -> tuple[dict, list[str]]:
    kc_type = task.get("kc_task_type", "auto")
    r = run_task(task, task_idx)
    gain = r["leo"]["criteria"] - r["no_ctx"]["criteria"]
    lines = [
        f"\n--- Tarea {task_idx+1}/{n_tasks} [{kc_type}]: {task['query'][:55]}... ---",
        f"  LEO:    {r['leo']['tokens']:,}tok crit={r['leo']['criteria']:.0%} judge={'OK' if r['leo']['judge'] else '--'}",
        f"  KC-API: {r['kc_api']['tokens']:,}tok crit={r['kc_api']['criteria']:.0%} ctx={r['kc_api']['context_tokens']}",
        f"  No-ctx: {r['no_ctx']['tokens']:,}tok crit={r['no_ctx']['criteria']:.0%}",
        f"  Gain KC-RAG vs no-ctx: {gain:+.0%}",
    ]
    return r, lines


def run_task(task: dict, task_idx: int) -> dict:
    q = task["query"]
    criterios = task["criterios"]
    kc_type = task.get("kc_task_type", "auto")

    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_leo    = ex.submit(_run_leo_mode,    q, criterios, task_idx)
        fut_kc_api = ex.submit(_run_kc_api_mode, q, criterios, kc_type, task_idx)
        fut_no_ctx = ex.submit(_run_no_ctx_mode, q, criterios, task_idx)
        leo    = fut_leo.result()
        kc_api = fut_kc_api.result()
        no_ctx = fut_no_ctx.result()

    return {"task": q, "type": kc_type, "leo": leo, "kc_api": kc_api, "no_ctx": no_ctx}


# ---------------------------------------------------------------------------
# Metrics & report
# ---------------------------------------------------------------------------

def compute_metrics(results: list[dict]) -> dict:
    modes = ("leo", "kc_api", "no_ctx")
    total = {m: 0 for m in modes}
    lat   = {m: 0.0 for m in modes}
    crit  = {m: [] for m in modes}
    judge = {m: 0 for m in modes}
    n = len(results)

    for r in results:
        for m in modes:
            total[m] += r[m]["tokens"]
            lat[m]   += r[m]["latency"]
            crit[m].append(r[m]["criteria"])
            judge[m] += int(r[m]["judge"])

    avg_crit = {m: statistics.mean(crit[m]) for m in modes}
    # gain: leo criteria vs no_ctx criteria (KC-RAG value)
    gain_crit = avg_crit["leo"] - avg_crit["no_ctx"]
    # efficiency: leo vs kc_api (agent overhead)
    overhead = (total["leo"] / max(total["kc_api"], 1)) - 1.0

    return {
        "n_tasks": n, "runs_per_task": RUNS_PER_TASK,
        "total_tokens": total,
        "gain_crit_leo_vs_noctx": round(gain_crit, 3),
        "agent_overhead_vs_kc_api": round(overhead, 3),
        "latency":      {m: round(lat[m], 2) for m in modes},
        "avg_criteria": {m: round(avg_crit[m], 3) for m in modes},
        "judge_ok": judge,
    }


def print_report(results: list[dict], m: dict):
    W = 100
    print("\n" + "=" * W)
    print("BENCHMARK KC-CODE  --  leo-code CLI (KC-RAG) vs kc_api vs no_ctx")
    print(f"Model: {MODEL} | Temp: {TEMPERATURE} | Runs/task: {RUNS_PER_TASK}")
    print(f"Referencia externa: Claude Code ~87.6% SWE-bench / ~88-90% HumanEval+ (ver evalplus_bench.py)")
    print("=" * W)

    tk = m["total_tokens"]
    lk = m["latency"]
    ac = m["avg_criteria"]
    jk = m["judge_ok"]
    n  = m["n_tasks"]

    print(f"\n{'Metrica':<45} {'leo-code':>10} {'kc-api':>10} {'no-ctx':>8}")
    print("-" * 75)
    print(f"{'Tokens totales':<45} {tk['leo']:>10,} {tk['kc_api']:>10,} {tk['no_ctx']:>8,}")
    print(f"{'Overhead agente leo vs kc_api':<45} {m['agent_overhead_vs_kc_api']:>+10.1%} {'baseline':>10} {'--':>8}")
    print(f"{'Latencia total (s)':<45} {lk['leo']:>10.1f} {lk['kc_api']:>10.1f} {lk['no_ctx']:>8.1f}")
    print(f"{'Criteria avg':<45} {ac['leo']:>10.1%} {ac['kc_api']:>10.1%} {ac['no_ctx']:>8.1%}")
    print(f"{'LLM judge OK':<45} {jk['leo']:>9}/{n} {jk['kc_api']:>9}/{n} {jk['no_ctx']:>7}/{n}")
    print(f"{'Gain KC-RAG vs no-ctx (criteria)':<45} {m['gain_crit_leo_vs_noctx']:>+10.1%}")

    print(f"\n{'Tarea':<40} {'LEO':>7} {'KC-API':>8} {'No-ctx':>8} {'LEOc':>6} {'KCc':>6} {'LEOj':>5}")
    print("-" * W)
    for r in results:
        lj = "OK" if r["leo"]["judge"] else "--"
        print(
            f"{r['task'][:39]:<40} {r['leo']['tokens']:>7,} {r['kc_api']['tokens']:>8,} "
            f"{r['no_ctx']['tokens']:>8,} {r['leo']['criteria']:>5.0%} "
            f"{r['kc_api']['criteria']:>5.0%} {lj:>5}"
        )

    print("\n--- Diagnosis ---")
    gain = m["gain_crit_leo_vs_noctx"]
    overhead = m["agent_overhead_vs_kc_api"]
    if gain > 0.05:
        print(f"[OK] KC-RAG mejora criteria {gain:+.0%} vs no-ctx")
    elif gain >= 0:
        print(f"[>>] KC-RAG mejora minima {gain:+.0%} vs no-ctx")
    else:
        print(f"[XX] KC-RAG no mejora criteria {gain:+.0%} vs no-ctx")
    if overhead < 0.50:
        print(f"[OK] Overhead agente leo vs kc_api: {overhead:+.0%} (aceptable)")
    else:
        print(f"[>>] Overhead agente leo vs kc_api: {overhead:+.0%} (alto)")
    leo_crit = ac["leo"]
    if leo_crit >= 0.80:
        print(f"[OK] Leo criteria {leo_crit:.0%} >= 80%")
    else:
        print(f"[>>] Leo criteria {leo_crit:.0%} -- objetivo 80%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    print(f"[{ts}] Benchmark {len(TASKS)} tareas x {RUNS_PER_TASK} runs x 3 modos")
    print(f"Modos: leo-code CLI (KC-RAG) | kc_api directo | no_ctx")
    print(f"Tokens: extraidos de step_finish JSON | KC-RAG sidecar: {SIDECAR}")

    try:
        h = httpx.get(f"{SIDECAR}/health", timeout=5)
        print(f"KC-RAG sidecar: {h.json()}")
        print(f"[warmup] Pre-indexando {REPO}...")
        w = httpx.post(f"{SIDECAR}/index", json={"repo_path": REPO, "languages": "python,text"}, timeout=120)
        print(f"[warmup] {w.json()}")
    except Exception as e:
        print(f"WARN sidecar KC-RAG no responde ({e}) -- leo-code correra sin contexto KG")

    n = len(TASKS)

    print(f"\n[Benchmark] {n} tareas x 3 modos en paralelo...")
    task_outputs: dict[int, tuple] = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = {ex.submit(_run_task_with_output, task, i, n): i
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
