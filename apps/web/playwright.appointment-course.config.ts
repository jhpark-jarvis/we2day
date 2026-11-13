import { defineConfig, devices } from "@playwright/test";
import auth from "./playwright.auth.config";

const servers = Array.isArray(auth.webServer) ? auth.webServer : [];

export default defineConfig({
  ...auth,
  testMatch: [
    "appointment-course.spec.ts",
    "visits.spec.ts",
    "personal-schedules.spec.ts",
    "device-push.spec.ts",
  ],
  workers: 1,
  outputDir: process.env.WE2DAY_COURSE_OUTPUT_DIR || "test-results",
  fullyParallel: false,
  webServer: servers.map((server, index) =>
    index === 2 && process.env.WE2DAY_COURSE_WEB_COMMAND
      ? { ...server, command: process.env.WE2DAY_COURSE_WEB_COMMAND }
      : server,
  ),
  projects: [
    { name: "course-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "course-safari", use: { ...devices["iPhone 13"], defaultBrowserType: "webkit" } },
  ],
});
