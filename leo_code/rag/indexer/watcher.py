"""Watcher: indexación inicial + reindexado incremental vía watchdog.

Usa leo_code.core.parser para extraer cápsulas (AST + tree-sitter).
Persiste el índice en disco comprimido para carga rápida.

Uso:
    indexer = Indexer()
    indexer.build("/path/to/repo", languages=["python"])
    indexer.save("kc_index.json.gz")
    indexer.watch("/path/to/repo")
"""

import gzip
import json
import os
import subprocess
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from leo_code.core.parser import extract_from_file, build_call_graph, Capsule, detect_language, EXT_LANG


class Indexer:
    """Indexa un codebase y mantiene el índice actualizado."""

    def __init__(self, vector_store=None, max_workers: int = 0,
                 hygiene: bool = False, max_file_kb: int = 512):
        self.vector_store = vector_store
        self._capsules: dict[str, Capsule] = {}
        self._capsules_lock = threading.Lock()
        self._max_workers = max_workers or min(32, (os.cpu_count() or 1) * 2)
        # hygiene = modo producto (MCP/CLI): todos los lenguajes con parser, respeta
        # .gitignore, salta build output / minificados / archivos enormes. Indexer()
        # plano conserva el descubrimiento histórico: la auditoría formal y los
        # oráculos lo usan y sus números deben seguir siendo reproducibles.
        self.hygiene = hygiene
        self.max_file_kb = max_file_kb
        self._junk_seen: dict[str, float] = {}   # path -> mtime de archivos descartados
        self._empty_seen: dict[str, float] = {}  # path -> mtime de archivos sin cápsulas

    def _process_one(self, path: Path, lang: str, use_tree_sitter: bool, verbose: bool, repo: Path) -> tuple[list[Capsule], str, int, str | None]:
        try:
            if lang in ("auto", "python"):
                lang = detect_language(str(path))
            if use_tree_sitter:
                from leo_code.core.parser import extract_from_tree_sitter
                content = path.read_text(encoding="utf-8")
                capsules = extract_from_tree_sitter(content, str(path), lang)
            else:
                capsules = extract_from_file(str(path), lang)
            build_call_graph(capsules)
            return capsules, lang, len(capsules), None
        except Exception as e:
            return [], lang, 0, str(e)

    _EXTENSIONS = {".py": "python", ".js": "javascript", ".ts": "typescript",
                   ".rs": "rust", ".go": "go", ".java": "java", ".txt": "text"}

    # Modo producto: todo lo que parser.py parsea como código (AST, tree-sitter o regex).
    CODE_EXTENSIONS = {ext.lower(): lang for ext, lang in EXT_LANG.items()
                       if lang not in ("text", "image", "html", "css")}
    CODE_LANGUAGES = sorted(set(CODE_EXTENSIONS.values()))
    _SKIP_DIRS = {"__pycache__", ".git", "node_modules", "venv", ".venv",
                  "dist", "build", ".tox", ".egg-info"}
    _PRODUCT_SKIP_DIRS = {".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", "out", "coverage",
                          "target", "vendor", "bower_components", "site-packages", ".mypy_cache",
                          ".pytest_cache", ".ruff_cache", ".gradle", ".terraform", ".idea", ".vscode"}
    _DOC_DIRS = {"data", "docs", "doc", "synthetic"}

    def _exts(self) -> dict[str, str]:
        return self.CODE_EXTENSIONS if self.hygiene else self._EXTENSIONS

    def _discover_files(self, repo_path: str, languages: list[str]) -> list[tuple[Path, str]]:
        """Lista [(path, lang)] de archivos indexables del repo según languages."""
        if self.hygiene:
            return self._discover_product(repo_path, languages)
        ext_to_lang = {ext: lang for ext, lang in self._EXTENSIONS.items() if lang in languages}
        repo = Path(repo_path)
        files = []
        for ext, lang in ext_to_lang.items():
            for path in sorted(repo.rglob(f"*{ext}")):
                if self._should_skip(path):
                    continue
                if ext == ".txt" and not any(p in self._DOC_DIRS for p in path.parts):
                    continue
                files.append((path, lang))
        return files

    def _discover_product(self, repo_path: str, languages: list[str]) -> list[tuple[Path, str]]:
        repo = Path(repo_path)
        wanted = {ext: lang for ext, lang in self.CODE_EXTENSIONS.items() if lang in languages}
        if "text" in languages:
            wanted[".txt"] = "text"
        indexed = {c.file_path for c in self._capsules.values()}
        skip = self._SKIP_DIRS | self._PRODUCT_SKIP_DIRS
        out = []
        for path in self._list_files(repo):
            lang = wanted.get(path.suffix.lower())
            if not lang or ".min." in path.name:
                continue
            rel_dirs = path.relative_to(repo).parts[:-1]
            if any(d in skip or d.endswith(".egg-info") for d in rel_dirs):
                continue
            if lang == "text" and not self._DOC_DIRS & set(rel_dirs):
                continue
            # Solo se inspeccionan archivos aún no indexados: coste una vez, no en cada sync.
            if str(path) not in indexed and self._is_junk(path):
                continue
            out.append((path, lang))
        return sorted(out)

    def _list_files(self, repo: Path) -> list[Path]:
        """`git ls-files` si es un repo git (respeta .gitignore); si no, walk podando
        directorios de dependencias/build."""
        try:
            # stdin=DEVNULL obligatorio: dentro del server MCP stdin es el pipe JSON-RPC
            # con una lectura síncrona pendiente, y en Windows el hijo que lo hereda se
            # bloquea (medido: 60 s = el timeout, en la 1ª llamada sobre NEXUS).
            r = subprocess.run(
                ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
            )
            if r.returncode == 0:
                paths = (repo / p for p in r.stdout.decode("utf-8", "replace").split("\0") if p)
                return [p for p in paths if p.is_file()]
        except (OSError, subprocess.TimeoutExpired):
            pass
        skip = self._SKIP_DIRS | self._PRODUCT_SKIP_DIRS
        files = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in skip and not d.endswith(".egg-info")]
            files.extend(Path(root) / n for n in names)
        return files

    def _is_junk(self, path: Path) -> bool:
        """Archivo enorme o minificado (bundle, página guardada): ruido en el grafo.

        ponytail: heurística de línea larga (>500 chars en los primeros 64 KB; medido
        2026-09-15: código real ≤400 en NEXUS y leo-code, 59/60 bundles de una página
        guardada >500). Un bundle diminuto pasa. Subir a entropía si molesta.
        """
        try:
            st = path.stat()
            key = str(path)
            if self._junk_seen.get(key) == st.st_mtime:
                return True
            junk = st.st_size > self.max_file_kb * 1024
            if not junk:
                with open(path, "rb") as f:
                    junk = max(len(line) for line in f.read(65536).split(b"\n")) > 1000
        except OSError:
            return True
        if junk:
            self._junk_seen[key] = st.st_mtime
        return junk

    def build(self, repo_path: str, languages: Optional[list[str]] = None,
              use_tree_sitter: bool = False, verbose: bool = False) -> int:
        """Indexa todos los archivos de un repo en paralelo. Retorna número de cápsulas."""
        if languages is None:
            languages = self.CODE_LANGUAGES if self.hygiene else ["python"]

        # Anti-acumulación: un rebuild NO debe apilar sobre cápsulas previas del
        # mismo repo (duplicados) ni conservar rutas absolutas ya inexistentes
        # (repo movido/renombrado — quedaban como símbolos fantasma en retrieval).
        # Cápsulas de OTROS repos vivos se conservan: el Indexer es multi-repo.
        # Se purga ANTES de descubrir: un repo vaciado debe quedar con 0 cápsulas.
        repo_abs = os.path.abspath(repo_path)
        with self._capsules_lock:
            self._capsules = {
                cid: c for cid, c in self._capsules.items()
                if not _under(c.file_path, repo_abs)
                and not (os.path.isabs(c.file_path) and not os.path.exists(c.file_path))
            }

        files = self._discover_files(repo_path, languages)
        repo = Path(repo_path)

        if not files:
            print("[indexer] 0 archivos encontrados")
            return 0

        stats = defaultdict(lambda: {"files": 0, "capsules": 0})
        count = 0

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(self._process_one, path, lang, use_tree_sitter, verbose, repo): (path, lang)
                for path, lang in files
            }
            for future in as_completed(futures):
                path, lang = futures[future]
                capsules, lang_out, n, error = future.result()
                if error and verbose:
                    print(f"  [!] Error en {path.relative_to(repo)}: {error}")
                if n:
                    with self._capsules_lock:
                        for c in capsules:
                            self._capsules[c.id] = c
                    count += n
                    stats[lang]["files"] += 1
                    stats[lang]["capsules"] += n
                if verbose and not error:
                    print(f"  [{lang}] {path.relative_to(repo)}: {n} cápsulas")

        if self.vector_store and self._capsules:
            self.vector_store.add(list(self._capsules.values()))

        total_files = sum(s["files"] for s in stats.values())
        print(f"[indexer] {total_files} archivos, {count} cápsulas")
        for lang, s in sorted(stats.items()):
            print(f"  {lang}: {s['files']} archivos, {s['capsules']} cápsulas")
        by_type = defaultdict(int)
        for c in self._capsules.values():
            by_type[c.type] += 1
        print(f"  Tipos: {', '.join(f'{t}={n}' for t, n in sorted(by_type.items()))}")

        return count

    def save(self, path: str = "kc_index.json.gz", repo: str | None = None):
        """Persiste el índice a disco comprimido (orjson+gzip, fallback json+gzip).

        repo: guarda solo las cápsulas de ese repo (caché por repo). Escritura atómica:
        el cliente MCP mata el server sin aviso y un gzip a medias no debe quedar."""
        items = self._capsules.items()
        if repo:
            repo_abs = os.path.abspath(repo)
            items = [(cid, c) for cid, c in items if _under(c.file_path, repo_abs)]
        data = {
            cid: {
                "id": c.id, "type": c.type, "name": c.name,
                "file_path": c.file_path, "start_line": c.start_line,
                "end_line": c.end_line, "language": c.language,
                "signature": c.signature, "docstring": c.docstring,
                "content": c.content,
                "calls": c.calls, "called_by": c.called_by,
                "imports": c.imports, "properties": c.properties,
            }
            for cid, c in items
        }
        try:
            import orjson
            raw = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        except ImportError:
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        tmp = Path(f"{path}.tmp{os.getpid()}")
        tmp.write_bytes(gzip.compress(raw))
        os.replace(tmp, path)
        print(f"[indexer] Guardado: {path} ({len(data)} cápsulas)")

    def load(self, path: str = "kc_index.json.gz", merge: bool = False):
        """Carga un índice comprimido desde disco. merge=True conserva lo ya cargado
        (otros repos del mismo proceso) en vez de reemplazarlo."""
        raw = gzip.decompress(Path(path).read_bytes())
        try:
            import orjson
            data = orjson.loads(raw)
        except ImportError:
            data = json.loads(raw.decode("utf-8"))
        if not merge:
            self._capsules = {}
        for cid, d in data.items():
            self._capsules[cid] = Capsule(
                id=d["id"], type=d["type"], name=d["name"],
                file_path=d["file_path"], start_line=d["start_line"],
                end_line=d["end_line"], language=d["language"],
                signature=d["signature"], content=d.get("content", ""),
                docstring=d.get("docstring"), calls=d.get("calls", []),
                called_by=d.get("called_by", []), imports=d.get("imports", []),
                properties=d.get("properties", {}),
            )
        print(f"[indexer] Cargado: {path} ({len(data)} cápsulas)")

    def _rebuild_call_graph(self) -> None:
        """Re-resuelve called_by global tras un sync (los edges son cross-file)."""
        caps = list(self._capsules.values())
        for c in caps:
            c.called_by = []
        build_call_graph(caps)

    def sync(self, repo_path: str, since_mtime: float,
             languages: Optional[list[str]] = None) -> dict:
        """Actualización incremental sobre un índice ya cargado: re-parsea solo
        archivos cambiados (mtime > since_mtime) o nuevos, quita los borrados, y
        re-resuelve el call-graph. Mucho más barato que build() cuando cambian pocos.
        Devuelve {changed, new, deleted, reparsed_capsules, removed, capsules}.
        """
        if languages is None:
            languages = self.CODE_LANGUAGES if self.hygiene else ["python", "text"]
        files = self._discover_files(repo_path, languages)
        disk_paths = {str(p) for p, _ in files}
        # Solo las cápsulas de ESTE repo: con varios repos cargados, los archivos de
        # los otros no están en disk_paths y se borraban como "eliminados".
        repo_abs = os.path.abspath(repo_path)
        indexed_paths = {c.file_path for c in self._capsules.values() if _under(c.file_path, repo_abs)}

        changed = [(p, l) for p, l in files if os.path.getmtime(p) > since_mtime]
        # Un archivo indexable que no produce cápsulas (`__init__.py` vacío, `types.ts`
        # de solo tipos, un .d.ts) no está en indexed_paths y se re-parseaba en CADA sync.
        # Se recuerda por mtime: se re-mira solo si cambia.
        new = [(p, l) for p, l in files
               if str(p) not in indexed_paths and self._empty_seen.get(str(p)) != os.path.getmtime(p)]
        to_parse = {str(p): (p, l) for p, l in changed}
        for p, l in new:
            to_parse[str(p)] = (p, l)
        deleted = [fp for fp in indexed_paths
                   if fp not in disk_paths and Path(fp).suffix.lower() in self._exts()]

        # Quitar cápsulas de archivos a re-parsear + borrados
        drop = set(to_parse) | set(deleted)
        removed = 0
        if drop:
            with self._capsules_lock:
                before = len(self._capsules)
                self._capsules = {cid: c for cid, c in self._capsules.items()
                                  if c.file_path not in drop}
                removed = before - len(self._capsules)

        # Re-parsear cambiados/nuevos
        reparsed = 0
        touched_capsules: list[Capsule] = []
        repo = Path(repo_path)
        for p, lang in to_parse.values():
            caps, _, n, _err = self._process_one(p, lang, False, False, repo)
            if n:
                with self._capsules_lock:
                    for c in caps:
                        self._capsules[c.id] = c
                reparsed += n
                touched_capsules.extend(caps)
                self._empty_seen.pop(str(p), None)
            else:
                try:
                    self._empty_seen[str(p)] = os.path.getmtime(p)
                except OSError:
                    pass

        if removed or reparsed:
            self._rebuild_call_graph()
            # Solo el delta (capsulas nuevas/re-parseadas), no todo el repo — un
            # sync que toca 1 archivo no debe re-embeber las ~1400 capsulas del resto.
            if self.vector_store and touched_capsules:
                self.vector_store.add(touched_capsules)
            print(f"[indexer] sync: {len(changed)} cambiados, {len(new)} nuevos, "
                  f"{len(deleted)} borrados ({reparsed} cápsulas)")

        return {"changed": len(changed), "new": len(new),
                "deleted": len(deleted), "reparsed_capsules": reparsed,
                "removed": removed, "capsules": touched_capsules}

    def watch(self, repo_path: str):
        """Inicia watchdog para reindexar archivos modificados."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            indexer = self

            class Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if event.is_directory:
                        return
                    path = event.src_path
                    if any(path.endswith(ext) for ext in [".py", ".js", ".ts", ".rs", ".go"]):
                        indexer.reindex_file(path)

            self._watcher = Observer()
            self._watcher.schedule(Handler(), repo_path, recursive=True)
            self._watcher.start()
            print(f"[indexer] Watching {repo_path} for changes...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self._watcher.stop()
            self._watcher.join()
        except ImportError:
            print("[indexer] watchdog no instalado. Ejecuta: pip install watchdog")

    def reindex_file(self, path: str, verbose: bool = True):
        """Reindexa un archivo tras ser modificado."""
        try:
            ext = Path(path).suffix
            lang_map = {".py": "python", ".js": "javascript", ".ts": "typescript",
                         ".rs": "rust", ".go": "go"}
            lang = lang_map.get(ext, "python")
            capsules = extract_from_file(path, lang)
            build_call_graph(capsules)
            with self._capsules_lock:
                for c in capsules:
                    self._capsules[c.id] = c
            if self.vector_store:
                self.vector_store.add(capsules)
            if verbose:
                print(f"[indexer] Reindexado: {path} ({len(capsules)} cápsulas)")
        except Exception as e:
            if verbose:
                print(f"[indexer] Error reindexando {path}: {e}")

    def stats(self) -> dict:
        """Estadísticas del índice actual."""
        by_type = defaultdict(int)
        by_lang = defaultdict(int)
        by_file = defaultdict(int)
        for c in self._capsules.values():
            by_type[c.type] += 1
            by_lang[c.language] += 1
            by_file[c.file_path] += 1
        return {
            "total_capsules": len(self._capsules),
            "total_files": len(by_file),
            "by_type": dict(by_type),
            "by_language": dict(by_lang),
        }

    def get_capsules(self) -> dict[str, Capsule]:
        return self._capsules

    @staticmethod
    def _should_skip(path: Path) -> bool:
        return any(p in Indexer._SKIP_DIRS for p in path.parts)


def _under(file_path: str, repo_abs: str) -> bool:
    """file_path pertenece a repo_abs (con separador: /a/proj no contiene /a/proj2)."""
    p = os.path.abspath(file_path)
    return p == repo_abs or p.startswith(repo_abs.rstrip(os.sep) + os.sep)
