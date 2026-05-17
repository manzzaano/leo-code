/**
 * KC-RAG search tool for leo-code.
 * Exposes structural code search to the LLM via tool calling.
 * 
 * This is a new TOOL that the LLM can call:
 *   kcrag_search(query: "how does bfs_subgraph work")
 * 
 * It replaces OpenCode's default search with KC-RAG semantic search.
 */

import { tool } from "ai"
import { z } from "zod"
import { searchKcRag } from "../context/kcrag"

export const kcragSearchTool = tool({
  description: `Search the codebase Knowledge Graph for relevant functions, classes, 
and modules using structural retrieval. More precise than grep — understands 
dependencies, call graphs, and semantic similarity.

Use this when you need to find code related to a concept, not just text matching.`,
  parameters: z.object({
    query: z.string().describe("What to search for — can be a concept, function name, or description"),
  }),
  execute: async ({ query }, { workingDirectory }) => {
    const results = await searchKcRag(query, workingDirectory || ".", 10)
    if (!results.length) return "No results found in the Knowledge Graph."

    return results
      .map(
        (r: any) =>
          `[${r.type}] ${r.name} (${r.file_path})\n  ${r.signature}${r.docstring ? `\n  ${r.docstring}` : ""}`
      )
      .join("\n\n")
  },
})
