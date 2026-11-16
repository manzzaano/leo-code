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

import os
import subprocess
import sys
from pathlib import Path


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
    # Solo rutas absolutas: una vacía o relativa se resolvería contra la carpeta de ESTE
    # proceso e indexaría otro repo.
    if (not isinstance(cwd, str) or not os.path.isabs(cwd)
            or not os.path.isdir(os.path.join(cwd, ".git"))):
        return None
    # Un home con dotfiles en git: indexaría todo el home en cada sesión abierta ahí.
    if os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(str(Path.home())):
        return None
    cmd = [sys.executable, "-m", "leo_code.cli", "index", cwd]
    _spawn(cmd)
    return cmd


def main() -> int:
    from leo_code.guard_hook import read_payload   # UTF-8 también en Windows
    try:
        run(read_payload())
    except BaseException:   # SystemExit(2) incluido: exit 2 es un bloqueo en Claude Code
        pass   # un fallo del hook no puede molestar al abrir sesión
    return 0


if __name__ == "__main__":
    sys.exit(main())
