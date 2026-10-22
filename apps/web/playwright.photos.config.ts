import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "photos.spec.ts",
  fullyParallel: true,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:3101", trace: "off" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" } },
  ],
  webServer: {
    command: "npm run dev -- --port 3101",
    url: "http://127.0.0.1:3101/memories",
    reuseExistingServer: false,
    env: {
      NEXT_TELEMETRY_DISABLED: "1",
      WE2DAY_SITE_URL: "http://127.0.0.1:3101",
      WE2DAY_SUPABASE_URL: "",
      WE2DAY_SUPABASE_PUBLISHABLE_KEY: "",
    },
  },
});
