"""Plugin system — extensible con Python, MCP, y subprocess (cualquier lenguaje).

Plugins se configuran en leo-code.json o ~/.leo-code/config.json:
{
  "plugins": {
    "lsp": {"type": "builtin", "config": {...}},
    "my-tool": {"type": "subprocess", "command": "./my-plugin", "config": {...}},
    "db": {"type": "mcp", "command": "npx", "args": ["-y", "mcp-server-postgres", "..."], "config": {}}
  }
}
"""

import json
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)


@dataclass
class PluginInfo:
    name: str
    type: str  # builtin, subprocess, mcp
    version: str = "0.1.0"
    tool_count: int = 0
    running: bool = False


class Plugin(ABC):
    """Interfaz base para plugins Python (built-in)."""
    name: str = "base"
    version: str = "0.1.0"

    def on_init(self, config: dict, repo_path: str) -> list[ToolDef]:
        return []

    def on_tool_register(self, registry) -> None:
        pass

    def on_pre_context(self, query: str, capsules: list) -> str:
        return ""

    def on_post_response(self, response: str, query: str) -> str:
        return response

    def on_pre_tool(self, tool_name: str, args: dict) -> bool:
        return True

    def on_post_tool(self, tool_name: str, args: dict, result: str) -> str:
        return result

    def on_pre_llm(self, messages: list[dict]) -> list[dict]:
        return messages

    def on_post_llm(self, response: str) -> str:
        return response

    def on_shutdown(self):
        pass

    def execute(self, tool_name: str, args: dict, repo_path: str) -> str:
        return f"[{self.name}: tool '{tool_name}' not found]"


class _SubprocessPlugin:
    """Wrapper para plugins externos (cualquier lenguaje) vía JSON lines."""

    def __init__(self, name: str, command: str, config: dict, repo_path: str):
        self.name = name
        self.command = command
        self.config = config
        self.repo_path = repo_path
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._tools: list[ToolDef] = []
        self._next_id = 0
        self.running = False

    def start(self) -> list[ToolDef]:
        try:
            self._proc = subprocess.Popen(
                self.command, shell=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
                cwd=self.repo_path,
            )
            self._send({"type": "init", "config": self.config, "repo": self.repo_path})
            resp = self._recv(timeout=5)
            if resp and resp.get("type") == "ready":
                for td in resp.get("tools", []):
                    self._tools.append(ToolDef(
                        name=f"{self.name}_{td['name']}",
                        description=td.get("description", ""),
                        parameters=td.get("parameters", {}),
                    ))
            self.running = True
        except Exception:
            self.running = False
        return self._tools

    def execute(self, tool_name: str, args: dict, repo_path: str) -> str:
        if not self._proc:
            return "[plugin not running]"
        base_name = tool_name.replace(f"{self.name}_", "", 1)
        with self._lock:
            sid = self._next_id
            self._next_id += 1
        self._send({"type": "execute", "id": sid, "tool": base_name, "args": args})
        resp = self._recv(timeout=60)
        return resp.get("output", "") if resp else "[no response]"

    def pre_context(self, query: str, capsules: list) -> str:
        if not self._proc:
            return ""
        self._send({"type": "pre_context", "query": query, "capsules": capsules})
        resp = self._recv(timeout=5)
        return resp.get("text", "") if resp else ""

    def shutdown(self):
        if self._proc:
            try:
                self._send({"type": "shutdown"})
                self._proc.stdin.close()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
            self._proc = None
            self.running = False

    def _send(self, data: dict):
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(json.dumps(data, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()

    def _recv(self, timeout: float) -> Optional[dict]:
        if not self._proc or not self._proc.stdout:
            return None
        start = time.time()
        while time.time() - start < timeout:
            line = self._proc.stdout.readline()
            if not line:
                break
            try:
                return json.loads(line.strip())
            except json.JSONDecodeError:
                continue
        return None


class PluginManager:
    """Orquesta plugins: carga configuración, arranca, registra tools, ejecuta hooks."""

    BUILTINS = {}  # registered via register_builtin()

    def __init__(self, config_path: str = "", repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)
        self.config = self._load_config(config_path)
        self._plugins: list[Plugin] = []
        self._subprocess_plugins: list[_SubprocessPlugin] = []
        self._mcp_plugins: list = []  # MCP client instances
        self._all_tool_defs: list[ToolDef] = []
        self._tool_index: dict[str, tuple] = {}  # name → (plugin, tool_name)

    @classmethod
    def _ensure_builtins_loaded(cls):
        if not cls.BUILTINS:
            try:
                import leo_code.plugins.lsp
                import leo_code.plugins.gh
                import leo_code.plugins.linter
                import leo_code.plugins.package
                import leo_code.plugins.web
            except ImportError:
                pass

    def _load_config(self, config_path: str) -> dict:
        paths = [config_path,
                 os.path.join(self.repo_path, "leo-code.json"),
                 os.path.expanduser("~/.leo-code/config.json")]
        for p in paths:
            if p and Path(p).exists():
                try:
                    return json.loads(Path(p).read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {}

    def init(self, registry=None) -> list[PluginInfo]:
        self._ensure_builtins_loaded()
        info_list = []
        plugins_cfg = self.config.get("plugins", {})

        for name, cfg in plugins_cfg.items():
            ptype = cfg.get("type", "builtin")
            pconfig = cfg.get("config", {})

            if ptype == "builtin":
                cls = self.BUILTINS.get(name)
                if cls:
                    try:
                        inst = cls()
                        inst.on_init(pconfig, self.repo_path)
                        if registry:
                            inst.on_tool_register(registry)
                        self._plugins.append(inst)
                        info_list.append(PluginInfo(name=name, type="builtin", version=inst.version, running=True))
                    except Exception as e:
                        info_list.append(PluginInfo(name=name, type="builtin", running=False))
                else:
                    info_list.append(PluginInfo(name=name, type="builtin", running=False))

            elif ptype == "subprocess":
                cmd = cfg.get("command", "")
                if cmd:
                    sp = _SubprocessPlugin(name, cmd, pconfig, self.repo_path)
                    tools = sp.start()
                    for td in tools:
                        if registry:
                            registry.register(td.name, lambda args, repo, sp=sp: sp.execute(td.name, args, repo),
                                             {"name": td.name, "description": td.description, "parameters": td.parameters})
                    self._subprocess_plugins.append(sp)
                    info_list.append(PluginInfo(name=name, type="subprocess", tool_count=len(tools), running=sp.running))

            elif ptype == "mcp":
                mp = _MCPPlugin(name, cfg)
                try:
                    mp.start()
                    tools = mp.list_tools()
                    for td in tools:
                        if registry:
                            registry.register(td.name, lambda args, repo, mp=mp: mp.call(td.name, args),
                                             {"name": td.name, "description": td.description, "parameters": td.parameters})
                    self._mcp_plugins.append(mp)
                    info_list.append(PluginInfo(name=name, type="mcp", tool_count=len(tools), running=True))
                except Exception as e:
                    info_list.append(PluginInfo(name=name, type="mcp", running=False))

        return info_list

    def pre_context(self, query: str, capsules: list) -> str:
        parts = []
        for p in self._plugins:
            try:
                ctx = p.on_pre_context(query, capsules)
                if ctx:
                    parts.append(ctx)
            except Exception:
                pass
        for sp in self._subprocess_plugins:
            try:
                ctx = sp.pre_context(query, capsules)
                if ctx:
                    parts.append(ctx)
            except Exception:
                pass
        return "\n".join(parts)

    def post_response(self, response: str, query: str) -> str:
        for p in self._plugins:
            try:
                response = p.on_post_response(response, query)
                response = p.on_post_llm(response)
            except Exception:
                pass
        return response

    def pre_tool(self, tool_name: str, args: dict) -> bool:
        for p in self._plugins:
            try:
                if not p.on_pre_tool(tool_name, args):
                    return False
            except Exception:
                pass
        return True

    def post_tool(self, tool_name: str, args: dict, result: str) -> str:
        for p in self._plugins:
            try:
                result = p.on_post_tool(tool_name, args, result)
            except Exception:
                pass
        return result

    def shutdown(self):
        for p in self._plugins:
            try:
                p.on_shutdown()
            except Exception:
                pass
        for sp in self._subprocess_plugins:
            sp.shutdown()
        for mp in self._mcp_plugins:
            try:
                mp.shutdown()
            except Exception:
                pass

    def info(self) -> list[PluginInfo]:
        info = []
        for p in self._plugins:
            info.append(PluginInfo(name=p.name, type="builtin", version=p.version, running=True))
        for sp in self._subprocess_plugins:
            info.append(PluginInfo(name=sp.name, type="subprocess", tool_count=len(getattr(sp, '_tools', [])), running=sp.running))
        for mp in self._mcp_plugins:
            info.append(PluginInfo(name=getattr(mp, 'name', 'mcp'), type="mcp", tool_count=len(getattr(mp, 'tools', [])), running=getattr(mp, 'running', False)))
        return info


class _MCPPlugin:
    """Cliente MCP JSON-RPC para conectar con servidores MCP (stdio)."""

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.command = cfg.get("command", "")
        self.args = cfg.get("args", [])
        self.env = cfg.get("env", {})
        self._proc = None
        self._next_id = 1
        self.running = False
        self.tools: list[ToolDef] = []

    def start(self):
        full_env = {**os.environ, **self.env}
        self._proc = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=full_env,
        )
        self._send({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                      "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "leo-code", "version": "0.2.0"}}})
        resp = self._recv()
        if resp and "result" in resp:
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            self.running = True

    def list_tools(self) -> list[ToolDef]:
        self._send({"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list", "params": {}})
        self._next_id += 1
        resp = self._recv()
        tools = []
        if resp and "result" in resp:
            for t in resp["result"].get("tools", []):
                td = ToolDef(
                    name=f"mcp_{self.name}_{t['name']}",
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {}),
                )
                tools.append(td)
        self.tools = tools
        return tools

    def call(self, tool_name: str, args: dict) -> str:
        base_name = tool_name.replace(f"mcp_{self.name}_", "", 1)
        self._send({"jsonrpc": "2.0", "id": self._next_id, "method": "tools/call",
                      "params": {"name": base_name, "arguments": args}})
        self._next_id += 1
        resp = self._recv()
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            texts = [c["text"] for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else json.dumps(content)
        return f"[MCP error: {resp}]"

    def shutdown(self):
        if self._proc:
            try:
                self._send({"jsonrpc": "2.0", "method": "shutdown", "params": {}})
                self._proc.stdin.close()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
            self._proc = None
            self.running = False

    def _send(self, data: dict):
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(json.dumps(data, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()

    def _recv(self, timeout: float = 10) -> Optional[dict]:
        if not self._proc or not self._proc.stdout:
            return None
        start = time.time()
        while time.time() - start < timeout:
            line = self._proc.stdout.readline()
            if not line:
                break
            try:
                return json.loads(line.strip())
            except json.JSONDecodeError:
                continue
        return None


def register_builtin(name: str, cls):
    PluginManager.BUILTINS[name] = cls
