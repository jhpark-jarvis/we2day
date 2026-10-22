import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

export default defineConfig({
  ...auth,
  testMatch: "places.spec.ts",
  workers: 1,
  fullyParallel: false,
  projects: [
    {
      name: "places-mobile",
      use: {
        ...devices["iPhone 13"],
        defaultBrowserType: process.env.WE2DAY_TEST_BROWSER === "webkit" ? "webkit" : "chromium",
      },
    },
  ],
});
