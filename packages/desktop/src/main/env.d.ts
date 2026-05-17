interface ImportMetaEnv {
  readonly LEO_CHANNEL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module "virtual:opencode-server" {
  export namespace Server {
    export const listen: typeof import("../../../leo-code/dist/types/src/node").Server.listen
    export type Listener = import("../../../leo-code/dist/types/src/node").Server.Listener
  }
  export namespace Config {
    export const get: typeof import("../../../leo-code/dist/types/src/node").Config.get
    export type Info = import("../../../leo-code/dist/types/src/node").Config.Info
  }
  export namespace Log {
    export const init: typeof import("../../../leo-code/dist/types/src/node").Log.init
  }
  export namespace Database {
    export const getPath: typeof import("../../../leo-code/dist/types/src/node").Database.getPath
    export const Client: typeof import("../../../leo-code/dist/types/src/node").Database.Client
  }
  export namespace JsonMigration {
    export type Progress = import("../../../leo-code/dist/types/src/node").JsonMigration.Progress
    export const run: typeof import("../../../leo-code/dist/types/src/node").JsonMigration.run
  }
  export const bootstrap: typeof import("../../../leo-code/dist/types/src/node").bootstrap
}
