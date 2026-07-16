"""C v5 para Claude Code: sustitución PASIVA del output de Read.

Port de .opencode/plugin/leo-first-action.js — misma lógica medida en M1:
un Read de archivo entero de código devuelve la vista comprimida del AST
(leo_code.filectx, body-chars 1400) en vez del crudo. Sin turnos extra ni
vetos. Rango offset/limit = crudo (editar exige líneas exactas).

Mecanismo: hook PostToolUse con hookSpecificOutput.updatedToolOutput.
Gated: solo actúa con LEO_FORCE=1 (benchmark lo pone; sin opt-in, no-op).
"""
import json
import os
import re
import subprocess
import sys

CODE_EXT = re.compile(r"\.(py|ts|tsx|js|jsx|java|kt|go|rs|rb|php|cs|ex|exs)$", re.I)


def debug(line: str) -> None:
    if os.environ.get("LEO_DEBUG") != "1":
        return
    with open(os.path.join(os.path.dirname(__file__), "_swap_debug.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def swapped_output(resp, compressed: str):
    """(texto_original, tool_response con el texto sustituido) o (texto, None).

    updatedToolOutput DEBE cumplir el outputSchema del tool (el binario lo
    valida y si no encaja descarta el hook): para Read es
    {type:'text', file:{content,...}} → mutamos la respuesta original.
    """
    if isinstance(resp, str):
        return resp, compressed
    if isinstance(resp, dict):
        f = resp.get("file")
        if isinstance(f, dict) and isinstance(f.get("content"), str):
            new = json.loads(json.dumps(resp))
            new["file"]["content"] = compressed
            new["file"]["numLines"] = compressed.count("\n") + 1
            return f["content"], new
        for k in ("content", "output", "text"):
            if isinstance(resp.get(k), str):
                new = dict(resp)
                new[k] = compressed
                return resp[k], new
    return json.dumps(resp, ensure_ascii=False), None


def main() -> None:
    if os.environ.get("LEO_FORCE") != "1":
        return
    # stdout de Windows arranca en cp1252; el JSON del hook lleva UTF-8 (→, ñ...).
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Read":
        return
    args = data.get("tool_input") or {}
    fp = str(args.get("file_path") or "").replace("\\", "/")
    surgical = args.get("offset") is not None or args.get("limit") is not None
    if not fp or surgical or not CODE_EXT.search(fp):
        return
    repo = data.get("cwd") or "."
    try:
        r = subprocess.run(
            [sys.executable, "-m", "leo_code.filectx", fp, "--repo", repo, "--body-chars", "1400"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, cwd=repo, env={**os.environ, "PYTHONUTF8": "1"},
        )
        compressed = r.stdout if r.returncode == 0 else ""
        original, new_output = swapped_output(data.get("tool_response"), compressed)
        # Solo sustituir si de verdad ahorra (>25%): si no, el crudo ya es barato.
        swap = new_output is not None and len(compressed) > 200 and len(compressed) < len(original) * 0.75
        debug(f"SWAP {json.dumps({'fp': fp, 'exit': r.returncode, 'comp': len(compressed), 'orig': len(original), 'swap': swap})}")
        if swap:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedToolOutput": new_output,
                }
            }, ensure_ascii=False))
    except Exception as e:  # nunca romper el Read del agente
        debug("SWAPERR " + repr(e))


if __name__ == "__main__":
    main()
