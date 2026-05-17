/**
 * KC-RAG client for leo-code.
 * Communicates with leo-code-mcp Python sidecar via HTTP.
 * Replaces OpenCode's default context building with structural retrieval.
 */

interface KcRagContext {
  query: string
  repo_path: string
  task_type?: string
  budget_tokens?: number
}

interface KcRagResponse {
  context: string
  tokens: number
  task_type: string
  capsules_total: number
}

const KC_RAG_URL = process.env.LEO_MCP_URL || "http://localhost:9898"

/**
 * Get structural code context from KC-RAG sidecar.
 */
export async function getKcRagContext(params: KcRagContext): Promise<KcRagResponse | null> {
  try {
    const resp = await fetch(`${KC_RAG_URL}/context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: params.query,
        repo_path: params.repo_path,
        task_type: params.task_type || "auto",
        budget_tokens: params.budget_tokens || 2000,
      }),
      signal: AbortSignal.timeout(15000),
    })

    if (!resp.ok) return null
    return await resp.json()
  } catch {
    return null // Silent fallback — server not running
  }
}

/**
 * Search the Knowledge Graph for relevant code entities.
 */
export async function searchKcRag(query: string, repoPath: string, topK = 10) {
  try {
    const resp = await fetch(`${KC_RAG_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, repo_path: repoPath, top_k: topK }),
      signal: AbortSignal.timeout(10000),
    })
    if (!resp.ok) return []
    const data = await resp.json()
    return data.results || []
  } catch {
    return []
  }
}

/**
 * Check if KC-RAG sidecar is running.
 */
export async function isKcRagAvailable(): Promise<boolean> {
  try {
    const resp = await fetch(`${KC_RAG_URL}/health`, {
      signal: AbortSignal.timeout(3000),
    })
    return resp.ok
  } catch {
    return false
  }
}

/**
 * Trigger re-indexing of a repository.
 */
export async function indexRepo(repoPath: string, languages = "python") {
  try {
    const resp = await fetch(`${KC_RAG_URL}/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_path: repoPath, languages }),
      signal: AbortSignal.timeout(60000),
    })
    if (!resp.ok) return null
    return await resp.json()
  } catch {
    return null
  }
}
