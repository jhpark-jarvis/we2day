import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

const servers = Array.isArray(auth.webServer) ? auth.webServer : [];
export default defineConfig({
  ...auth,
  testMatch: "ai-intake.spec.ts",
  workers: 1,
  fullyParallel: false,
  projects: [
    { name: "ai-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "ai-safari", use: { ...devices["iPhone 13"], defaultBrowserType: "webkit" } },
  ],
  webServer: servers.map((server) => ({
    ...server,
    env: {
      ...server.env,
      WE2DAY_CLOUDFLARE_ACCOUNT_ID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      WE2DAY_CLOUDFLARE_API_TOKEN: "synthetic-never-sent",
    },
  })),
});
