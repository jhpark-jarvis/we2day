import { expect, test } from "@playwright/test";

test("theme survives navigation, reload, and server rendering", async ({ page, context }) => {
  await page.goto("/settings");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "warm");
  await page.getByRole("button", { name: /화이트/ }).click();
  await expect(page.getByRole("status")).toContainText("1년");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "white");
  const cookie = (await context.cookies()).find((item) => item.name === "we2day-theme");
  expect(cookie).toMatchObject({ value: "white", path: "/", httpOnly: true, sameSite: "Lax" });
  expect(cookie?.expires).toBeGreaterThan(Date.now() / 1000 + 3600 * 24 * 360);
  await page.getByRole("link", { name: "일정", exact: true }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "white");
  const response = await context.request.get("/");
  expect(await response.text()).toContain('data-theme="white"');
  const newTab = await context.newPage();
  await newTab.goto("/");
  await expect(newTab.locator("html")).toHaveAttribute("data-theme", "white");
  await newTab.close();
  await page.goto("/settings");
  await page.getByRole("button", { name: /웜 클린/ }).click();
  await expect(page.getByRole("status")).toContainText("1년");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "warm");
});

test("failed theme save restores the previous appearance", async ({ page, context }) => {
  await page.goto("/settings");
  await page.route("**/settings", (route) =>
    route.request().method() === "POST" ? route.abort("failed") : route.continue(),
  );
  await page.getByRole("button", { name: /화이트/ }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("저장하지 못했어요");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "warm");
  expect((await context.cookies()).find((item) => item.name === "we2day-theme")).toBeUndefined();
});

test("invalid theme cookie falls back without affecting content", async ({ page, context }) => {
  await context.addCookies([
    { name: "we2day-theme", value: "unexpected", url: "http://127.0.0.1:3000" },
  ]);
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "warm");
  await expect(page.getByRole("link", { name: "WE2DAY 홈" })).toHaveText("WE2DAY");
  await expect(page.getByRole("heading", { name: "아직 약속이 없어요" })).toBeVisible();
});

test("calendar preview keeps photos tied to a date and fits narrow screens", async ({ page }) => {
  await page.goto("/preview");
  await expect(page.getByRole("heading", { name: "10월 24일 토요일" })).toBeVisible();
  await page.getByRole("button", { name: /10월 10일,/ }).click();
  await page.getByRole("button", { name: /15:00 가을 산책/ }).click();
  await page.getByText("사진 정보", { exact: true }).click();
  await expect(page.getByText("iPhone 15 · 15:42 (예시)")).toBeVisible();
  await page.goto("/preview");
  await page.getByRole("button", { name: "다음 달" }).click();
  await expect(page.getByRole("heading", { name: "2026년 11월" })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 850 });
  for (const route of ["/", "/settings", "/preview", "/memories"]) {
    await page.goto(route);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
});
