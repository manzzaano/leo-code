import { Config } from "effect"

function truthy(key: string) {
  const value = process.env[key]?.toLowerCase()
  return value === "true" || value === "1"
}

const LEO_EXPERIMENTAL = truthy("LEO_EXPERIMENTAL")
const copy = process.env["LEO_EXPERIMENTAL_DISABLE_COPY_ON_SELECT"]

export const Flag = {
  OTEL_EXPORTER_OTLP_ENDPOINT: process.env["OTEL_EXPORTER_OTLP_ENDPOINT"],
  OTEL_EXPORTER_OTLP_HEADERS: process.env["OTEL_EXPORTER_OTLP_HEADERS"],

  LEO_AUTO_HEAP_SNAPSHOT: truthy("LEO_AUTO_HEAP_SNAPSHOT"),
  LEO_GIT_BASH_PATH: process.env["LEO_GIT_BASH_PATH"],
  LEO_CONFIG: process.env["LEO_CONFIG"],
  LEO_CONFIG_CONTENT: process.env["LEO_CONFIG_CONTENT"],
  LEO_DISABLE_AUTOUPDATE: truthy("LEO_DISABLE_AUTOUPDATE"),
  LEO_ALWAYS_NOTIFY_UPDATE: truthy("LEO_ALWAYS_NOTIFY_UPDATE"),
  LEO_DISABLE_PRUNE: truthy("LEO_DISABLE_PRUNE"),
  LEO_DISABLE_TERMINAL_TITLE: truthy("LEO_DISABLE_TERMINAL_TITLE"),
  LEO_SHOW_TTFD: truthy("LEO_SHOW_TTFD"),
  LEO_PERMISSION: process.env["LEO_PERMISSION"],
  LEO_DISABLE_AUTOCOMPACT: truthy("LEO_DISABLE_AUTOCOMPACT"),
  LEO_DISABLE_MODELS_FETCH: truthy("LEO_DISABLE_MODELS_FETCH"),
  LEO_DISABLE_MOUSE: truthy("LEO_DISABLE_MOUSE"),
  LEO_FAKE_VCS: process.env["LEO_FAKE_VCS"],
  LEO_SERVER_PASSWORD: process.env["LEO_SERVER_PASSWORD"],
  LEO_SERVER_USERNAME: process.env["LEO_SERVER_USERNAME"],

  // Experimental
  LEO_EXPERIMENTAL_FILEWATCHER: Config.boolean("LEO_EXPERIMENTAL_FILEWATCHER").pipe(
    Config.withDefault(false),
  ),
  LEO_EXPERIMENTAL_DISABLE_FILEWATCHER: Config.boolean("LEO_EXPERIMENTAL_DISABLE_FILEWATCHER").pipe(
    Config.withDefault(false),
  ),
  LEO_EXPERIMENTAL_DISABLE_COPY_ON_SELECT:
    copy === undefined ? process.platform === "win32" : truthy("LEO_EXPERIMENTAL_DISABLE_COPY_ON_SELECT"),
  LEO_MODELS_URL: process.env["LEO_MODELS_URL"],
  LEO_MODELS_PATH: process.env["LEO_MODELS_PATH"],
  LEO_DB: process.env["LEO_DB"],

  LEO_WORKSPACE_ID: process.env["LEO_WORKSPACE_ID"],
  LEO_EXPERIMENTAL_WORKSPACES: LEO_EXPERIMENTAL || truthy("LEO_EXPERIMENTAL_WORKSPACES"),

  // Evaluated at access time (not module load) because tests, the CLI, and
  // external tooling set these env vars at runtime.
  get LEO_DISABLE_PROJECT_CONFIG() {
    return truthy("LEO_DISABLE_PROJECT_CONFIG")
  },
  get LEO_TUI_CONFIG() {
    return process.env["LEO_TUI_CONFIG"]
  },
  get LEO_CONFIG_DIR() {
    return process.env["LEO_CONFIG_DIR"]
  },
  get LEO_PURE() {
    return truthy("LEO_PURE")
  },
  get LEO_PLUGIN_META_FILE() {
    return process.env["LEO_PLUGIN_META_FILE"]
  },
  get LEO_CLIENT() {
    return process.env["LEO_CLIENT"] ?? "cli"
  },
}
