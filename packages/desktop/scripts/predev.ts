import { $ } from "bun"

await $`bun ./scripts/copy-icons.ts ${process.env.LEO_CHANNEL ?? "dev"}`

await $`cd ../opencode && bun script/build-node.ts`
