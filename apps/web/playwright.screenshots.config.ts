import { defineConfig, devices } from "@playwright/test";
import journey from "./playwright.journey.config";

export default defineConfig({
  ...journey,
  testMatch: "screenshots.spec.ts",
  projects: [{ name: "documentation", use: { ...devices["Desktop Chrome"] } }],
  use: { ...journey.use, screenshot: "off", video: "off", trace: "off" },
});
