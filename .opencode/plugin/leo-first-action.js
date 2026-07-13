// C de M1 (v3): sustitución forzada, no persuadida.
// 1) Veta exploración nativa hasta la primera llamada a get_context.
// 2) Un archivo cuyas fuentes YA vinieron en get_context no se relee entero
//    (sin válvula: el código ya está en el contexto; rango offset/limit pasa).
// 3) Leer entero cualquier OTRO archivo exige pedir antes su versión
//    comprimida: get_context("<archivo>"). Si tras eso insiste, pasa (válvula:
//    a veces el archivo entero hace falta de verdad).
//
// Medido antes de v3: el agente pagaba contexto Y relecturas (11/15 tareas
// peor que vanilla, t11 +575%). Sustituir, no añadir.
//
// Gated: solo actúa con LEO_FORCE=1 (benchmark lo pone en OCMCP; OC vanilla
// y usuarios sin opt-in quedan intactos).
export const LeoFirstAction = async () => {
  if (process.env.LEO_FORCE !== "1") return {}

  let ctxDone = false
  let blocks = 0
  const included = new Set()   // rutas relativas ya entregadas por get_context
  const queried = new Set()    // stems de archivo pedidos a get_context
  const vetoedOnce = new Set() // válvula por archivo para NO-incluidos
  // ponytail: bash queda fuera del veto (lo necesitan edits/tests); v1 asume
  // que el agente no esquiva leyendo via cat. Subir el cerco si se mide fuga.
  const EXPLORE = new Set(["read", "grep", "glob", "list"])

  const norm = (p) => String(p || "").replace(/\\/g, "/").toLowerCase()
  const stem = (p) => {
    const base = norm(p).split("/").pop() || ""
    return base.replace(/\.[^.]+$/, "")
  }

  return {
    "tool.execute.before": async (input, output) => {
      const t = (input.tool || "").toLowerCase()
      if (t.includes("get_context")) {
        ctxDone = true
        const q = norm(((output && output.args) || {}).query || "")
        // "explica pipeline.py" → stem "pipeline" queda desbloqueado
        for (const w of q.split(/[^a-z0-9_.-]+/)) {
          if (w.includes(".")) queried.add(w.replace(/\.[^.]+$/, ""))
        }
        return
      }
      // Válvula global: si get_context no está (MCP caído), tras 3 vetos se
      // deja trabajar — bloquear para siempre sería peor que no ahorrar.
      if (!ctxDone && blocks < 3 && EXPLORE.has(t)) {
        blocks++
        throw new Error(
          "Antes de explorar archivos llama a la tool MCP get_context (leo-code) " +
          "con tu tarea: devuelve las funciones/clases relevantes CON su codigo. " +
          "Despues podras usar " + t + " si de verdad falta algo."
        )
      }
      if (ctxDone && t === "read") {
        const args = (output && output.args) || {}
        const fp = norm(args.filePath || args.file_path)
        const surgical = args.offset != null || args.limit != null
        if (!fp || surgical) return
        // Fuente ya entregada: nunca entera de nuevo (el codigo ya lo tienes).
        for (const inc of included) {
          if (fp.endsWith(inc)) {
            throw new Error(
              "Ese archivo ya vino en el contexto de get_context: usa el codigo " +
              "que ya tienes. Para EDITAR con lineas exactas, relee con " +
              "offset/limit (rango), no el archivo entero."
            )
          }
        }
        // Archivo nuevo: primero su version comprimida, una insistencia pasa.
        const s = stem(fp)
        if (!queried.has(s) && !vetoedOnce.has(fp)) {
          vetoedOnce.add(fp)
          throw new Error(
            "Antes de leer ese archivo entero pide su version comprimida: " +
            "get_context(\"" + (fp.split("/").pop()) + "\") — devuelve sus " +
            "funciones/clases con codigo por ~80% menos tokens. Si tras eso " +
            "aun necesitas el archivo entero, reintenta este read."
          )
        }
      }
    },
    "tool.execute.after": async (input, output) => {
      const t = (input.tool || "").toLowerCase()
      if (!t.includes("get_context")) return
      // Footer de get_context: "[fuentes ya incluidas ... NO las releas: a.py, b.py]"
      const text =
        typeof output === "string" ? output :
        (output && (output.output || output.text || "")) || ""
      const m = String(text).match(/NO las releas:\s*([^\]]+)\]/)
      if (!m) return
      for (const f of m[1].split(",")) {
        const p = norm(f.trim())
        if (p) included.add(p)
      }
    },
  }
}
