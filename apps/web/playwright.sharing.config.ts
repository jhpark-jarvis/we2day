import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

export default defineConfig({
  ...auth,
  testMatch: "photo-sharing.spec.ts",
  fullyParallel: false,
  workers: 1,
  expect: { timeout: 15_000 },
  use: { ...auth.use, actionTimeout: 15_000, navigationTimeout: 20_000 },
  projects: [
    {
      name: "photo-sharing",
      use: {
        ...devices["Desktop Chrome"],
        defaultBrowserType: process.env.WE2DAY_TEST_BROWSER === "webkit" ? "webkit" : "chromium",
      },
    },
  ],
});
