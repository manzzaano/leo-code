// Oráculo TS INDEPENDIENTE: re-deriva el grafo de llamadas con el COMPILADOR TypeScript
// (Microsoft tsc, parser distinto al tree-sitter de leo). Por símbolo function/method/class
// recoge los callees: CallExpression con callee Identifier (foo()) o PropertyAccess
// (obj.foo()). Tagged templates y NewExpression NO cuentan (no son CallExpression).
// Salida: JSON {archivo: [[name, line, [calls...]], ...]} por stdout.
//
// Uso:  node benchmark/ts_oracle.js <repo_dir>
const ts = require("typescript");
const fs = require("fs");
const path = require("path");

function walkFiles(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".git") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkFiles(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.d\.ts$/.test(e.name)) out.push(p);
  }
}

function callsIn(node) {
  const out = new Set();
  (function rec(n) {
    if (ts.isCallExpression(n)) {
      const c = n.expression;
      if (ts.isIdentifier(c)) out.add(c.text);
      else if (ts.isPropertyAccessExpression(c)) out.add(c.name.text);
    }
    ts.forEachChild(n, rec);
  })(node);
  return [...out];
}

const repo = process.argv[2];
const files = [];
walkFiles(repo, files);
const result = {};
for (const f of files) {
  let sf;
  try { sf = ts.createSourceFile(f, fs.readFileSync(f, "utf8"), ts.ScriptTarget.Latest, true); }
  catch { continue; }
  const syms = [];
  (function rec(n) {
    let name = null;
    if (ts.isFunctionDeclaration(n) && n.name) name = n.name.text;
    else if (ts.isMethodDeclaration(n) && n.name) name = n.name.getText(sf);
    else if (ts.isClassDeclaration(n) && n.name) name = n.name.text;
    if (name) {
      const line = sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
      syms.push([name, line, callsIn(n)]);
    }
    ts.forEachChild(n, rec);
  })(sf);
  if (syms.length) result[f] = syms;
}
process.stdout.write(JSON.stringify(result));
