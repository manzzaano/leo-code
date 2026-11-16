"""leo-mcp — CLI del producto.

  leo-mcp [serve]            servidor MCP por stdio (lo que lanza el cliente MCP)
  leo-mcp index [repo]       indexa y enseña qué ve leo-mcp (lenguajes, símbolos más usados)
  leo-mcp doctor [repo]      comprueba la instalación y da el snippet de configuración
  leo-mcp init [--client X]  registra leo-mcp en la config MCP del proyecto
  leo-mcp init --user        lo registra para el usuario (Claude Code), sin tocar el repo

Salida al usuario en inglés. `serve` no escribe NADA en stdout (canal JSON-RPC).
"""

import argparse
import functools
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from leo_code import __version__

CLIENTS = ("claude", "cursor", "opencode", "codex")


@functools.lru_cache(maxsize=1)
def _uv_cache_dir() -> str | None:
    """`uv cache dir` del uv que nos lanzó. `UV` (uv >= 0.6) es la ruta de ese uv y se hereda
    a los hijos; sin ella no nos lanzó uv y no hay nada que preguntar."""
    uv = os.environ.get("UV")
    if not uv:
        return None
    try:
        out = subprocess.run([uv, "cache", "dir"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _ephemeral(path: str) -> bool:
    """¿Está en la caché de uv (lo que corre `npx`/`uvx`)? La doc de uv trata esos entornos
    como desechables: `uv cache clean` los borra.

    Primero la señal documentada (dentro de `uv cache dir`); si no, el bucket `archive-v*`
    donde uv crea esos entornos (no documentado), que cubre `uvx --no-cache`: ahí el entorno
    vive en un temporal fuera de `uv cache dir`.
    """
    cache = _uv_cache_dir()
    if cache:
        p, c = (os.path.normcase(os.path.abspath(x)) for x in (path, cache))
        try:
            if os.path.commonpath([p, c]) == c:
                return True
        except ValueError:   # otra unidad en Windows
            pass
    return "archive-v" in path.replace("\\", "/")


def _launch() -> list[str]:
    """Comando que el cliente MCP ejecutará.

    El `leo-mcp` del entorno que está corriendo y, si no, el del PATH (uv tool install / pip):
    arranca sin red y es esta misma versión. Si no, uvx con la versión publicada fijada, como
    el launcher npm (o LEO_MCP_FROM). Un binario dentro de la caché de uv (lo que ve un `uvx`
    efímero) no vale: uv puede borrarlo y la config quedaría rota.
    """
    for exe in (shutil.which("leo-mcp", path=sysconfig.get_path("scripts")), shutil.which("leo-mcp")):
        if exe and not _ephemeral(exe):
            return [exe]
    return ["uvx", "--from", os.environ.get("LEO_MCP_FROM", f"leo-mcp=={__version__}"), "leo-mcp"]


def _quiet_index(repo: str) -> dict | None:
    """ensure_structural con los print() del indexer desviados a stderr."""
    from leo_code import engine
    real, sys.stdout = sys.stdout, sys.stderr
    try:
        return engine.ensure_structural(repo)
    finally:
        sys.stdout = real


def cmd_serve(_args) -> int:
    from leo_code.server.mcp_server import run_stdio
    run_stdio()
    return 0


def cmd_index(args) -> int:
    from leo_code import engine
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"not a directory: {repo}", file=sys.stderr)
        return 2
    stats = _quiet_index(repo)
    caps = engine._repo_caps(engine._get_indexer(), repo)
    if not caps:
        print(f"No indexable source files found in {repo}.")
        return 1
    langs = stats["by_language"] if stats else {}
    how = f"{stats['action']} in {stats['seconds']}s" if stats else "already up to date"
    print(f"leo-mcp indexed {repo}  ({how})")
    print(f"  {len(caps):,} symbols in {len({c.file_path for c in caps}):,} files")
    for lang, n in langs.items():
        print(f"    {lang:<12}{n:>8,}")
    from leo_code.core.graphquery import GraphQuery
    gq = GraphQuery({c.id: c for c in caps})
    n_callers = lambda c: len({x.name for x in gq._callers_of(c.name)})
    hubs = sorted((c for c in caps if c.type not in ("module", "file_header", "variable", "constant")),
                  key=n_callers, reverse=True)[:5]
    hubs = [c for c in hubs if n_callers(c)]
    if hubs:
        print("  most depended-on (run graph op=guard before touching these):")
        for c in hubs:
            rel = os.path.relpath(c.file_path, repo).replace("\\", "/")
            print(f"    {c.name:<32} {n_callers(c):>3} callers  {rel}:{c.start_line}")
    print(f"  index cache: {engine.repo_index_path(repo)}")
    return 0


def cmd_doctor(args) -> int:
    from importlib import metadata, util
    from leo_code import engine
    ok = True

    def row(name, good, detail):
        nonlocal ok
        ok = ok and good is not False
        mark = {True: "ok ", False: "ERR", None: "-  "}[good]
        print(f"  [{mark}] {name:<11} {detail}")

    print(f"leo-mcp {__version__} doctor")
    py_ok = sys.version_info >= (3, 11)
    row("python", py_ok, f"{platform.python_version()} ({sys.executable})")
    try:
        row("mcp", True, f"{metadata.version('mcp')}")
    except metadata.PackageNotFoundError:
        row("mcp", False, "not installed")
    try:
        from leo_code.core.parser_ts import _parser
        _parser("tsx")
        row("typescript", True, "tree-sitter AST parser (TS/TSX/JS)")
    except Exception as e:
        row("typescript", False, f"tree-sitter unavailable, falling back to regex: {e}")
    row("semantic", None, "on (sentence-transformers)" if engine.SEMANTIC
        else "off (optional: install the leo-mcp[semantic] extra)")
    # El watcher decide si cada llamada re-escanea el repo: sin él, en un árbol grande
    # se pagan segundos por llamada. Diagnosticarlo aquí y no en un cuelgue raro.
    repo = os.path.abspath(args.repo)
    if not engine._WATCH:
        row("watch", None, "off (LEO_WATCH=0) - every call rescans the tree")
    elif engine._get_indexer().watch(repo):
        row("watch", True, "filesystem events - a call with no changes does no rescan")
        engine._get_indexer().stop_watch(repo)
    else:
        row("watch", None, "unavailable here - falling back to rescanning the tree "
                           "(watchdog missing, or the OS ran out of watches)")
    # "no me avisa" tiene dos causas posibles y ninguna es obvia: el hook no está
    # instalado, o lo está apagado. Que se vea aquí.
    # Vale el settings del repo (init) o el del usuario (init --user).
    texts = [f.read_text(encoding="utf-8", errors="replace")
             for f in (Path(repo) / ".claude" / "settings.json", _user_settings()) if f.exists()]

    def hook_state(module: str) -> bool | None:
        states = [_hook_python_ok(t, module) for t in texts]
        return True if True in states else (False if False in states else None)

    stale = "points to a Python that no longer exists (re-run: leo-mcp init)"
    idx = hook_state("leo_code.index_hook")
    if os.getenv("LEO_INDEX_HOOK") == "0":
        row("index hook", None, "off (LEO_INDEX_HOOK=0)")
    elif idx:
        row("index hook", True, "indexes a git repo in the background when a session opens")
    elif idx is False:
        row("index hook", None, stale)
    else:
        row("index hook", None, "not installed (run: leo-mcp init --user)")
    installed = hook_state("leo_code.guard_hook")
    if os.getenv("LEO_GUARD_HOOK") == "0":
        row("guard hook", None, "off (LEO_GUARD_HOOK=0)")
    elif installed:
        row("guard hook", True, "warns before editing a symbol whose dependents have no test")
    elif installed is False:
        row("guard hook", None, stale)
    elif _ephemeral(sys.executable):
        row("guard hook", None, "not installed here (needs `uv tool install leo-mcp`, then leo-mcp init)")
    else:
        row("guard hook", None, "not installed here (run: leo-mcp init)")
    row("cache", None, str(engine._CACHE_DIR))
    idx_path = engine.repo_index_path(repo)
    row("repo", None, f"{repo} - " + ("indexed" if idx_path.exists() else "not indexed yet (run: leo-mcp index)"))
    if util.find_spec("sentence_transformers") and not engine.SEMANTIC:
        row("note", None, "semantic packages installed but LEO_SEMANTIC=0")

    launch = " ".join(_launch())
    print("\nAdd leo-mcp to your agent:")
    print(f"  Claude Code   claude mcp add leo-mcp -- {launch}")
    print("  Claude Code, all repos (writes nothing in them)   leo-mcp init --user")
    print(f"  any client    leo-mcp init --client {{{','.join(CLIENTS)}}}")
    print("\n" + ("Ready." if ok else "Fix the ERR rows above."))
    return 0 if ok else 1


def _hook_command(module: str = "leo_code.guard_hook") -> str:
    """Comando de un hook de leo, apuntando a ESTE intérprete.

    No pasa por `npx`/`uvx` a propósito: el hook corre en cada edición y un arranque de
    npx por edición no cabe en el presupuesto (medido con el intérprete directo: 0,28 s
    sobre un índice de 1.220 símbolos). Si mueves o reinstalas el entorno, vuelve a
    ejecutar `leo-mcp init`.
    """
    # Claude Code lanza los hooks con Git Bash en Windows: sin comillas y con `\` bash se
    # come las barras (exit 127). Con comillas y `/` vale en bash y en cmd.
    # ponytail: una ruta POSIX con `\` literal se rompería; no existe en la práctica.
    exe = sys.executable.replace("\\", "/")
    return f'"{exe}" -m {module}'


def _hook_python_ok(settings_text: str, module: str) -> bool | None:
    """None si no hay hook de `module`; si lo hay, ¿existe el python al que apunta?
    Solo buscar el nombre daba "ok" con el entorno borrado o movido."""
    try:
        data = json.loads(settings_text or "{}")
    except json.JSONDecodeError:
        return None
    found = None
    groups = data.get("hooks", {}) if isinstance(data, dict) else {}
    for entries in (groups.values() if isinstance(groups, dict) else []):
        for group in entries if isinstance(entries, list) else []:
            for h in group.get("hooks", []) if isinstance(group, dict) else []:
                cmd = str(h.get("command", "")) if isinstance(h, dict) else ""
                if f"-m {module}" in cmd:
                    exe = cmd.split(f" -m {module}")[0].strip().strip('"')
                    found = found or os.path.exists(exe)
    return found


def _install_hook(target: Path, event: str, matcher: str, module: str) -> int:
    """Añade un hook de leo a un settings.json de Claude Code, sin pisar lo que haya.
    Idempotente; si el intérprete cambió de sitio, re-apunta la entrada existente."""
    data = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            print(f"{target} is not valid JSON ({e}); not touching it.", file=sys.stderr)
            return 1
    entries = data.setdefault("hooks", {}).setdefault(event, [])
    command = _hook_command(module)
    for group in entries:
        for h in group.get("hooks", []):
            if module in str(h.get("command", "")):
                if h.get("command") != command:
                    h["command"] = command   # el entorno cambió de sitio: repuntar
                    _write_json(target, data)
                    print(f"Updated the leo-mcp {event} hook in {target}")
                    return 0
                print(f"leo-mcp {event} hook already in {target}")
                return 0
    entry = {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
    entries.append(entry)
    _write_json(target, data)
    print(f"Added to {target}:")
    print(json.dumps({"hooks": {event: [entry]}}, indent=2))
    return 0


def _install_guard_hook(root: Path) -> int:
    """Añade el hook PreToolUse al settings.json del proyecto, sin pisar lo que haya."""
    target = root / ".claude" / "settings.json"
    code = _install_hook(target, "PreToolUse", "Edit|Write", "leo_code.guard_hook")
    if code == 0:
        print("  It warns you before Claude edits a symbol whose dependents have no test, and"
              " stays quiet otherwise. It never blocks an edit. Turn it off with LEO_GUARD_HOOK=0"
              " or by deleting those lines.")
    return code


def _maybe_hook(args, root: Path) -> int:
    """El hook es lo que hace que leo hable sin que el agente se acuerde de preguntar.
    Solo Claude Code: es el único harness con PreToolUse."""
    if args.client == "claude" and not getattr(args, "no_hook", False):
        if _ephemeral(sys.executable):
            # El hook apunta a este intérprete (ver _hook_command): desde la caché de uv
            # fallaría en cada edición el día que uv lo borre.
            print("Guard hook not installed: leo-mcp is running from uv's cache (npx/uvx),"
                  " which uv may delete. To get it: `uv tool install leo-mcp`, then run"
                  " `leo-mcp init` again.")
            return 0
        return _install_guard_hook(root)
    return 0


def _write_json(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _user_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _register_user_mcp(launch: list[str]) -> str:
    """Registra el MCP con scope user a través del CLI de Claude Code, que es el dueño de
    ~/.claude.json (lo reescribe mientras corre: editarlo a mano pisaría o sería pisado).
    Devuelve "added", "exists" o "manual". Un registro existente no se toca nunca: puede
    llevar variables de entorno del usuario."""
    claude = shutil.which("claude")
    if claude:
        try:
            out = subprocess.run([claude, "mcp", "add", "--scope", "user", "leo-mcp", "--", *launch],
                                 capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            out = None
        if out is not None and out.returncode == 0:
            print("Added leo-mcp to Claude Code (user scope, all your projects).")
            return "added"
        if out is not None and "already exists" in f"{out.stdout}{out.stderr}":
            print("leo-mcp is already registered in Claude Code (user scope); leaving it as is.")
            return "exists"
    shown = " ".join(f'"{a}"' if " " in a else a for a in launch)
    print("Register the MCP server by running:\n"
          f"  claude mcp add --scope user leo-mcp -- {shown}")
    return "manual"


def _init_user(args) -> int:
    """`init --user`: servidor + aviso antes de editar + índice al abrir sesión, para todos
    los repos del usuario y sin escribir nada en ninguno."""
    if args.client != "claude":
        print("--user is only supported for Claude Code (--client claude).", file=sys.stderr)
        return 2
    _register_user_mcp(_launch())
    if getattr(args, "no_hook", False):
        return 0
    if _ephemeral(sys.executable):
        print("Hooks not installed: leo-mcp is running from uv's cache (npx/uvx), which uv may"
              " delete. To get them: `uv tool install leo-mcp`, then run `leo-mcp init --user` again.")
        return 0
    target = _user_settings()
    code = _install_hook(target, "PreToolUse", "Edit|Write", "leo_code.guard_hook")
    if code:
        return code
    code = _install_hook(target, "SessionStart", "startup|resume", "leo_code.index_hook")
    if code == 0:
        print("  PreToolUse warns before Claude edits a symbol whose dependents have no test"
              " (off: LEO_GUARD_HOOK=0). SessionStart indexes a git repo in the background when"
              " a session opens (off: LEO_INDEX_HOOK=0). Neither ever blocks Claude.")
    return code


def cmd_init(args) -> int:
    if getattr(args, "user", False):
        return _init_user(args)
    root = Path(args.repo).resolve()
    launch = _launch()
    if args.client == "codex":
        print("Add this to ~/.codex/config.toml:\n")
        print("[mcp_servers.leo-mcp]")
        # json.dumps escapa como una cadena básica de TOML (rutas de Windows con \)
        print(f"command = {json.dumps(launch[0])}")
        print("args = [" + ", ".join(json.dumps(a) for a in launch[1:]) + "]")
        return 0
    std = {"command": launch[0], "args": launch[1:]}
    target, key, entry = {
        "claude": (root / ".mcp.json", "mcpServers", std),
        "cursor": (root / ".cursor" / "mcp.json", "mcpServers", std),
        "opencode": (root / "opencode.json", "mcp", {"type": "local", "command": launch, "enabled": True}),
    }[args.client]
    data = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            # Nunca reescribir una config que no entendemos: se perderían otros servers.
            print(f"{target} is not valid JSON ({e}); not touching it. Add manually:\n"
                  + json.dumps({key: {"leo-mcp": entry}}, indent=2), file=sys.stderr)
            return 1
    servers = data.setdefault(key, {})
    old = servers.get("leo-mcp")
    # Repuntar una config vieja (p. ej. la de 0.3.0 a git+https) sin perder las claves
    # que haya puesto el usuario, como `env`.
    new = {**old, **entry} if isinstance(old, dict) else entry
    if old == new:
        # Sin return: quien ya tenía el server configurado es justo quien aún no tiene
        # el hook, y salir aquí dejaba a todos los usuarios previos sin él.
        print(f"leo-mcp is already configured in {target}")
        return _maybe_hook(args, root)
    servers["leo-mcp"] = new
    _write_json(target, data)
    done = "Updated leo-mcp in" if old else "Added leo-mcp to"
    print(f"{done} {target}. Restart {args.client} to load it.")
    return _maybe_hook(args, root)


def main(argv: list[str] | None = None) -> int:
    # Antes de imprimir nada: el texto del producto lleva `·`/`→` y la consola de
    # Windows fuera de inglés es cp1252/cp437. `serve` re-envuelve stdout aparte.
    from leo_code.logging_config import utf8_console
    utf8_console()
    ap = argparse.ArgumentParser(prog="leo-mcp", description="Call graph + AST context for coding agents, over MCP.")
    ap.add_argument("--version", action="version", version=f"leo-mcp {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the MCP server on stdio (default)")
    for name, help_ in (("index", "index a repo and show what leo-mcp sees"),
                        ("doctor", "check the installation and print the config snippet")):
        sub.add_parser(name, help=help_).add_argument("repo", nargs="?", default=".")
    p = sub.add_parser("init", help="register leo-mcp in a project's MCP config")
    p.add_argument("--client", choices=CLIENTS, default="claude")
    p.add_argument("--user", action="store_true",
                   help="register for your user in Claude Code (all repos), writing nothing in the repo")
    p.add_argument("--no-hook", action="store_true",
                   help="do not install the hooks (Claude Code only)")
    p.add_argument("repo", nargs="?", default=".")
    args = ap.parse_args(argv)
    if args.cmd not in (None, "serve"):
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(errors="replace")  # consolas cp1252 de Windows
    handler = {"index": cmd_index, "doctor": cmd_doctor, "init": cmd_init}.get(args.cmd, cmd_serve)
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
