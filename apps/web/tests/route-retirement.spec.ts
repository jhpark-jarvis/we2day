import { expect, test } from "@playwright/test";

test("calendar and record search omit retired two-point routes", async ({ page }, testInfo) => {
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  let routeRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/routes")) routeRequests++;
  });
  await page.goto("/");
  await expect(page.getByLabel("이 날 만났어요", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "함께한 동선" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "동선 기록 열기" })).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("calendar-without-routes.png"),
    fullPage: true,
  });
  await page.goto("/memories/search?type=routes");
  await expect(page.getByLabel("검색 대상")).toHaveValue("photos");
  await expect(page.getByLabel("검색 대상").locator("option")).toHaveText([
    "사진",
    "기록",
    "월간 추억",
  ]);
  await page.goto("/memories/routes");
  await expect(page).toHaveURL(/\/memories\/search\?type=records$/);
  await expect(page.getByLabel("검색 대상")).toHaveValue("records");
  expect(routeRequests).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("search-without-routes.png"), fullPage: true });
  await page.goto("/settings/export");
  await expect(
    page.getByLabel("내보낼 기록 종류").locator('option[value="meeting_routes"]'),
  ).toHaveText("출발·도착 기록 (기존 자료)");
});
