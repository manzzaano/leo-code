// C de M1 (v5): sustitución PASIVA, cero fricción.
// Lección medida (v1-v4): en un loop de agente cada turno extra re-envía la
// conversación entera — vetos y llamadas forzadas son turnos y salen más caros
// que lo que ahorran (v3: +108% tokens). Y un veto puede dejar al agente
// respondiendo a ciegas (visto en smoke test).
// v5: un read de archivo entero devuelve la versión comprimida del AST
// (leo_code.filectx) en vez del crudo. Mismos turnos, menos contenido; el
// agente ni se entera. Rango offset/limit = crudo (editar exige líneas).
// get_context/graph siguen disponibles vía MCP (steering en AGENTS.md).
//
// Gated: solo actúa con LEO_FORCE=1 (benchmark lo pone en OCMCP; OC vanilla
// y usuarios sin opt-in quedan intactos).
export const LeoFirstAction = async ({ $ }) => {
  if (process.env.LEO_FORCE !== "1") return {}

  const CODE_EXT = /\.(py|ts|tsx|js|jsx|java|kt|go|rs|rb|php|cs|ex|exs)$/i
  const norm = (p) => String(p || "").replace(/\\/g, "/")
  const debug = async (line) => {
    if (process.env.LEO_DEBUG !== "1") return
    const fs = await import("node:fs")
    fs.appendFileSync(".opencode/_debug.log", line + "\n")
  }

  return {
    "tool.execute.after": async (input, output) => {
      if ((input.tool || "").toLowerCase() !== "read") return
      const args = (input && input.args) || {}
      const fp = norm(args.filePath || args.file_path)
      const surgical = args.offset != null || args.limit != null
      if (!fp || surgical || !CODE_EXT.test(fp)) return
      try {
        const r = await $`python -m leo_code.filectx ${fp} --repo . --body-chars 600`.quiet().nothrow()
        const compressed = r.exitCode === 0 ? r.stdout.toString() : ""
        const original = String((output && output.output) || "")
        // Solo sustituir si de verdad ahorra (>25%): si no, el crudo ya es barato.
        const swap = compressed.length > 200 && compressed.length < original.length * 0.75
        await debug(`SWAP ${JSON.stringify({ fp, exit: r.exitCode, comp: compressed.length, orig: original.length, swap })}`)
        if (swap) output.output = compressed
      } catch (e) {
        await debug("SWAPERR " + String(e))
      }
    },
  }
}
