"""Comparacion real: DeepSeek models × RAG / Agent / Opencode.

Uso: python benchmark/run_config.py --model deepseek/deepseek-chat --mode rag --tasks all
Modos: rag (KC-RAG directo), agent (AgentLoop con tools), oc (opencode CLI)
"""

import asyncio, json, os, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from benchmark.judge import judge, score_summary

RESULTS_DIR = Path("benchmark/results_final")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TASKS = json.loads(Path("benchmark/tasks.json").read_text(encoding="utf-8"))
TASK_IDS = ["t1_code_query", "t8_review", "t11_onboard", "t12_design_review"]
OC_CMD = [r"C:\Users\Ismael\AppData\Roaming\npm\opencode.cmd", "run"]

MODELS = ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner",
          "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro"]



def run_rag_direct(model: str, query: str, repo: str) -> dict:
    """LEO con KC-RAG directo — sin tools."""
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        leo_ask = str(Path(__file__).parent / "leo_ask.py")
        r = subprocess.run(
            [sys.executable, leo_ask, query, repo, model],
            capture_output=True, text=True, timeout=300, env=env, cwd=repo,
        )
        stderr = r.stderr or ""
        resp = ""
        tokens = 0
        iterations = 0
        for line in stderr.split("\n"):
            if "__LEO_RESULT__" in line:
                try:
                    data = json.loads(line.split("__LEO_RESULT__", 1)[1])
                    resp = data.get("response", "")
                    tokens = data.get("tokens", len(resp) // 4)
                    iterations = data.get("iterations", 0)
                except json.JSONDecodeError:
                    resp = line
        if not resp:
            resp = (r.stdout or "").strip()
        return {"system": "LEO-RAG", "response": resp[:8000], "tokens": tokens,
                "duration_s": round(time.time() - t0, 1), "model": model,
                "mode": "rag", "iterations": iterations}
    except subprocess.TimeoutExpired:
        return {"system": "LEO-RAG", "response": "[TIMEOUT 300s]", "tokens": 0,
                "duration_s": 300, "model": model, "mode": "rag"}
    except Exception as e:
        return {"system": "LEO-RAG", "response": f"[ERROR: {e}]", "tokens": 0,
                "duration_s": round(time.time() - t0, 1), "model": model, "mode": "rag"}


def run_agent(model: str, query: str, repo: str) -> dict:
    """LEO con AgentLoop + tools."""
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        leo_ask = str(Path(__file__).parent / "leo_ask.py")
        r = subprocess.run(
            [sys.executable, leo_ask, query, repo, model],
            capture_output=True, text=True, timeout=300, env=env, cwd=repo,
        )
        # Parse from stderr (leo_ask writes result there)
        stderr = r.stderr or ""
        resp = ""
        tokens = 0
        iterations = 0
        for line in stderr.split("\n"):
            if "__LEO_RESULT__" in line:
                try:
                    data = json.loads(line.split("__LEO_RESULT__", 1)[1])
                    resp = data.get("response", "")
                    tokens = data.get("tokens", len(resp) // 4)
                    iterations = data.get("iterations", 0)
                except json.JSONDecodeError:
                    resp = line
        if not resp:
            resp = (r.stdout or "").strip()
        return {"system": "LEO-AGT", "response": resp[:8000], "tokens": tokens,
                "duration_s": round(time.time() - t0, 1), "model": model,
                "mode": "agent", "iterations": iterations}
    except subprocess.TimeoutExpired:
        return {"system": "LEO-AGT", "response": "[TIMEOUT 300s]", "tokens": 0,
                "duration_s": 300, "model": model, "mode": "agent"}
    except Exception as e:
        return {"system": "LEO-AGT", "response": f"[ERROR: {e}]", "tokens": 0,
                "duration_s": round(time.time() - t0, 1), "model": model, "mode": "agent"}


def run_opencode(model: str, query: str, repo: str) -> dict:
    """Opencode CLI real."""
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        r = subprocess.run(
            OC_CMD + [query, "-m", model],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, env=env, cwd=repo,
        )
        out = r.stdout or ""
        # Strip ANSI codes
        import re as _re
        out = _re.sub(r'\x1b\[[0-9;]*m', '', out)
        out = _re.sub(r'\x1b\]8;.*?\x1b\\', '', out)
        lines = [l for l in out.split("\n") if l.strip() and l.strip()[:4] not in ("INFO", "WARN", "ERRO", "   ")]
        response = "\n".join(lines).strip()
        return {"system": "OC", "response": response[:4000], "tokens": len(response) // 4,
                "duration_s": round(time.time() - t0, 1), "model": model, "mode": "oc"}
    except subprocess.TimeoutExpired:
        return {"system": "OC", "response": "[TIMEOUT 300s]", "tokens": 0,
                "duration_s": 300, "model": model, "mode": "oc"}
    except FileNotFoundError:
        return {"system": "OC", "response": "[opencode not found]", "tokens": 0,
                "duration_s": 0, "model": model, "mode": "oc"}
    except Exception as e:
        return {"system": "OC", "response": f"[ERROR: {e}]", "tokens": 0,
                "duration_s": round(time.time() - t0, 1), "model": model, "mode": "oc"}


async def run_config(model: str, mode: str, tasks: list[dict], repo: str) -> list[dict]:
    """Ejecuta 1 configuracion (modelo + modo) para N tareas."""
    results = []

    async def run_one(task):
        tid = task["id"]
        q = task["query"]
        print(f"    [{model.split('/')[-1]}:{mode}] {tid} ...")
        try:
            if mode == "rag":
                r = await asyncio.to_thread(run_rag_direct, model, q, repo)
            elif mode == "agent":
                r = await asyncio.to_thread(run_agent, model, q, repo)
            elif mode == "oc":
                r = await asyncio.to_thread(run_opencode, model, q, repo)
            r["task_id"] = tid
            return r
        except Exception as e:
            return {"system": mode, "task_id": tid, "response": f"[{e}]",
                    "tokens": 0, "duration_s": 0, "model": model, "mode": mode}

    if mode in ("rag", "agent"):
        # Secuencial: evita conflictos de acceso concurrente a Qdrant
        raw_results = []
        for task in tasks:
            raw_results.append(await run_one(task))
    else:
        # OC es subproceso independiente, puede correr en paralelo
        raw_results = list(await asyncio.gather(*[run_one(t) for t in tasks]))

    tasks_by_id = {t["id"]: t for t in tasks}
    for r in raw_results:
        if r:
            task = tasks_by_id.get(r.get("task_id", ""))
            resp = r.get("response", "")
            if task and resp and len(resp) > 20 and not resp.startswith("["):
                scores = judge(resp, task)
                r["scores"] = scores
                r["score"] = score_summary(scores)
            else:
                r["score"] = 0
            results.append(r)
            print(f"      {r.get('duration_s',0):.0f}s | {r.get('tokens',0)} tok | {r.get('score',0):.1f}/10")
    return results


def print_table(all_results: list[dict]):
    """Imprime tabla comparativa por modelo y modo."""
    print("\n" + "=" * 90)
    print("DEEPSEEK COMPARISON — LEO-RAG vs LEO-AGT vs OPENCODE")
    print("=" * 90)

    # Aggregate by model+mode
    agg = {}
    for r in all_results:
        key = f"{r['model']}|{r['mode']}"
        agg.setdefault(key, {"times": [], "scores": [], "tokens": []})
        agg[key]["times"].append(r.get("duration_s", 0))
        agg[key]["scores"].append(r.get("score", 0))
        agg[key]["tokens"].append(r.get("tokens", 0))

    modes = ["rag", "agent", "oc"]
    print(f"\n{'Model':<28} {'RAG time':>7} {'RAG score':>8} {'RAG tok':>7}  {'AGT time':>7} {'AGT score':>8} {'AGT tok':>7}  {'OC time':>7} {'OC score':>8} {'OC tok':>7}")
    print("-" * 90)

    for model in ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner",
                   "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro"]:
        row = [model.split("/")[-1][:26]]
        for mode in modes:
            key = f"{model}|{mode}"
            data = agg.get(key)
            if data and data["times"]:
                avg_t = sum(data["times"]) / len(data["times"])
                avg_s = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
                avg_tok = sum(data["tokens"]) / len(data["tokens"]) if data["tokens"] else 0
                row.extend([f"{avg_t:.0f}s", f"{avg_s:.1f}", f"{avg_tok:.0f}"])
            else:
                row.extend(["  N/A", "  N/A", "  N/A"])
        print("  ".join(f"{c:>9}" if i > 0 else c for i, c in enumerate(row)))

    print("=" * 90)


def generate_report(all_results: list[dict]):
    """Escribe benchmark/REPORT_FINAL.md desde los resultados."""
    from datetime import datetime

    lines = [
        "# Benchmark leo-code vs opencode — REPORT FINAL",
        "",
        f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Ejecuciones:** {len(all_results)}  ",
        "**Modelos:** DeepSeek V3, R1, V4 Flash, V4 Pro  ",
        "**Modos:** LEO-RAG, LEO-AGT, OC  ",
        "",
        "---",
        "",
        "## Tabla comparativa",
        "",
        "| Modelo | Modo | Score | Tokens | Tiempo |",
        "|--------|------|------:|-------:|-------:|",
    ]

    # Aggregate by model+mode
    agg: dict[str, dict] = {}
    for r in all_results:
        key = f"{r['model']}|{r['mode']}"
        agg.setdefault(key, {"scores": [], "tokens": [], "times": [], "model": r["model"], "mode": r["mode"]})
        agg[key]["scores"].append(r.get("score", 0))
        agg[key]["tokens"].append(r.get("tokens", 0))
        agg[key]["times"].append(r.get("duration_s", 0))

    mode_order = {"rag": 0, "agent": 1, "oc": 2}
    sorted_keys = sorted(agg, key=lambda k: (agg[k]["model"], mode_order.get(agg[k]["mode"], 9)))

    for key in sorted_keys:
        d = agg[key]
        avg_score = sum(d["scores"]) / len(d["scores"]) if d["scores"] else 0
        avg_tok = int(sum(d["tokens"]) / len(d["tokens"])) if d["tokens"] else 0
        avg_t = sum(d["times"]) / len(d["times"]) if d["times"] else 0
        mode_label = {"rag": "LEO-RAG", "agent": "LEO-AGT", "oc": "OC"}.get(d["mode"], d["mode"])
        model_short = d["model"].split("/")[-1]
        lines.append(f"| {model_short} | {mode_label} | {avg_score:.1f} | {avg_tok} | {avg_t:.0f}s |")

    # Per-task breakdown
    lines += ["", "---", "", "## Detalle por tarea", ""]
    for task_id in TASK_IDS:
        task_results = [r for r in all_results if r.get("task_id") == task_id]
        if not task_results:
            continue
        lines += [f"### {task_id}", "", "| Sistema | Score | Tokens | Tiempo |",
                  "|---------|------:|-------:|-------:|"]
        for r in sorted(task_results, key=lambda x: -x.get("score", 0)):
            sys = f"{r['model'].split('/')[-1]}:{r['mode']}"
            lines.append(f"| {sys} | {r.get('score', 0):.1f} | {r.get('tokens', 0)} | {r.get('duration_s', 0):.0f}s |")
        lines.append("")

    # Winners
    lines += ["---", "", "## Winners por categoría", ""]
    for mode in ["rag", "agent", "oc"]:
        mode_res = [r for r in all_results if r.get("mode") == mode and r.get("score", 0) > 0]
        if not mode_res:
            continue
        by_model: dict[str, list] = {}
        for r in mode_res:
            by_model.setdefault(r["model"], []).append(r.get("score", 0))
        best = max(by_model, key=lambda m: sum(by_model[m]) / len(by_model[m]))
        avg = sum(by_model[best]) / len(by_model[best])
        label = {"rag": "LEO-RAG", "agent": "LEO-AGT", "oc": "OC"}.get(mode, mode)
        lines.append(f"- **{label} mejor modelo:** `{best.split('/')[-1]}` — {avg:.1f}/10")

    report_path = Path("benchmark/REPORT_FINAL.md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport -> {report_path}")


def main():
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        print("ERROR: DEEPSEEK_API_KEY no configurada.")
        print("  PowerShell: $env:DEEPSEEK_API_KEY = 'sk-...'")
        print("  Bash:       export DEEPSEEK_API_KEY='sk-...'")
        sys.exit(1)

    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="deepseek/deepseek-chat")
    p.add_argument("--mode", default="rag", choices=["rag", "agent", "oc"])
    p.add_argument("--tasks", default="all")
    p.add_argument("--repo", default=".")
    p.add_argument("--all-models", action="store_true", help="Run ALL models")
    args = p.parse_args()

    task_ids = TASK_IDS if args.tasks == "all" else args.tasks.split(",")
    tasks = [t for t in TASKS if t["id"] in task_ids]

    if args.all_models:
        all_results = []
        for model in MODELS:
            for mode in ["rag", "agent", "oc"]:
                # Skip agent mode for reasoner (no tool calling)
                if model == "deepseek/deepseek-reasoner" and mode == "agent":
                    continue
                print(f"\n{'='*60}")
                print(f"{model} | {mode}")
                print("=" * 60)
                results = asyncio.run(run_config(model, mode, tasks, args.repo))
                all_results.extend(results)
        print("\n")
        print_table(all_results)

        # Save
        (RESULTS_DIR / "summary.json").write_text(
            json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        generate_report(all_results)
    else:
        print(f"{args.model} | {args.mode} | {len(tasks)} tasks")
        results = asyncio.run(run_config(args.model, args.mode, tasks, args.repo))
        print_table(results)

        (RESULTS_DIR / f"{args.model.replace('/', '_')}_{args.mode}.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
