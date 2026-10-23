import { expect, test } from "@playwright/test";

test("question prompt search preserves answer privacy and recovers from network failure", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
  const partnerContext = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    const partner = await partnerContext.newPage();
    for (const [view, username] of [
      [page, "member"],
      [partner, "partner"],
    ] as const) {
      await view.goto("/login");
      await view.getByLabel("아이디", { exact: true }).fill(username);
      await view.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await view.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(view).toHaveURL(/\/account$/);
    }
    await page.goto("/couple");
    await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
    await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
    await partner.goto("/couple");
    await partner.getByLabel("받은 초대 코드").fill(code);
    await partner.getByRole("button", { name: "초대 수락하기", exact: true }).click();
    await expect(partner.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await page.goto("/questions?date=2026-10-24");
    await page
      .locator("summary")
      .filter({ hasText: /^질문 추가$/ })
      .click();
    await page.getByLabel("함께 나눌 질문").fill("함께 하고 싶은 일 100% · 합성 질문");
    await page.getByRole("button", { name: "질문 추가", exact: true }).click();
    await expect(page).toHaveURL(/\/questions\/[a-f0-9-]+$/);
    const questionUrl = page.url();
    await page.getByLabel("답변 내용", { exact: true }).fill("답변전용 비공개검색어");
    await page.getByRole("button", { name: "개인 답변 저장", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "개인 답변으로 저장했어요." }),
    ).toBeVisible();
    for (const view of [page, partner]) {
      await view.goto("/questions");
      await view.getByRole("link", { name: "날짜·문구로 질문 찾기", exact: true }).click();
      await view.getByLabel("시작 날짜", { exact: true }).fill("2026-10-01");
      await view.getByLabel("마지막 날짜", { exact: true }).fill("2026-10-31");
      await view.getByLabel("질문 문구 검색어 (선택)").fill("100%");
      await view.getByRole("button", { name: "질문 검색", exact: true }).click();
      await expect(view.getByRole("region", { name: "질문 검색 결과" })).toContainText(
        "함께 하고 싶은 일 100% · 합성 질문",
      );
      expect(view.url()).toBe("http://127.0.0.1:3100/questions/search");
      await expect(view.getByText("답변전용 비공개검색어", { exact: true })).toHaveCount(0);
    }
    await partner.getByLabel("질문 문구 검색어 (선택)").fill("답변전용");
    await partner.getByRole("button", { name: "질문 검색", exact: true }).click();
    await expect(partner.getByText("이 조건에 맞는 질문이 없어요.", { exact: true })).toBeVisible();
    await page.getByLabel("질문 문구 검색어 (선택)").fill("연결 실패 중 입력");
    await page.context().setOffline(true);
    await page.getByRole("button", { name: "질문 검색", exact: true }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: "입력한 조건은 유지돼요" }),
    ).toBeVisible();
    await expect(page.getByLabel("질문 문구 검색어 (선택)")).toHaveValue("연결 실패 중 입력");
    await expect(page.getByRole("region", { name: "질문 검색 결과" })).toContainText(
      "이전에 검색한 결과",
    );
    await page.context().setOffline(false);
    await page.getByLabel("질문 문구 검색어 (선택)").fill("%");
    await page.getByRole("button", { name: "질문 검색", exact: true }).click();
    await expect(page.getByRole("region", { name: "질문 검색 결과" })).toContainText("합성 질문");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath("question-search-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    await page.getByRole("link", { name: /답변 쓰기·보기/ }).click();
    await expect(page).toHaveURL(questionUrl);
    await expect(page.getByLabel("답변 내용", { exact: true })).toHaveValue(
      "답변전용 비공개검색어",
    );
    await partner.goto(questionUrl);
    await expect(partner.getByText("답변전용 비공개검색어", { exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await page.context().setOffline(false);
    await partnerContext.close();
  }
});
