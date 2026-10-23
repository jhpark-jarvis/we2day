import { expect, test } from "@playwright/test";

test("record discovery respects sharing and next appointment preserves date-only semantics", async ({
  browser,
}, testInfo) => {
  test.setTimeout(240_000);
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
    for (const [page, name] of [
      [a, "member"],
      [b, "partner"],
    ] as const) {
      await page.goto("/login");
      await page.getByLabel("아이디", { exact: true }).fill(name);
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
    await a.goto("/wishlist");
    await a.getByRole("button", { name: "위시 추가", exact: true }).click();
    await a.getByLabel("위시 이름").fill("우리의 작은 산책");
    await a.getByLabel("위시 메모").fill("물과 우산 준비");
    await a.getByRole("button", { name: "위시 저장", exact: true }).click();
    await expect(a.getByRole("heading", { name: "우리의 작은 산책", exact: true })).toBeVisible();
    await b.goto("/wishlist");
    await expect(b.getByRole("heading", { name: "우리의 작은 산책", exact: true })).toBeVisible();
    await a.getByRole("link", { name: "이 위시로 플랜 초안 만들기" }).click();
    await expect(a.getByLabel("활동 1 장소", { exact: true })).toHaveValue("우리의 작은 산책");
    await expect(a.getByLabel("활동 1 메모")).toHaveValue("물과 우산 준비");
    const date = await a.getByLabel("플랜 날짜", { exact: true }).inputValue();
    await a.getByLabel("활동 1 시간").fill("00:00");
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByText("초안", { exact: true })).toBeVisible();
    const list = await (await first.request.get("/api/plans")).json();
    expect(list).toHaveLength(1);
    const id = list[0].id;
    await b.goto(`/today?date=${date}`);
    await expect(b.getByText("이 날짜에 확정한 플랜이 없어요.")).toBeVisible();
    await a.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await a.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
    await expect(a.getByText("확정됨", { exact: true })).toBeVisible();

    await a.goto(`/plans/${id}/report`);
    await a.getByLabel("오늘의 한 줄").fill("합성 검색 비공개 원문 %_");
    await a.getByRole("button", { name: "개인 초안 저장", exact: true }).click();
    await expect(a.getByRole("status")).toContainText("나만 보는 초안");
    await b.goto("/memories/records");
    await b
      .getByRole("group", { name: "기록 종류", exact: true })
      .getByRole("button", { name: "회고", exact: true })
      .click();
    await b.getByLabel("기록 검색어").fill("%_");
    await b.getByRole("button", { name: "기록 검색", exact: true }).click();
    const results = b.getByRole("region", { name: "기록 검색 결과" });
    await expect(results).toContainText("조건에 맞는 기록이 없어요");
    await a.getByRole("button", { name: "이 내용을 상대와 공유", exact: true }).click();
    await expect(a.getByRole("status")).toContainText("상대와 공유");
    await b.getByRole("button", { name: "기록 검색", exact: true }).click();
    await expect(results).toContainText("합성 검색 비공개 원문 %_");
    await expect(results).toContainText("상대가 공유한 회고");
    await b.screenshot({
      path: testInfo.outputPath("record-search-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await a.getByRole("button", { name: "공유 철회하고 개인 저장", exact: true }).click();
    await expect(a.getByRole("status")).toContainText("더 이상 표시되지 않아요");
    await b.getByRole("button", { name: "기록 검색", exact: true }).click();
    await expect(results).not.toContainText("합성 검색 비공개 원문 %_");
    await b
      .getByRole("group", { name: "기록 종류", exact: true })
      .getByRole("button", { name: "플랜", exact: true })
      .click();
    await b.getByLabel("기록 검색어").fill("우리의 작은 산책");
    await b.getByRole("button", { name: "기록 검색", exact: true }).click();
    await expect(results).toContainText("확정됨");
    await second.setOffline(true);
    await b.getByRole("button", { name: "기록 검색", exact: true }).click();
    await expect(b.getByRole("alert").filter({ hasText: "조건과 이전 결과" })).toBeVisible();
    await expect(b.getByLabel("기록 검색어")).toHaveValue("우리의 작은 산책");
    await expect(results).toContainText("우리의 작은 산책");
    await second.setOffline(false);
    await results.getByRole("link", { name: "원본 열기 · 우리의 작은 산책", exact: true }).click();
    await expect(b.getByLabel("플랜 이름", { exact: true })).toHaveValue("우리의 작은 산책");
    // A future date-only calendar entry must not receive an invented local time.
    await a.goto("/");
    await a.getByRole("button", { name: "약속 추가하기", exact: true }).click();
    const future = new Date(`${date}T12:00:00Z`);
    future.setUTCDate(future.getUTCDate() + 2);
    const futureDate = future.toISOString().slice(0, 10);
    await a.getByLabel("약속 이름").fill("합성 다음 약속");
    await a.getByLabel("날짜", { exact: true }).fill(futureDate);
    await a.getByRole("button", { name: "약속 저장하기", exact: true }).click();
    await a.goto("/timezones");
    await a.getByText("약속 시간 미리보기", { exact: true }).click();
    const next = a.getByRole("complementary", { name: "다음 약속", exact: true });
    await expect(next).toContainText("합성 다음 약속");
    await expect(next).toContainText("D-2 · 시간 미정");
    await expect(next.getByLabel("현지 시각 보조")).toHaveCount(0);
    await a.screenshot({
      path: testInfo.outputPath("next-appointment-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    await next.getByRole("link", { name: "달력에서 약속 보기", exact: true }).click();
    await expect(a).toHaveURL(new RegExp(`date=${futureDate}`), { timeout: 20_000 });
    await expect(a.getByRole("button", { name: /합성 다음 약속/ })).toBeVisible();
  } finally {
    await first.close();
    await second.close();
  }
});
