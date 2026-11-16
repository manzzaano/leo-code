"""index_hook — al abrir sesión en un repo git, indexa en segundo plano.

Hook `SessionStart` de Claude Code (lo instala `leo-mcp init --user`). El aviso antes de
editar (guard_hook) nunca construye índice; sin este hook se quedaría mudo en un repo
nuevo hasta que el agente llamara a get_context o graph.

Reglas duras, todas con test:
  · NADA en stdout: en SessionStart el stdout entra en el contexto del agente.
  · NUNCA sale con código != 0 (payloads basura incluidos).
  · NO espera al indexado: lo lanza desacoplado y sale.
  · LEO_INDEX_HOOK=0 lo apaga.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _spawn(cmd: list[str]) -> None:
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def run(payload: dict) -> list[str] | None:
    """Lanza el indexado si `cwd` es la raíz de un repo git. Devuelve el comando o None."""
    if os.getenv("LEO_INDEX_HOOK") == "0" or not isinstance(payload, dict):
        return None
    cwd = payload.get("cwd")
    # ponytail: solo la raíz del repo (como el hook de craft); subir hasta .git si alguien
    # abre sesiones en subcarpetas
    if not isinstance(cwd, str) or not os.path.isdir(os.path.join(cwd, ".git")):
        return None
    cmd = [sys.executable, "-m", "leo_code.cli", "index", cwd]
    _spawn(cmd)
    return cmd


def main() -> int:
    try:
        run(json.loads(sys.stdin.read() or "{}"))
    except Exception:
        pass   # un fallo del hook no puede molestar al abrir sesión
    return 0


if __name__ == "__main__":
    sys.exit(main())
