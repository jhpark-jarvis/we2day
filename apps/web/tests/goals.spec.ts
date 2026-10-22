import { expect, test } from "@playwright/test";

test("shared goal separates steps from completion and restores conflicts and archives", async ({
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
  await page.goto("/goals");
  await page.getByRole("button", { name: "목표 만들기", exact: true }).click();
  await page.getByLabel("목표 이름", { exact: true }).fill("함께 걷기 · 합성 목표");
  await page.getByLabel("희망 날짜 (선택)", { exact: true }).fill("2028-02-29");
  await expect(page.getByRole("group", { name: "단계 진행률", exact: true })).toContainText(
    "단계 미정",
  );
  await page.getByRole("button", { name: "목표 저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "목표를 저장했어요." })).toBeVisible();
  await page.reload();
  await expect(page.getByText("단계 미정", { exact: true })).toBeVisible();
  const open = "목표 열기 · 함께 걷기 · 합성 목표";
  await page.getByRole("button", { name: open, exact: true }).click();
  await expect(page.getByLabel("희망 날짜 (선택)", { exact: true })).toHaveValue("2028-02-29");
  await page.getByRole("button", { name: "단계 추가", exact: true }).click();
  await page.getByLabel("단계 1 이름", { exact: true }).fill("시간 정하기");
  await page.getByRole("button", { name: "단계 추가", exact: true }).click();
  await page.getByLabel("단계 2 이름", { exact: true }).fill("코스 정하기");
  await page.getByLabel("단계 1 완료", { exact: true }).check();
  await expect(page.getByRole("group", { name: "단계 진행률", exact: true })).toContainText(
    "1 / 2단계 · 50%",
  );
  await page.getByLabel("단계 2 완료", { exact: true }).check();
  await expect(page.getByRole("group", { name: "단계 진행률", exact: true })).toContainText(
    "2 / 2단계 · 100%",
  );
  await expect(page.getByLabel("목표 달성 (직접 선택·해제)", { exact: true })).not.toBeChecked();
  await page.getByRole("button", { name: "목표 저장", exact: true }).click();
  await expect(page.getByText("함께 진행 중", { exact: true })).toBeVisible();
  const stale = await page.context().newPage();
  try {
    await stale.goto("/goals");
    await stale.getByRole("button", { name: open, exact: true }).click();
    await page.getByRole("button", { name: open, exact: true }).click();
    await page.getByLabel("목표 달성 (직접 선택·해제)", { exact: true }).check();
    await page.getByRole("button", { name: "목표 저장", exact: true }).click();
    await expect(page.getByText("달성한 목표", { exact: true })).toBeVisible();
    await stale.getByLabel("목표 이름", { exact: true }).fill("충돌 시 보존할 목표 이름");
    await stale.getByRole("button", { name: "목표 저장", exact: true }).click();
    await expect(stale.getByRole("main").getByRole("alert")).toContainText(
      "상대가 목표를 수정했어요",
    );
    await expect(stale.getByLabel("목표 이름", { exact: true })).toHaveValue(
      "충돌 시 보존할 목표 이름",
    );
    await stale
      .getByRole("button", { name: "작성 내용을 버리고 최신본 불러오기", exact: true })
      .click();
    await expect(stale.getByLabel("목표 달성 (직접 선택·해제)", { exact: true })).toBeChecked();
    await stale.getByLabel("단계 1 완료", { exact: true }).uncheck();
    await expect(stale.getByLabel("목표 달성 (직접 선택·해제)", { exact: true })).toBeChecked();
    await stale.getByLabel("목표 달성 (직접 선택·해제)", { exact: true }).uncheck();
    await stale.getByLabel("희망 날짜 (선택)", { exact: true }).fill("");
    await stale.getByLabel("목표 보관 (해제하면 복원)", { exact: true }).check();
    await stale.getByRole("button", { name: "목표 저장", exact: true }).click();
    await expect(stale.getByRole("button", { name: open, exact: true })).toHaveCount(0);
    await stale.getByRole("button", { name: "보관함", exact: true }).click();
    await stale.getByRole("button", { name: open, exact: true }).click();
    await expect(stale.getByLabel("단계 1 이름", { exact: true })).toHaveValue("시간 정하기");
    await expect(stale.getByLabel("희망 날짜 (선택)", { exact: true })).toHaveValue("");
    await stale.getByLabel("목표 보관 (해제하면 복원)", { exact: true }).uncheck();
    await stale.getByRole("button", { name: "목표 저장", exact: true }).click();
    await stale.getByRole("button", { name: "현재", exact: true }).click();
    await expect(stale.getByText("1 / 2단계 · 50%", { exact: true })).toBeVisible();
    await expect(stale.getByText("함께 진행 중", { exact: true })).toBeVisible();
    await stale.screenshot({
      path: testInfo.outputPath("goals-mobile.png"),
      fullPage: true,
      style: "nextjs-portal{display:none}",
    });
    expect(
      await stale.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  } finally {
    await stale.close();
  }
});
