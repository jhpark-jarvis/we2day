import { expect, test } from "@playwright/test";

test("shared preparation list saves, checks, preserves conflicts and restores", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/checklists");
  await page.getByRole("button", { name: "목록 만들기", exact: true }).click();
  await page.getByLabel("목록 이름", { exact: true }).fill("산책 준비 · 합성 예시");
  await page.getByLabel("목록 메모", { exact: true }).fill("함께 챙길 준비물");
  await page.getByRole("button", { name: "항목 추가", exact: true }).click();
  await page.getByLabel("항목 1 이름", { exact: true }).fill("물");
  await page.getByLabel("항목 1 수량·참고", { exact: true }).fill("두 병");
  await page.getByRole("button", { name: "목록 저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "목록을 저장했어요." })).toBeVisible();
  await page.reload();
  const open = "목록 열기 · 산책 준비 · 합성 예시";
  await page.getByRole("button", { name: open, exact: true }).click();
  await expect(page.getByLabel("항목 1 수량·참고", { exact: true })).toHaveValue("두 병");
  const stale = await page.context().newPage();
  try {
    await stale.goto("/checklists");
    await stale.getByRole("button", { name: open, exact: true }).click();
    await page.getByLabel("항목 1 준비 완료", { exact: true }).check();
    await page.getByRole("button", { name: "목록 저장", exact: true }).click();
    await expect(page.getByText("1 / 1개 준비", { exact: true })).toBeVisible();
    await stale.getByLabel("목록 메모", { exact: true }).fill("충돌해도 남아야 하는 작성 내용");
    await stale.getByRole("button", { name: "목록 저장", exact: true }).click();
    await expect(stale.getByRole("main").getByRole("alert")).toContainText(
      "상대가 목록을 수정했어요",
    );
    await expect(stale.getByLabel("목록 메모", { exact: true })).toHaveValue(
      "충돌해도 남아야 하는 작성 내용",
    );
    await stale
      .getByRole("button", { name: "작성 내용을 버리고 최신본 불러오기", exact: true })
      .click();
    await expect(stale.getByLabel("항목 1 준비 완료", { exact: true })).toBeChecked();
    await stale.getByLabel("항목 1 준비 완료", { exact: true }).uncheck();
    await stale.getByLabel("목록 보관 (해제하면 복원)", { exact: true }).check();
    await stale.getByRole("button", { name: "목록 저장", exact: true }).click();
    await expect(stale.getByRole("button", { name: open, exact: true })).toHaveCount(0);
    const toggle = stale.getByRole("group", { name: "목록 구분", exact: true });
    await expect(toggle.getByRole("button", { name: "현재", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await toggle.getByRole("button", { name: "보관함", exact: true }).click();
    await expect(toggle.getByRole("button", { name: "보관함", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const refresh = stale.getByRole("button", { name: "목록 새로고침", exact: true });
    await expect(refresh).toHaveText("");
    const response = stale.waitForResponse(
      (r) => r.url().includes("/api/checklists?archived=true") && r.request().method() === "GET",
    );
    await refresh.click();
    expect((await response).ok()).toBe(true);
    await expect(refresh).toBeEnabled();
    await expect(toggle.getByRole("button", { name: "보관함", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await stale.getByRole("button", { name: open, exact: true }).click();
    await expect(stale.getByLabel("항목 1 준비 완료", { exact: true })).not.toBeChecked();
    await stale.getByLabel("목록 보관 (해제하면 복원)", { exact: true }).uncheck();
    await stale.getByRole("button", { name: "목록 저장", exact: true }).click();
    await toggle.getByRole("button", { name: "현재", exact: true }).click();
    await expect(toggle.getByRole("button", { name: "보관함", exact: true })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(stale.getByText("0 / 1개 준비", { exact: true })).toBeVisible();
    await stale.screenshot({ path: testInfo.outputPath("checklist-mobile.png"), fullPage: true });
    expect(
      await stale.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  } finally {
    await stale.close();
  }
});
