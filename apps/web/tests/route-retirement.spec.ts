import { expect, test } from "@playwright/test";
import { confirmPlanAndReopen } from "./plan-confirmation";

test("course entry replaces duplicate route views and preserves all stops and visits", async ({
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
  await expect(page.getByRole("heading", { name: "하루 동선", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "동선 보기", exact: true })).toHaveCount(0);
  await expect(
    page.locator(".agenda-header-actions").getByRole("link", { name: /데이트 코스/ }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("calendar-without-routes.png"),
    fullPage: true,
  });
  await page.goto("/memories/search");
  await expect(page.getByLabel("검색 대상").locator("option")).toHaveText([
    "사진",
    "기록",
    "월간 추억",
  ]);
  await page.goto("/memories/search?type=routes");
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/memories/routes");
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/memories/routes?date=2026-02-30");
  await expect(page).toHaveURL(/\/today$/);
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
  await expect(page).toHaveURL(/\/today\?date=2026-10-24$/);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "세 장소 코스", exact: true }).click();
  const stops = page.locator(".activity-card");
  await expect(stops).toHaveCount(3);
  for (const [index, place] of ["산책 공원", "점심 식당", "저녁 카페"].entries()) {
    await expect(stops.nth(index)).toContainText(place);
    await stops
      .nth(index)
      .getByRole("button", { name: new RegExp(`장소 ${index + 1}`) })
      .click();
    const map = page.getByRole("link", { name: "네이버 지도", exact: true });
    if (index === 0) {
      await expect(map).toHaveAttribute("href", "https://naver.me/Example12");
    } else {
      const url = new URL((await map.getAttribute("href")) || "");
      expect(url.protocol).toBe("nmap:");
      expect(url.hostname).toBe("search");
      expect(url.searchParams.get("query")).toBe(place);
    }
  }
  const visit = page.getByRole("group", { name: "장소 2 방문 상태", exact: true });
  await visit.getByRole("button", { name: "방문 완료", exact: true }).click();
  await expect(visit.getByRole("button", { name: "방문 완료", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "추가 산책 코스", exact: true }).click();
  await expect(stops).toHaveCount(1);
  await expect(stops).toContainText("밤 산책길");
  await page.goto("/memories/search?type=routes&date=2026-10-24");
  await expect(page).toHaveURL(/\/today\?date=2026-10-24$/);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "세 장소 코스", exact: true }).click();
  await expect(visit.getByRole("button", { name: "방문 완료", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  for (const width of [1280, 393, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`unified-course-${width}.png`),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 393, height: 1000 });
  await page.screenshot({
    path: testInfo.outputPath("unified-course-public.png"),
    fullPage: true,
    animations: "disabled",
    // Documentation capture: put the sticky navigation at the document end and hide dev chrome.
    style:
      "nextjs-portal { display: none !important; } .app-navigation { position: static !important; }",
  });
  await page.getByLabel("살펴볼 날짜").fill("2026-10-25");
  await page.getByRole("button", { name: "이 날짜 보기", exact: true }).click();
  await expect(page.getByText("이 날짜에 확정한 플랜이 없어요.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "세 장소 코스" })).toHaveCount(0);
  expect((await page.request.get("/api/plans?date=2026-02-30")).status()).toBe(422);
  expect(routeRequests).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("search-without-routes.png"), fullPage: true });
  await page.goto("/settings/export");
  await expect(
    page.getByLabel("내보낼 기록 종류").locator('option[value="meeting_routes"]'),
  ).toHaveText("출발·도착 기록 (기존 자료)");
});
