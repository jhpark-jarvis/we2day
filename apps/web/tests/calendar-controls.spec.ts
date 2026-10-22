import { expect, test } from "@playwright/test";

test("calendar controls center day labels independently of dots and keep refresh in its section", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/");
  await expect(
    page.locator(".app-header").getByText("둘의 시간을 한곳에", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: "WE2DAY 홈", exact: true })).toBeVisible();
  const calendar = page.getByRole("region", { name: "월 달력", exact: true });
  async function centered(selector: string) {
    const circle = calendar.locator(selector).locator(".day-number");
    const label = circle.locator(".day-label");
    const a = await circle.boundingBox(),
      b = await label.boundingBox();
    if (!a || !b) throw new Error("calendar number is not visible");
    expect(Math.abs(a.width - a.height)).toBeLessThan(0.75);
    expect(Math.abs(a.x + a.width / 2 - b.x - b.width / 2)).toBeLessThan(0.75);
    expect(Math.abs(a.y + a.height / 2 - b.y - b.height / 2)).toBeLessThan(0.75);
  }
  await centered('.calendar-day[aria-current="date"]');
  await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
  await page.getByLabel("약속 이름").fill("달력 표시 확인용 예시");
  await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
  await expect(page.getByRole("button", { name: /달력 표시 확인용 예시/ })).toBeVisible();
  await expect(
    calendar.locator('.calendar-day[aria-current="date"] .day-dot.has-event'),
  ).toHaveCount(1);
  await centered('.calendar-day[aria-current="date"]');
  await calendar.locator(".calendar-day").first().click();
  await centered('.calendar-day[aria-pressed="true"]');
  const refresh = calendar.getByRole("button", { name: "일정 새로고침", exact: true });
  await expect(refresh).toHaveText("");
  await expect(
    page.locator(".calendar-toolbar").getByRole("button", { name: "일정 새로고침", exact: true }),
  ).toHaveCount(0);
  const icon = await refresh.boundingBox(),
    heading = await calendar.getByRole("heading").boundingBox();
  if (!icon || !heading) throw new Error("calendar header is not visible");
  expect(icon.x).toBeGreaterThan(heading.x + heading.width);
  expect(icon.height).toBeGreaterThanOrEqual(44);
  let reads = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/appointments") reads++;
  });
  await refresh.click();
  await expect.poll(() => reads).toBeGreaterThan(0);
  await expect(refresh).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await calendar.getByRole("button", { name: "오늘", exact: true }).click();
  await page.screenshot({
    path: testInfo.outputPath("calendar-controls-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await centered('.calendar-day[aria-current="date"]');
  await page.goto("/preview");
  const selectedDay = calendar.locator('.calendar-day[aria-pressed="true"]');
  await expect(calendar.locator('.calendar-day[tabindex="0"]')).toHaveCount(1);
  await selectedDay.focus();
  await selectedDay.press("ArrowRight");
  await expect(selectedDay).toHaveAttribute("data-date", "2026-10-25");
  await expect(selectedDay).toBeFocused();
  await selectedDay.press("End");
  await expect(selectedDay).toHaveAttribute("data-date", "2026-10-31");
  await selectedDay.press("PageDown");
  await expect(selectedDay).toHaveAttribute("data-date", "2026-11-30");
  await expect(selectedDay).toBeFocused();
  await selectedDay.press("ArrowRight");
  await expect(selectedDay).toHaveAttribute("data-date", "2026-12-01");
  await selectedDay.press("Home");
  await expect(selectedDay).toHaveAttribute("data-date", "2026-11-29");
  await selectedDay.press("ArrowDown");
  await expect(selectedDay).toHaveAttribute("data-date", "2026-12-06");
  await selectedDay.press("Tab");
  await expect(selectedDay).not.toBeFocused();
  await page.goto("/?date=2024-02-29");
  await selectedDay.focus();
  await selectedDay.press("Shift+PageDown");
  await expect(selectedDay).toHaveAttribute("data-date", "2025-02-28");
  await expect(selectedDay).toBeFocused();
  await page.goto("/?date=2000-01-01");
  await selectedDay.focus();
  await selectedDay.press("ArrowLeft");
  await expect(selectedDay).toHaveAttribute("data-date", "2000-01-01");
  await page.goto("/?date=2100-12-31");
  await selectedDay.focus();
  await selectedDay.press("ArrowRight");
  await expect(selectedDay).toHaveAttribute("data-date", "2100-12-31");
});
