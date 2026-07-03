"""audit — auditoría ESTRICTA de TODAS las promesas de leo-code.

Un check por promesa, con número MEDIDO y umbral duro (sin afirmaciones). Imprime
una tabla verde/roja y sale con código 0 SOLO si pasa el 100%. Reproducible, offline
(cero API key). Es la "fuente oficial": si esto está verde, las promesas son ciertas.

Uso:  python benchmark/audit.py        (o: leo-code audit)
"""

import subprocess
import sys
import zipfile
import glob
from pathlib import Path

# Windows: consola/redirección usa cp1252 y no codifica ✅/❌ → crash. UTF-8 siempre.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
REPO = str(ROOT)


def _cite_real(repo: Path, cite) -> bool:
    fp = Path(cite.file)
    if not fp.is_absolute():
        fp = repo / cite.file
    if not fp.exists():
        return False
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    bare = cite.name.split(".")[-1]
    lo, hi = max(0, cite.line - 3), min(len(lines), cite.line + 3)
    return any(bare in ln for ln in lines[lo:hi])


# ---- cada check: () -> (ok: bool, detalle con número) ----

def c1_tokens():
    from benchmark.token_efficiency import run, UMBRAL_RED
    red, _ = run(REPO)
    return red >= UMBRAL_RED, f"reducción {red*100:.1f}% (umbral {UMBRAL_RED*100:.0f}%)"


def c2_recall_precision():
    from benchmark.token_efficiency import run, UMBRAL_REC
    _, rec = run(REPO)
    from benchmark.agent_vs_agent import run as ava
    _, _, prec = ava(REPO)
    ok = rec >= UMBRAL_REC and prec >= 0.999
    return ok, f"recall {rec*100:.0f}% · precisión estructural {prec*100:.0f}% (cero alucinación)"


def c3_graph_tools():
    from leo_code.rag.indexer import Indexer
    from leo_code.core.graphquery import GraphQuery
    idx = Indexer(); idx.build(REPO, verbose=False)
    g = GraphQuery(idx.get_capsules())
    repo = Path(REPO)
    probes = [g.who_calls("compress"), g.impact("compute_context"),
              g.trace("get_context", "compress"), g.where("Capsule")]
    nonempty = all(p.found for p in probes)
    all_cites = [c for p in probes for c in p.cites]
    real = all(_cite_real(repo, c) for c in all_cites)
    return nonempty and real, f"4 tools OK · {len(all_cites)} citas, todas reales={real}"


def c4_cross():
    from leo_code.core.boundary import _demo as bdemo
    from leo_code.core.orggraph import _demo as odemo
    bdemo(); odemo()  # lanzan AssertionError si fallan (cross-lenguaje + cross-repo)
    return True, "boundary (HTTP) + orggraph (N repos) self-checks OK"


def c5_guardian():
    from leo_code.core.guardian import _demo
    _demo()  # AssertionError si el blast radius / cobertura / cross-lenguaje falla
    return True, "blast radius + cobertura + cross-lenguaje OK"


def c6_agent_uses_engine():
    import inspect
    from leo_code.rag.agent.loop import AgentLoop
    from leo_code.rag.agent.tools import ToolRegistry
    src = inspect.getsource(AgentLoop._build_context)
    # path real: llama engine.compute_context y devuelve ese contexto (no el zero-seed "").
    injects = "engine.compute_context" in src and "return ctx, timings" in src
    t = ToolRegistry()
    has_tools = all(k in t._tools for k in ("trace", "impact", "who_calls", "where"))
    # cablea el cerebro al hacer set_index
    from leo_code.core.parser import Capsule
    t.set_index({"x": Capsule(id="x", type="function", name="x", file_path="a.py",
                              start_line=1, end_line=2, language="python",
                              signature="", content="")})
    wired = t._gq is not None
    return injects and has_tools and wired, \
        f"inyecta compute_context={injects} · tools={has_tools} · GraphQuery cableado={wired}"


def c7_wheels():
    dists = ["leo-code-core", "leo-code", "leo-mcp"]
    whls = {}
    for d in dists:
        hit = glob.glob(str(ROOT / f"packaging/{d}/dist/*.whl"))
        if not hit:
            return False, f"falta wheel de {d} (construye: cd packaging/{d} && python -m build --wheel)"
        whls[d] = set(n for n in zipfile.ZipFile(hit[0]).namelist()
                      if n.endswith(".py") and "dist-info" not in n)
    pairs = [("leo-code-core", "leo-code"), ("leo-code-core", "leo-mcp"), ("leo-code", "leo-mcp")]
    disjoint = all(not (whls[a] & whls[b]) for a, b in pairs)
    return disjoint, f"3 wheels presentes, disjuntos={disjoint}"


def c8_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else "?"
    return r.returncode == 0, f"pytest exit {r.returncode} · {last}"


def c9_mcp_tools():
    from leo_code.server import mcp_server
    names = {t.name for t in mcp_server._GRAPH_TOOLS} | {mcp_server._TOOL.name}
    need = {"get_context", "trace", "impact", "who_calls", "where", "guard"}
    missing = need - names
    return not missing, f"tools MCP: {sorted(names)}" + (f" · faltan {missing}" if missing else "")


CHECKS = [
    ("1. ≥80% menos tokens", c1_tokens),
    ("2. recall + precisión estructural 100%", c2_recall_precision),
    ("3. trace/impact/who_calls/where correctos", c3_graph_tools),
    ("4. cross-repo + cross-lenguaje (HTTP)", c4_cross),
    ("5. guardián (blast radius + cobertura)", c5_guardian),
    ("6. el agente usa su propio motor", c6_agent_uses_engine),
    ("7. 3 wheels instalables y disjuntos", c7_wheels),
    ("8. suite de tests verde", c8_tests),
    ("9. MCP expone tools deterministas", c9_mcp_tools),
]


def main():
    print("=" * 70)
    print("AUDITORÍA DE PROMESAS — leo-code (suma estricta, exit 0 solo al 100%)")
    print("=" * 70)
    results = []
    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"EXCEPCIÓN: {type(e).__name__}: {str(e)[:120]}"
        mark = "✅" if ok else "❌"
        print(f"{mark} {label:<44} {detail}")
        results.append(ok)
    passed = sum(results)
    print("-" * 70)
    print(f"RESULTADO: {passed}/{len(results)} promesas verificadas"
          + ("  →  100% OFICIAL ✅" if passed == len(results) else "  →  INCOMPLETO ❌"))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
