const stage = process.env.SST_STAGE || "dev"

export default {
  url: stage === "production" ? "https://leosoftware.dev" : `https://${stage}.leosoftware.dev`,
  console: stage === "production" ? "https://leosoftware.dev/auth" : `https://${stage}.leosoftware.dev/auth`,
  email: "contact@anoma.ly",
  socialCard: "https://social-cards.sst.dev",
  github: "https://github.com/anomalyco/opencode",
  discord: "https://leosoftware.dev/discord",
  headerLinks: [
    { name: "app.header.home", url: "/" },
    { name: "app.header.docs", url: "/docs/" },
  ],
}
