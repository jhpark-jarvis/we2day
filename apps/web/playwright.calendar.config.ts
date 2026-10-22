import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

export default defineConfig({
  ...auth,
  testMatch: "calendar.spec.ts",
  fullyParallel: false,
  workers: 1,
  projects: [{ name: "shared-calendar", use: { ...devices["Desktop Chrome"] } }],
});
