/**
 * KC-RAG built-in plugin for leo/code.
 * Injects structural code context into the system prompt using the actual user query.
 *
 * Two-hook pattern:
 *   1. chat.message  — captures the incoming user query
 *   2. experimental.chat.system.transform — injects KC-RAG context into system prompt
 *
 * chat.message fires when the user sends a message (has the query text).
 * experimental.chat.system.transform fires right before the LLM call (can modify system).
 */
import type { Hooks, PluginInput } from "@leo-code/plugin"
import { getKcRagContext, isKcRagAvailable } from "../context/kcrag"

// Shared state: last user query captured by chat.message hook
let _pendingQuery = ""

export async function kcragPlugin(_input: PluginInput): Promise<Hooks> {
  return {
    // Hook 1: capture the user query as soon as the message arrives
    "chat.message": async (input, _output) => {
      try {
        // Parts from the output contain the user text; input has session/message IDs
        // Store the query from the message content — will be used in system transform
        const msg = _output.parts
          .filter((p: any) => p.type === "text")
          .map((p: any) => p.text as string)
          .join(" ")
          .trim()
        if (msg) _pendingQuery = msg
      } catch {
        // ignore
      }
    },

    // Hook 2: inject KC-RAG context into system prompt using the captured query
    "experimental.chat.system.transform": async (_input, output) => {
      try {
        const query = _pendingQuery
        if (!query) return

        const available = await isKcRagAvailable()
        if (!available) return

        const ctx = await getKcRagContext({
          query,
          repo_path: process.cwd(),
          task_type: "auto",
          budget_tokens: 3000,
        })

        if (ctx?.context) {
          const taskHint = ctx.task_type === "search"
            ? "Lista completa de funciones con indicador ✓doc (tiene docstring) o ✗doc (sin docstring). Usa esa lista directamente."
            : ctx.task_type === "refactor"
            ? "Función target con TODAS sus llamadas y relaciones LLAMA ya resueltas."
            : ctx.task_type === "no_code"
            ? "Documentación de dominio con condiciones, tarifas y requisitos."
            : "Código fuente completo de las funciones relevantes con firmas, imports y call graph."

          const kcBlock =
            `\n\n<kcrag_context tokens="${ctx.tokens}" capsules="${ctx.capsules_total}" task="${ctx.task_type}">\n${ctx.context}\n</kcrag_context>` +
            `\n\n⚠️ INSTRUCCION KC-RAG — PRIORIDAD MAXIMA — ANULA TODO LO ANTERIOR ⚠️\n` +
            `El contexto <kcrag_context> contiene: ${taskHint}\n` +
            `PROHIBIDO: read_file, list_directory, search_files, bash, grep, o cualquier herramienta de lectura.\n` +
            `Responde DIRECTAMENTE del contexto KC-RAG. No abras ningún archivo. Empieza la respuesta ahora.`
          if (output.system.length > 0) {
            output.system[0] = output.system[0] + kcBlock
          } else {
            output.system.push(kcBlock)
          }
        }
      } catch {
        // Silent fallback — KC-RAG unavailable
      }
    },
  }
}
