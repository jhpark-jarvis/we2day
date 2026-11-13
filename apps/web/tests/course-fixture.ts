import { type APIRequestContext, expect } from "@playwright/test";

// This RPC is created only inside the disposable local course fixture, never migrations.
export async function resetCourseFixture(request: APIRequestContext) {
  if (process.env.WE2DAY_TEST_COURSE_RESET !== "1") return;
  const url = process.env.WE2DAY_TEST_REST_URL;
  if (url !== "http://127.0.0.1:54330") throw new Error("Disposable course fixture required");
  const response = await request.post(`${url}/rpc/fixture_reset_course_tests`, { data: {} });
  expect(response.ok()).toBe(true);
}
