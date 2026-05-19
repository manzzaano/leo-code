import { Config, ConfigProvider, Context, Effect, Layer } from "effect"
import { ConfigService } from "@/effect/config-service"

const bool = (name: string) => Config.boolean(name).pipe(Config.withDefault(false))
const positiveInteger = (name: string) =>
  Config.number(name).pipe(
    Config.map((value) => (Number.isInteger(value) && value > 0 ? value : undefined)),
    Config.orElse(() => Config.succeed(undefined)),
  )
const experimental = bool("LEO_EXPERIMENTAL")
const enabledByExperimental = (name: string) =>
  Config.all({ experimental, enabled: bool(name) }).pipe(Config.map((flags) => flags.experimental || flags.enabled))

export class Service extends ConfigService.Service<Service>()("@leo-code/RuntimeFlags", {
  autoShare: bool("LEO_AUTO_SHARE"),
  pure: bool("LEO_PURE"),
  disableDefaultPlugins: bool("LEO_DISABLE_DEFAULT_PLUGINS"),
  disableChannelDb: bool("LEO_DISABLE_CHANNEL_DB"),
  disableEmbeddedWebUi: bool("LEO_DISABLE_EMBEDDED_WEB_UI"),
  disableExternalSkills: bool("LEO_DISABLE_EXTERNAL_SKILLS"),
  disableLspDownload: bool("LEO_DISABLE_LSP_DOWNLOAD"),
  skipMigrations: bool("LEO_SKIP_MIGRATIONS"),
  disableClaudeCodePrompt: Config.all({
    broad: bool("LEO_DISABLE_CLAUDE_CODE"),
    direct: bool("LEO_DISABLE_CLAUDE_CODE_PROMPT"),
  }).pipe(Config.map((flags) => flags.broad || flags.direct)),
  disableClaudeCodeSkills: Config.all({
    broad: bool("LEO_DISABLE_CLAUDE_CODE"),
    direct: bool("LEO_DISABLE_CLAUDE_CODE_SKILLS"),
  }).pipe(Config.map((flags) => flags.broad || flags.direct)),
  enableExa: Config.all({
    experimental,
    enabled: bool("LEO_ENABLE_EXA"),
    legacy: bool("LEO_EXPERIMENTAL_EXA"),
  }).pipe(Config.map((flags) => flags.experimental || flags.enabled || flags.legacy)),
  enableParallel: Config.all({
    enabled: bool("LEO_ENABLE_PARALLEL"),
    legacy: bool("LEO_EXPERIMENTAL_PARALLEL"),
  }).pipe(Config.map((flags) => flags.enabled || flags.legacy)),
  enableExperimentalModels: bool("LEO_ENABLE_EXPERIMENTAL_MODELS"),
  enableQuestionTool: bool("LEO_ENABLE_QUESTION_TOOL"),
  experimentalScout: enabledByExperimental("LEO_EXPERIMENTAL_SCOUT"),
  experimentalBackgroundSubagents: enabledByExperimental("LEO_EXPERIMENTAL_BACKGROUND_SUBAGENTS"),
  experimentalLspTy: bool("LEO_EXPERIMENTAL_LSP_TY"),
  experimentalLspTool: enabledByExperimental("LEO_EXPERIMENTAL_LSP_TOOL"),
  experimentalOxfmt: enabledByExperimental("LEO_EXPERIMENTAL_OXFMT"),
  experimentalPlanMode: enabledByExperimental("LEO_EXPERIMENTAL_PLAN_MODE"),
  experimentalEventSystem: enabledByExperimental("LEO_EXPERIMENTAL_EVENT_SYSTEM"),
  experimentalWorkspaces: enabledByExperimental("LEO_EXPERIMENTAL_WORKSPACES"),
  experimentalIconDiscovery: enabledByExperimental("LEO_EXPERIMENTAL_ICON_DISCOVERY"),
  outputTokenMax: positiveInteger("LEO_EXPERIMENTAL_OUTPUT_TOKEN_MAX"),
  bashDefaultTimeoutMs: positiveInteger("LEO_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS"),
  client: Config.string("LEO_CLIENT").pipe(Config.withDefault("cli")),
}) {}

export type Info = Context.Service.Shape<typeof Service>

const emptyConfigLayer = Service.defaultLayer.pipe(
  Layer.provide(ConfigProvider.layer(ConfigProvider.fromUnknown({}))),
  Layer.orDie,
)

export const layer = (overrides: Partial<Info> = {}) =>
  Layer.effect(
    Service,
    Effect.gen(function* () {
      const flags = yield* Service
      return Service.of({ ...flags, ...overrides })
    }),
  ).pipe(Layer.provide(emptyConfigLayer))

export const defaultLayer = Service.defaultLayer.pipe(Layer.orDie)

export * as RuntimeFlags from "./runtime-flags"
