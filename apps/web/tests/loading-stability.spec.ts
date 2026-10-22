import path from "node:path";
import { expect, type Locator, type Page, type Route, test } from "@playwright/test";

test.use({ serviceWorkers: "block", actionTimeout: 15_000 });

async function open(page: Page, url: string) {
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}

async function geometry(target: Locator) {
  return target.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { x: rect.x + scrollX, y: rect.y + scrollY, width: rect.width, height: rect.height };
  });
}

function unchanged(actual: Awaited<ReturnType<typeof geometry>>, expected: typeof actual) {
  for (const key of ["x", "y", "width", "height"] as const)
    expect(Math.abs(actual[key] - expected[key]), key).toBeLessThanOrEqual(1);
}

async function pause(page: Page, pattern: string, reply?: Parameters<Route["fulfill"]>[0]) {
  let release = () => {};
  let observed = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const started = new Promise<void>((resolve) => {
    observed = resolve;
  });
  const handler = async (route: Route) => {
    observed();
    await gate;
    if (reply) await route.fulfill(reply);
    else await route.continue();
  };
  await page.route(pattern, handler);
  return { started, release, remove: () => page.unroute(pattern, handler) };
}

test("slow reads preserve content geometry, block stale edits and recover in both themes", async ({
  page,
}, info) => {
  test.setTimeout(300_000);
  await open(page, "/login");
  await page.getByLabel("아이디", { exact: true }).fill("audit");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await open(page, "/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await open(page, "/memories");
  await page.getByLabel("사진 선택").setInputFiles(path.resolve("public/demo/autumn.jpg"));
  await expect(page.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
  await page.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
  await expect(
    page.getByText("둘의 사진으로 저장했어요. 아래 날짜별 앨범에서 확인할 수 있어요."),
  ).toBeVisible();

  for (const [width, theme] of [
    [390, "warm"],
    [1280, "white"],
    [320, "white"],
  ] as const) {
    await page.setViewportSize({ width, height: 844 });
    await page
      .context()
      .addCookies([{ name: "we2day-theme", value: theme, domain: "127.0.0.1", path: "/" }]);
    await open(page, "/");
    const calendar = page.locator(".calendar-workspace");
    const meeting = page.locator(".meeting-day-editor");
    const original = await geometry(calendar),
      meetingOriginal = await geometry(meeting);
    const flow = () =>
      page.locator("main > *").evaluateAll((nodes) =>
        nodes.map((n) => ({
          tag: n.tagName,
          cls: n.className,
          y: n.getBoundingClientRect().y + scrollY,
          h: n.getBoundingClientRect().height,
        })),
      );
    const flowBefore = await flow();
    const appointments = await pause(page, "**/api/appointments?*");
    const meetings = await pause(page, "**/api/meetings?*");
    try {
      await page.getByRole("button", { name: "일정 새로고침", exact: true }).click();
      await Promise.all([appointments.started, meetings.started]);
      await expect(page.locator(".loading-veil:visible").first()).toBeVisible();
      expect(
        await page
          .locator(".loading-veil:visible")
          .first()
          .evaluate((node) => !!node.closest('[inert], [aria-busy="true"]')),
      ).toBe(false);
      await info.attach(`calendar-geometry-${width}`, {
        body: JSON.stringify({
          before: flowBefore,
          after: await flow(),
          original,
          current: await geometry(calendar),
        }),
        contentType: "application/json",
      });
      unchanged(await geometry(calendar), original);
      unchanged(await geometry(meeting), meetingOriginal);
      expect(await meeting.evaluate((node) => !!node.closest("[inert]"))).toBe(true);
      await page.screenshot({
        path: info.outputPath(`calendar-pending-${width}.png`),
        fullPage: true,
      });
    } finally {
      appointments.release();
      meetings.release();
    }
    await expect(page.locator(".loading-veil")).toHaveCount(0);
    unchanged(await geometry(calendar), original);
    unchanged(await geometry(meeting), meetingOriginal);
    await appointments.remove();
    await meetings.remove();

    if (width === 390) {
      await page.route("**/api/appointments?*", (request) =>
        request.fulfill({ status: 503, json: { error: "합성 일정 조회 실패" } }),
      );
      await page.getByRole("button", { name: "일정 새로고침", exact: true }).click();
      await expect(
        page.getByRole("alert").filter({ hasText: "합성 일정 조회 실패" }),
      ).toBeVisible();
      await expect(page.locator(".loading-veil")).toHaveCount(0);
      await page.unroute("**/api/appointments?*");
      const retryBox = await geometry(calendar);
      const retry = await pause(page, "**/api/appointments?*");
      try {
        await page.getByRole("button", { name: "일정 새로고침", exact: true }).click();
        await retry.started;
        unchanged(await geometry(calendar), retryBox);
      } finally {
        retry.release();
      }
      await expect(page.getByRole("alert").filter({ hasText: "합성 일정 조회 실패" })).toHaveCount(
        0,
      );
      await expect(page.locator(".loading-veil")).toHaveCount(0);
      await retry.remove();
    }

    const route = await pause(page, "**/api/routes?*");
    let initialForm: Awaited<ReturnType<typeof geometry>>;
    try {
      await page.getByRole("button", { name: "동선 기록 열기", exact: true }).click();
      await route.started;
      initialForm = await geometry(page.locator(".route-form"));
      expect(await page.locator(".route-form").evaluate((node) => !!node.closest("[inert]"))).toBe(
        true,
      );
    } finally {
      route.release();
    }
    await expect(
      page.locator(".route-form").getByRole("button", { name: "동선 저장", exact: true }),
    ).toBeEnabled();
    unchanged(await geometry(page.locator(".route-form")), initialForm);
    await route.remove();

    await open(page, "/memories");
    const album = page.getByRole("region", { name: "날짜별 사진 앨범" });
    await expect(album.locator(".shared-photo-grid article")).toHaveCount(1);
    const albumBox = await geometry(album);
    const photos = await pause(page, "**/api/photos?*");
    try {
      await album.getByRole("button", { name: "사진 새로고침", exact: true }).click();
      await photos.started;
      await expect(album.locator(".loading-veil")).toBeVisible();
      const spinner = await album.locator(".loading-veil > .loading-spinner").boundingBox();
      expect(spinner).not.toBeNull();
      expect(spinner?.y).toBeGreaterThanOrEqual(0);
      expect((spinner?.y ?? 0) + (spinner?.height ?? 0)).toBeLessThanOrEqual(844);
      await expect(album.locator(".shared-photo-grid article")).toHaveCount(1);
      unchanged(await geometry(album), albumBox);
      await page.screenshot({
        path: info.outputPath(`album-pending-${width}.png`),
        fullPage: true,
      });
    } finally {
      photos.release();
    }
    await expect(album.locator(".loading-veil")).toHaveCount(0);
    unchanged(await geometry(album), albumBox);
    await photos.remove();

    // Changing date may replace actual results, but failed reads must never expose the old album as editable.
    const failure = await pause(page, "**/api/photos?*", {
      status: 503,
      json: { error: "합성 조회 실패" },
    });
    try {
      await page.getByLabel("만난 날짜", { exact: true }).fill("2025-01-01");
      await failure.started;
      expect(
        await album.locator(".shared-photo-grid").evaluate((node) => !!node.closest("[inert]")),
      ).toBe(true);
    } finally {
      failure.release();
    }
    await expect(album.getByRole("alert")).toHaveText("합성 조회 실패");
    await expect(album.locator(".loading-veil")).toHaveCount(0);
    await expect(album.locator(".shared-photo-grid")).toBeHidden();
    await failure.remove();
    await album.getByRole("button", { name: "사진 새로고침", exact: true }).click();
    await expect(
      album.getByText("아직 이 날의 사진이 없어요. 첫 장면을 남겨보세요."),
    ).toBeVisible();

    for (const [url, label, pattern] of [
      ["/questions/search", "질문 검색", "**/questions/search*"],
      ["/memories/search", "사진 검색", "**/memories/search*"],
      ["/memories/records", "기록 검색", "**/api/records/search"],
      ["/memories/routes", "동선 조회", "**/api/routes/history"],
    ]) {
      await open(page, url);
      const selectStyles = await page.locator("main select").evaluateAll((nodes) =>
        nodes.map((node) => {
          const style = getComputedStyle(node);
          return {
            id: node.id,
            border: style.border,
            width: style.borderTopWidth,
            appearance: style.appearance,
            image: style.backgroundImage,
            parent: node.parentElement?.className,
            line: style.getPropertyValue("--line"),
            rootLine: getComputedStyle(document.documentElement).getPropertyValue("--line"),
            html: node.outerHTML,
          };
        }),
      );
      expect(
        selectStyles.every((style) => parseFloat(style.width) > 0),
        JSON.stringify(selectStyles),
      ).toBe(true);
      await page.getByRole("button", { name: label, exact: true }).click();
      await expect(page.locator(".loading-veil")).toHaveCount(0);
      await page.waitForLoadState("networkidle");
      const form = page.locator("main form"),
        formBox = await geometry(form);
      const region = page.locator("main .loading-region").first(),
        regionBox = await geometry(region);
      const query = await pause(page, pattern);
      try {
        await page.getByRole("button", { name: label, exact: true }).click();
        await query.started;
        await expect(region.locator(".loading-veil")).toBeVisible();
        unchanged(await geometry(form), formBox);
        unchanged(await geometry(region), regionBox);
      } finally {
        query.release();
      }
      await expect(region.locator(".loading-veil")).toHaveCount(0);
      unchanged(await geometry(form), formBox);
      await query.remove();
    }

    const config = await pause(page, "**/api/push/config", {
      json: { configured: false, public_key: null },
    });
    let settingsBox: Awaited<ReturnType<typeof geometry>>;
    try {
      await page.goto("/settings");
      await config.started;
      const panel = page.getByRole("region", { name: "이 기기의 알림" });
      await expect(panel.locator(".loading-veil")).toBeVisible();
      settingsBox = await geometry(panel);
    } finally {
      config.release();
    }
    const panel = page.getByRole("region", { name: "이 기기의 알림" });
    await expect(panel.locator(".loading-veil")).toHaveCount(0);
    unchanged(await geometry(panel), settingsBox);
    await config.remove();
    await page.emulateMedia({ reducedMotion: "reduce" });
    const refreshConfig = await pause(page, "**/api/push/config", {
      json: { configured: false, public_key: null },
    });
    try {
      await panel.getByRole("button", { name: "알림 상태 다시 확인" }).click();
      await refreshConfig.started;
      expect(
        await panel
          .locator(".loading-spinner")
          .evaluate((node) => getComputedStyle(node).animationName),
      ).toBe("none");
      unchanged(await geometry(panel), settingsBox);
    } finally {
      refreshConfig.release();
    }
    await expect(panel.locator(".loading-veil")).toHaveCount(0);
    await refreshConfig.remove();
    await page.emulateMedia({ reducedMotion: "no-preference" });
  }
});
