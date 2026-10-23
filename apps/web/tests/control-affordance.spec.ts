import fs from "node:fs/promises";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

const mobileDeepAudit = process.env.WE2DAY_TEST_MOBILE_DEEP === "1";
let textScale = 1;

test.use({ actionTimeout: 15_000, serviceWorkers: "block" });

async function open(page: Page, url: string) {
  await page.goto(url);
  // Wait for client form hydration before entering controlled input values.
  await page.waitForLoadState("networkidle");
}

async function auditControls(page: Page, label: string) {
  await expect(page.locator(".page-loading")).toHaveCount(0, { timeout: 30_000 });
  if (mobileDeepAudit && textScale === 1) {
    for (const field of await page
      .locator(
        'main input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="file"]),main textarea,main select',
      )
      .all()) {
      if (!(await field.isVisible()) || !(await field.isEnabled())) continue;
      await field.focus();
      await expect(field).toBeFocused();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        ),
        `${label}/focused field overflow`,
      ).toBe(true);
    }
  }
  if (textScale > 1) {
    await page.locator("body").evaluate((body, scale) => {
      const sizes = [...body.querySelectorAll<HTMLElement>("*")]
        .filter((node) => !node.dataset.auditTextScale)
        .map((node) => [node, parseFloat(getComputedStyle(node).fontSize)] as const);
      for (const [node, size] of sizes) {
        node.style.setProperty("font-size", `${size * scale}px`, "important");
        node.dataset.auditTextScale = String(scale);
      }
    }, textScale);
  }
  const issues = await page.locator("main").evaluate((main, deep) => {
    const problems: string[] = [];
    for (const control of main.querySelectorAll<HTMLElement>("button, a, summary")) {
      if (control.closest("[inert]")) continue;
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
      const icon = control.matches(".icon-button") && !!control.querySelector("svg");
      const activityCard =
        control.matches(".activity-card > .timeline-item") &&
        !!control.parentElement &&
        parseFloat(getComputedStyle(control.parentElement).borderTopWidth) > 0;
      if (!dateCell && !grouped && !underlined && !outline && !icon && !activityCard)
        problems.push(`plain text control: ${name}`);
      if (icon && parseFloat(style.borderTopWidth) !== 0) problems.push(`outlined icon: ${name}`);
      if (control.tagName !== "A" && !dateCell && bounds.height < 43.5)
        problems.push(`short target: ${name}`);
      if (deep && control.scrollWidth > control.clientWidth + 2)
        problems.push(`clipped control text: ${name}`);
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
      if (
        (document.documentElement.clientWidth <= 840 ||
          matchMedia("(hover: none) and (pointer: coarse)").matches) &&
        parseFloat(style.fontSize) < 16
      )
        problems.push(
          `iOS focus zoom: ${field.getAttribute("id") || field.getAttribute("name") || field.tagName}`,
        );
      const parent = field.parentElement?.getBoundingClientRect();
      if (parent && (box.right > parent.right + 1 || box.left < parent.left - 1))
        problems.push(`field escapes parent: ${field.id || field.tagName}`);
      if (box.right > document.documentElement.clientWidth + 1 || box.left < -1)
        problems.push(`field overflow: ${field.getAttribute("id") || field.tagName}`);
    }
    if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
      problems.push("horizontal page overflow");
    if (deep) {
      for (const label of main.querySelectorAll<HTMLElement>(
        ".agenda-heading small, .agenda-heading > .muted",
      )) {
        if (
          label.getClientRects().length > 1 ||
          label.scrollHeight > parseFloat(getComputedStyle(label).lineHeight) * 1.1
        )
          problems.push(`split calendar header label: ${label.textContent}`);
      }
      for (const time of main.querySelectorAll<HTMLElement>(".appointment-row time")) {
        if (time.scrollWidth > time.clientWidth + 1)
          problems.push("appointment time spills into title");
      }
      const swatches = [...main.querySelectorAll<HTMLElement>(".theme-swatch")];
      if (
        swatches.length === 2 &&
        Math.abs(
          swatches[0].getBoundingClientRect().left - swatches[1].getBoundingClientRect().left,
        ) > 1 &&
        Math.abs(
          swatches[0].getBoundingClientRect().top - swatches[1].getBoundingClientRect().top,
        ) > 1
      )
        problems.push("theme previews are vertically misaligned");
      const controls = [...main.querySelectorAll<HTMLElement>("button,a,summary")].filter((node) =>
        node.checkVisibility(),
      );
      for (let i = 0; i < controls.length; i++) {
        const a = controls[i],
          ar = a.getBoundingClientRect();
        for (const b of controls.slice(i + 1)) {
          if (a.contains(b) || b.contains(a)) continue;
          // An open popover intentionally covers the page behind it.
          const menuA = a.closest(".schedule-tools nav"),
            menuB = b.closest(".schedule-tools nav");
          if (menuA !== menuB && (menuA || menuB)) continue;
          const br = b.getBoundingClientRect();
          if (
            Math.min(ar.right, br.right) - Math.max(ar.left, br.left) > 2 &&
            Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top) > 2
          )
            problems.push(
              `overlapping controls: ${a.textContent?.trim().slice(0, 30)} / ${b.textContent?.trim().slice(0, 30)}`,
            );
        }
      }
    }
    return problems;
  }, mobileDeepAudit);
  // The worker's standalone offline document deliberately has no application shell.
  const headingIssues = label.startsWith("offline-notice/")
    ? []
    : await page.locator(".app-header").evaluate((header) => {
        const issues: string[] = [];
        const word = header.querySelector<HTMLElement>(".wordmark")?.getBoundingClientRect();
        const titles = [...header.querySelectorAll<HTMLElement>("h1")].filter((h) =>
          h.checkVisibility(),
        );
        if (titles.length !== 1) issues.push("expected one visible page heading in header");
        for (const title of titles) {
          const box = title.getBoundingClientRect();
          if (word && box.left < word.right + 7) issues.push("page heading overlaps wordmark");
          if (box.right > document.documentElement.clientWidth + 1)
            issues.push("page heading overflow");
          if (getComputedStyle(title).textAlign !== "right")
            issues.push("page heading is not right aligned");
        }
        return issues;
      });
  issues.push(...headingIssues);
  if (mobileDeepAudit) {
    const reachability = await page.locator("body").evaluate((body) => {
      const problems: string[] = [];
      for (const target of body.querySelectorAll<HTMLElement>(
        'main button:not(.calendar-day),main a,main summary,main input:not([type="hidden"]),main select,main textarea,.app-navigation a',
      )) {
        const style = getComputedStyle(target);
        if (!target.checkVisibility() || style.visibility === "hidden" || target.closest("[inert]"))
          continue;
        target.scrollIntoView({ block: "center", inline: "nearest" });
        const reachable = [...target.getClientRects()].some((rect) => {
          const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          if (hit?.closest(".schedule-tools[open] nav") && !target.closest(".schedule-tools nav"))
            return true;
          return !!hit && (target === hit || target.contains(hit));
        });
        if (!reachable)
          problems.push(
            `unreachable control: ${target.getAttribute("aria-label") || target.id || target.textContent?.trim().slice(0, 40)}`,
          );
      }
      for (const link of body.querySelectorAll<HTMLElement>(".app-navigation a")) {
        const rect = link.getBoundingClientRect();
        if (
          link.scrollWidth > link.clientWidth + 2 ||
          rect.right > innerWidth + 1 ||
          rect.left < -1
        )
          problems.push(`navigation overflow: ${link.textContent?.trim()}`);
      }
      return problems;
    });
    issues.push(...reachability);
  }
  if (issues.length) console.log(`UI issues ${label}: ${JSON.stringify(issues)}`);
  expect.soft(issues, label).toEqual([]);
}

test("mobile offline notice remains readable at narrow widths", async ({ page }, info) => {
  const worker = await fs.readFile(path.resolve("public/sw.js"), "utf8");
  const html = worker.match(/const offlineDocument = `([\s\S]*?)`;/)?.[1];
  if (!html) throw new Error("offline notice is missing");
  try {
    for (const width of [320, 393]) {
      for (const scale of [1, 2]) {
        textScale = scale;
        await page.setViewportSize({ width, height: 852 });
        // Render the worker's exact notice; this does not test SW delivery.
        await page.setContent(html);
        await expect(
          page.getByRole("heading", { name: "인터넷 연결을 확인해 주세요" }),
        ).toBeVisible();
        await auditControls(page, `offline-notice/${width}/text${scale}`);
        await page.screenshot({
          path: info.outputPath(`offline-notice-${width}-text${scale}.png`),
          fullPage: true,
          scale: "css",
        });
      }
    }
  } finally {
    textScale = 1;
  }
});

test("mobile calendar labels remain whole when text grows", async ({ page }, info) => {
  try {
    for (const width of [320, 393]) {
      for (const scale of [1, 2]) {
        textScale = scale;
        await page.setViewportSize({ width, height: 852 });
        await open(page, "/preview");
        await auditControls(page, `calendar-labels/${width}/text${scale}`);
        const labels = page.locator(".agenda-heading small, .agenda-heading > .muted");
        for (const label of await labels.all()) {
          expect(await label.evaluate((node) => node.getClientRects().length)).toBe(1);
          expect(
            await label.evaluate(
              (node) => node.scrollHeight <= parseFloat(getComputedStyle(node).lineHeight) * 1.1,
            ),
          ).toBe(true);
        }
        await page.screenshot({
          path: info.outputPath(`calendar-labels-${width}-text${scale}.png`),
          fullPage: true,
          scale: "css",
        });
      }
    }
  } finally {
    textScale = 1;
  }
});

test("mobile theme cards remain readable with enlarged text", async ({ page }, info) => {
  try {
    textScale = 2;
    for (const width of [320, 393]) {
      await page.setViewportSize({ width, height: 852 });
      await open(page, "/settings");
      await auditControls(page, `theme-text200/${width}`);
      await page.screenshot({
        path: info.outputPath(`theme-text200-${width}.png`),
        fullPage: true,
        scale: "css",
      });
      for (const swatch of await page.locator(".theme-swatch").all()) {
        const container = await swatch.boundingBox();
        const word = await swatch.locator("span").boundingBox();
        if (!container || !word) throw new Error("theme preview is missing");
        expect(word.x + word.width).toBeLessThanOrEqual(container.x + container.width);
      }
    }
  } finally {
    textScale = 1;
  }
});

test("all page controls remain identifiable in both themes and narrow layouts", async ({
  page,
  context,
  browser,
}, testInfo) => {
  test.setTimeout(1_800_000);
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
  await page.getByRole("button", { name: "사진 업로드", exact: true }).click();
  await page.getByLabel("사진 선택").setInputFiles(path.resolve("public/demo/autumn.jpg"));
  await expect(page.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
  await page.getByLabel("이 사진의 한마디").fill("긴사진설명과함께남기는하루의기록".repeat(4));
  await page.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
  await expect(
    page.getByText("둘의 사진으로 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요."),
  ).toBeVisible();
  await open(page, "/questions");
  await page
    .locator("summary")
    .filter({ hasText: /^질문 추가$/ })
    .click();
  await page.getByLabel("함께 나눌 질문").fill("화면 확인용 질문");
  await page.getByRole("button", { name: "질문 추가", exact: true }).click();
  await expect(page).toHaveURL(/\/questions\/[a-f0-9-]+$/, { timeout: 30_000 });
  const question = new URL(page.url()).pathname;
  await open(page, "/roulette");
  await page.getByRole("button", { name: "룰렛 만들기", exact: true }).click();
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
  await page.getByLabel("활동 1 장소", { exact: true }).fill("직접 적은 예시 공원");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "확정 내용 확인", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }),
  ).toBeVisible();
  await auditControls(page, "long-plan-editor");
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
        widths: mobileDeepAudit ? [320, 375, 393, 430, 844] : [320, 390, 768, 844, 1280],
        textScales: mobileDeepAudit ? [1, 2] : [1],
        themes: ["warm", "white"],
      },
      null,
      2,
    ),
  );
  if (mobileDeepAudit) {
    await page.setViewportSize({ width: 393, height: 852 });
    const detailedStates = [
      ["/", /LongUnbrokenAppointmentTitle/, "appointment-detail"],
      ["/plans", /LongUnbrokenPlanTitle/, "plan-edit"],
      ["/checklists", /^목록 열기/, "checklist-edit"],
      ["/goals", /^목표 열기/, "goal-edit"],
      ["/wishlist", /^위시 추가$/, "wish-editor"],
      ["/anniversaries", / 수정$/, "anniversary-edit"],
    ] as const;
    for (const [route, name, label] of detailedStates) {
      await open(page, route);
      await page.getByRole("button", { name }).first().click();
      await auditControls(page, `mobile-detail/${label}`);
      await page.screenshot({
        path: testInfo.outputPath(`mobile-detail-${label}.png`),
        fullPage: true,
        scale: "css",
      });
    }
    await open(page, "/today");
    await page.getByRole("button", { name: "앱 연결 옵션", exact: true }).click();
    await page.getByText("목적지 좌표로 바로 길찾기", { exact: true }).click();
    await auditControls(page, "mobile-detail/naver-app-handoff");
    await page.screenshot({
      path: testInfo.outputPath("mobile-detail-handoff.png"),
      fullPage: true,
      scale: "css",
    });
    await open(page, "/memories");
    await page.getByRole("button", { name: "사진 업로드", exact: true }).click();
    await page.getByLabel("사진 선택").setInputFiles(path.resolve("public/demo/autumn.jpg"));
    await expect(page.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
    await page
      .getByLabel("이 사진의 한마디")
      .fill("사진 미리보기와 긴 설명을 작성하는 상태".repeat(10));
    await auditControls(page, "mobile-detail/photo-draft");
    await page.screenshot({
      path: testInfo.outputPath("mobile-detail-photo-draft.png"),
      fullPage: true,
      scale: "css",
    });
    for (const route of ["/account", "/questions", "/memories/search"]) {
      await page.setViewportSize({ width: 393, height: 350 });
      await open(page, route);
      const field = page.locator('main input:not([type="hidden"]),main textarea').first();
      await field.focus();
      await field.scrollIntoViewIfNeeded();
      await expect(field).toBeFocused();
      await auditControls(page, `short-viewport/${route}`);
      await field.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: testInfo.outputPath(`short-viewport-${route.replaceAll("/", "_")}.png`),
        scale: "css",
      });
    }
    await page.setViewportSize({ width: 393, height: 852 });
  }

  const desktop = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 1280, height: 900 },
    storageState: await context.storageState(),
    serviceWorkers: "block",
  });
  try {
    const desktopPage = await desktop.newPage();
    const layouts = mobileDeepAudit
      ? ([
          ["warm", 320, 740, 1],
          ["white", 320, 740, 1],
          ["warm", 375, 667, 1],
          ["white", 393, 852, 1],
          ["warm", 430, 932, 1],
          ["white", 844, 390, 1],
          ["warm", 320, 740, 2],
          ["white", 393, 852, 2],
        ] as const)
      : ([
          ["warm", 320, 900, 1],
          ["white", 390, 900, 1],
          ["warm", 768, 900, 1],
          ["white", 844, 390, 1],
          ["warm", 1280, 900, 1],
          ["white", 1280, 900, 1],
        ] as const);
    for (const [baseTheme, width, height, scale] of layouts) {
      textScale = scale;
      console.log(`Mobile layout ${baseTheme}/${width}x${height}/text${scale}`);
      const theme = `${baseTheme}${scale > 1 ? "-text200" : ""}`;
      const current = width < 641 || mobileDeepAudit ? page : desktopPage;
      const currentContext = width < 641 || mobileDeepAudit ? context : desktop;
      await current.setViewportSize({ width, height });
      await currentContext.addCookies([
        { name: "we2day-theme", value: baseTheme, url: "http://127.0.0.1:3100" },
      ]);
      for (const route of routes) {
        await open(current, route);
        await auditControls(current, `${theme}/${width}/${route}`);
        if (route !== "/page-not-found-fixture") {
          const expected = route.startsWith("/memories")
            ? "/memories"
            : /^\/(together|checklists|goals|questions|roulette)(?:\/|$)/.test(route)
              ? "/together"
              : route.startsWith("/settings") ||
                  ["/account", "/couple", "/login", "/timezones"].includes(route)
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
        if (mobileDeepAudit && width === 393 && scale === 1) {
          const sections = current.locator("main details:not([open]) > summary");
          let expanded = 0;
          for (const summary of await sections.all()) {
            if (await summary.isVisible()) {
              await summary.click();
              expanded++;
            }
          }
          if (expanded) {
            await auditControls(current, `${theme}/${width}/${route}/expanded`);
            await current.screenshot({
              path: testInfo.outputPath(
                `${theme}-${width}-${route.replaceAll("/", "_") || "home"}-expanded.png`,
              ),
              fullPage: true,
              scale: "css",
            });
          }
        }
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
      await current
        .locator(".route-point")
        .filter({ hasText: "출발점" })
        .getByText("좌표 직접 입력", { exact: true })
        .click();
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
    textScale = 1;
    const guest = await browser.newContext({
      baseURL: "http://127.0.0.1:3100",
      viewport: { width: 390, height: 844 },
      serviceWorkers: "block",
    });
    try {
      const loginPage = await guest.newPage();
      await open(loginPage, "/login");
      await loginPage.getByLabel("아이디", { exact: true }).fill("missing");
      await loginPage.getByLabel("비밀번호", { exact: true }).fill("wrong-password");
      await loginPage.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(loginPage.getByRole("main").getByRole("alert")).toBeVisible();
      await auditControls(loginPage, "login/error");
    } finally {
      await guest.close();
    }
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
    await expect(page.getByRole("heading", { name: "설정", exact: true })).toBeVisible();
    await expect(page.locator(".page-loading")).toHaveCount(0);
    expect(
      await pending.evaluate((element) => {
        const link = element.closest("a");
        const icon = link?.querySelector("svg");
        const label = link?.querySelector("span:not(.navigation-pending)");
        return (
          !!icon &&
          !!label &&
          getComputedStyle(icon).visibility === "visible" &&
          element.getBoundingClientRect().bottom <= label.getBoundingClientRect().top
        );
      }),
    ).toBe(true);
  } finally {
    release();
  }
  await expect(page).toHaveURL(/\/together$/);
});

test("mobile inputs keep portrait and landscape size without disabling user zoom", async ({
  page,
}) => {
  for (const width of [320, 393, 768, 844]) {
    await page.setViewportSize({ width, height: width > 640 ? 390 : 852 });
    await open(page, "/login");
    const field = page.getByLabel("아이디", { exact: true });
    await field.fill("long_unbroken_account_name_for_mobile");
    await field.focus();
    await expect(field).toBeFocused();
    expect(
      await field.evaluate((e) => parseFloat(getComputedStyle(e).fontSize)),
      `input font at ${width}`,
    ).toBeGreaterThanOrEqual(16);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
      ),
    ).toBe(true);
    const viewport = await page.locator('meta[name="viewport"]').getAttribute("content");
    expect(viewport).not.toMatch(/user-scalable=no|maximum-scale=1(?:,|$)/);
  }
});

test("mobile preview badge stays within the heading at enlarged text", async ({
  page,
  context,
}, info) => {
  try {
    for (const theme of ["warm", "white"]) {
      await context.addCookies([
        { name: "we2day-theme", value: theme, url: "http://127.0.0.1:3100" },
      ]);
      for (const width of [320, 393]) {
        await page.setViewportSize({ width, height: 852 });
        textScale = 2;
        await open(page, "/preview");
        await auditControls(page, `preview-badge/${theme}/${width}/text200`);
        const badge = page.locator(".preview-badge");
        expect(
          await badge.evaluate(
            (e) => e.getBoundingClientRect().right <= document.documentElement.clientWidth,
          ),
        ).toBe(true);
        await page.screenshot({
          path: info.outputPath(`preview-badge-${theme}-${width}.png`),
          fullPage: true,
        });
      }
    }
  } finally {
    textScale = 1;
  }
});
