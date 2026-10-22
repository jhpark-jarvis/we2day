import fs from "node:fs/promises";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

test.use({ actionTimeout: 15_000, serviceWorkers: "block" });

async function open(page: Page, url: string) {
  await page.goto(url);
  // Wait for client form hydration before entering controlled input values.
  await page.waitForLoadState("networkidle");
}

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
    for (const field of main.querySelectorAll<HTMLElement>(
      'input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]),select,textarea',
    )) {
      const box = field.getBoundingClientRect();
      if (!box.width || !box.height) continue;
      const style = getComputedStyle(field);
      if (box.height < 43.5) problems.push(`short field: ${field.id || field.tagName}`);
      if (!parseFloat(style.borderTopWidth))
        problems.push(`unmarked field: ${field.id || field.tagName}`);
      if (document.documentElement.clientWidth <= 640 && parseFloat(style.fontSize) < 16)
        problems.push(
          `iOS focus zoom: ${field.getAttribute("id") || field.getAttribute("name") || field.tagName}`,
        );
      if (box.right > document.documentElement.clientWidth + 1 || box.left < -1)
        problems.push(`field overflow: ${field.getAttribute("id") || field.tagName}`);
    }
    if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
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
  test.setTimeout(900_000);
  await open(page, "/login");
  await page.getByLabel("아이디", { exact: true }).fill("audit");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await open(page, "/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();

  // Audit populated lists and unbroken user text alongside empty states.
  await open(page, "/anniversaries");
  await page.getByRole("button", { name: "기념일 추가하기", exact: true }).click();
  await page.getByLabel("기념일 이름").fill("함께기억하는아주긴기념일이름".repeat(3));
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(page.getByRole("button", { name: "기념일 추가하기", exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle");
  for (const [route, create, label, save] of [
    ["/checklists", "목록 만들기", "목록 이름", "목록 저장"],
    ["/goals", "목표 만들기", "목표 이름", "목표 저장"],
  ]) {
    await open(page, route);
    await page.getByRole("button", { name: create, exact: true }).click();
    await page.getByLabel(label, { exact: true }).fill("LongUnbrokenTitle".repeat(5));
    await page.getByRole("button", { name: save, exact: true }).click();
    await expect(page.getByRole("button", { name: create, exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
  }
  await open(page, "/");
  await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
  await page
    .getByLabel("약속 이름", { exact: true })
    .fill("LongUnbrokenAppointmentTitle".repeat(3));
  await page.getByLabel("시간 (선택)").fill("14:30");
  await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
  await expect(page.getByRole("button", { name: "약속 추가하기", exact: true })).toBeVisible();
  await page.getByLabel("이 날 만났어요", { exact: true }).check();
  await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
  await open(page, "/memories");
  await page.getByLabel("사진 선택").setInputFiles(path.resolve("public/demo/autumn.jpg"));
  await expect(page.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
  await page.getByLabel("이 사진의 한마디").fill("긴사진설명과함께남기는하루의기록".repeat(4));
  await page.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
  await expect(
    page.getByText("둘의 사진으로 저장했어요. 아래 날짜별 앨범에서 확인할 수 있어요."),
  ).toBeVisible();
  await open(page, "/questions");
  await page.getByLabel("함께 나눌 질문").fill("화면 확인용 질문");
  await page.getByRole("button", { name: "질문 추가", exact: true }).click();
  await expect(page).toHaveURL(/\/questions\/[a-f0-9-]+$/, { timeout: 30_000 });
  const question = new URL(page.url()).pathname;
  await open(page, "/roulette");
  await page.getByLabel("룰렛 이름").fill("화면 확인용 선택");
  await page.getByLabel("후보 (한 줄에 하나, 2~20개)").fill("산책\n카페");
  await page.getByRole("button", { name: "룰렛 저장", exact: true }).click();
  await expect(page).toHaveURL(/\/roulette\/[a-f0-9-]+$/, { timeout: 30_000 });
  const roulette = new URL(page.url()).pathname;
  await open(page, "/plans");
  await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
  await page.getByLabel("플랜 이름").fill("LongUnbrokenPlanTitle".repeat(4));
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
    (item: { content: { title: string } }) =>
      item.content.title === "LongUnbrokenPlanTitle".repeat(4),
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
  await fs.writeFile(
    testInfo.outputPath("route-coverage.json"),
    JSON.stringify(
      {
        routes,
        engine: testInfo.project.use.defaultBrowserType || "chromium",
        widths: [320, 390, 768, 1280],
        themes: ["warm", "white"],
      },
      null,
      2,
    ),
  );
  const desktop = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 1280, height: 900 },
    storageState: await context.storageState(),
    serviceWorkers: "block",
  });
  try {
    const desktopPage = await desktop.newPage();
    for (const [theme, width, current, currentContext] of [
      ["warm", 320, page, context],
      ["white", 390, page, context],
      ["warm", 768, desktopPage, desktop],
      ["warm", 1280, desktopPage, desktop],
      ["white", 1280, desktopPage, desktop],
    ] as const) {
      await current.setViewportSize({ width, height: 900 });
      await currentContext.addCookies([
        { name: "we2day-theme", value: theme, url: "http://127.0.0.1:3100" },
      ]);
      for (const route of routes) {
        await open(current, route);
        await auditControls(current, `${theme}/${width}/${route}`);
        if (route !== "/page-not-found-fixture") {
          const expected = route.startsWith("/memories")
            ? "/memories"
            : /^\/(together|checklists|goals|questions|roulette)(?:\/|$)/.test(route)
              ? "/together"
              : ["/settings", "/account", "/couple", "/login", "/timezones"].includes(route)
                ? "/settings"
                : "/";
          await expect(current.locator('.app-navigation [aria-current="page"]')).toHaveAttribute(
            "href",
            expected,
          );
        }
        await current.screenshot({
          path: testInfo.outputPath(
            `${theme}-${width}-${route.replaceAll("/", "_") || "home"}.png`,
          ),
          fullPage: true,
          scale: "css",
        });
      }
      for (const [route, button] of [
        ["/plans", "플랜 만들기"],
        ["/checklists", "목록 만들기"],
        ["/goals", "목표 만들기"],
        ["/", "약속 추가하기"],
        ["/anniversaries", "기념일 추가하기"],
      ]) {
        await open(current, route);
        await current.getByRole("button", { name: button, exact: true }).click();
        if (route === "/plans") {
          await current.getByRole("button", { name: "활동 추가", exact: true }).click();
          await current
            .getByLabel("활동 1 이름")
            .fill("긴 활동 이름과 메모를 입력하는 모바일 편집 상태");
        }
        if (route === "/checklists")
          await current.getByRole("button", { name: "항목 추가", exact: true }).click();
        if (route === "/goals")
          await current.getByRole("button", { name: "단계 추가", exact: true }).click();
        await auditControls(current, `${theme}/${width}/${route}/editor`);
        await current.screenshot({
          path: testInfo.outputPath(
            `${theme}-${width}-${route.slice(1) || "appointment"}-editor.png`,
          ),
          fullPage: true,
          scale: "css",
        });
      }
      await open(current, "/");
      await current.getByRole("button", { name: "동선 기록 열기", exact: true }).click();
      await expect(current.getByLabel("직접 정한 출발 장소 이름")).toBeVisible();
      await current.getByLabel("출발 경도", { exact: true }).fill("127.0276368");
      await auditControls(current, `${theme}/${width}/route-editor`);
      await current.screenshot({
        path: testInfo.outputPath(`${theme}-${width}-route-editor.png`),
        fullPage: true,
        scale: "css",
      });
      await open(current, "/account");
      const profile = current.getByLabel("사용자 이름", { exact: true });
      await profile.fill("예시 이름");
      await profile.focus();
      await expect(profile).toBeFocused();
      await expect(current.getByRole("button", { name: "이름 저장", exact: true })).toBeEnabled();
      await open(current, "/settings");
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
        scale: "css",
      });
      await open(current, "/");
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
        scale: "css",
      });
    }
    await open(page, "/login");
    await page.getByLabel("아이디", { exact: true }).fill("missing");
    await page.getByLabel("비밀번호", { exact: true }).fill("wrong-password");
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
    await auditControls(page, "login/error");
    await open(page, "/plans");
    await page.route("**/api/plans?*", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "연결을 확인한 뒤 다시 시도해 주세요." }),
      }),
    );
    await page.getByRole("button", { name: "플랜 새로고침", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
    await auditControls(page, "plans/retry-error");
    await page.unroute("**/api/plans?*");
  } finally {
    await desktop.close();
  }
});

test("mobile navigation keeps pending feedback separate from menu labels", async ({ page }) => {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/together*", async (route) => {
    await gate;
    await route.continue();
  });
  try {
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "설정", exact: true })).toBeVisible();
    await page
      .getByRole("navigation", { name: "주요 메뉴" })
      .getByRole("link", { name: "함께", exact: true })
      .click();
    const pending = page.locator(".app-navigation .navigation-pending");
    await expect(pending).toBeVisible();
    expect(
      await pending.evaluate((element) => {
        const link = element.closest("a");
        const icon = link?.querySelector("svg");
        const label = link?.querySelector("span:not(.navigation-pending)");
        return (
          !!icon &&
          !!label &&
          getComputedStyle(icon).visibility === "hidden" &&
          element.getBoundingClientRect().bottom <= label.getBoundingClientRect().top
        );
      }),
    ).toBe(true);
  } finally {
    release();
  }
  await expect(page).toHaveURL(/\/together$/);
});
