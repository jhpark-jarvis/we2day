import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

const servers = Array.isArray(auth.webServer) ? auth.webServer : [];
export default defineConfig({
  ...auth,
  testMatch: "plans.spec.ts",
  workers: 1,
  fullyParallel: false,
  projects: [
    { name: "plans-mobile", use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" } },
  ],
  webServer: servers.map((server) => ({
    ...server,
    env: {
      ...server.env,
      WE2DAY_NAVER_MAPS_CLIENT_ID: "synthetic-maps-key",
      WE2DAY_NAVER_SEARCH_ENABLED: "false",
      WE2DAY_NAVER_SEARCH_CLIENT_ID: "",
      WE2DAY_NAVER_SEARCH_CLIENT_SECRET: "",
    },
  })),
});
