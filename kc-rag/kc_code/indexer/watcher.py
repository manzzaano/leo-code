"""Watcher: indexación inicial + reindexado incremental vía watchdog.

Usa kc_core.parser para extraer cápsulas (AST + tree-sitter).
Persiste el índice en disco como JSON para carga rápida.

Uso:
    indexer = Indexer()
    indexer.build("/path/to/repo", languages=["python"])
    indexer.save("index.json")
    indexer.watch("/path/to/repo")
"""

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from kc_core.parser import extract_from_file, build_call_graph, Capsule


class Indexer:
    """Indexa un codebase y mantiene el índice actualizado."""

    def __init__(self, vector_store=None):
        self.vector_store = vector_store
        self._capsules: dict[str, Capsule] = {}

    def build(self, repo_path: str, languages: Optional[list[str]] = None,
              use_tree_sitter: bool = False, verbose: bool = False) -> int:
        """Indexa todos los archivos de un repo. Retorna número de cápsulas."""
        if languages is None:
            languages = ["python"]

        extensions = {".py": "python", ".js": "javascript", ".ts": "typescript",
                       ".rs": "rust", ".go": "go", ".java": "java", ".txt": "text"}
        ext_to_lang = {ext: lang for ext, lang in extensions.items() if lang in languages}

        stats = defaultdict(lambda: {"files": 0, "capsules": 0})
        count = 0
        repo = Path(repo_path)

        for ext, lang in ext_to_lang.items():
            for path in sorted(repo.rglob(f"*{ext}")):
                if self._should_skip(path):
                    continue
                if ext == ".txt" and not any(p in {"data", "docs", "doc", "synthetic"} for p in path.parts):
                    continue
                try:
                    if use_tree_sitter:
                        from kc_core.parser import extract_from_tree_sitter
                        content = path.read_text(encoding="utf-8")
                        capsules = extract_from_tree_sitter(content, str(path), lang)
                    else:
                        capsules = extract_from_file(str(path), lang)

                    build_call_graph(capsules)
                    for c in capsules:
                        self._capsules[c.id] = c
                    n = len(capsules)
                    count += n
                    stats[lang]["files"] += 1
                    stats[lang]["capsules"] += n

                    if verbose:
                        print(f"  [{lang}] {path.relative_to(repo)}: {n} cápsulas")
                except Exception as e:
                    if verbose:
                        print(f"  [!] Error en {path.relative_to(repo)}: {e}")

        if self.vector_store and self._capsules:
            self.vector_store.add(list(self._capsules.values()))

        # Print summary
        total_files = sum(s["files"] for s in stats.values())
        print(f"[indexer] {total_files} archivos, {count} cápsulas")
        for lang, s in sorted(stats.items()):
            print(f"  {lang}: {s['files']} archivos, {s['capsules']} cápsulas")
        by_type = defaultdict(int)
        for c in self._capsules.values():
            by_type[c.type] += 1
        print(f"  Tipos: {', '.join(f'{t}={n}' for t, n in sorted(by_type.items()))}")

        return count

    def save(self, path: str = "kc_index.json"):
        """Persiste el índice a disco como JSON."""
        data = {
            cid: {
                "id": c.id, "type": c.type, "name": c.name,
                "file_path": c.file_path, "start_line": c.start_line,
                "end_line": c.end_line, "language": c.language,
                "signature": c.signature, "docstring": c.docstring,
                "calls": c.calls, "called_by": c.called_by,
                "imports": c.imports, "properties": c.properties,
            }
            for cid, c in self._capsules.items()
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[indexer] Guardado: {path} ({len(data)} cápsulas)")

    def load(self, path: str = "kc_index.json"):
        """Carga un índice desde disco."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
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
        print(f"[indexer] Cargado: {path} ({len(self._capsules)} cápsulas)")

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
        skip_dirs = {"__pycache__", ".git", "node_modules", "venv", ".venv",
                       "dist", "build", ".tox", ".egg-info", "__pycache__"}
        return any(p in skip_dirs for p in path.parts)
