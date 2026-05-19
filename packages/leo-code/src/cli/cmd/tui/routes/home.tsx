import { Prompt, type PromptRef } from "@tui/component/prompt"
import { createEffect, createSignal, createMemo, onMount, Show, For } from "solid-js"
import { useProject } from "../context/project"
import { useSync } from "../context/sync"
import { Toast } from "../ui/toast"
import { Badge } from "../ui/badge"
import { useArgs } from "../context/args"
import { useRouteData, useRoute } from "@tui/context/route"
import { usePromptRef } from "../context/prompt"
import { useLocal } from "../context/local"
import { TuiPluginRuntime } from "@/cli/cmd/tui/plugin/runtime"
import { useEditorContext } from "@tui/context/editor"
import { useTheme } from "@tui/context/theme"
import { useSDK } from "@tui/context/sdk"
import { TextAttributes } from "@opentui/core"
import { useTuiConfig } from "../context/tui-config"
import { useLeoCodeKeymap, formatKeySequence } from "../keymap"
import { RoundedBorder } from "../component/border"

let once = false
const placeholder = {
  normal: ["Fix a TODO in the codebase", "What is the tech stack of this project?", "Fix broken tests"],
  shell: ["ls -la", "git status", "pwd"],
}

const SIDEBAR_WIDTH = 24

function relativeTime(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60_000) return "just now"
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`
  return new Date(ts).toLocaleDateString("en", { month: "short", day: "numeric" })
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen - 1) + "…"
}

function sessionKeyShortcut(config: ReturnType<typeof useTuiConfig>, keymap: ReturnType<typeof useLeoCodeKeymap>) {
  const bindings = keymap
    .getCommandBindings({ visibility: "registered", commands: ["session.list"] })
    .get("session.list")
  const key = bindings?.[0]?.sequence
  return key ? formatKeySequence(key, config) : "Ctrl+P"
}

export function Home() {
  const sync = useSync()
  const project = useProject()
  const route = useRouteData("home")
  const promptRef = usePromptRef()
  const [ref, setRef] = createSignal<PromptRef | undefined>()
  const args = useArgs()
  const local = useLocal()
  const editor = useEditorContext()
  const { theme } = useTheme()
  const navigate = useRoute()
  const sdk = useSDK()
  const config = useTuiConfig()
  const keymap = useLeoCodeKeymap()
  let sent = false

  onMount(() => {
    editor.clearSelection()
  })

  const bind = (r: PromptRef | undefined) => {
    setRef(r)
    promptRef.set(r)
    if (once || !r) return
    if (route.prompt) {
      r.set(route.prompt)
      once = true
      return
    }
    if (!args.prompt) return
    r.set({ input: args.prompt, parts: [] })
    once = true
  }

  createEffect(() => {
    const r = ref()
    if (sent) return
    if (!r) return
    if (!sync.ready || !local.model.ready) return
    if (!args.prompt) return
    if (r.current.input !== args.prompt) return
    sent = true
    r.submit()
  })

  const recentSessions = createMemo(() =>
    sync.data.session
      .filter((s) => s.parentID === undefined)
      .sort((a, b) => b.time.updated - a.time.updated)
      .slice(0, 8),
  )

  const modelInfo = createMemo(() => local.model.parsed())
  const agentInfo = createMemo(() => local.agent.current())
  const sessionShortcut = createMemo(() => sessionKeyShortcut(config, keymap))

  return (
    <>
      {/* Two-column layout: sidebar + main */}
      <box flexDirection="row" flexGrow={1} minHeight={0}>

        {/* ── Sidebar ────────────────────────────────────────────────── */}
        <box
          width={SIDEBAR_WIDTH}
          flexShrink={0}
          flexDirection="column"
          backgroundColor={theme.backgroundPanel}
          border={["right"]}
          borderColor={theme.borderSubtle}
          paddingTop={1}
          paddingLeft={1}
          paddingRight={1}
        >
          {/* Sidebar section header */}
          <box paddingBottom={1}>
            <text fg={theme.textMuted} attributes={TextAttributes.BOLD}>
              {"Sessions"}
            </text>
          </box>

          {/* Session list */}
          <Show
            when={sync.ready && recentSessions().length > 0}
            fallback={
              <box paddingTop={1}>
                <text fg={theme.borderSubtle}>{"No sessions yet"}</text>
              </box>
            }
          >
            <For each={recentSessions()}>
              {(session, index) => (
                <box
                  flexDirection="column"
                  paddingTop={index() === 0 ? 0 : 0.5}
                  paddingBottom={0.5}
                  onMouseUp={() => {
                    navigate.navigate({ type: "session", sessionID: session.id })
                  }}
                >
                  <text fg={theme.text} attributes={TextAttributes.BOLD}>
                    {truncate(session.title || "New session", SIDEBAR_WIDTH - 3)}
                  </text>
                  <text fg={theme.textMuted}>
                    {"  " + relativeTime(session.time.updated)}
                  </text>
                </box>
              )}
            </For>
          </Show>

          {/* Spacer pushes hint to bottom */}
          <box flexGrow={1} />

          {/* Browse hint */}
          <box paddingBottom={1}>
            <text fg={theme.borderSubtle}>{sessionShortcut() + " browse all"}</text>
          </box>
        </box>

        {/* ── Main content ───────────────────────────────────────────── */}
        <box
          flexGrow={1}
          flexDirection="column"
          alignItems="center"
          paddingLeft={2}
          paddingRight={2}
        >
          <box flexGrow={1} minHeight={0} />

          {/* Logo */}
          <box flexShrink={0} paddingTop={1} paddingBottom={1}>
            <TuiPluginRuntime.Slot name="home_logo" mode="replace">
              <box flexDirection="row">
                <text fg={theme.text} attributes={TextAttributes.BOLD}>{"leo"}</text>
                <text fg={theme.primary} attributes={TextAttributes.BOLD}>{"-"}</text>
                <text fg={theme.text} attributes={TextAttributes.BOLD}>{"code"}</text>
              </box>
            </TuiPluginRuntime.Slot>
          </box>

          <box height={1} minHeight={0} flexShrink={1} />

          {/* Prompt input card */}
          <box width="100%" maxWidth={65} zIndex={1000} paddingTop={1} flexShrink={0}>
            <TuiPluginRuntime.Slot
              name="home_prompt"
              mode="replace"
              workspace_id={project.workspace.current()}
              ref={bind}
            >
              <Prompt
                ref={bind}
                workspaceID={project.workspace.current()}
                right={<TuiPluginRuntime.Slot name="home_prompt_right" workspace_id={project.workspace.current()} />}
                placeholders={placeholder}
              />
            </TuiPluginRuntime.Slot>
          </box>

          <TuiPluginRuntime.Slot name="home_bottom" />
          <box flexGrow={1} minHeight={0} />

          {/* Status bar — model · agent */}
          <Show when={modelInfo() || agentInfo()}>
            <box
              flexDirection="row"
              gap={1}
              paddingTop={1}
              paddingBottom={1}
              justifyContent="center"
            >
              <Show when={agentInfo()?.name}>
                <Badge variant="primary">{agentInfo()!.name}</Badge>
                <text fg={theme.borderSubtle}>{"·"}</text>
              </Show>
              <Show when={modelInfo()?.model}>
                <Badge variant="muted">{modelInfo()!.model}</Badge>
              </Show>
            </box>
          </Show>

          <Toast />
        </box>
      </box>

      {/* ── Status bar / Footer ────────────────────────────────────── */}
      <box width="100%" flexShrink={0}>
        <TuiPluginRuntime.Slot name="home_footer" mode="single_winner" />
      </box>
    </>
  )
}
