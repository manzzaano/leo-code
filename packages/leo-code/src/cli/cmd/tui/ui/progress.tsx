import { useTheme } from "@tui/context/theme"

type ProgressBarProps = {
  value: number
  width?: number
  showPercent?: boolean
}

const FILLED = "█"
const EMPTY = "░"

export function ProgressBar(props: ProgressBarProps) {
  const { theme } = useTheme()
  const barWidth = () => props.width ?? 20
  const clamped = () => Math.max(0, Math.min(1, props.value))
  const filled = () => Math.round(clamped() * barWidth())
  const bar = () => FILLED.repeat(filled()) + EMPTY.repeat(barWidth() - filled())
  const pct = () => Math.round(clamped() * 100)

  return (
    <box flexDirection="row" gap={1}>
      <text fg={theme.primary}>{bar()}</text>
      {props.showPercent !== false && (
        <text fg={theme.textMuted}>{`${pct()}%`}</text>
      )}
    </box>
  )
}
