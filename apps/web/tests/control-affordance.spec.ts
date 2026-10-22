import fs from "node:fs/promises";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

async function auditControls(page: Page, label: string) {
  await expect(page.locator(".page-loading")).toHaveCount(0, { timeout: 30_000 });
  const issues = await page.locator("main").evaluate((main) => {
    const problems: string[] = [];
    for (const control of main.querySelectorAll<HTMLElement>("button, a, summary")) {
      const bounds = control.getBoundingClientRect();
      if (!bounds.width || !bounds.height || getComputedStyle(control).visibility === "hidden")
        continue;
      const style = getComputedStyle(control);
      const name = (control.getAttribute("aria-label") || control.textContent || "")
        .trim()
        .slice(0, 70);
      const grouped = control.closest(".list-view-toggle, .archive-links, .schedule-tools nav");
      const dateCell = control.matches(".calendar-day");
      const underlined = style.textDecorationLine.includes("underline");
      const outline = parseFloat(style.borderTopWidth) > 0 && style.borderTopStyle !== "none";
      if (!dateCell && !grouped && !underlined && !outline)
        problems.push(`plain text control: ${name}`);
      if (control.tagName !== "A" && !dateCell && bounds.height < 43.5)
        problems.push(`short target: ${name}`);
      if (control.matches(".icon-button") && bounds.width < 43.5)
        problems.push(`narrow icon: ${name}`);
      if (bounds.right > document.documentElement.clientWidth + 1 || bounds.left < -1)
        problems.push(`overflow: ${name}`);
    }
    if (document.documentElement.scrollWidth > window.innerWidth)
      problems.push("horizontal page overflow");
    return problems;
  });
  expect.soft(issues, label).toEqual([]);
}

test("all page controls remain identifiable in both themes and narrow layouts", async ({
  page,
  context,
  browser,
}, testInfo) => {
  test.setTimeout(480_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();

  await page.goto("/questions");
  await page.getByLabel("함께 나눌 질문").fill("화면 확인용 질문");
  await page.getByRole("button", { name: "질문 추가", exact: true }).click();
  await expect(page).toHaveURL(/\/questions\/[a-f0-9-]+$/, { timeout: 30_000 });
  const question = new URL(page.url()).pathname;
  await page.goto("/roulette");
  await page.getByLabel("룰렛 이름").fill("화면 확인용 선택");
  await page.getByLabel("후보 (한 줄에 하나, 2~20개)").fill("산책\n카페");
  await page.getByRole("button", { name: "룰렛 저장", exact: true }).click();
  await expect(page).toHaveURL(/\/roulette\/[a-f0-9-]+$/, { timeout: 30_000 });
  const roulette = new URL(page.url()).pathname;
  await page.goto("/plans");
  await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
  await page.getByLabel("플랜 이름").fill("화면 확인용 산책");
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 1 이름").fill("공원 산책");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "확정 내용 확인", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }),
  ).toBeVisible();
  const plans = await (await context.request.get("/api/plans")).json();
  const plan = plans.find(
    (item: { content: { title: string } }) => item.content.title === "화면 확인용 산책",
  );
  expect(plan).toBeTruthy();
  const dynamic = [question, roulette, `/plans/${plan.id}/report`];

  // Discover every static page so new pages join the audit automatically.
  const root = path.resolve("src/app");
  const files = await fs.readdir(root, { recursive: true });
  const routes = files
    .filter((file) => file.endsWith("page.tsx") && !file.includes("["))
    .map((file) => `/${file.replaceAll("\\", "/").replace(/\/?page\.tsx$/, "")}`);
  routes.push(...dynamic, "/page-not-found-fixture");
  const desktop = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 1280, height: 900 },
    storageState: await context.storageState(),
  });
  try {
    const desktopPage = await desktop.newPage();
    for (const [theme, width, current, currentContext] of [
      ["warm", 320, page, context],
      ["white", 390, page, context],
      ["warm", 1280, desktopPage, desktop],
      ["white", 1280, desktopPage, desktop],
    ] as const) {
      await current.setViewportSize({ width, height: 900 });
      await currentContext.addCookies([
        { name: "we2day-theme", value: theme, url: "http://127.0.0.1:3100" },
      ]);
      for (const route of routes) {
        await current.goto(route);
        await auditControls(current, `${theme}/${width}/${route}`);
      }
      for (const [route, button] of [
        ["/plans", "플랜 만들기"],
        ["/checklists", "목록 만들기"],
        ["/goals", "목표 만들기"],
      ]) {
        await current.goto(route);
        await current.getByRole("button", { name: button, exact: true }).click();
        await auditControls(current, `${theme}/${width}/${route}/editor`);
      }
      await current.goto("/settings");
      const update = current.getByRole("button", { name: "업데이트 확인", exact: true });
      await update.focus();
      await current.keyboard.press("Tab");
      await current.keyboard.press("Shift+Tab");
      await expect(update).toBeFocused();
      expect(
        await update.evaluate((element) => parseFloat(getComputedStyle(element).outlineWidth)),
      ).toBeGreaterThanOrEqual(2);
      await current.screenshot({
        path: testInfo.outputPath(`settings-${theme}-${width}.png`),
        fullPage: true,
      });
      await current.goto("/");
      const tools = current.locator(".schedule-tools summary");
      await expect(tools).toBeVisible({ timeout: 30_000 });
      await tools.focus();
      await expect(tools).toBeFocused();
      await tools.press("Enter");
      await expect(current.locator(".schedule-tools")).toHaveAttribute("open", "");
      for (const link of await current.locator(".schedule-tools nav a").all()) {
        await link.scrollIntoViewIfNeeded();
        expect(
          await link.evaluate((element) => {
            const bounds = element.getBoundingClientRect();
            const target = document.elementFromPoint(
              bounds.x + bounds.width / 2,
              bounds.y + bounds.height / 2,
            );
            return !!target && element.contains(target);
          }),
          "menu action remains reachable above fixed navigation",
        ).toBe(true);
      }
      await auditControls(current, `${theme}/${width}/schedule-tools`);
      await current.screenshot({
        path: testInfo.outputPath(`calendar-${theme}-${width}.png`),
        fullPage: true,
      });
    }
  } finally {
    await desktop.close();
  }
});
