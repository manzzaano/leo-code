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

export interface KcRagResponse {
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
      signal: AbortSignal.timeout(30000),
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

export type RepoMode = "large" | "medium" | "small"

/**
 * Detect repo size mode from KC-RAG stats.
 * large: >500 capsules (e.g. Laravel) — KC-RAG must dominate, no file browsing
 * medium: 100-500 capsules — current three-tier logic
 * small: <100 capsules — KC-RAG as supplement, all tools available
 */
export async function detectRepoMode(): Promise<RepoMode> {
  try {
    const resp = await fetch(`${KC_RAG_URL}/stats`, {
      signal: AbortSignal.timeout(3000),
    })
    if (!resp.ok) return "medium"
    const stats = (await resp.json()) as { total_capsules?: number }
    const n = stats.total_capsules ?? 0
    if (n > 500) return "large"
    if (n > 100) return "medium"
    return "small"
  } catch {
    return "medium"
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

/**
 * Single-shot LLM call with KC-RAG context injected — no tools, no agent loop.
 * Returns the answer plus a confidence score (1-5).
 */
export async function getKcRagAnswer(
  query: string,
  context: string,
  model = "deepseek-chat",
): Promise<{ text: string; confidence: number; tokens: number } | null> {
  const systemPrompt = [
    "Eres un asistente experto en código. Responde en español, preciso y conciso.",
    "Usa SOLO el contexto proporcionado abajo. No inventes información.",
    "",
    "<context>",
    context,
    "</context>",
    "",
    "Al final de tu respuesta, en una línea separada, escribe CONFianza: X/5",
    "donde X es tu confianza en la respuesta (1=poca, 5=mucha).",
  ].join("\n")

  const apiKey = process.env.DEEPSEEK_API_KEY
  if (!apiKey) return null

  try {
    const resp = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: query },
        ],
        temperature: 0.2,
        max_tokens: 1024,
      }),
      signal: AbortSignal.timeout(30000),
    })

    if (!resp.ok) return null
    const data = (await resp.json()) as any
    const text: string = data.choices?.[0]?.message?.content ?? ""
    const tokens: number = data.usage?.total_tokens ?? 0

    const confMatch = text.match(/CONFianza:?\s*(\d)\s*\/\s*5/i)
    const confidence = confMatch ? parseInt(confMatch[1], 10) : 3

    return {
      text: text.replace(/\n?CONFianza:?\s*\d\s*\/\s*5\n?/i, "").trim(),
      confidence,
      tokens,
    }
  } catch {
    return null
  }
}
