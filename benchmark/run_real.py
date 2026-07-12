"""Benchmark real: leo-code vs opencode CLI (subprocesos paralelos, judge separado).

Uso: python benchmark/run_real.py [--tasks t1,t2] [--systems leo,oc,no] [--batch 3]
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.judge import judge, score_summary


def _prewarm_index(repo_path: str) -> str:
    """Corre engine._do_index() UNA vez en un subproceso propio, contra un Qdrant
    FIJO (no temporal), para pagar el costo de parseo+embedding una sola vez por
    corrida de benchmark en vez de una vez por cada uno de los 15 tasks x N
    subprocesos paralelos de --batch. Los runners de LEO copian este Qdrant ya
    poblado a su directorio aislado (ver bench_qdrant.py)."""
    qdrant_path = str(Path("cache/qdrant_bench_prewarm").resolve())
    script = f"from leo_code import engine; engine._do_index({os.path.abspath(repo_path)!r})"
    env = {**os.environ, "LEO_QDRANT_PATH": qdrant_path}
    t0 = time.time()
    subprocess.run([sys.executable, "-c", script], env=env, check=True,
                    cwd=str(Path(__file__).parent.parent))
    print(f"  Prewarm index: {int((time.time() - t0) * 1000)}ms")
    return qdrant_path


def parse_leo_tokens(stderr: str, response: str) -> int:
    """Coste real (input+output) que leo_runner emite como [LEO_TOKENS=N] por stderr.

    Fallback len//4 (solo salida) si el marcador no llegó (crash/timeout del runner).
    """
    m = re.search(r"\[LEO_TOKENS=(\d+)\]", stderr or "")
    return int(m.group(1)) if m else len(response) // 4

MODEL = "deepseek/deepseek-chat"  # V3 - fiable con tool calling en streaming
RUNNER = str(Path(__file__).parent / "leo_runner.py")
RAG_RUNNER = str(Path(__file__).parent / "leo_rag_runner.py")
SMART_RUNNER = str(Path(__file__).parent / "leo_smart_runner.py")
RESULTS_DIR = Path("benchmark/results_real")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
BATCH_SIZE = 3


def run_leo_subprocess(query: str, repo_path: str) -> dict:
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""), "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, RUNNER, query, repo_path, MODEL],
            capture_output=True, text=True, timeout=300, env=env, encoding="utf-8", errors="replace",
            cwd=repo_path,
        )
        # La respuesta es la ULTIMA linea de stdout (despues del indexer log)
        stdout = (r.stdout or "").strip()
        lines = stdout.split("\n")
        # Remove indexer log lines
        response_lines = [l for l in lines if not l.startswith("[indexer]") and "Tipos:" not in l and "capsulas" not in l and "archivos" not in l]
        response = "\n".join(response_lines).strip() or (r.stderr or "").strip()
        out = {"system": "LEO", "response": response[:4000],
               "tokens": parse_leo_tokens(r.stderr, response),
               "duration_ms": int((time.time() - t0) * 1000)}
        mt = re.search(r"\[LEO_TIMINGS=(\{.*?\})\]", r.stderr or "")
        if mt:
            try:
                out["timings"] = json.loads(mt.group(1))
            except Exception:
                pass
        return out
    except subprocess.TimeoutExpired:
        return {"system": "LEO", "response": "[Timeout]", "tokens": 0, "duration_ms": 300000}
    except Exception as e:
        return {"system": "LEO", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


def run_leo_rag_subprocess(query: str, repo_path: str) -> dict:
    """rag_direct(): UNA llamada con contexto KC-RAG, sin loop de tools. Solo apto
    para tasks de solo-lectura (no edita archivos)."""
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""), "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, RAG_RUNNER, query, repo_path, MODEL],
            capture_output=True, text=True, timeout=300, env=env, encoding="utf-8", errors="replace",
            cwd=repo_path,
        )
        stdout = (r.stdout or "").strip()
        lines = stdout.split("\n")
        response_lines = [l for l in lines if not l.startswith("[indexer]") and "Tipos:" not in l and "capsulas" not in l and "archivos" not in l]
        response = "\n".join(response_lines).strip() or (r.stderr or "").strip()
        return {"system": "RAG", "response": response[:4000],
                "tokens": parse_leo_tokens(r.stderr, response),
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"system": "RAG", "response": "[Timeout]", "tokens": 0, "duration_ms": 300000}
    except Exception as e:
        return {"system": "RAG", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


def run_leo_smart_subprocess(query: str, repo_path: str) -> dict:
    """run_smart(): rag_direct() primero, escala a run() si hace falta (breadth/edit/
    respuesta insuficiente)."""
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""), "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, SMART_RUNNER, query, repo_path, MODEL],
            capture_output=True, text=True, timeout=300, env=env, encoding="utf-8", errors="replace",
            cwd=repo_path,
        )
        stdout = (r.stdout or "").strip()
        lines = stdout.split("\n")
        response_lines = [l for l in lines if not l.startswith("[indexer]") and "Tipos:" not in l and "capsulas" not in l and "archivos" not in l]
        response = "\n".join(response_lines).strip() or (r.stderr or "").strip()
        return {"system": "SMART", "response": response[:4000],
                "tokens": parse_leo_tokens(r.stderr, response),
                "escalated": "[ESCALATED=True]" in (r.stderr or ""),
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"system": "SMART", "response": "[Timeout]", "tokens": 0, "duration_ms": 300000}
    except Exception as e:
        return {"system": "SMART", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


MCP_TOOLS = {"get_context", "trace", "impact", "who_calls", "where", "guard"}
NATIVE_EXPLORE = {"read", "grep", "glob", "list"}


def parse_oc_events(stdout: str) -> dict:
    """Parsea el stream --format json de opencode: texto final, tokens reales por
    step_finish, y telemetría de tool-calls (adopción MCP vs exploración nativa).

    'redundant_native_after_ctx': reads/greps/globs nativos DESPUÉS del primer
    get_context — mide el 'doble coste' (el agente pidió contexto comprimido y aun
    así releyó archivos)."""
    text_parts, tool_seq = [], []
    real_tokens = 0
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        part = evt.get("part", {}) or {}
        if evt.get("type") == "text" and part.get("type") == "text":
            text_parts.append(part.get("text", ""))
        elif evt.get("type") == "step_finish":
            real_tokens += (part.get("tokens", {}) or {}).get("total", 0)
        elif evt.get("type") == "tool_use" and part.get("type") == "tool":
            tool_seq.append(part.get("tool", "?"))

    # opencode nombra las tools MCP con el server como prefijo (p.ej.
    # "leo-code_get_context" o "leo-code.get_context"); detectar por sufijo.
    def base(t):
        for m in MCP_TOOLS:
            if t == m or t.endswith("_" + m) or t.endswith("." + m):
                return m
        return t

    mcp_calls, native_calls = {}, {}
    redundant = 0
    seen_ctx = False
    for t in tool_seq:
        b = base(t)
        if b in MCP_TOOLS and ("leo" in t or t == b):
            mcp_calls[b] = mcp_calls.get(b, 0) + 1
            if b == "get_context":
                seen_ctx = True
        else:
            native_calls[t] = native_calls.get(t, 0) + 1
            if seen_ctx and t in NATIVE_EXPLORE:
                redundant += 1
    return {"response": "\n".join(text_parts).strip(), "tokens": real_tokens,
            "tool_seq": tool_seq, "mcp_calls": mcp_calls, "native_calls": native_calls,
            "redundant_native_after_ctx": redundant}


def run_oc_subprocess(query: str, repo_path: str) -> dict:
    """Corre opencode vanilla — SIN MCP (ni el leo-code local ni codegraph/pencil
    globales del usuario). --pure NO desactiva MCP (solo plugins), asi que:
    - XDG_CONFIG_HOME apunta a un dir vacio -> ignora ~/.config/opencode/opencode.json
      (que registra codegraph + pencil como MCP servers globales).
    - opencode.json del repo (registra el MCP de leo-code) se renombra un instante.
    Requiere --batch 1 (serial): el rename no es seguro con OC corriendo en paralelo."""
    t0 = time.time()
    repo = Path(repo_path)
    local_cfg = repo / "opencode.json"
    local_cfg_bak = repo / "opencode.json.bench_bak"
    renamed = False
    try:
        if local_cfg.exists():
            local_cfg.rename(local_cfg_bak)
            renamed = True

        empty_xdg = Path("benchmark/.oc_empty_config")
        empty_xdg.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
               "PYTHONIOENCODING": "utf-8", "XDG_CONFIG_HOME": str(empty_xdg.resolve()),
               # opencode (bun) confia en $PWD heredado por encima del cwd real:
               # con PWD apuntando al repo principal, resolvia la raiz del proyecto
               # ALLI y editaba el repo real pese al aislamiento (visto en su DB:
               # "cd C:\...\leo-code && ..." en cada bash). Forzar PWD a la copia.
               "PWD": os.path.abspath(repo_path)}
        import shutil
        oc_bin = shutil.which("opencode") or "opencode"  # Windows: resuelve opencode.cmd
        r = subprocess.run(
            [oc_bin, "run", query, "-m", "deepseek/deepseek-chat", "--format", "json"],
            capture_output=True, text=True, timeout=180, cwd=repo_path, env=env, encoding="utf-8", errors="replace",
        )
        p = parse_oc_events(r.stdout)
        response = p["response"] or (r.stderr or "").strip()
        return {"system": "OC", "response": response[:4000], "tokens": p["tokens"],
                "mcp_calls": p["mcp_calls"], "native_calls": p["native_calls"],
                "redundant_native_after_ctx": p["redundant_native_after_ctx"],
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"system": "OC", "response": "[Timeout]", "tokens": 0, "duration_ms": 180000}
    except FileNotFoundError:
        return {"system": "OC", "response": "[opencode not installed]", "tokens": 0, "duration_ms": 0}
    except Exception as e:
        return {"system": "OC", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}
    finally:
        if renamed and local_cfg_bak.exists():
            local_cfg_bak.rename(local_cfg)


def run_oc_mcp_subprocess(query: str, repo_path: str) -> dict:
    """opencode CON el MCP de leo-code habilitado (opencode.json del repo intacto),
    pero SIN helpers globales (codegraph/pencil) — misma XDG_CONFIG_HOME vacia que
    run_oc_subprocess, solo que aqui NO se renombra opencode.json.
    Mide: agente generico + motor de leo-code vs LEO nativo (mismo motor, integracion propia)."""
    t0 = time.time()
    repo = Path(repo_path)
    try:
        empty_xdg = Path("benchmark/.oc_empty_config")
        empty_xdg.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
               "PYTHONIOENCODING": "utf-8", "XDG_CONFIG_HOME": str(empty_xdg.resolve()),
               # opencode (bun) confia en $PWD heredado por encima del cwd real:
               # con PWD apuntando al repo principal, resolvia la raiz del proyecto
               # ALLI y editaba el repo real pese al aislamiento (visto en su DB:
               # "cd C:\...\leo-code && ..." en cada bash). Forzar PWD a la copia.
               "PWD": os.path.abspath(repo_path)}
        import shutil
        oc_bin = shutil.which("opencode") or "opencode"
        r = subprocess.run(
            [oc_bin, "run", query, "-m", "deepseek/deepseek-chat", "--format", "json"],
            capture_output=True, text=True, timeout=180, cwd=repo_path, env=env, encoding="utf-8", errors="replace",
        )
        p = parse_oc_events(r.stdout)
        response = p["response"] or (r.stderr or "").strip()
        return {"system": "OCMCP", "response": response[:4000], "tokens": p["tokens"],
                "mcp_calls": p["mcp_calls"], "native_calls": p["native_calls"],
                "redundant_native_after_ctx": p["redundant_native_after_ctx"],
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"system": "OCMCP", "response": "[Timeout]", "tokens": 0, "duration_ms": 180000}
    except FileNotFoundError:
        return {"system": "OCMCP", "response": "[opencode not installed]", "tokens": 0, "duration_ms": 0}
    except Exception as e:
        return {"system": "OCMCP", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


async def run_no_direct_async(query: str) -> dict:
    from leo_code.rag.llm import get_provider
    provider = get_provider("openai",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com", model="deepseek-chat")
    t0 = time.time()
    resp = await provider.generate([{"role": "user", "content": query}], tools=[], temperature=0.2)
    return {"system": "NO", "response": (resp.text or "")[:4000],
            "tokens": resp.usage.input_tokens + resp.usage.output_tokens,
            "duration_ms": int((time.time() - t0) * 1000)}


async def run_batch(tasks: list[dict], repo_path: str, systems: list[str]) -> list[dict]:
    """Ejecuta en paralelo, SIN judge."""
    async def run_one(task, sys_name):
        tid = task["id"]
        print(f"    [{sys_name}] {tid} ...")
        try:
            if sys_name == "LEO":
                r = await asyncio.to_thread(run_leo_subprocess, task["query"], repo_path)
            elif sys_name == "RAG":
                r = await asyncio.to_thread(run_leo_rag_subprocess, task["query"], repo_path)
            elif sys_name == "SMART":
                r = await asyncio.to_thread(run_leo_smart_subprocess, task["query"], repo_path)
            elif sys_name == "OC":
                r = await asyncio.to_thread(run_oc_subprocess, task["query"], repo_path)
            elif sys_name == "OCMCP":
                r = await asyncio.to_thread(run_oc_mcp_subprocess, task["query"], repo_path)
            else:
                r = await run_no_direct_async(task["query"])
            r["task_id"] = tid
            esc = " escalated" if r.get("escalated") else ""
            print(f"      tok={r.get('tokens',0)} time={r.get('duration_ms',0)}ms{esc}")
            return r
        except Exception as e:
            print(f"      ERR: {e}")
            return {"system": sys_name, "task_id": tid, "response": f"[{e}]", "tokens": 0, "duration_ms": 0}

    coros = [run_one(task, s) for task in tasks for s in systems if s in ("LEO", "RAG", "SMART", "OC", "OCMCP", "NO")]
    return await asyncio.gather(*coros)


def judge_results(raw_results: list[dict], tasks: list[dict]) -> list[dict]:
    """Judge secuencial después de ejecutar."""
    task_map = {t["id"]: t for t in tasks}
    for r in raw_results:
        tid = r.get("task_id", "")
        task = task_map.get(tid)
        if task and r.get("response") and r["response"][:1] != "[":
            scores = judge(r["response"], task)
            r["scores"] = scores
            r["score_total"] = score_summary(scores)
        else:
            r["scores"] = {"relevancia": 1, "correccion": 1, "completitud": 1, "accionabilidad": 1}
            r["score_total"] = 1.0
        print(f"    Judge [{r['system']}] {tid}: {r['score_total']:.1f}/10")
    return raw_results


def print_summary(results: list[dict]):
    print("\n" + "=" * 80)
    print("LEO-CODE vs OPENCODE - BENCHMARK REAL")
    print(f"Model: {MODEL}")
    print("=" * 80)
    by_sys = {}
    for r in results:
        by_sys.setdefault(r["system"], []).append(r)
    for s in ["LEO", "RAG", "SMART", "OC", "OCMCP", "NO"]:
        valid = [r for r in by_sys.get(s, []) if r.get("response")]
        if not valid:
            continue
        tok = sum(r.get("tokens", 0) for r in valid)
        score = sum(r.get("score_total", 0) for r in valid) / len(valid)
        time_ms = sum(r.get("duration_ms", 0) for r in valid) / len(valid)
        print(f"  {s}: {len(valid)} tasks | {tok:,} tok | {tok/len(valid):.0f} tok/task | {score:.1f}/10 | {time_ms:.0f}ms avg")
        if s == "OCMCP":
            adopted = [r for r in valid if r.get("mcp_calls")]
            n_mcp = sum(sum(r.get("mcp_calls", {}).values()) for r in valid)
            n_red = sum(r.get("redundant_native_after_ctx", 0) for r in valid)
            print(f"       adopcion MCP: {len(adopted)}/{len(valid)} tasks | {n_mcp} llamadas MCP | {n_red} reads nativos redundantes tras get_context")
    leo = [r for r in results if r["system"] == "LEO" and r.get("response")]
    oc = [r for r in results if r["system"] == "OC" and r.get("response")]
    if leo and oc:
        lt = sum(r["tokens"] for r in leo)
        ot = sum(r["tokens"] for r in oc)
        ls = sum(r.get("score_total", 0) for r in leo) / len(leo)
        os = sum(r.get("score_total", 0) for r in oc) / len(oc)
        print(f"\n  Token reduction: {(1 - lt/max(ot,1))*100:.1f}%")
        print(f"  LEO: {ls:.1f}/10 | OC: {os:.1f}/10")
        faster = sum(r.get("duration_ms", 0) for r in oc) / max(sum(r.get("duration_ms", 0) for r in leo), 1)
        print(f"  LEO is {faster:.1f}x faster")
    print("=" * 80)


def _isolated_worktree(repo: str) -> str:
    """Copia desechable del repo SIN ningun puntero git al original: los agentes
    write-enabled editan archivos reales durante el benchmark. Ni worktree (su
    .git apunta al repo principal) ni clone --local (deja remote origin): con
    ambos, opencode resolvia la raiz del proyecto via git y editaba el repo
    REAL con rutas absolutas (confirmado en su DB). git archive de HEAD +
    git init fresco: la copia es un repo independiente sin rastro del origen."""
    import tempfile
    wt = Path(tempfile.mkdtemp(prefix="leo_bench_iso_")) / "repo"
    wt.mkdir(parents=True)
    ar = subprocess.run(["git", "archive", "HEAD"], cwd=repo, check=True,
                        capture_output=True)
    import io, tarfile
    with tarfile.open(fileobj=io.BytesIO(ar.stdout)) as tf:
        tf.extractall(wt)
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=bench@leo", "-c", "user.name=bench",
                 "commit", "-q", "-m", "bench snapshot", "--no-gpg-sign"]):
        subprocess.run(cmd, cwd=str(wt), check=True, capture_output=True)
    print(f"  Copia aislada (git archive): {wt}")
    return str(wt)


def _remove_worktree(repo: str, wt: str):
    import shutil, stat
    def _rw(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)  # .git trae read-only en Windows
        func(path)
    shutil.rmtree(Path(wt).parent, onerror=_rw)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", default="")
    p.add_argument("--systems", default="leo,oc,no")
    p.add_argument("--repo", default=".")
    p.add_argument("--batch", type=int, default=BATCH_SIZE)
    p.add_argument("--isolate", action="store_true",
                   help="corre los agentes contra un git worktree desechable de HEAD")
    args = p.parse_args()

    origin_repo = args.repo
    worktree = None
    if args.isolate:
        worktree = _isolated_worktree(origin_repo)
        args.repo = worktree
    try:
        _run_benchmark(args)
    finally:
        if worktree:
            _remove_worktree(origin_repo, worktree)
            print("  Worktree eliminado — repo original intacto.")


def _run_benchmark(args):

    tasks = json.loads(Path("benchmark/tasks.json").read_text(encoding="utf-8"))
    if args.tasks:
        ids = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in ids]
    systems = [s.strip().upper() for s in args.systems.split(",")]
    batches = [tasks[i:i + args.batch] for i in range(0, len(tasks), args.batch)]

    print(f"Benchmark: {len(tasks)} tasks x {len(systems)} systems")
    print(f"Model: {MODEL} | Batches: {len(batches)} x {args.batch}\n")

    if {"LEO", "RAG", "SMART"} & set(systems):
        os.environ["LEO_QDRANT_PREWARM_PATH"] = _prewarm_index(args.repo)
    # Con --isolate los subprocesos corren con cwd=copia: sembrar alli el cache
    # de indice estructural (si no, cada task re-parsea el repo desde cero).
    # Aplica a LEO/RAG/SMART y tambien a OCMCP (su MCP server carga este cache).
    if ({"LEO", "RAG", "SMART", "OCMCP"} & set(systems)
            and os.path.abspath(args.repo) != os.path.abspath(".")):
        import shutil
        dst = Path(args.repo) / "cache"
        dst.mkdir(exist_ok=True)
        for f in ("kc_index.json.gz", "kc_indexed_repos.json"):
            src = Path("cache") / f
            if src.exists():
                shutil.copy(src, dst / f)

    t0 = time.time()
    all_results = []
    for i, batch in enumerate(batches, 1):
        print(f"  Batch {i}/{len(batches)} - running...")
        raw = asyncio.run(run_batch(batch, args.repo, systems))
        all_results.extend(raw)

    print(f"\n  Judging...")
    all_results = judge_results(all_results, tasks)

    total = int(time.time() - t0)
    print(f"\n  Total: {total}s")
    print_summary(all_results)

    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
