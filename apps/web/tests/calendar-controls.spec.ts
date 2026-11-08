import { expect, type Route, test } from "@playwright/test";

test("calendar controls keep tinted day labels centered and refresh in its section", async ({
  page,
  browser,
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
  await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
  const invite = await page.getByLabel("상대에게 전달할 코드").inputValue();
  await page.goto("/");
  await page.waitForLoadState("networkidle");
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
  const selectedDate = await calendar
    .locator('.calendar-day[aria-pressed="true"]')
    .getAttribute("data-date");
  const day = calendar.locator(`.calendar-day[data-date="${selectedDate}"]`);
  const actions = page.locator(".agenda-header-actions");
  const record = actions.getByRole("button", { name: "만남 기록", exact: true });
  const dialog = page.getByRole("dialog", { name: "만남 기록", exact: true });
  const tools = page.locator(".schedule-tools > summary");
  await expect(actions.getByRole("link", { name: /데이트 코스/ })).toHaveAttribute(
    "href",
    `/today?date=${selectedDate}`,
  );
  await expect(actions.getByRole("link", { name: "이 날짜의 사진", exact: true })).toHaveAttribute(
    "href",
    `/memories?date=${selectedDate}`,
  );
  await expect(page.locator(".meeting-day-editor")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "함께한 날의 사진", exact: true })).toHaveCount(0);
  await expect(tools).toHaveAccessibleName("일정 도구");
  await expect(tools).toHaveText("");
  for (const width of [320, 393, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const anniversary = await page
      .locator(".home-anniversary-slot > .anniversary-summary")
      .boundingBox();
    const next = await page.locator(".next-appointment").boundingBox();
    const toolbar = await page.locator(".home-calendar-toolbar").boundingBox();
    if (!anniversary || !next || !toolbar) throw Error("Missing home section geometry");
    expect(Math.abs(next.y - anniversary.y - anniversary.height - 12)).toBeLessThanOrEqual(1);
    expect(
      Math.abs(next.y - anniversary.y - anniversary.height - (toolbar.y - next.y - next.height)),
    ).toBeLessThanOrEqual(1);
    const controls = [...(await actions.locator("a,button").all()), tools];
    for (const control of controls) {
      const box = await control.boundingBox();
      if (!box) throw Error("Missing date/tool icon");
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    const more = await tools.boundingBox(),
      ai = await page.locator(".home-ai-entry").boundingBox();
    if (!more || !ai) throw Error("Missing toolbar controls");
    expect(more.x).toBeGreaterThan(ai.x);
    expect(Math.abs(more.y - ai.y)).toBeLessThan(2);
    await tools.focus();
    await tools.press("Enter");
    const menu = page.getByRole("navigation", { name: "일정 도구", exact: true });
    await expect(menu.getByRole("link")).toHaveText([
      "플랜",
      "코스",
      "다가오는 일정",
      "캘린더 내보내기",
    ]);
    await expect(menu.locator("a > svg")).toHaveCount(4);
    const menuBox = await menu.boundingBox();
    if (!menuBox) throw Error("Missing tool menu");
    expect(menuBox.x).toBeGreaterThanOrEqual(0);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width);
    await tools.press("Escape");
    await expect(menu).toBeHidden();
    await expect(tools).toBeFocused();
    await tools.click();
    await calendar.locator(".month-heading h2").click();
    await expect(menu).toBeHidden();
  }
  await record.click();
  await expect(dialog).toBeVisible();
  await page.getByLabel("함께한 날의 메모").fill("저장하지 않는 합성 메모");
  expect(await page.evaluate(() => JSON.stringify(history.state.we2dayView))).not.toContain(
    "저장하지 않는 합성 메모",
  );
  await page.goBack();
  await expect(dialog).toHaveCount(0);
  await expect(record).toBeFocused();
  await page.goForward();
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("함께한 날의 메모")).toHaveValue("");
  await page.getByLabel("이 날 만났어요", { exact: true }).check();
  await page.getByLabel("함께한 날의 메모").fill("함께 남긴 합성 기록");
  let releaseSave = () => {};
  const gate = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  const delaySave = async (route: Route) => {
    if (route.request().method() === "POST" && route.request().headers()["next-action"]) await gate;
    await route.continue();
  };
  await page.route("**/*", delaySave);
  try {
    const sent = page.waitForRequest(
      (request) => request.method() === "POST" && Boolean(request.headers()["next-action"]),
    );
    await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await sent;
    await page.getByRole("button", { name: "만남 기록 닫기", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    releaseSave();
    await expect(day).toHaveClass(/has-meeting/);
  } finally {
    releaseSave();
    await page.unroute("**/*", delaySave);
  }
  await record.click();
  await expect(page.getByLabel("함께한 날의 메모")).toHaveValue("함께 남긴 합성 기록");
  const partnerContext = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    serviceWorkers: "block",
  });
  try {
    const partner = await partnerContext.newPage();
    await partner.goto("/login");
    await partner.getByLabel("아이디", { exact: true }).fill("partner");
    await partner.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
    await partner.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(partner).toHaveURL(/\/account$/);
    await partner.goto("/couple");
    await partner.getByLabel("받은 초대 코드").fill(invite);
    await partner.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(partner.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await partner.goto(`/?date=${selectedDate}`);
    await partner.waitForLoadState("networkidle");
    await partner.getByRole("button", { name: "만남 기록", exact: true }).click();
    await expect(partner.getByLabel("함께한 날의 메모")).toHaveValue("함께 남긴 합성 기록");
    await page.getByLabel("함께한 날의 메모").fill("먼저 저장한 합성 기록");
    await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "만남 기록을 저장했어요" }),
    ).toBeVisible();
    await partner.getByLabel("함께한 날의 메모").fill("충돌 시 유지할 합성 입력");
    await partner.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(partner.getByRole("dialog").getByRole("alert")).toContainText(
      "만남 기록이 바뀌었어요",
    );
    await expect(partner.getByLabel("함께한 날의 메모")).toHaveValue("충돌 시 유지할 합성 입력");
    await partner.getByRole("button", { name: "최신 만남 기록 불러오기", exact: true }).click();
    await expect(partner.getByLabel("함께한 날의 메모")).toHaveValue("먼저 저장한 합성 기록");
    await partner.getByLabel("이 날 만났어요", { exact: true }).uncheck();
    await partner.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(
      partner.getByRole("status").filter({ hasText: "만남 기록을 저장했어요" }),
    ).toBeVisible();
    await page.reload();
    await page.waitForLoadState("networkidle");
    // A completed save can refresh the route; open the record again to read its current version.
    if (!(await dialog.count())) await record.click();
    await expect(dialog).toBeVisible();
    await expect(page.getByLabel("이 날 만났어요", { exact: true })).not.toBeChecked();
    await expect(page.getByLabel("함께한 날의 메모")).toHaveValue("먼저 저장한 합성 기록");
  } finally {
    await partnerContext.close();
  }
  await page.getByLabel("이 날 만났어요", { exact: true }).check();
  await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "만남 기록을 저장했어요" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "만남 기록 닫기", exact: true }).click();
  for (const theme of ["warm", "white", "pongni", "dumung", "sopoo", "kuku"]) {
    await page
      .context()
      .addCookies([{ name: "we2day-theme", value: theme, url: "http://127.0.0.1:3100" }]);
    await page.reload();
    await page.waitForLoadState("networkidle");
    for (const width of [320, 393, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await record.click();
      await expect(dialog).toBeVisible();
      const box = await dialog.boundingBox();
      if (!box) throw Error("Record dialog not visible");
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      expect(Math.abs(box.x + box.width / 2 - width / 2)).toBeLessThan(1);
      expect(box.y).toBeGreaterThanOrEqual(16);
      expect(box.y + box.height).toBeLessThanOrEqual(884);
      expect(Math.abs(box.y + box.height / 2 - 450)).toBeLessThan(1);
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
        true,
      );
      if (theme === "warm" && width !== 320)
        await page.screenshot({
          path: testInfo.outputPath(`record-dialog-${width}.png`),
          fullPage: false,
        });
      await dialog.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(record).toBeFocused();
      if (theme === "warm" && width !== 320)
        await page.screenshot({
          path: testInfo.outputPath(`home-icons-${width}.png`),
          fullPage: true,
          style:
            "nextjs-portal { display: none !important; } .app-navigation { position: static !important; }",
        });
    }
  }
  await page
    .context()
    .addCookies([{ name: "we2day-theme", value: "warm", url: "http://127.0.0.1:3100" }]);
  await page.setViewportSize({ width: 393, height: 900 });
  await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
  await page.getByLabel("약속 이름").fill("달력 표시 확인용 예시");
  await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
  await expect(page.getByRole("button", { name: /달력 표시 확인용 예시/ })).toBeVisible();
  await expect(calendar.locator('.calendar-day[aria-current="date"]')).toHaveClass(/has-event/);
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
  for (const [theme, width] of [
    ["warm", 393],
    ["warm", 1280],
    ["white", 393],
  ] as const) {
    await page
      .context()
      .addCookies([{ name: "we2day-theme", value: theme, url: "http://127.0.0.1:3100" }]);
    await page.setViewportSize({ width, height: 1000 });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.screenshot({
      path: testInfo.outputPath(`calendar-public-${theme}-${width}.png`),
      fullPage: true,
      animations: "disabled",
      style:
        "nextjs-portal { display: none !important; } .app-navigation { position: static !important; }",
    });
  }
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
  await page.waitForLoadState("networkidle");
  await selectedDay.focus();
  await selectedDay.press("Shift+PageDown");
  await expect(selectedDay).toHaveAttribute("data-date", "2025-02-28");
  await expect(selectedDay).toBeFocused();
  await page.goto("/?date=2000-01-01");
  await page.waitForLoadState("networkidle");
  await selectedDay.focus();
  await selectedDay.press("ArrowLeft");
  await expect(selectedDay).toHaveAttribute("data-date", "2000-01-01");
  await page.goto("/?date=2100-12-31");
  await page.waitForLoadState("networkidle");
  await selectedDay.focus();
  await selectedDay.press("ArrowRight");
  await expect(selectedDay).toHaveAttribute("data-date", "2100-12-31");
  await record.click();
  await expect(dialog.getByText("만난 날은 오늘과 지난 날짜에 기록할 수 있어요.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "만남 기록 저장", exact: true })).toHaveCount(0);
  await dialog.press("Escape");
  await page.route("**/api/meetings?*", (route) =>
    route.fulfill({ status: 503, json: { error: "합성 만남 읽기 실패" } }),
  );
  await page.goto("/?date=2026-10-24");
  await page.waitForLoadState("networkidle");
  await record.click();
  await expect(dialog.getByRole("alert")).toContainText("만남 기록을 불러오지 못했어요");
  await expect(dialog.locator(".loading-region > div[inert]")).toHaveCount(1);
  expect(
    await dialog.getByLabel("함께한 날의 메모").evaluate((element) => {
      (element as HTMLElement).focus();
      return document.activeElement === element;
    }),
  ).toBe(false);
  await page.unroute("**/api/meetings?*");
  await dialog.getByRole("button", { name: "다시 불러오기", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "만남 기록 저장", exact: true })).toBeEnabled();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await dialog.getByLabel("함께한 날의 메모").focus();
  await expect(dialog.getByLabel("함께한 날의 메모")).toBeFocused();
  await dialog.press("Escape");
  await expect(dialog).toHaveCount(0);
  await actions.getByRole("link", { name: "이 날짜의 사진", exact: true }).click();
  await expect(page).toHaveURL(/\/memories\?date=2026-10-24$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "함께한 날들", exact: true })).toBeVisible();
});
