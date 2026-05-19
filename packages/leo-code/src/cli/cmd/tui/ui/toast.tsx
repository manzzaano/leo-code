import { createContext, useContext, type ParentProps, Show, For } from "solid-js"
import { createStore } from "solid-js/store"
import { useTheme } from "@tui/context/theme"
import { useTerminalDimensions } from "@opentui/solid"
import { RoundedBorder } from "../component/border"
import { TextAttributes } from "@opentui/core"
import { Schema } from "effect"
import { TuiEvent } from "../event"

type ToastInput = Schema.Codec.Encoded<typeof TuiEvent.ToastShow.properties>
export type ToastOptions = Schema.Schema.Type<typeof TuiEvent.ToastShow.properties>

const decodeToastOptions = Schema.decodeUnknownSync(TuiEvent.ToastShow.properties)

const MAX_VISIBLE = 3

const VARIANT_ICON: Record<string, string> = {
  success: "✓ ",
  error: "✗ ",
  warning: "⚠ ",
  info: "ℹ ",
}

export function Toast() {
  const toast = useToast()
  const { theme } = useTheme()
  const dimensions = useTerminalDimensions()

  return (
    <Show when={toast.queue.length > 0}>
      <box
        position="absolute"
        top={2}
        right={2}
        flexDirection="column"
        gap={1}
        maxWidth={Math.min(60, dimensions().width - 6)}
      >
        <For each={toast.queue}>
          {(item) => (
            <box
              paddingLeft={2}
              paddingRight={2}
              paddingTop={1}
              paddingBottom={1}
              backgroundColor={theme.backgroundPanel}
              borderColor={theme[item.options.variant]}
              border={["top", "left", "right", "bottom"]}
              customBorderChars={RoundedBorder.customBorderChars}
            >
              {/* Icon + title row */}
              <box flexDirection="row" marginBottom={1}>
                <text fg={theme[item.options.variant]} attributes={TextAttributes.BOLD}>
                  {VARIANT_ICON[item.options.variant] ?? "· "}
                </text>
                <Show when={item.options.title}>
                  <text attributes={TextAttributes.BOLD} fg={theme.text}>
                    {item.options.title}
                  </text>
                </Show>
              </box>
              <text fg={theme.text} wrapMode="word" width="100%">
                {item.options.message}
              </text>
            </box>
          )}
        </For>
      </box>
    </Show>
  )
}

function init() {
  const [store, setStore] = createStore({
    queue: [] as { id: number; options: ToastOptions }[],
  })

  let nextId = 0
  const timers = new Map<number, NodeJS.Timeout>()

  function removeId(id: number) {
    timers.delete(id)
    setStore("queue", (q) => q.filter((t) => t.id !== id))
  }

  const toast = {
    show(input: ToastInput) {
      const options = decodeToastOptions(input)
      const id = nextId++

      setStore("queue", (q) => {
        const next = [...q, { id, options }]
        if (next.length > MAX_VISIBLE) {
          const removed = next.shift()!
          const timer = timers.get(removed.id)
          if (timer) clearTimeout(timer)
          timers.delete(removed.id)
        }
        return next
      })

      const timer = setTimeout(() => removeId(id), options.duration).unref()
      timers.set(id, timer)
    },
    error: (err: any) => {
      if (err instanceof Error)
        return toast.show({
          variant: "error",
          message: err.message,
        })
      toast.show({
        variant: "error",
        message: "An unknown error has occurred",
      })
    },
    get queue() {
      return store.queue
    },
  }
  return toast
}

export type ToastContext = ReturnType<typeof init>

const ctx = createContext<ToastContext>()

export function ToastProvider(props: ParentProps) {
  const value = init()
  return <ctx.Provider value={value}>{props.children}</ctx.Provider>
}

export function useToast() {
  const value = useContext(ctx)
  if (!value) {
    throw new Error("useToast must be used within a ToastProvider")
  }
  return value
}
