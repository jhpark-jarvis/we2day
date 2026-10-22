import { defineConfig, devices } from "@playwright/test";

const providers = process.env.WE2DAY_TEST_AUTH_PROVIDERS ?? "password,google,kakao";

export default defineConfig({
  testDir: "./tests",
  testMatch: "auth.spec.ts",
  fullyParallel: true,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:3100", trace: "off" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" } },
  ],
  webServer: [
    {
      command: "node tests/fixtures/auth-server.mjs",
      url: "http://127.0.0.1:54329/health",
      reuseExistingServer: false,
    },
    {
      command: "uv run --directory ../api uvicorn we2day_api.main:app --host 127.0.0.1 --port 8100",
      url: "http://127.0.0.1:8100/health/live",
      reuseExistingServer: false,
      env: {
        WE2DAY_SUPABASE_URL: "http://127.0.0.1:54329",
        WE2DAY_SUPABASE_PUBLISHABLE_KEY: "synthetic-publishable-key",
      },
    },
    {
      command:
        process.env.WE2DAY_TEST_WEB_ENGINE === "standalone"
          ? "node .next/standalone/apps/web/server.js"
          : process.env.WE2DAY_TEST_WEB_ENGINE === "webpack"
            ? "npm run dev -- --webpack --port 3100"
            : "npm run dev -- --port 3100",
      timeout: 180_000,
      url: "http://127.0.0.1:3100/login",
      reuseExistingServer: false,
      env: {
        PORT: "3100",
        HOSTNAME: "127.0.0.1",
        NEXT_TELEMETRY_DISABLED: "1",
        WE2DAY_SITE_URL: "http://127.0.0.1:3100",
        WE2DAY_SUPABASE_URL: "http://127.0.0.1:54329",
        WE2DAY_SUPABASE_PUBLISHABLE_KEY: "synthetic-publishable-key",
        WE2DAY_AUTH_PROVIDERS: providers,
        WE2DAY_API_URL: "http://127.0.0.1:8100",
      },
    },
  ],
});
