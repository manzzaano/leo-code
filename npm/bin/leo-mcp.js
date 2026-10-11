#!/usr/bin/env node
// leo-mcp launcher. The engine is the Python package `leo-mcp` (PyPI); this runs it
// through uvx (uv downloads Python if needed) or, without uv, from a private venv.
// Never write to stdout here: in `serve` mode stdout is the MCP JSON-RPC channel.
"use strict";

const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const VERSION = require("../package.json").version;
const isWin = process.platform === "win32";
const log = (msg) => process.stderr.write(`[leo-mcp] ${msg}\n`);

function which(cmd, env = process.env) {
  const exts = isWin ? (env.PATHEXT || ".EXE;.CMD;.BAT").split(";") : [""];
  for (const dir of (env.PATH || "").split(path.delimiter)) {
    for (const ext of exts) {
      const p = path.join(dir, cmd + ext);
      if (dir && fs.existsSync(p) && fs.statSync(p).isFile()) return p;
    }
  }
  return null;
}

// Pure: decides how to run the Python package. Tested in leo-mcp.test.js.
function buildCommand({ env, argv, which: find, version = VERSION }) {
  const from = env.LEO_MCP_FROM || `leo-mcp${env.LEO_SEMANTIC === "1" ? "[semantic]" : ""}==${version}`;
  const uvx = find("uvx", env);
  if (uvx) {
    return { mode: "uvx", cmd: uvx, args: ["--python", ">=3.11", "--from", from, "leo-mcp", ...argv] };
  }
  return { mode: "venv", from, argv };
}

function cacheDir(env) {
  if (isWin && env.LOCALAPPDATA) return path.join(env.LOCALAPPDATA, "leo-mcp");
  return path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache"), "leo-mcp");
}

function findPython(env) {
  for (const [cmd, pre] of [["python3", []], ["python", []], ["py", ["-3"]]]) {
    const exe = which(cmd, env);
    if (!exe) continue;
    const r = spawnSync(exe, [...pre, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    const [major, minor] = String(r.stdout || "").trim().split(".").map(Number);
    if (major === 3 && minor >= 11) return [exe, pre];
  }
  return null;
}

// Fallback without uv: private venv per version, installed once (pip output -> stderr).
function venvCommand(from, env) {
  const py = findPython(env);
  if (!py) return null;
  const venv = path.join(cacheDir(env), `venv-${VERSION}`);
  const bin = path.join(venv, isWin ? "Scripts" : "bin", isWin ? "leo-mcp.exe" : "leo-mcp");
  if (fs.existsSync(bin)) return bin;
  const vpy = path.join(venv, isWin ? "Scripts" : "bin", isWin ? "python.exe" : "python");
  const run = (cmd, args) => spawnSync(cmd, args, { stdio: ["ignore", 2, 2], env }).status === 0;
  log(`first run: installing ${from} into ${venv} (one time)...`);
  const ok = run(py[0], [...py[1], "-m", "venv", venv])
    && run(vpy, ["-m", "pip", "install", "--disable-pip-version-check", "-q", from]);
  return ok && fs.existsSync(bin) ? bin : null;
}

function main() {
  const argv = process.argv.slice(2);
  const env = { PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", ...process.env };
  const plan = buildCommand({ env, argv, which });
  let { cmd, args } = plan;
  if (plan.mode === "venv") {
    cmd = venvCommand(plan.from, env);
    args = argv;
    if (!cmd) {
      log("needs uv (recommended) or Python >= 3.11 on PATH. Install uv:");
      log('  Windows:     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"');
      log("  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh");
      process.exit(1);
    }
  }
  const child = spawn(cmd, args, { stdio: "inherit", env });
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
  child.on("error", (e) => { log(`failed to start ${cmd}: ${e.message}`); process.exit(1); });
  child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
}

if (require.main === module) main();

module.exports = { buildCommand, cacheDir, which };
