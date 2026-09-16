"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { buildCommand } = require("./leo-mcp.js");

const withUvx = (cmd) => (cmd === "uvx" ? "/opt/uv/uvx" : null);
const noTools = () => null;

test("uvx runs the pinned PyPI version and passes args through", () => {
  const plan = buildCommand({ env: {}, argv: ["doctor", "."], which: withUvx, version: "1.2.3" });
  assert.deepStrictEqual(plan, {
    mode: "uvx",
    cmd: "/opt/uv/uvx",
    args: ["--python", ">=3.11", "--from", "leo-mcp==1.2.3", "leo-mcp", "doctor", "."],
  });
});

test("LEO_SEMANTIC=1 adds the semantic extra", () => {
  const plan = buildCommand({ env: { LEO_SEMANTIC: "1" }, argv: [], which: withUvx, version: "1.2.3" });
  assert.strictEqual(plan.args[3], "leo-mcp[semantic]==1.2.3");
});

test("LEO_MCP_FROM overrides the source (unpublished wheel or git url)", () => {
  const plan = buildCommand({ env: { LEO_MCP_FROM: "./dist/leo_mcp.whl" }, argv: [], which: withUvx });
  assert.strictEqual(plan.args[3], "./dist/leo_mcp.whl");
});

test("without uvx it falls back to a private venv", () => {
  const plan = buildCommand({ env: {}, argv: ["index"], which: noTools, version: "1.2.3" });
  assert.deepStrictEqual(plan, { mode: "venv", from: "leo-mcp==1.2.3", argv: ["index"] });
});
