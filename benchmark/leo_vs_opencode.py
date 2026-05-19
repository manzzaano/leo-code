"""Benchmark exigente: leo-code CLI vs opencode CLI (via WSL Ubuntu)
sobre el codebase TypeScript de packages/leo-code/src.

Modos:
  leo      : leo-code CLI con KC-RAG + CodeGraph (deepseek-chat)
  opencode : opencode CLI via WSL Ubuntu con herramientas nativas grep/read/glob
  no_ctx   : DeepSeek API directo sin contexto (cota inferior)

Metricas:
  - criteria score (keyword match %)
  - LLM judge vs ground_truth (OK/FAIL)
  - tokens totales
  - latencia

Prerequisitos:
  - KC-RAG sidecar corriendo en :9898 (python -m leo_mcp.server)
  - opencode instalado en WSL Ubuntu (npm install -g opencode-ai)
  - DEEPSEEK_API_KEY en RAG/.env
  - bun en C:\\Users\\Ismael\\.bun\\bin\\bun.exe

Run: python -u benchmark/leo_vs_opencode.py
"""

import sys, os, json, time, httpx, statistics, subprocess, threading
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
MODEL = "deepseek-chat"
TEMPERATURE = 0.2
RUNS_PER_TASK = 1
TIMEOUT_LEO = 150
TIMEOUT_OC  = 180

SIDECAR    = "http://localhost:9898"
LEO_MODEL  = "deepseek/deepseek-chat"
# leo-code se ejecuta con KC-RAG apuntando al repo TypeScript propio
LEO_REPO   = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"
# WSL path del mismo repo
WSL_REPO   = "/mnt/c/Users/Ismael/Desktop/leo-code/packages/leo-code"

BUN     = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"

TASKS_FILE = Path(__file__).parent / "leo_vs_opencode_tasks.json"
TASKS = json.loads(TASKS_FILE.read_text(encoding="utf-8"))

RUNS_DIR = Path(__file__).parent / "runs_leovoc"
RUNS_DIR.mkdir(exist_ok=True)

SYSTEM_INSTR = (
    "Eres un asistente experto en TypeScript y arquitectura de software. "
    "Responde en espanol. Se preciso y conciso."
)

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
    "LEO_REPO_PATH": LEO_REPO,
}

# WSLENV transmite estas vars al entorno de Ubuntu sin conversion de rutas
_WSL_ENV = {
    **os.environ,
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "WSLENV": "DEEPSEEK_API_KEY/u:OC_QUERY/u",
}


# ---------------------------------------------------------------------------
# Streaming subprocess helper
# ---------------------------------------------------------------------------

def _run_cli_streaming(cmd, cwd, env, timeout=120) -> str:
    """Lee stdout hasta step_finish o timeout, luego mata el proceso."""
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


# ---------------------------------------------------------------------------
# JSON output parser (opencode / leo-code --format json)
# ---------------------------------------------------------------------------

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
                total_input  += toks.get("total", 0) - out
            elif ev_type == "assistant":
                for part in ev.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        text += part.get("text", "")
        except Exception:
            pass
    return text.strip(), total_input, total_output


# ---------------------------------------------------------------------------
# LLM judge con ground_truth
# ---------------------------------------------------------------------------

def _judge_fn(prompt: str) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=5,
    )
    return resp.choices[0].message.content or ""


def judge_with_truth(answer: str, ground_truth: str, criterios: list[str]) -> bool:
    """LLM judge que compara contra ground_truth y criterios."""
    crit_str = ", ".join(criterios)
    prompt = (
        f"Evalua si la siguiente respuesta cubre los puntos clave.\n\n"
        f"Ground truth:\n{ground_truth}\n\n"
        f"Criterios obligatorios (al menos 60% deben aparecer): {crit_str}\n\n"
        f"Respuesta del agente:\n{answer[:3000]}\n\n"
        "Responde solo 'OK' si la respuesta cubre los criterios y es consistente "
        "con el ground truth. Responde 'FAIL' en caso contrario."
    )
    result = _judge_fn(prompt)
    return "OK" in result.upper()


# ---------------------------------------------------------------------------
# leo-code CLI runner (TypeScript repo como contexto)
# ---------------------------------------------------------------------------

def run_leo(query: str, task_idx: int) -> dict:
    t0 = time.time()
    stdout = _run_cli_streaming(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", query, "--format", "json", "--model", LEO_MODEL,
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=TIMEOUT_LEO,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_oc_json_output(stdout)
    (RUNS_DIR / f"leo_t{task_idx+1}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:500],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"respuesta": respuesta, "input_tokens": inp, "output_tokens": out,
            "latency_s": latency}


# ---------------------------------------------------------------------------
# opencode CLI runner via WSL Ubuntu
# ---------------------------------------------------------------------------

def run_opencode_wsl(query: str, task_idx: int) -> dict:
    """Invoca opencode en WSL Ubuntu con CWD = packages/leo-code (TypeScript).

    Pasa query via variable de entorno OC_QUERY para evitar problemas de quoting.
    WSLENV propaga las vars al entorno Linux sin conversion de rutas.
    """
    t0 = time.time()
    env = {**_WSL_ENV, "OC_QUERY": query}
    bash_cmd = (
        f'cd "{WSL_REPO}" && '
        'opencode run "$OC_QUERY" '
        '--format json '
        f'--model deepseek/deepseek-chat '
        '--dangerously-skip-permissions 2>/dev/null'
    )
    stdout = _run_cli_streaming(
        ["wsl", "-d", "Ubuntu", "bash", "-c", bash_cmd],
        cwd=None, env=env, timeout=TIMEOUT_OC,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_oc_json_output(stdout)
    (RUNS_DIR / f"oc_t{task_idx+1}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:500],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"respuesta": respuesta, "input_tokens": inp, "output_tokens": out,
            "latency_s": latency}


# ---------------------------------------------------------------------------
# no_ctx baseline: DeepSeek directo sin contexto
# ---------------------------------------------------------------------------

def run_no_ctx(query: str, task_idx: int) -> dict:
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
# Task runner (los 3 modos en paralelo por tarea)
# ---------------------------------------------------------------------------

def run_task(task: dict, task_idx: int) -> dict:
    query  = task["query"]
    crit   = task["criterios"]
    truth  = task["ground_truth"]

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_leo = ex.submit(run_leo,          query, task_idx)
        f_oc  = ex.submit(run_opencode_wsl, query, task_idx)
        f_nc  = ex.submit(run_no_ctx,       query, task_idx)
        r_leo = f_leo.result()
        r_oc  = f_oc.result()
        r_nc  = f_nc.result()

    def _score(r):
        ans = r["respuesta"]
        return {
            "tokens":    r["input_tokens"] + r["output_tokens"],
            "latency":   r["latency_s"],
            "criteria":  score_answer(ans, crit)["score"],
            "judge":     judge_with_truth(ans, truth, crit) if ans else False,
            "answer":    ans[:300],
        }

    return {
        "id":    task["id"],
        "type":  task["type"],
        "query": query,
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
    n = len(results)

    for r in results:
        for m in modes:
            total[m] += r[m]["tokens"]
            lat[m]   += r[m]["latency"]
            crit[m].append(r[m]["criteria"])
            judge[m] += int(r[m]["judge"])

    avg_crit = {m: statistics.mean(crit[m]) for m in modes}
    leo_vs_oc   = avg_crit["leo"] - avg_crit["opencode"]
    leo_vs_nctx = avg_crit["leo"] - avg_crit["no_ctx"]

    return {
        "n_tasks": n,
        "total_tokens": total,
        "latency": {m: round(lat[m], 2) for m in modes},
        "avg_criteria": {m: round(avg_crit[m], 3) for m in modes},
        "judge_ok": judge,
        "leo_vs_opencode_criteria": round(leo_vs_oc, 3),
        "leo_vs_noctx_criteria":    round(leo_vs_nctx, 3),
    }


def print_report(results: list[dict], m: dict):
    W = 110
    print("\n" + "=" * W)
    print("BENCHMARK EXIGENTE  --  leo-code CLI (KC-RAG+CodeGraph)  vs  opencode CLI (nativo)")
    print(f"Target: packages/leo-code/src (TypeScript) | Model: {MODEL} | Temp: {TEMPERATURE}")
    print("=" * W)

    tk = m["total_tokens"]
    lk = m["latency"]
    ac = m["avg_criteria"]
    jk = m["judge_ok"]
    n  = m["n_tasks"]

    print(f"\n{'Metrica':<45} {'leo-code':>10} {'opencode':>10} {'no-ctx':>8}")
    print("-" * 75)
    print(f"{'Tokens totales':<45} {tk['leo']:>10,} {tk['opencode']:>10,} {tk['no_ctx']:>8,}")
    print(f"{'Latencia total (s)':<45} {lk['leo']:>10.1f} {lk['opencode']:>10.1f} {lk['no_ctx']:>8.1f}")
    print(f"{'Criteria avg':<45} {ac['leo']:>10.1%} {ac['opencode']:>10.1%} {ac['no_ctx']:>8.1%}")
    print(f"{'LLM judge OK':<45} {jk['leo']:>9}/{n} {jk['opencode']:>9}/{n} {jk['no_ctx']:>7}/{n}")
    print(f"{'Leo vs opencode (criteria)':<45} {m['leo_vs_opencode_criteria']:>+10.1%}")
    print(f"{'Leo vs no-ctx   (criteria)':<45} {m['leo_vs_noctx_criteria']:>+10.1%}")

    print(f"\n{'ID':<4} {'Tipo':<14} {'Tarea':<32} {'LEOc':>6} {'OCc':>6} {'NCc':>5} {'LEOj':>5} {'OCj':>5} {'LEOtok':>7} {'OCtok':>7}")
    print("-" * W)
    for r in results:
        leo_j = "OK" if r["leo"]["judge"] else "--"
        oc_j  = "OK" if r["opencode"]["judge"] else "--"
        print(
            f"{r['id']:<4} {r['type']:<14} {r['query'][:31]:<32} "
            f"{r['leo']['criteria']:>5.0%} {r['opencode']['criteria']:>5.0%} "
            f"{r['no_ctx']['criteria']:>4.0%} "
            f"{leo_j:>5} {oc_j:>5} "
            f"{r['leo']['tokens']:>7,} {r['opencode']['tokens']:>7,}"
        )

    print("\n--- Diagnosis ---")
    leo_vs_oc = m["leo_vs_opencode_criteria"]
    if leo_vs_oc > 0.10:
        print(f"[OK] leo-code supera opencode criteria {leo_vs_oc:+.0%}")
    elif leo_vs_oc >= 0:
        print(f"[>>] leo-code mejora minima vs opencode {leo_vs_oc:+.0%}")
    else:
        print(f"[XX] opencode supera leo-code criteria {leo_vs_oc:+.0%}")

    judge_leo = jk["leo"]
    judge_oc  = jk["opencode"]
    if judge_leo > judge_oc:
        print(f"[OK] LLM judge: leo {judge_leo}/{n} > opencode {judge_oc}/{n}")
    elif judge_leo == judge_oc:
        print(f"[==] LLM judge: empate leo={judge_leo}/{n} oc={judge_oc}/{n}")
    else:
        print(f"[XX] LLM judge: opencode {judge_oc}/{n} > leo {judge_leo}/{n}")

    if ac["leo"] >= 0.80:
        print(f"[OK] Leo criteria {ac['leo']:.0%} >= objetivo 80%")
    else:
        print(f"[>>] Leo criteria {ac['leo']:.0%} -- objetivo 80%")


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

def _check_wsl_opencode() -> bool:
    try:
        r = subprocess.run(
            ["wsl", "-d", "Ubuntu", "bash", "-c", "opencode --version 2>/dev/null || echo NOTFOUND"],
            capture_output=True, text=True, timeout=15
        )
        if "NOTFOUND" in r.stdout or r.returncode != 0:
            print("WARN opencode no encontrado en WSL Ubuntu -- modo opencode retornara vacio")
            return False
        print(f"opencode WSL: {r.stdout.strip()}")
        return True
    except Exception as e:
        print(f"WARN WSL no disponible ({e}) -- modo opencode deshabilitado")
        return False


def _index_leorepo():
    """Indexa el repo TypeScript de leo-code en KC-RAG."""
    try:
        w = httpx.post(
            f"{SIDECAR}/index",
            json={"repo_path": LEO_REPO, "languages": "typescript,javascript"},
            timeout=120,
        )
        print(f"[index] KC-RAG leo-code: {w.json()}")
    except Exception as e:
        print(f"WARN KC-RAG index fallo ({e}) -- KC-RAG sin contexto TypeScript")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    n  = len(TASKS)
    print(f"[{ts}] Benchmark exigente: {n} tareas | leo-code vs opencode")
    print(f"Target repo: {LEO_REPO}")
    print(f"Modelo: {MODEL} | Temperatura: {TEMPERATURE}")

    # Verificar KC-RAG
    try:
        h = httpx.get(f"{SIDECAR}/health", timeout=5)
        print(f"KC-RAG sidecar: {h.json()}")
        _index_leorepo()
    except Exception as e:
        print(f"WARN sidecar KC-RAG no responde ({e}) -- leo-code sin KC-RAG")

    # Verificar opencode en WSL
    oc_ok = _check_wsl_opencode()
    if not oc_ok:
        print("[!] opencode no disponible -- sus tokens seran 0 y criteria 0%")

    print(f"\n[Benchmark] {n} tareas x 3 modos en paralelo...")
    task_outputs: dict[int, tuple] = {}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = {ex.submit(run_task, task, i): i for i, task in enumerate(TASKS)}
        for fut in as_completed(futures):
            i = futures[fut]
            r = fut.result()
            task_outputs[i] = r
            leo_c = r["leo"]["criteria"]
            oc_c  = r["opencode"]["criteria"]
            print(f"[done] {r['id']} ({r['type']}) -- leo={leo_c:.0%} oc={oc_c:.0%}", flush=True)

    results = []
    for i in range(n):
        r = task_outputs[i]
        print(f"\n--- {r['id']} [{r['type']}]: {r['query'][:60]}... ---")
        print(f"  LEO:      {r['leo']['tokens']:>6,}tok  crit={r['leo']['criteria']:.0%}  judge={'OK' if r['leo']['judge'] else '--'}")
        print(f"  OPENCODE: {r['opencode']['tokens']:>6,}tok  crit={r['opencode']['criteria']:.0%}  judge={'OK' if r['opencode']['judge'] else '--'}")
        print(f"  NO-CTX:   {r['no_ctx']['tokens']:>6,}tok  crit={r['no_ctx']['criteria']:.0%}")
        results.append(r)

    m = compute_metrics(results)
    print_report(results, m)

    out = Path(__file__).parent / "leovoc_results.json"
    out.write_text(json.dumps({
        "run_timestamp": ts, "model": MODEL, "temperature": TEMPERATURE,
        "target_repo": LEO_REPO,
        "metrics": m, "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {out}")


if __name__ == "__main__":
    main()
