/**
 * KC-RAG built-in plugin for leo/code.
 * Injects structural code context into the system prompt.
 */
import type { Hooks, PluginInput } from "@leo-code/plugin"
import { getKcRagContext, isKcRagAvailable } from "../context/kcrag"

export async function kcragPlugin(_input: PluginInput): Promise<Hooks> {
  return {
    "experimental.chat.system.transform": async (_input, output) => {
      try {
        const available = await isKcRagAvailable()
        if (!available) return

        const ctx = await getKcRagContext({
          query: "",
          repo_path: process.cwd(),
          task_type: "auto",
          budget_tokens: 1500,
        })

        if (ctx?.context) {
          output.system.push(
            `<kcrag_context tokens="${ctx.tokens}" capsules="${ctx.capsules_total}">\n${ctx.context}\n</kcrag_context>`
          )
        }
      } catch {
        // Silent fallback — KC-RAG unavailable
      }
    },
  }
}
