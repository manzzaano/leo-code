import { type KcRagResponse, type RepoMode } from "./kcrag"

export function shouldDisableAllTools(
  result: KcRagResponse | null,
  repoMode: RepoMode = "medium",
): boolean {
  if (!result || result.tokens === 0) return false
  if (result.task_type === "no_code") return true
  // Large repo: even weak context is enough — file browsing too expensive
  if (repoMode === "large" && result.tokens > 100) return true
  return result.tokens > 300 && (
    result.task_type === "code_query" ||
    result.task_type === "search"     ||
    result.task_type === "refactor"   ||
    result.task_type === "code_gen"   ||
    result.task_type === "auto"
  )
}
