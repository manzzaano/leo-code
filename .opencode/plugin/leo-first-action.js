// C de M1: adopción forzada, no persuadida.
// 1) Bloquea las tools nativas de exploración hasta que el agente llame UNA vez
//    a get_context (MCP leo-code), cuya respuesta ya incluye los cuerpos.
// 2) Tras get_context, veta releer los archivos cuyas fuentes YA vinieron en la
//    respuesta (medido en benchmark: hasta 28 relecturas/corrida que duplican
//    coste). Lectura con rango (offset/limit) se permite: editar exige líneas.
//
// Gated: solo actúa con LEO_FORCE=1 (el benchmark lo pone en OCMCP; OC vanilla
// y cualquier usuario sin opt-in quedan intactos).
export const LeoFirstAction = async () => {
  if (process.env.LEO_FORCE !== "1") return {}

  let ctxDone = false
  let blocks = 0
  const included = new Set()      // rutas (relativas) ya entregadas por get_context
  const vetoedOnce = new Set()    // válvula por archivo: 1 veto, luego pasa
  // ponytail: bash queda fuera del veto (lo necesitan edits/tests); v1 asume
  // que el agente no esquiva leyendo via cat. Subir el cerco si se mide fuga.
  const EXPLORE = new Set(["read", "grep", "glob", "list"])

  const norm = (p) => String(p || "").replace(/\\/g, "/").toLowerCase()

  return {
    "tool.execute.before": async (input, output) => {
      const t = (input.tool || "").toLowerCase()
      if (t.includes("get_context")) {
        ctxDone = true
        return
      }
      // Válvula: si get_context no está disponible (MCP caído), tras 3 vetos
      // se deja trabajar — bloquear para siempre sería peor que no ahorrar.
      if (!ctxDone && blocks < 3 && EXPLORE.has(t)) {
        blocks++
        throw new Error(
          "Antes de explorar archivos llama a la tool MCP get_context (leo-code) " +
          "con tu tarea: devuelve las funciones/clases relevantes CON su codigo. " +
          "Despues podras usar " + t + " si de verdad falta algo."
        )
      }
      // Relectura de fuente ya entregada: veta una vez por archivo, salvo
      // lectura quirúrgica con rango (editar exige ver líneas exactas).
      if (ctxDone && t === "read") {
        const args = (output && output.args) || {}
        const fp = norm(args.filePath || args.file_path)
        const surgical = args.offset != null || args.limit != null
        if (fp && !surgical) {
          for (const inc of included) {
            if (fp.endsWith(inc) && !vetoedOnce.has(inc)) {
              vetoedOnce.add(inc)
              throw new Error(
                "Ese archivo ya vino en el contexto de get_context: usa el codigo " +
                "que ya tienes. Si vas a EDITAR y necesitas lineas exactas, relee " +
                "con offset/limit (rango concreto), no el archivo entero."
              )
            }
          }
        }
      }
    },
    "tool.execute.after": async (input, output) => {
      const t = (input.tool || "").toLowerCase()
      if (!t.includes("get_context")) return
      // El footer de get_context lista las fuentes incluidas:
      // "[fuentes ya incluidas en este contexto — NO las releas: a.py, b.py]"
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
