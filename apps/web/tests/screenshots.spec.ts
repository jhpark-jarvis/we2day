import fs from "node:fs/promises";
import path from "node:path";
import { expect, type Locator, type Page, test } from "@playwright/test";

const output = path.resolve("../../assets/screenshots");
const date = "2026-10-24";

async function capture(page: Page, name: string, region?: Locator) {
  await expect(page.locator(".page-loading")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText(/불러오는 중/)).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
  for (const img of await page.locator("main img").all()) {
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0))
      .toBe(true);
  }
  await expect(page.locator("main")).not.toContainText("fixture-password");
  await page.evaluate(() => window.scrollTo(0, 0));
  await (region || page).screenshot({
    path: path.join(output, name),
    animations: "disabled",
    caret: "hide",
  });
}

test("generate public screenshots using disposable synthetic records only", async ({ browser }) => {
  test.setTimeout(360_000);
  await fs.mkdir(output, { recursive: true });
  const context = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 1280, height: 1180 },
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
  });
  const partner = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
  try {
    // Even optional browser integrations must not contact a live service for documentation.
    for (const current of [context, partner]) {
      await current.route("**/*", (route) => {
        const url = new URL(route.request().url());
        return ["127.0.0.1", "localhost"].includes(url.hostname) ? route.continue() : route.abort();
      });
    }
    const page = await context.newPage();
    const other = await partner.newPage();
    for (const [current, username] of [
      [page, "member"],
      [other, "partner"],
    ] as const) {
      await current.goto("/login");
      await current.getByLabel("아이디", { exact: true }).fill(username);
      await current.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await current.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(current).toHaveURL(/\/account$/, { timeout: 30_000 });
    }
    await page.goto("/couple");
    await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
    await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
    await other.goto("/couple");
    await other.getByLabel("받은 초대 코드").fill(code);
    await other.getByRole("button", { name: "초대 수락하기", exact: true }).click();
    await expect(other.getByRole("status")).toContainText("두 사람이 연결되었어요");

    await page.goto("/anniversaries");
    await page.getByRole("button", { name: "기념일 추가하기", exact: true }).click();
    await page.getByLabel("기념일 이름").fill("우리의 시작");
    await page.getByLabel("기준 날짜").fill("2025-10-24");
    await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
    await expect(page.getByRole("heading", { name: "우리의 시작", exact: true })).toBeVisible();

    for (const [when, title, time, place] of [
      [date, "느긋한 오후 산책", "14:00", "강변 산책길"],
      [date, "따뜻한 저녁 약속", "18:30", "동네 작은 식당"],
      ["2026-10-10", "함께 걸었던 가을 오후", "15:00", "산책길"],
    ]) {
      await page.goto(`/?date=${when}`);
      await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
      await page.getByLabel("약속 이름").fill(title);
      await page.getByLabel("시간 (선택)").fill(time);
      await page.getByLabel("만날 장소 (선택)").fill(place);
      await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
      await expect(page.getByRole("button", { name: new RegExp(title) })).toBeVisible();
    }
    await page.getByLabel("이 날 만났어요", { exact: true }).check();
    await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "만남 기록을 저장했어요" }),
    ).toBeVisible();
    await page.goto(`/?date=${date}`);
    await expect(page.getByRole("button", { name: /느긋한 오후 산책/ })).toBeVisible();
    await capture(page, "calendar-desktop.png");
    await page.setViewportSize({ width: 390, height: 1180 });
    await capture(page, "calendar-mobile.png");
    await context.addCookies([
      { name: "we2day-theme", value: "white", url: "http://127.0.0.1:3100" },
    ]);
    await page.reload();
    await expect(page.getByRole("button", { name: /느긋한 오후 산책/ })).toBeVisible();
    await capture(page, "white-mobile.png");
    await context.addCookies([
      { name: "we2day-theme", value: "warm", url: "http://127.0.0.1:3100" },
    ]);

    await page.setViewportSize({ width: 1280, height: 980 });
    await page.goto("/plans");
    await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
    await page.getByLabel("플랜 이름").fill("가을, 느긋한 하루");
    await page.getByLabel("플랜 날짜").fill(date);
    for (const [index, title, time, place] of [
      [1, "함께 브런치", "12:00", "동네 브런치 가게"],
      [2, "강변 산책", "14:00", "강변 산책길"],
      [3, "카페에서 쉬어가기", "16:00", "창가 있는 카페"],
    ] as const) {
      await page.getByRole("button", { name: "활동 추가", exact: true }).click();
      await page.getByLabel(`활동 ${index} 이름`).fill(title);
      await page.getByLabel(`활동 ${index} 시간`).fill(time);
      await page.getByLabel(`활동 ${index} 장소`).fill(place);
    }
    await page.getByLabel("준비물 (한 줄에 하나, 최대 30개)").fill("물 한 병\n가벼운 겉옷");
    await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }),
    ).toBeVisible();
    await capture(page, "plan-desktop.png", page.getByRole("region", { name: "플랜 확정 내용" }));

    await page.goto("/memories?date=2026-10-10");
    await expect(page.getByLabel("사진 선택")).toBeEnabled({ timeout: 30_000 });
    await page.getByLabel("사진 선택").setInputFiles(path.resolve("public/demo/autumn.jpg"));
    await expect(page.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible({
      timeout: 30_000,
    });
    await page.getByLabel("이 사진의 한마디").fill("함께 걸었던 가을 오후");
    await page.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
    await expect(
      page.getByText("둘의 사진으로 저장했어요. 아래 날짜별 앨범에서 확인할 수 있어요."),
    ).toBeVisible();
    await page.setViewportSize({ width: 390, height: 1100 });
    await page.goto("/memories/month?month=2026-10");
    await expect(page.getByRole("heading", { name: "월간 추억", exact: true })).toBeVisible();
    await expect(page.locator(".monthly-photo")).toHaveCount(1);
    await capture(page, "memories-mobile.png");
  } finally {
    await context.close();
    await partner.close();
  }
});
