declare global {
  const LEO_VERSION: string
  const LEO_CHANNEL: string
}

export const InstallationVersion = typeof LEO_VERSION === "string" ? LEO_VERSION : "local"
export const InstallationChannel = typeof LEO_CHANNEL === "string" ? LEO_CHANNEL : "local"
export const InstallationLocal = InstallationChannel === "local"
