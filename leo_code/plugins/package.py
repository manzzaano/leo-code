"""Package Manager Plugin — instala dependencias automáticamente."""

import subprocess
from leo_code.plugins import Plugin, register_builtin


class PackagePlugin(Plugin):
    name = "package"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path

    def on_tool_register(self, registry):
        registry.register("install_deps", self.install_deps,
            {"name": "install_deps", "description": "Instalar dependencias del proyecto (pip install / npm install / go mod tidy)",
             "parameters": {"type": "object", "properties": {
                 "package": {"type": "string", "description": "Paquete específico a instalar (opcional, si no se especifica instala todas las dependencias)"},
             }}})
        registry.register("check_deps", self.check_deps,
            {"name": "check_deps", "description": "Verificar si una dependencia está instalada",
             "parameters": {"type": "object", "properties": {"package": {"type": "string", "description": "Nombre del paquete a verificar"}}, "required": ["package"]}})
        registry.register("list_deps", self.list_deps,
            {"name": "list_deps", "description": "Listar dependencias instaladas del proyecto",
             "parameters": {"type": "object", "properties": {}}})

    def install_deps(self, args: dict, repo_path: str) -> str:
        pkg = args.get("package", "")
        pkg_str = f" \"{pkg}\"" if pkg else ""

        if self._detect("pyproject.toml", repo_path) or self._detect("setup.py", repo_path):
            cmd = f"pip install{pkg_str}"
        elif self._detect("package.json", repo_path):
            cmd = f"npm install{pkg_str}"
        elif self._detect("go.mod", repo_path):
            cmd = "go mod tidy" if not pkg else f"go get {pkg}"
        elif self._detect("Cargo.toml", repo_path):
            cmd = "cargo build" if not pkg else f"cargo add {pkg}"
        else:
            return "[No se detectó gestor de paquetes. pyproject.toml/package.json/go.mod/Cargo.toml no encontrados]"

        try:
            r = subprocess.run(cmd, shell=True, cwd=repo_path, capture_output=True, text=True, timeout=120)
            out = (r.stdout + r.stderr).strip()
            return out[:2000] if out else "[Instalado]"
        except Exception as e:
            return f"[Package error: {e}]"

    def check_deps(self, args: dict, repo_path: str) -> str:
        pkg = args.get("package", "")
        if self._detect("pyproject.toml", repo_path):
            r = subprocess.run(f"python -c \"import {pkg}; print('OK')\" 2>&1", shell=True,
                               cwd=repo_path, capture_output=True, text=True, timeout=10)
        elif self._detect("package.json", repo_path):
            r = subprocess.run(f"node -e \"require('{pkg}')\" 2>&1", shell=True,
                               cwd=repo_path, capture_output=True, text=True, timeout=10)
        else:
            return f"[No se detectó gestor. Verifica manualmente si {pkg} está instalado]"
        out = r.stdout.strip()
        return f"{pkg}: instalado" if out == "OK" else f"{pkg}: NO instalado ({r.stderr.strip()[:200]})"

    def list_deps(self, args: dict, repo_path: str) -> str:
        if self._detect("pyproject.toml", repo_path):
            r = subprocess.run("pip list --format freeze 2>&1", shell=True,
                               cwd=repo_path, capture_output=True, text=True, timeout=15)
            return (r.stdout.strip() or "[sin dependencias]")[:2000]
        elif self._detect("package.json", repo_path):
            r = subprocess.run("npm ls --depth 0 2>&1", shell=True,
                               cwd=repo_path, capture_output=True, text=True, timeout=15)
            return r.stdout.strip()[:2000] or "[sin dependencias]"
        return "[Gestor no detectado]"

    @staticmethod
    def _detect(filename: str, repo_path: str) -> bool:
        import os
        return os.path.exists(os.path.join(repo_path, filename))


register_builtin("package", PackagePlugin)
