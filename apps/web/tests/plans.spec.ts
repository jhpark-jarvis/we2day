import { expect, test } from "@playwright/test";
import { confirmPlanAndReopen } from "./plan-confirmation";

test("plan confirmation preserve calendar and actual records", async ({ browser }, testInfo) => {
  test.setTimeout(180_000);
  const first = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  const second = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  try {
    const a = await first.newPage(),
      b = await second.newPage();
    a.setDefaultTimeout(15_000);
    b.setDefaultTimeout(15_000);
    for (const [page, username] of [
      [a, "member"],
      [b, "partner"],
    ] as const) {
      await page.goto("/login");
      await page.getByLabel("아이디", { exact: true }).fill(username);
      await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(page).toHaveURL(/\/account$/);
    }
    await a.goto("/couple");
    await a.getByRole("button", { name: "새 공간 만들기" }).click();
    await a.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await a.getByLabel("상대에게 전달할 코드").inputValue();
    await b.goto("/couple");
    await b.getByLabel("받은 초대 코드").fill(code);
    await b.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(b.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await a.goto("/");
    await expect(a.getByRole("heading", { name: "함께한 동선" })).toHaveCount(0);
    await a.goto("/plans");
    await a.getByRole("button", { name: "플랜 만들기" }).click();
    await a.getByLabel("플랜 이름", { exact: true }).fill("함께하는 주말");
    const date = await a.getByLabel("플랜 날짜").inputValue();
    await a.getByRole("button", { name: "활동 추가", exact: true }).click();
    await a.getByLabel("활동 1 이름").fill("산책");
    await a.getByLabel("활동 1 시간").fill("14:00");
    await a.getByLabel("활동 1 장소", { exact: true }).fill("직접 정한 공원");
    await a.locator("#activity-0-map-url").fill("https://naver.me/Example12");
    await a.getByRole("button", { name: "활동 추가", exact: true }).click();
    await a.getByLabel("활동 2 이름").fill("카페");
    await a.getByRole("button", { name: "활동 2 위로", exact: true }).click();
    await expect(a.getByLabel("활동 1 이름")).toHaveValue("카페");
    await a.getByRole("button", { name: "활동 1 아래로", exact: true }).click();
    await a.getByText("준비물 (선택)", { exact: true }).click();
    await a.getByLabel("준비물 (한 줄에 하나, 최대 30개)").fill("물\n우산");
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByRole("heading", { name: "함께하는 주말", exact: true })).toBeVisible();
    const before = await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect(await before.json()).toEqual([]);
    await b.goto("/plans");
    await b.getByRole("button", { name: /함께하는 주말/ }).click();
    await expect(b.getByLabel("활동 1 이름")).toHaveValue("산책");
    await a.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await confirmPlanAndReopen(a);
    await expect(a.getByText("확정됨", { exact: true })).toBeVisible();
    const after = await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    const events = await after.json();
    expect(events).toHaveLength(1);
    expect(events[0].time).toBe("14:00:00");
    const course = await first.newPage();
    await course.goto(`/today?date=${date}`);
    await expect(course.getByRole("link", { name: "네이버 지도", exact: true })).toHaveAttribute(
      "href",
      "https://naver.me/Example12",
    );
    await course.screenshot({
      path: testInfo.outputPath("shared-map-course-mobile.png"),
      fullPage: true,
    });
    await course.close();
    await expect(a.locator("#activity-0-map-url")).toHaveValue("https://naver.me/Example12");
    await b.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await b.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
    await expect(
      b.getByRole("alert").filter({ hasText: "플랜 또는 연결된 약속이 바뀌었어요" }),
    ).toBeVisible();
    await expect(b).toHaveURL(/\/plans$/);
    await expect(b.getByLabel("플랜 이름", { exact: true })).toHaveValue("함께하는 주말");
    // A rejected confirmation preserves the draft and freezes editing until an explicit reload.
    await expect(b.getByLabel("플랜 이름", { exact: true })).toBeDisabled();
    await b.getByRole("button", { name: "작성 내용을 버리고 최신 플랜 불러오기" }).click();
    await expect(b.getByLabel("플랜 이름", { exact: true })).toHaveValue("함께하는 주말");
    await b.getByLabel("플랜 이름", { exact: true }).fill("함께하는 주말 변경");
    await b.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(b.getByText("변경안 · 다시 확정 필요", { exact: true })).toBeVisible();
    const unchanged = await second.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect((await unchanged.json())[0].title).toBe("함께하는 주말");
    await b.getByRole("button", { name: "변경 내용 확인·재확정" }).click();
    await b.screenshot({ path: testInfo.outputPath("plan-mobile.png"), fullPage: true });
    await confirmPlanAndReopen(b);
    await expect(b.getByText("확정됨", { exact: true })).toBeVisible();
    await b.getByRole("button", { name: "플랜 보관", exact: true }).click();
    await expect(b.getByRole("status")).toContainText("플랜을 보관했어요");
    await b.getByRole("button", { name: "보관함" }).click();
    await b.getByRole("button", { name: /함께하는 주말 변경/ }).click();
    await b.getByRole("button", { name: "플랜 복원", exact: true }).click();
    await expect(b.getByRole("status")).toContainText("플랜을 복원했어요");
    const final = await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect(await final.json()).toHaveLength(1);
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
      true,
    );
    await b.goto("/");
    await expect(b.getByRole("button", { name: "동선 기록 열기" })).toHaveCount(0);
  } finally {
    await first.close();
    await second.close();
  }
});
