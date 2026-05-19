import type { JSX } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { TextAttributes } from "@opentui/core"

type BadgeVariant = "primary" | "success" | "error" | "warning" | "info" | "muted"

type BadgeProps = {
  variant?: BadgeVariant
  children: JSX.Element
}

const variantKey: Record<BadgeVariant, string> = {
  primary: "primary",
  success: "success",
  error: "error",
  warning: "warning",
  info: "info",
  muted: "textMuted",
}

export function Badge(props: BadgeProps) {
  const { theme } = useTheme()
  const variant = () => props.variant ?? "muted"
  const color = () => (theme[variantKey[variant()] as keyof typeof theme] as unknown) as string

  return (
    <box flexDirection="row">
      <text fg={color()}>{"╴"}</text>
      <text fg={color()} attributes={TextAttributes.BOLD}>
        {props.children}
      </text>
      <text fg={color()}>{"╶"}</text>
    </box>
  )
}
