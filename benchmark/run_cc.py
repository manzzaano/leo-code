"""Mini-benchmark M2: Claude Code vanilla (CC) vs Claude Code + leo (CCMCP).

Uso: python benchmark/run_cc.py [--tasks t1,t2] [--label cc_mini_run1]

Espejo de run_real.py para el harness Claude Code:
- Copia aislada de HEAD (git archive) — los agentes editan archivos reales.
- CC vanilla: sin MCP (--strict-mcp-config sin --mcp-config) y sin LEO_FORCE.
- CCMCP: --mcp-config .mcp.json + LEO_FORCE=1 (activa hook swap de Read) +
  steering AGENTS.md via --append-system-prompt.
- Telemetría: el JSON de `claude -p` da la sesión padre; la verdad completa
  (subagentes Task incluidos — lección del sesgo opencode 14/07) sale del
  transcript JSONL de ~/.claude/projects/, deduplicando usage por message.id.
- Serial (batch 1): atribución limpia de transcripts y sin carreras de archivos.

Lanzar SIEMPRE desacoplado (Start-Process): el shell sandboxeado del agente
no tiene red y produce 100% timeouts (lección 2026-07-14).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.run_real import (_isolated_worktree, _remove_worktree,
                                _run_capture, judge_results, RESULTS_DIR)

# El judge necesita DEEPSEEK_API_KEY; el proceso desacoplado no hereda el shell
# del usuario → cargar .env de la raíz (solo claves ausentes).
for _line in (Path(__file__).parent.parent / ".env").read_text(encoding="utf-8").splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

MODEL = "haiku"
TIMEOUT = 300
NO_DEFER = False  # --no-defer: ENABLE_TOOL_SEARCH=false (tools MCP upfront, sin ToolSearch)
DEFAULT_TASKS = "t1_code_query,t2_debug,t5_search,t7_code_edit,t14_cross_file"
NATIVE_EXPLORE = {"Read", "Grep", "Glob"}
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def transcript_stats(session_id: str) -> dict:
    """Tokens y tool-calls del transcript JSONL, subagentes/sidechains incluidos.

    Una respuesta del API puede partirse en varias filas (texto + tool_use)
    que repiten el mismo message.id y usage → dedupe por id antes de sumar.
    Unidades = in+out+cache_read+cache_creation (comparable al criterio opencode:
    stream total == in+out+reasoning+cache, verificado exacto el 14/07).
    """
    hits = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    if not hits:
        return {"tokens_jsonl": 0, "tool_seq": [], "transcript": None}
    usage_by_id, tool_seq = {}, []
    for line in hits[0].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        m = d.get("message") or {}
        u = m.get("usage")
        if u and m.get("id"):
            usage_by_id[m["id"]] = (u.get("input_tokens", 0) + u.get("output_tokens", 0)
                                    + u.get("cache_read_input_tokens", 0)
                                    + u.get("cache_creation_input_tokens", 0))
        content = m.get("content")
        if isinstance(content, list):
            tool_seq.extend(b.get("name", "?") for b in content
                            if isinstance(b, dict) and b.get("type") == "tool_use")
    return {"tokens_jsonl": sum(usage_by_id.values()), "tool_seq": tool_seq,
            "transcript": str(hits[0])}


def tool_telemetry(tool_seq: list[str]) -> dict:
    """Adopción MCP vs exploración nativa, y relecturas tras get_context."""
    mcp_calls, native_calls = {}, {}
    redundant, seen_ctx = 0, False
    for t in tool_seq:
        # Claude Code normaliza el nombre del server: "leo-code" → "mcp__leo_code__*"
        if t.startswith(("mcp__leo_code__", "mcp__leo-code__")):
            b = t.rsplit("__", 1)[-1]
            mcp_calls[b] = mcp_calls.get(b, 0) + 1
            seen_ctx = seen_ctx or b == "get_context"
        else:
            native_calls[t] = native_calls.get(t, 0) + 1
            if seen_ctx and t in NATIVE_EXPLORE:
                redundant += 1
    return {"mcp_calls": mcp_calls, "native_calls": native_calls,
            "redundant_native_after_ctx": redundant}


def run_cc(query: str, repo_path: str, leo: bool) -> dict:
    name = "CCMCP" if leo else "CC"
    t0 = time.time()
    cc_bin = shutil.which("claude") or "claude"
    cmd = [cc_bin, "-p", query, "--model", MODEL, "--output-format", "json",
           "--dangerously-skip-permissions", "--strict-mcp-config"]
    env = {**os.environ, "PYTHONUTF8": "1", "LEO_DEBUG": "1"}
    env.pop("LEO_FORCE", None)
    if leo:
        env["LEO_FORCE"] = "1"
        if NO_DEFER:
            env["ENABLE_TOOL_SEARCH"] = "false"
        cmd += ["--mcp-config", ".mcp.json"]
        steering = Path(repo_path) / "_leo_steering.md"  # AGENTS.md renombrado en la copia
        if steering.exists():
            # Solo la sección MCP: el style guide ("conciso") sesgaría al judge
            # contra CCMCP — CC vanilla no recibe steering de estilo (en opencode
            # ambos autocargaban AGENTS.md entero; aquí hay que igualar a mano).
            txt = steering.read_text(encoding="utf-8")
            txt = txt.split("## Style Guide")[0]
            cmd += ["--append-system-prompt", txt]
    try:
        r = _run_capture(cmd, timeout=TIMEOUT, cwd=repo_path, env=env)
        out = json.loads((r.stdout or "").strip() or "{}")
        sid = out.get("session_id", "")
        stats = transcript_stats(sid) if sid else {"tokens_jsonl": 0, "tool_seq": [], "transcript": None}
        u = out.get("usage") or {}
        stream_tokens = (u.get("input_tokens", 0) + u.get("output_tokens", 0)
                         + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0))
        return {"system": name, "response": (out.get("result") or "")[:4000],
                "tokens": stats["tokens_jsonl"] or stream_tokens,
                "tokens_stream": stream_tokens, "session_id": sid,
                "num_turns": out.get("num_turns"), "cost_usd": out.get("total_cost_usd"),
                "duration_ms": int((time.time() - t0) * 1000),
                **tool_telemetry(stats["tool_seq"])}
    except subprocess.TimeoutExpired:
        return {"system": name, "response": "[Timeout]", "tokens": 0,
                "duration_ms": TIMEOUT * 1000}
    except Exception as e:
        return {"system": name, "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", default=DEFAULT_TASKS)
    p.add_argument("--label", default="cc_mini_run1")
    p.add_argument("--no-defer", action="store_true",
                   help="CCMCP con ENABLE_TOOL_SEARCH=false (tools MCP upfront)")
    args = p.parse_args()
    global NO_DEFER
    NO_DEFER = args.no_defer

    tasks = json.loads(Path("benchmark/tasks.json").read_text(encoding="utf-8"))
    ids = set(args.tasks.split(","))
    tasks = [t for t in tasks if t["id"] in ids]
    print(f"CC mini-bench: {len(tasks)} tasks x 2 systems | model={MODEL}")

    wt = _isolated_worktree(".")
    try:
        # Sin CLAUDE.md (ordena leer PLAN.md: ruido para ambos). AGENTS.md fuera
        # del auto-load: solo CCMCP lo recibe via --append-system-prompt.
        (Path(wt) / "CLAUDE.md").unlink(missing_ok=True)
        agents = Path(wt) / "AGENTS.md"
        if agents.exists():
            agents.rename(Path(wt) / "_leo_steering.md")
        # Cache de índice estructural en la copia (como run_real para OCMCP).
        dst = Path(wt) / "cache"
        dst.mkdir(exist_ok=True)
        for f in ("kc_index.json.gz", "kc_indexed_repos.json"):
            src = Path("cache") / f
            if src.exists():
                shutil.copy(src, dst / f)

        results = []
        for leo in (False, True):
            for t in tasks:
                print(f"  [{'CCMCP' if leo else 'CC'}] {t['id']} ...", flush=True)
                r = run_cc(t["query"], wt, leo)
                r["task_id"] = t["id"]
                print(f"    tok={r.get('tokens',0):,} stream={r.get('tokens_stream',0):,} "
                      f"dur={r.get('duration_ms',0)}ms turns={r.get('num_turns')}", flush=True)
                results.append(r)

        swap_log = Path(wt) / ".claude" / "hooks" / "_swap_debug.log"
        swaps = swap_log.read_text(encoding="utf-8").splitlines() if swap_log.exists() else []

        print("\n  Judging...", flush=True)
        results = judge_results(results, tasks)

        payload = {"model": MODEL, "tasks": sorted(ids), "swap_log": swaps, "results": results}
        out = RESULTS_DIR / f"{args.label}.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Guardado: {out}")

        for s in ("CC", "CCMCP"):
            rs = [r for r in results if r["system"] == s]
            tok = sum(r["tokens"] for r in rs)
            sc = sum(r.get("score_total", 0) for r in rs) / max(len(rs), 1)
            dur = sum(r["duration_ms"] for r in rs) / max(len(rs), 1)
            print(f"  {s}: {tok:,} tok | {sc:.2f}/10 | {dur:.0f}ms avg")
    finally:
        _remove_worktree(".", wt)
        print("  Copia eliminada.")


if __name__ == "__main__":
    main()
