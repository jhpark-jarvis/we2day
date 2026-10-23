import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test("last-year links change album dates on the same route and survive reload", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("outsider");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  const dates: string[] = [];
  await page.route("**/api/photos?**", async (route) => {
    expect(route.request().method()).toBe("GET");
    const query = new URL(route.request().url()).searchParams;
    if (query.has("month")) {
      await route.fulfill({ json: { month: query.get("month"), days: [] } });
      return;
    }
    dates.push(query.get("date") || "");
    await route.fulfill({ json: { items: [], next_after: null } });
  });
  await page.goto("/memories");
  const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const lastYear = `${Number(today.slice(0, 4)) - 1}${today.slice(4)}`;
  await expect(
    page.getByText(`${today.slice(0, 4)}년 ${today.slice(5, 7)}월 ${today.slice(8, 10)}일`, {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "작년 오늘의 사진 보기", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`date=${lastYear}$`));
  await expect(
    page.getByText(
      `${lastYear.slice(0, 4)}년 ${lastYear.slice(5, 7)}월 ${lastYear.slice(8, 10)}일`,
      { exact: true },
    ),
  ).toBeVisible();
  await expect.poll(() => dates.at(-1)).toBe(lastYear);
  await page.reload();
  await expect(
    page.getByText(
      `${lastYear.slice(0, 4)}년 ${lastYear.slice(5, 7)}월 ${lastYear.slice(8, 10)}일`,
      { exact: true },
    ),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("last-year-memory-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("navigation", { name: "주요 메뉴" })
    .getByRole("link", { name: "기록", exact: true })
    .click();
  await expect(
    page.getByText(`${today.slice(0, 4)}년 ${today.slice(5, 7)}월 ${today.slice(8, 10)}일`, {
      exact: true,
    }),
  ).toBeVisible();
  await expect.poll(() => dates.at(-1)).toBe(today);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
