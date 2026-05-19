"""EvalPlus benchmark: leo-code CLI en HumanEval+.

Genera completions via leo-code CLI, evalúa con evalplus pass@1.
Referencia publicada: Claude Sonnet 4.5 ~97.6% HumanEval, ~90% HumanEval+.

Run: python benchmark/evalplus_bench.py [--tasks N] [--out results.json]
"""

import sys, os, re, json, time, subprocess, threading, argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BUN          = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC      = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"
SIDECAR      = "http://localhost:9898"
LEO_MODEL    = "deepseek/deepseek-chat"

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
}

RUNS_DIR = Path(__file__).parent / "runs_evalplus"
RUNS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Streaming subprocess (idéntico al benchmark principal)
# ---------------------------------------------------------------------------

def _run_cli_streaming(cmd, cwd, env, timeout=90) -> str:
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


def _parse_leo_output(stdout: str) -> tuple[str, int, int]:
    """Extrae texto y tokens del stream JSON de leo-code --format json."""
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


def _extract_code(text: str, entry_point: str) -> str:
    """Extrae el bloque de código Python de la respuesta del agente."""
    # Buscar bloque ```python ... ```
    m = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Buscar bloque ``` ... ```
    m = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Buscar la función directamente
    m = re.search(rf"def {re.escape(entry_point)}\s*\(.*", text, re.DOTALL)
    if m:
        return text[m.start():].strip()
    # Devolver todo si no hay bloque
    return text.strip()


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def run_leo_on_task(task_id: str, prompt: str, entry_point: str) -> dict:
    """Ejecuta leo-code en una tarea HumanEval+ y retorna la solución."""
    query = (
        f"Complete the following Python function. Return ONLY the full function implementation "
        f"in a ```python``` code block, no explanations:\n\n```python\n{prompt}\n```"
    )
    t0 = time.time()
    stdout = _run_cli_streaming(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", query, "--format", "json", "--model", LEO_MODEL,
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=90,
    )
    latency = round(time.time() - t0, 3)
    text, input_tok, output_tok = _parse_leo_output(stdout)
    code = _extract_code(text, entry_point)

    safe_id = task_id.replace("/", "_")
    (RUNS_DIR / f"{safe_id}.json").write_text(
        json.dumps({
            "task_id": task_id, "entry_point": entry_point,
            "raw_response": text[:1000], "extracted_code": code[:500],
            "input_tokens": input_tok, "output_tokens": output_tok,
            "latency_s": latency,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "task_id": task_id, "solution": code,
        "input_tokens": input_tok, "output_tokens": output_tok,
        "latency_s": latency, "raw_response": text,
    }


def build_evalplus_submission(results: list[dict]) -> dict:
    """Construye el dict de submissions en formato evalplus."""
    samples = {}
    for r in results:
        samples[r["task_id"]] = [r["solution"]]
    return samples


def run_evalplus_evaluate(samples_path: Path) -> dict:
    """Ejecuta evalplus.evaluate y devuelve los resultados."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "evalplus.evaluate",
             "--dataset", "humaneval",
             "--samples", str(samples_path)],
            capture_output=True, text=True, timeout=300,
        )
        output = result.stdout + result.stderr
        # Parsear pass@1 del output
        m = re.search(r"pass@1.*?(\d+\.\d+)", output)
        pass1 = float(m.group(1)) if m else None
        return {"raw": output, "pass_at_1": pass1}
    except Exception as e:
        return {"raw": str(e), "pass_at_1": None}


def print_report(results: list[dict], eval_result: dict, n_tasks: int):
    W = 90
    print("\n" + "=" * W)
    print("EVALPLUS BENCHMARK  --  leo-code CLI (KC-RAG + DeepSeek)")
    print(f"Dataset: HumanEval+ | Tasks: {n_tasks}/164 | Model: {LEO_MODEL}")
    print(f"Referencia publicada: Claude Sonnet 4.5 = 97.6% HumanEval, ~88-90% HumanEval+")
    print("=" * W)

    ok_results = [r for r in results if r["input_tokens"] > 0]
    failed = len(results) - len(ok_results)

    all_tokens = [r["input_tokens"] + r["output_tokens"] for r in ok_results]
    avg_tokens = sum(all_tokens) / max(len(all_tokens), 1)
    avg_latency = sum(r["latency_s"] for r in results) / max(len(results), 1)

    print(f"\nTareas ejecutadas:  {len(results)}")
    print(f"Respuestas válidas: {len(ok_results)} ({len(ok_results)/len(results):.0%})")
    print(f"Timeouts/errores:   {failed}")
    print(f"Tokens promedio:    {avg_tokens:,.0f} tok/tarea")
    print(f"Latencia promedio:  {avg_latency:.1f}s/tarea")

    p1 = eval_result.get("pass_at_1")
    print(f"\n{'pass@1 leo-code (HumanEval+)':<40} {f'{p1:.1%}' if p1 else 'N/A (ejecutar evalplus manual)'}")
    print(f"{'pass@1 Claude Sonnet 4.5 (HumanEval+)':<40} ~88-90% (publicado)")
    print(f"{'pass@1 DeepSeek-chat (HumanEval ref.)':<40} ~80-85% (estimado)")

    if eval_result.get("raw"):
        print(f"\n--- EvalPlus output ---")
        print(eval_result["raw"][:500])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=20, help="Número de tasks a ejecutar (default: 20)")
    parser.add_argument("--out", default=None, help="Fichero de salida JSON")
    args = parser.parse_args()

    from evalplus.data import get_human_eval_plus
    dataset = get_human_eval_plus()
    task_ids = list(dataset.keys())[:args.tasks]

    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    print(f"[{ts}] EvalPlus benchmark: {args.tasks} tasks via leo-code CLI")
    print(f"Model: {LEO_MODEL} | Sidecar: {SIDECAR}")

    results = []
    for i, task_id in enumerate(task_ids):
        task = dataset[task_id]
        print(f"  [{i+1}/{args.tasks}] {task_id} ({task['entry_point']})...", end=" ", flush=True)
        r = run_leo_on_task(task_id, task["prompt"], task["entry_point"])
        tok = r["input_tokens"] + r["output_tokens"]
        print(f"{tok}tok {r['latency_s']:.1f}s {'OK' if tok > 0 else 'TIMEOUT'}")
        results.append(r)

    # Guardar submissions para evalplus
    samples = build_evalplus_submission(results)
    samples_path = Path(__file__).parent / f"evalplus_samples_{ts}.json"
    samples_path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSubmissions guardadas: {samples_path}")

    # Evaluar con evalplus
    print("Ejecutando evalplus.evaluate...")
    eval_result = run_evalplus_evaluate(samples_path)

    print_report(results, eval_result, args.tasks)

    out_path = args.out or str(Path(__file__).parent / f"evalplus_results_{ts}.json")
    Path(out_path).write_text(json.dumps({
        "timestamp": ts, "model": LEO_MODEL, "n_tasks": args.tasks,
        "eval": eval_result, "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {out_path}")


if __name__ == "__main__":
    main()
