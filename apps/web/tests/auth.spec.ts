import { expect, test } from "@playwright/test";

const enabled = (process.env.WE2DAY_TEST_AUTH_PROVIDERS ?? "password,google,kakao").split(",");

test("providers follow the server configuration", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Google로 계속하기" })).toHaveCount(
    enabled.includes("google") ? 1 : 0,
  );
  await expect(page.getByRole("button", { name: "카카오로 계속하기" })).toHaveCount(
    enabled.includes("kakao") ? 1 : 0,
  );
  await expect(page.getByRole("form", { name: "아이디 로그인" })).toHaveCount(
    enabled.includes("password") ? 1 : 0,
  );
  if (!enabled.some((s) => ["password", "google", "kakao"].includes(s))) {
    await expect(page.getByText("로그인을 준비 중이에요.", { exact: false })).toBeVisible();
  }
});

test("disabled OAuth callback does not exchange a code", async ({ page, request }) => {
  test.skip(
    enabled.some((method) => ["google", "kakao"].includes(method)),
    "OAuth is enabled",
  );
  const readCount = async () =>
    (await (await request.get("http://127.0.0.1:54329/__auth-events")).json()).pkceExchanges;
  const before = await readCount();
  await page.goto("/auth/callback?code=synthetic-unused-code");
  await expect(page).toHaveURL(/\/login\?error=callback#?$/);
  expect(await readCount()).toBe(before);
});

test("username login validates the API, hides internal addresses and persists", async ({
  page,
  context,
}) => {
  test.skip(!enabled.includes("password"), "Password login is disabled");
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("MEMBER");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByText("이름 미설정", { exact: true })).toBeVisible();
  await expect(page.getByText("member", { exact: true })).toHaveCount(0);
  await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
  expect(await page.content()).not.toContain("login.we2day.invalid");
  await page.reload();
  await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
  const other = await context.newPage();
  await other.goto("/account");
  await expect(other.getByText("계정 확인 완료", { exact: true })).toBeVisible();
  await other.close();
  expect(
    (await context.cookies())
      .filter((c) => c.name.includes("auth-token"))
      .every((c) => c.httpOnly && c.sameSite === "Lax"),
  ).toBe(true);
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("로그아웃했어요.");
  await page.goto("/account");
  await expect(page).toHaveURL(/\/login/);
});

for (const username of ["member", "missing_user", "other@example.invalid"]) {
  test(`invalid username/password is generic: ${username}`, async ({ page }) => {
    test.skip(!enabled.includes("password"), "Password login is disabled");
    await page.goto("/login");
    // Remove HTML validation to exercise the server's validation as well.
    await page
      .getByLabel("아이디", { exact: true })
      .evaluate((el) => el.removeAttribute("pattern"));
    await page.getByLabel("아이디", { exact: true }).fill(username);
    await page.getByLabel("비밀번호", { exact: true }).fill("wrong-fixture-password");
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toHaveText(
      "아이디 또는 비밀번호를 확인해 주세요.",
    );
    expect(await page.content()).not.toContain("wrong-fixture-password");
    expect(await page.content()).not.toContain("synthetic invalid login");
    await page.goto("/account");
    await expect(page).toHaveURL(/\/login/);
  });
}

test("password whitespace is preserved and login fits a narrow viewport", async ({ page }) => {
  test.skip(!enabled.includes("password"), "Password login is disabled");
  await page.setViewportSize({ width: 320, height: 850 });
  await page.goto("/login");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("아이디", { exact: true }).fill("spaced");
  await page.getByLabel("비밀번호", { exact: true }).fill("  fixture-password  ");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
});

for (const [username, expected] of [
  ["throttled", "시도가 많아요"],
  ["offline", "연결하지 못했어요"],
]) {
  test(`password service failure is recoverable: ${username}`, async ({ page }) => {
    test.skip(!enabled.includes("password"), "Password login is disabled");
    await page.goto("/login");
    await page.getByLabel("아이디", { exact: true }).fill(username);
    await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText(expected);
    expect(await page.content()).not.toContain("synthetic private upstream");
    await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeEnabled();
  });
}

for (const provider of ["google", "kakao"]) {
  test(`${provider} PKCE login, server identity and logout`, async ({ page, context }) => {
    test.skip(!enabled.includes(provider), "Provider is disabled in this configuration");
    await page.goto("/login");
    await page
      .getByRole("button", {
        name: provider === "google" ? "Google로 계속하기" : "카카오로 계속하기",
      })
      .click();
    await expect(page).toHaveURL(/\/account#?$/);
    await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
    await expect(
      page.getByText(provider === "google" ? "synthetic@example.invalid" : "이메일 제공 안 함", {
        exact: true,
      }),
    ).toBeVisible();
    const cookies = (await context.cookies()).filter(
      (cookie) =>
        cookie.name.startsWith("sb-") &&
        cookie.name.includes("auth-token") &&
        !cookie.name.includes("code-verifier"),
    );
    expect(cookies.length).toBeGreaterThan(0);
    expect(
      cookies.every(
        (cookie) => cookie.httpOnly && cookie.sameSite === "Lax" && cookie.path === "/",
      ),
    ).toBe(true);
    expect(await page.evaluate(() => document.cookie)).not.toContain("auth-token");
    await page.reload();
    await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
    const tab = await context.newPage();
    await tab.goto("/account");
    await expect(tab.getByText("계정 확인 완료", { exact: true })).toBeVisible();
    await tab.close();
    await page.getByRole("button", { name: "로그아웃", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("로그아웃했어요.");
    await page.goto("/account");
    await expect(page).toHaveURL(/\/login/);
  });
}

test("callback failure removes provider details and ignores external destinations", async ({
  page,
}) => {
  const response = await page.goto(
    "/auth/callback?error=access_denied&error_description=private-detail&next=https://unrelated.invalid",
  );
  await expect(page).toHaveURL(/\/login\?error=callback#?$/);
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "로그인을 완료하지 못했어요",
  );
  expect(await page.content()).not.toContain("private-detail");
  expect(response?.headers()["cache-control"]).toContain("no-store");
  await page.goto("/auth/callback?code=forged&next=https://unrelated.invalid");
  await expect(page).toHaveURL(/\/login\?error=callback#?$/);
  await page.goto("/auth/callback#error=server_error&error_description=synthetic-private-fragment");
  await expect(page).toHaveURL(/\/login\?error=callback#?$/);
  expect(new URL(page.url()).hash).toBe("");
});

test("untrusted session cookies do not authenticate", async ({ page, context }) => {
  await context.addCookies([
    { name: "sb-127-auth-token", value: "base64-invalid", url: "http://127.0.0.1:3100" },
  ]);
  await page.goto("/account");
  await expect(page).toHaveURL(/\/login/);
  await page.setViewportSize({ width: 320, height: 850 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test("forged user data inside a well-formed session is rejected", async ({ page, context }) => {
  const encode = (data: unknown) => Buffer.from(JSON.stringify(data)).toString("base64url");
  const token = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: "11111111-1111-4111-8111-111111111111", exp: Math.floor(Date.now() / 1000) + 3600 })}.${encode("forged")}`;
  const session = {
    access_token: token,
    refresh_token: "forged",
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    token_type: "bearer",
    user: { id: "11111111-1111-4111-8111-111111111111", email: "forged@example.invalid" },
  };
  await context.addCookies([
    { name: "sb-127-auth-token", value: `base64-${encode(session)}`, url: "http://127.0.0.1:3100" },
  ]);
  await page.goto("/account");
  await expect(page).toHaveURL(/\/login/);
  expect(await page.content()).not.toContain("forged@example.invalid");
});

test("expired session refresh persists and renders without JavaScript", async ({
  page,
  context,
  browser,
}) => {
  test.skip(!enabled.includes("google"), "Google is disabled in this configuration");
  await page.goto("/login");
  await page.getByRole("button", { name: "Google로 계속하기" }).click();
  await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
  const cookie = (await context.cookies()).find((item) => item.name === "sb-127-auth-token");
  expect(cookie).toBeDefined();
  if (!cookie) throw new Error("Missing synthetic session cookie");
  const session = JSON.parse(Buffer.from(cookie.value.slice(7), "base64url").toString());
  const previous = session.refresh_token;
  session.expires_at = 1;
  await context.addCookies([
    { ...cookie, value: `base64-${Buffer.from(JSON.stringify(session)).toString("base64url")}` },
  ]);
  await page.reload();
  await expect(page.getByText("계정 확인 완료", { exact: true })).toBeVisible();
  const refreshed = (await context.cookies()).find((item) => item.name === cookie.name);
  expect(refreshed).toBeDefined();
  const updated = JSON.parse(Buffer.from(refreshed?.value.slice(7) || "", "base64url").toString());
  expect(updated.refresh_token).not.toBe(previous);
  const noJS = await browser.newContext({
    javaScriptEnabled: false,
    storageState: await context.storageState(),
  });
  const tab = await noJS.newPage();
  const response = await tab.goto("http://127.0.0.1:3100/account");
  await expect(tab.getByText("계정 확인 완료", { exact: true })).toBeVisible();
  expect(response?.headers()["cache-control"]).toContain("no-store");
  await noJS.close();
});

test("tampering with the provider cannot start an unsupported login", async ({ page }) => {
  const provider = enabled.includes("google") ? "Google로 계속하기" : "카카오로 계속하기";
  test.skip(!enabled.some((s) => ["google", "kakao"].includes(s)), "No enabled provider form");
  await page.goto("/login");
  await page
    .locator('input[name="provider"]')
    .first()
    .evaluate((input) => {
      (input as HTMLInputElement).value = "unsupported";
    });
  await page.getByRole("button", { name: provider }).click();
  await expect(page).toHaveURL(/\/login\?error=unavailable$/);
});
