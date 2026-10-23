import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

const characters = [
  ["pongni", "퐁니 라벤더"],
  ["dumung", "두뭉 크림"],
  ["sopoo", "소푸 버터"],
  ["kuku", "쿠쿠 코코아"],
] as const;

test("four character themes persist, remain legible and retain compact navigation", async ({
  page,
  context,
  browser,
}, info) => {
  test.setTimeout(120_000);
  await page.goto("/settings");
  const choices = page.getByRole("group", { name: "화면 테마", exact: true });
  await expect(choices.getByRole("button")).toHaveCount(6);
  await page.setViewportSize({ width: 320, height: 852 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 393, height: 852 });
  for (const [value, name] of characters) {
    await page.goto("/settings");
    const saved = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith("/settings"),
    );
    await page.getByRole("button", { name: new RegExp(name) }).click();
    const wireCookie = (await (await saved).allHeaders())["set-cookie"];
    expect(wireCookie).toMatch(/SameSite=lax/i);
    expect(wireCookie).toMatch(/HttpOnly/i);
    expect(wireCookie).toMatch(/Secure/i);
    await expect
      .poll(async () => (await context.cookies()).find((c) => c.name === "we2day-theme")?.value)
      .toBe(value);
    await expect(page.locator("html")).toHaveAttribute("data-theme", value);
    const cookie = (await context.cookies()).find((c) => c.name === "we2day-theme");
    expect(cookie).toMatchObject({ path: "/", httpOnly: true });
    // Only the disposable fixture uses HTTP. WebKit does not send Secure cookies
    // over loopback HTTP. Production headers stay verified above; adapt only
    // this test jar's transport and verify real HTTPS separately on deployment.
    if (browser.browserType().name() === "webkit" && cookie) {
      await context.addCookies([{ ...cookie, secure: false, sameSite: "Lax" }]);
    }
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", value);
    expect(await (await context.request.get("/settings")).text()).toContain(
      `data-theme="${value}"`,
    );
    const mascot = page.locator(`.app-header .character-${value}`);
    await expect(mascot).toBeVisible();
    await expect
      .poll(() => mascot.evaluate((el) => (el as HTMLImageElement).naturalWidth))
      .toBeGreaterThan(0);
    await expect(page.getByRole("link", { name: "WE2DAY 홈", exact: true })).toHaveText("WE2DAY");
    const contrasts = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      const luminance = (key: string) => {
        const hex = key.startsWith("#") ? key : css.getPropertyValue(key).trim();
        const pairs = hex.slice(1).match(/../g);
        if (pairs?.length !== 3) throw new Error("Invalid palette color");
        const rgb = pairs
          .map((v) => Number.parseInt(v, 16) / 255)
          .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
      };
      return [
        ["--foreground", "--background"],
        ["--muted", "--surface"],
        ["--foreground", "--panel"],
        ["--accent", "--soft"],
        ["#ffffff", "--accent"],
      ].map(([a, b]) => {
        const x = luminance(a),
          y = luminance(b);
        return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
      });
    });
    expect(Math.min(...contrasts)).toBeGreaterThanOrEqual(4.5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: info.outputPath(`${value}-settings.png`), fullPage: true });
    await page.goto("/preview");
    await expect(page.locator("html")).toHaveAttribute("data-theme", value);
    await expect(page.getByRole("region", { name: "월 달력" })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`${value}-calendar.png`), fullPage: true });
  }
  await page.goto("/settings");
  await page.setViewportSize({ width: 1280, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("themes-desktop.png"), fullPage: true });
  await page.route("**/settings", (route) =>
    route.request().method() === "POST" ? route.abort() : route.continue(),
  );
  await page.getByRole("button", { name: /퐁니 라벤더/ }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("저장하지 못했어요");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "kuku");
  await page.unroute("**/settings");
  await page.getByRole("button", { name: /화이트/ }).click();
  await expect
    .poll(async () => (await context.cookies()).find((c) => c.name === "we2day-theme")?.value)
    .toBe("white");
  await expect(page.locator(".wordmark-character:visible")).toHaveCount(0);
  await context.addCookies([
    { name: "we2day-theme", value: "invalid-character", url: "http://127.0.0.1:3100" },
  ]);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "warm");
});
