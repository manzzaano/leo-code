import { Show, For, createMemo } from "solid-js"
import { useLeaderActive, useLeoCodeKeymap, formatKeySequence } from "../keymap"
import { useTuiConfig } from "../context/tui-config"
import { useTheme } from "../context/theme"
import { useTerminalDimensions } from "@opentui/solid"

const COMMANDS = [
  { name: "session.list", title: "Switch session" },
  { name: "session.new", title: "New session" },
  { name: "command.palette.show", title: "Command palette" },
  { name: "model.list", title: "Switch model" },
  { name: "agent.list", title: "Switch agent" },
  { name: "help.show", title: "Help" },
  { name: "app.exit", title: "Exit" },
] as const

export function WhichKey() {
  const leaderActive = useLeaderActive()
  const keymap = useLeoCodeKeymap()
  const config = useTuiConfig()
  const { theme } = useTheme()
  const dimensions = useTerminalDimensions()

  const shortcuts = createMemo(() =>
    COMMANDS.map((cmd) => {
      const bindings = keymap
        .getCommandBindings({
          visibility: "registered",
          commands: [cmd.name],
        })
        .get(cmd.name)
      const key = bindings?.[0]?.sequence ? formatKeySequence(bindings[0].sequence, config) : ""
      return { ...cmd, key }
    }),
  )

  const maxKeyWidth = createMemo(() => Math.max(...shortcuts().map((s) => s.key.length), 1) + 2)
  const popupWidth = createMemo(() => Math.min(maxKeyWidth() + 24, dimensions().width - 4))

  return (
    <Show when={leaderActive()}>
      <box
        position="absolute"
        bottom={0}
        left={0}
        right={0}
        flexDirection="row"
        justifyContent="center"
        paddingBottom={2}
        zIndex={5000}
      >
        <box
          width={popupWidth()}
          paddingTop={1}
          paddingBottom={1}
          paddingLeft={2}
          paddingRight={2}
          backgroundColor={theme.backgroundPanel}
          borderColor={theme.borderActive}
          border={["top", "left", "right", "bottom"]}
          flexDirection="column"
          gap={0.5}
        >
          <box paddingBottom={0.5}>
            <text fg={theme.textMuted}>Leader key shortcuts</text>
          </box>
          <For each={shortcuts()}>
            {(cmd) => (
              <box flexDirection="row" justifyContent="space-between">
                <text fg={theme.text}>{cmd.title}</text>
                <Show when={cmd.key}>
                  <text fg={theme.primary}>{cmd.key}</text>
                </Show>
              </box>
            )}
          </For>
        </box>
      </box>
    </Show>
  )
}
