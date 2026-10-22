import fs from "node:fs/promises";
import vm from "node:vm";
import { expect, test } from "@playwright/test";

test("device push explicit permission, retry, revoke and logout", async ({
  page,
  context,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    // Both browser engines exercise the same synthetic Push API, without OS permission.
    Object.defineProperty(window, "PushManager", { configurable: true, value: class {} });
    Object.defineProperty(navigator, "standalone", { configurable: true, value: true });
    let sub: object | null = null;
    let permissionRequests = 0;
    const subscription = {
      endpoint: "https://fcm.googleapis.com/fcm/send/synthetic-ui-device",
      toJSON: () => ({ keys: { p256dh: "synthetic", auth: "synthetic" } }),
      unsubscribe: async () => {
        sub = null;
        return true;
      },
    };
    const registration = {
      pushManager: {
        getSubscription: async () => sub,
        subscribe: async () => {
          sub = subscription;
          return subscription;
        },
      },
    };
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: {
        getRegistration: async () => registration,
        register: async () => registration,
        ready: Promise.resolve(registration),
      },
    });
    Object.defineProperty(window, "Notification", {
      configurable: true,
      value: {
        requestPermission: async () => {
          permissionRequests++;
          return "granted";
        },
      },
    });
    Object.defineProperty(window, "fixturePermissionCount", { get: () => permissionRequests });
  });
  let enabled = false,
    fail = true;
  let automatic = false,
    automaticFail = true;
  const actions: string[] = [];
  await page.route("**/api/push/config", (route) =>
    route.fulfill({
      json: {
        configured: true,
        public_key: "B".repeat(87),
        automatic_available: true,
      },
    }),
  );
  await page.route("**/api/push/device", async (route) => {
    const body = route.request().postDataJSON();
    actions.push(body.action);
    if (body.action === "register") enabled = true;
    if (body.action === "remove") enabled = false;
    if (body.action === "automatic_on" && automaticFail) {
      automaticFail = false;
      return route.fulfill({ status: 503, json: { error: "자동 알림 설정 연결 실패" } });
    }
    if (body.action === "automatic_on") automatic = true;
    if (body.action === "automatic_off") automatic = false;
    if (body.action === "test" && fail) {
      fail = false;
      return route.fulfill({ status: 503, json: { error: "합성 연결 실패. 다시 시도해 주세요." } });
    }
    return route.fulfill({
      json: body.action === "test" ? { accepted: true } : { enabled, automatic_enabled: automatic },
    });
  });
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/settings");
  const panel = page.getByRole("region", { name: "이 기기의 알림", exact: true });
  await expect(panel.getByRole("button", { name: "이 기기에서 알림 켜기" })).toBeEnabled();
  expect(
    await page.evaluate(
      () =>
        (window as unknown as Window & { fixturePermissionCount: number }).fixturePermissionCount,
    ),
  ).toBe(0);
  expect(actions).toEqual([]);
  await panel.getByRole("button", { name: "이 기기에서 알림 켜기" }).click();
  await expect(panel.getByText("이 기기를 등록했어요.", { exact: false })).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        (window as unknown as Window & { fixturePermissionCount: number }).fixturePermissionCount,
    ),
  ).toBe(1);
  const toggle = panel.getByRole("switch", { name: "자동 기념일 알림" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(panel.getByRole("status")).toContainText("설정 연결 실패");
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(panel.getByRole("status")).toContainText("켠 이후의 예약 시점");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(panel.getByRole("button", { name: "테스트 알림 보내기" })).toBeEnabled();
  await panel.getByRole("button", { name: "테스트 알림 보내기" }).click();
  await expect(panel.getByRole("status")).toContainText("합성 연결 실패");
  await panel.getByRole("button", { name: "테스트 알림 보내기" }).click();
  await expect(panel.getByRole("status")).toContainText("요청을 수락");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: testInfo.outputPath("device-push-mobile.png") });
  enabled = false;
  await panel.getByRole("button", { name: "알림 상태 다시 확인" }).click();
  await expect(panel.getByText("이 기기에는 알림이 꺼져 있어요.")).toBeVisible();
  await panel.getByRole("button", { name: "이 기기 알림 끄기" }).click();
  await expect(panel.getByRole("status")).toContainText("알림을 껐어요");
  expect(actions).toEqual([
    "register",
    "status",
    "automatic_on",
    "automatic_on",
    "automatic_off",
    "test",
    "test",
    "status",
    "remove",
  ]);
  const denied = await context.request.post("/api/push/device", {
    data: { action: "remove_all" },
    headers: { Origin: "https://unrelated.example" },
  });
  expect(denied.status()).toBe(403);
  await page.goto("/account");
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page).toHaveURL(/\/login\?notice=signed-out$/);
  await page.goto("/account");
  await expect(page).toHaveURL(/\/login/);
});

test("push service worker fixed text and same origin destination", async () => {
  const handlers: Record<string, (event: object) => void> = {};
  const notifications: unknown[] = [],
    destinations: string[] = [];
  const worker = {
    addEventListener: (name: string, callback: (event: object) => void) => {
      handlers[name] = callback;
    },
    location: { origin: "https://synthetic.example" },
    registration: {
      showNotification: async (...args: unknown[]) => {
        notifications.push(args);
      },
    },
    clients: {
      matchAll: async () => [],
      openWindow: async (url: string) => {
        destinations.push(url);
      },
    },
  };
  vm.runInNewContext(await fs.readFile("public/sw.js", "utf8"), { self: worker, URL });
  let completion: Promise<void> = Promise.resolve();
  const waitUntil = (promise: Promise<void>) => {
    completion = promise;
  };
  handlers.push({
    data: { json: () => ({ url: "https://evil.example", title: "private title" }) },
    waitUntil,
  });
  await completion;
  expect(JSON.stringify(notifications)).not.toMatch(/private title|evil.example/);
  handlers.notificationclick({ notification: { close: () => {} }, waitUntil });
  await completion;
  expect(destinations).toEqual(["https://synthetic.example/reminders"]);
});
