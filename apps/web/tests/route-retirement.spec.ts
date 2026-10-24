import { expect, test } from "@playwright/test";
import { confirmPlanAndReopen } from "./plan-confirmation";

test("two-point input is absent while all confirmed day-course stops remain available", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
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
  await expect(page.getByLabel("검색 대상")).toHaveValue("routes");
  await expect(page.getByLabel("검색 대상").locator("option")).toHaveText([
    "사진",
    "기록",
    "동선",
    "월간 추억",
  ]);
  await page.goto("/memories/routes");
  await expect(page).toHaveURL(/\/memories\/search\?type=routes$/);
  await expect(page.getByLabel("검색 대상")).toHaveValue("routes");
  await page.goto("/plans?date=2026-10-24&new=1");
  await page.getByLabel("플랜 이름", { exact: true }).fill("세 장소 코스");
  await page.getByLabel("플랜 날짜").fill("2026-10-24");
  for (const [index, place] of ["산책 공원", "점심 식당", "저녁 카페"].entries()) {
    if (index > 0) await page.getByRole("button", { name: "활동 추가", exact: true }).click();
    await page.getByLabel(`활동 ${index + 1} 이름`).fill(`장소 ${index + 1}`);
    await page.getByLabel(`활동 ${index + 1} 장소`, { exact: true }).fill(place);
  }
  await page.locator("#activity-0-map-url").fill("https://naver.me/Example12");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "세 장소 코스", exact: true })).toBeVisible();
  await confirmPlanAndReopen(page);
  await page.goto("/plans?date=2026-10-24&new=1");
  await page.getByLabel("플랜 이름", { exact: true }).fill("추가 산책 코스");
  await page.getByLabel("플랜 날짜").fill("2026-10-24");
  await page.getByLabel("활동 1 이름").fill("밤 산책");
  await page.getByLabel("활동 1 장소", { exact: true }).fill("밤 산책길");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "추가 산책 코스", exact: true })).toBeVisible();
  await confirmPlanAndReopen(page);
  await page.goto("/memories/routes?date=2026-10-24");
  await expect(page).toHaveURL(/type=routes&date=2026-10-24/);
  const day = page.getByRole("region", { name: "날짜별 하루 동선", exact: true });
  await expect(day.getByRole("heading", { name: "세 장소 코스" })).toBeVisible();
  await expect(day.getByRole("heading", { name: "추가 산책 코스" })).toBeVisible();
  await expect(day.getByText("밤 산책길", { exact: true })).toBeVisible();
  const stops = day.getByRole("list", { name: "세 장소 코스 장소 순서" });
  await expect(stops.getByRole("listitem")).toHaveCount(3);
  await expect(stops.getByRole("listitem").nth(0)).toContainText("산책 공원");
  await expect(stops.getByRole("listitem").nth(1)).toContainText("점심 식당");
  await expect(stops.getByRole("listitem").nth(2)).toContainText("저녁 카페");
  await expect(stops.getByRole("link").nth(0)).toHaveAttribute(
    "href",
    "https://naver.me/Example12",
  );
  await expect(stops.getByRole("link")).toHaveCount(3);
  await page.screenshot({ path: testInfo.outputPath("all-day-course-stops.png"), fullPage: true });
  await page.getByLabel("동선 날짜").fill("2026-10-25");
  await page.getByRole("button", { name: "동선 조회", exact: true }).click();
  await expect(day.getByText("이 날짜에 확정한 코스가 없어요.")).toBeVisible();
  await expect(day.getByRole("heading", { name: "세 장소 코스" })).toHaveCount(0);
  expect((await page.request.get("/api/plans?date=2026-02-30")).status()).toBe(422);
  expect(routeRequests).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("search-without-routes.png"), fullPage: true });
  await page.goto("/settings/export");
  await expect(
    page.getByLabel("내보낼 기록 종류").locator('option[value="meeting_routes"]'),
  ).toHaveText("출발·도착 기록 (기존 자료)");
});
