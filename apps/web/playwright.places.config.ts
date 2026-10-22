import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

const servers = Array.isArray(auth.webServer) ? auth.webServer : [];
export default defineConfig({
  ...auth,
  testMatch: "places.spec.ts",
  workers: 1,
  fullyParallel: false,
  projects: [
    { name: "places-mobile", use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" } },
  ],
  webServer: servers.map((server) => ({
    ...server,
    env: {
      ...server.env,
      WE2DAY_NAVER_SEARCH_ENABLED: "false",
      WE2DAY_NAVER_SEARCH_CLIENT_ID: "",
      WE2DAY_NAVER_SEARCH_CLIENT_SECRET: "",
    },
  })),
});
