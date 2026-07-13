// C de M1: adopción forzada, no persuadida. Bloquea las tools nativas de
// exploración hasta que el agente llame UNA vez a get_context (MCP leo-code),
// cuya respuesta ya incluye los cuerpos. Convierte el steering en garantía.
//
// Gated: solo actúa con LEO_FORCE=1 (el benchmark lo pone en OCMCP; OC vanilla
// y cualquier usuario sin opt-in quedan intactos).
export const LeoFirstAction = async () => {
  if (process.env.LEO_FORCE !== "1") return {}

  let ctxDone = false
  let blocks = 0
  // ponytail: bash queda fuera del veto (lo necesitan edits/tests); v1 asume
  // que el agente no esquiva leyendo via cat. Subir el cerco si se mide fuga.
  const EXPLORE = new Set(["read", "grep", "glob", "list"])

  return {
    "tool.execute.before": async (input) => {
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
    },
  }
}
