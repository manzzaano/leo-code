/**
 * KC-RAG built-in plugin for leo/code.
 * Injects structural code context into the system prompt and controls tools
 * based on context quality AND repo size (RepoMode).
 *
 * RepoMode (detected once per session via /stats):
 *   large  (>500 capsules) — KC-RAG dominates, file browsing disabled always
 *   medium (100-500)       — three-tier system based on token count + task_type
 *   small  (<100)          — KC-RAG as supplement, all tools available
 *
 * Tier matrix for medium repos:
 *   Tier 1 — tokens>300 + code_query/search/refactor/code_gen/auto:
 *            replace system prompt, disable ALL tools
 *   Tier 2 — tokens>200 + code_query/search:
 *            disable heavy tools, keep read/glob
 *   Tier 2 — tokens>200 + refactor/code_gen:
 *            disable read tools, keep edit/write
 *   Tier 2 — auto:
 *            disable heavy tools
 *   Tier 3 — tokens<=200 or no context:
 *            all tools, add CodeGraph hint
 */
import type { Hooks, PluginInput } from "@leo-code/plugin"
import {
  getKcRagContext,
  isKcRagAvailable,
  detectRepoMode,
  type KcRagResponse,
  type RepoMode,
} from "../context/kcrag"

let _kcragResult: KcRagResponse | null = null
let _pendingQuery = ""
let _repoMode: RepoMode | null = null

const HEAVY_TOOLS = [
  "grep", "bash", "task", "task_status", "webfetch", "websearch",
  "repo_clone", "repo_overview", "lsp", "skill",
]
const ALL_READ_TOOLS = [...HEAVY_TOOLS, "read", "glob"]

const MINIMAL_SYSTEM = "Eres un asistente experto en codigo. Responde en espanol. Se preciso y conciso."

function taskHint(taskType: string) {
  if (taskType === "search")
    return "Lista de funciones con indicador ✓doc (tiene docstring) o ✗doc (sin docstring)."
  if (taskType === "refactor")
    return "Función target con sus llamadas y relaciones resueltas."
  if (taskType === "no_code")
    return "Documentación de dominio con condiciones, tarifas y requisitos."
  return "Código fuente de las funciones relevantes con firmas, imports y call graph."
}

const READ_TASKS = new Set(["search", "code_query", "auto"])

export async function kcragPlugin(_input: PluginInput): Promise<Hooks> {
  return {
    "chat.message": async (_input, output) => {
      try {
        const query = output.parts
          .filter((p: any) => p.type === "text")
          .map((p: any) => p.text as string)
          .join(" ")
          .trim()
        if (!query) return
        _pendingQuery = query

        const available = await isKcRagAvailable()
        if (!available) return

        // Detect repo size once per session
        if (_repoMode === null) {
          _repoMode = await detectRepoMode()
        }

        const repoPath = process.env.LEO_REPO_PATH || process.cwd()
        _kcragResult = await getKcRagContext({
          query,
          repo_path: repoPath,
          task_type: "auto",
          budget_tokens: 800,
        })
      } catch {
        _kcragResult = null
      }
    },

    "experimental.chat.system.transform": async (_input, output) => {
      const hasKcContext = !!_kcragResult?.context && _kcragResult.tokens > 0
      const mode = _repoMode ?? "medium"

      // Tier 3: no KC-RAG context — hint agent to use CodeGraph tools
      if (!hasKcContext) {
        const cgHint = "\n\nUsa codegraph_context para obtener contexto estructural del repositorio. " +
          "Para call graph usa codegraph_callers y codegraph_callees."
        if (output.system.length > 0) {
          output.system[0] = output.system[0] + cgHint
        } else {
          output.system.push(cgHint)
        }
        return
      }

      const hint = taskHint(_kcragResult!.task_type)
      const kcBlock =
        `\n\n<kcrag_context tokens="${_kcragResult!.tokens}" task="${_kcragResult!.task_type}" repo="${mode}">\n${_kcragResult!.context}\n</kcrag_context>` +
        `\n\n${hint}`

      // Large repo: KC-RAG always dominates — replace system prompt
      if (mode === "large") {
        const hasRead = READ_TASKS.has(_kcragResult!.task_type)
        const largeHint = "\nRepositorio grande: usa SOLO el contexto KC-RAG proporcionado. No navegues archivos directamente."
        const isFlowQuery = /flujo|flow|traza|trace|orden|order|paso|step|ejecuci/i.test(_pendingQuery)
        const flowHint = hasRead && isFlowQuery
          ? "\nPara trazar un flujo de ejecución: lee SOLO el archivo mencionado con read (una sola llamada), lista TODAS las funciones llamadas en orden exacto del cuerpo. No sigas imports ni leas más archivos."
          : ""
        const toolHint = hasRead
          ? `\nPuedes usar read para ver el contenido completo del archivo identificado por KC-RAG. No explores el repositorio arbitrariamente.${flowHint}`
          : "\nResponde DIRECTAMENTE. No tienes herramientas de fichero."
        output.system[0] = MINIMAL_SYSTEM + kcBlock + largeHint + toolHint
        return
      }

      // Small repo: KC-RAG as supplement — add context but allow tools
      if (mode === "small") {
        const smallHint = "\nKC-RAG proporciona contexto adicional. Puedes explorar el repo si necesitas más información."
        if (output.system.length > 0) {
          output.system[0] = output.system[0] + kcBlock + smallHint
        } else {
          output.system.push(kcBlock + smallHint)
        }
        return
      }

      // Medium repo: three-tier logic
      const isStrong = _kcragResult!.tokens > 300
      const isTier1 = isStrong && (
        _kcragResult!.task_type === "code_query" ||
        _kcragResult!.task_type === "search"     ||
        _kcragResult!.task_type === "no_code"    ||
        _kcragResult!.task_type === "refactor"   ||
        _kcragResult!.task_type === "code_gen"   ||
        _kcragResult!.task_type === "auto"
      )
      const hasRead = READ_TASKS.has(_kcragResult!.task_type)
      const isFlowQuery = /flujo|flow|traza|trace|orden|order|paso|step|ejecuci/i.test(_pendingQuery)
      const flowHint = hasRead && isFlowQuery
        ? "\nPara trazar un flujo de ejecución: lee SOLO el archivo mencionado con read (una sola llamada), lista TODAS las funciones llamadas en orden exacto del cuerpo. No sigas imports ni leas más archivos."
        : ""
      const toolHint = isTier1
        ? (hasRead
          ? `\nPuedes usar read para ver el contenido completo del archivo identificado. No explores el repositorio arbitrariamente.${flowHint}`
          : "\nResponde DIRECTAMENTE. No tienes herramientas.")
        : ""

      const fullBlock = kcBlock + toolHint
      if (isTier1) {
        output.system[0] = MINIMAL_SYSTEM + fullBlock
      } else if (output.system.length > 0) {
        output.system[0] = output.system[0] + fullBlock
      } else {
        output.system.push(fullBlock)
      }
    },

    "experimental.chat.tools.filter": async (_input, output) => {
      if (!_kcragResult || _kcragResult.tokens === 0) return

      const mode = _repoMode ?? "medium"
      const taskType = _kcragResult.task_type

      // Small repo: keep all tools
      if (mode === "small") return

      // Large repo: disable ALL tools except read+glob for READ_TASKS
      if (mode === "large" && _kcragResult.tokens > 100) {
        for (const t of Object.keys(output.tools)) {
          if (t === "question") continue
          if (READ_TASKS.has(taskType) && (t === "read" || t === "glob")) continue
          delete output.tools[t]
        }
        return
      }

      // Medium repo below follows:

      // Tier 1: no_code — always disable all tools
      if (taskType === "no_code") {
        for (const t of Object.keys(output.tools)) {
          if (t !== "question") delete output.tools[t]
        }
        return
      }

      // Tier 1: strong context — disable ALL tools except read+glob for READ_TASKS
      if (_kcragResult.tokens > 300 && (
        taskType === "code_query" ||
        taskType === "search"     ||
        taskType === "refactor"   ||
        taskType === "code_gen"   ||
        taskType === "auto"
      )) {
        for (const t of Object.keys(output.tools)) {
          if (t === "question") continue
          if (READ_TASKS.has(taskType) && (t === "read" || t === "glob")) continue
          delete output.tools[t]
        }
        return
      }

      // Tier 2: medium context — disable heavy tools, keep read/glob for verification
      if (_kcragResult.tokens > 200 && (taskType === "code_query" || taskType === "search")) {
        for (const t of HEAVY_TOOLS) delete output.tools[t]
        return
      }

      // Tier 2: medium context for refactor/code_gen — disable read tools, keep edit/write
      if (_kcragResult.tokens > 200 && (taskType === "refactor" || taskType === "code_gen")) {
        for (const t of ALL_READ_TOOLS) delete output.tools[t]
        return
      }

      // Tier 2: auto with context — disable heavy tools
      if (taskType === "auto") {
        for (const t of HEAVY_TOOLS) delete output.tools[t]
      }
    },
  }
}
