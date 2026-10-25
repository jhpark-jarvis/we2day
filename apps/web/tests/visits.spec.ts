import { expect, type Page, test } from "@playwright/test";
import { confirmPlanAndReopen } from "./plan-confirmation";

test.use({ serviceWorkers: "block" });

test("activity cards show latest publication and handle shared state conflicts and retries", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  const partnerContext = await browser.newContext({
    serviceWorkers: "block",
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    const partner = await partnerContext.newPage();
    for (const [view, username] of [
      [page, "member"],
      [partner, "partner"],
    ] as const) {
      await open(view, "/login");
      await view.getByLabel("아이디", { exact: true }).fill(username);
      await view.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await view.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(view).toHaveURL(/\/account$/);
    }
    await open(page, "/couple");
    await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
    await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
    await open(partner, "/couple");
    await partner.getByLabel("받은 초대 코드").fill(code);
    await partner.getByRole("button", { name: "초대 수락하기", exact: true }).click();
    await expect(partner.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await open(page, "/plans");
    await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
    await page.getByLabel("플랜 이름", { exact: true }).fill("합성 방문 플랜");
    const date = await page.getByLabel("플랜 날짜").inputValue();
    await page.getByRole("button", { name: "활동 추가", exact: true }).click();
    await page.getByLabel("활동 1 이름").fill("합성 산책");
    await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: "합성 방문 플랜", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await page.route("**/api/visits?*", (request) =>
      request.fulfill({ status: 503, json: { error: "합성 방문 조회 실패" } }),
    );
    await confirmPlanAndReopen(page);
    await expect(page.getByText("확정됨", { exact: true })).toBeVisible();
    await open(page, `/today?date=${date}`);
    const initialProgress = page.getByRole("region", { name: "데이트 활동", exact: true });
    await expect(initialProgress.getByRole("alert")).toBeVisible();
    await expect(initialProgress.locator(".visit-state").first()).toHaveText("확인 필요");
    await expect(
      initialProgress.getByRole("button", { name: "방문 완료", exact: true }).first(),
    ).toBeDisabled();
    await page.unroute("**/api/visits?*");
    await initialProgress
      .getByRole("button", { name: "최신 방문 진행 불러오기", exact: true })
      .click();
    await expect(initialProgress.locator(".visit-state").first()).toHaveText("예정");
    for (const view of [page, partner]) {
      await open(view, `/today?date=${date}`);
      await expect(
        view
          .getByRole("group", { name: "합성 산책 방문 상태" })
          .getByRole("button", { name: "건너뜀", exact: true }),
      ).toHaveAttribute("aria-pressed", "false");
    }
    const a = page.getByRole("group", { name: "합성 산책 방문 상태" });
    const b = partner.getByRole("group", { name: "합성 산책 방문 상태" });
    await a.getByRole("button", { name: "방문 완료", exact: true }).click();
    await expect(a.getByRole("button", { name: "방문 완료", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await b.getByRole("button", { name: "건너뜀", exact: true }).click();
    await expect(partner.getByRole("alert").filter({ hasText: "다른 곳에서" })).toBeVisible();
    await partner.getByRole("button", { name: "최신 방문 진행 불러오기", exact: true }).click();
    await expect(b.getByRole("button", { name: "방문 완료", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await b.getByRole("button", { name: "건너뜀", exact: true }).click();
    await expect(b.getByRole("button", { name: "건너뜀", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.getByRole("button", { name: "최신 방문 진행 불러오기", exact: true }).click();
    await expect(a.getByRole("button", { name: "건너뜀", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.route("**/api/visits?*", (route) =>
      route.fulfill({ status: 503, json: { error: "합성 방문 상태 연결 실패" } }),
    );
    await a.getByRole("button", { name: "건너뜀", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "같은 변경 다시 시도", exact: true }),
    ).toBeVisible();
    await expect(a.getByRole("button", { name: "건너뜀", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.unroute("**/api/visits?*");
    await page.getByRole("button", { name: "같은 변경 다시 시도", exact: true }).click();
    await expect(a.getByRole("button", { name: "건너뜀", exact: true })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await a.getByRole("button", { name: "방문 완료", exact: true }).click();
    await expect(a.getByRole("button", { name: "방문 완료", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await open(page, "/plans");
    await page.getByRole("button", { name: /합성 방문 플랜/ }).click();
    await page.getByLabel("활동 1 이름").fill("변경한 합성 활동");
    await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }).click();
    await confirmPlanAndReopen(page);
    await expect(page.getByText("확정됨", { exact: true })).toBeVisible();
    await open(page, `/today?date=${date}`);
    await expect(
      page
        .getByRole("group", { name: "변경한 합성 활동 방문 상태" })
        .getByRole("button", { name: "건너뜀", exact: true }),
    ).toHaveAttribute("aria-pressed", "false");
    await b.getByRole("button", { name: "건너뜀", exact: true }).click();
    await expect(
      partner.getByRole("alert").filter({ hasText: "확정 내용이 바뀌었어요" }),
    ).toBeVisible();
    await partner.getByRole("button", { name: "확정 플랜 새로고침", exact: true }).click();
    await expect(
      partner
        .getByRole("group", { name: "변경한 합성 활동 방문 상태" })
        .getByRole("button", { name: "건너뜀", exact: true }),
    ).toHaveAttribute("aria-pressed", "false");
    await expect(
      partner
        .getByRole("group", { name: "변경한 합성 활동 방문 상태" })
        .getByRole("button", { name: "방문 완료", exact: true }),
    ).toBeEnabled();
    await expect(
      partner.getByRole("button", { name: "같은 변경 다시 시도", exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText(/이전 확정안/)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "둘의 방문 진행", exact: true })).toHaveCount(0);
    await expect(page.locator(".activity-card")).toHaveCount(1);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath("visit-progress-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    const plans = await (await page.request.get("/api/plans")).json();
    const id = plans[0].id;
    const denied = await page.request.post(`/api/visits?id=${id}`, {
      headers: { Origin: "https://example.invalid", "Content-Type": "application/json" },
      data: {},
    });
    expect(denied.status()).toBe(403);
    const large = await page.request.post(`/api/visits?id=${id}`, {
      headers: { Origin: "http://127.0.0.1:3100", "Content-Type": "application/json" },
      data: "x".repeat(4097),
    });
    expect(large.status()).toBe(413);
    expect(large.headers()["cache-control"]).toBe("private, no-store");
    expect(errors).toEqual([]);
  } finally {
    if (!page.isClosed()) await page.context().setOffline(false);
    await partnerContext.close();
  }
});

async function open(page: Page, url: string) {
  // Let the owned fixture finish background reads before a hard navigation.
  // WebKit reports canceled document fetches as page errors during immediate goto().
  await page.waitForLoadState("networkidle");
  await page.goto(url);
}
