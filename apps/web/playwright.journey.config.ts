import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

const servers = Array.isArray(auth.webServer) ? auth.webServer : [];
export default defineConfig({
  ...auth,
  testMatch: "journey.spec.ts",
  workers: 1,
  fullyParallel: false,
  projects: [
    {
      name: "journey-mobile",
      use: {
        ...devices["iPhone 13"],
        defaultBrowserType: process.env.WE2DAY_TEST_BROWSER === "webkit" ? "webkit" : "chromium",
      },
    },
  ],
  webServer: servers.map((server) => ({
    ...server,
    timeout: 120_000,
    env: {
      ...server.env,
      WE2DAY_NAVER_SEARCH_ENABLED: "false",
      WE2DAY_NAVER_SEARCH_CLIENT_ID: "",
      WE2DAY_NAVER_SEARCH_CLIENT_SECRET: "",
      WE2DAY_NAVER_MAPS_CLIENT_ID: "",
    },
  })),
});
