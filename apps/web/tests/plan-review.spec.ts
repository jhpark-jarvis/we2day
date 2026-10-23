import { expect, test } from "@playwright/test";
import { confirmPlanAndReopen } from "./plan-confirmation";

test("plan review updates on edit and reorder while preserving save and confirm", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("partner");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/plans");
  await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
  const checks = page.getByLabel("플랜 시간·예산 점검", { exact: true });
  await expect(checks).toContainText("활동을 추가하면");
  await page.getByLabel("플랜 이름", { exact: true }).fill("시간·예산 점검 예시");
  await page.getByLabel("플랜 날짜", { exact: true }).fill("2026-11-07");
  await page.getByText("예산 (선택)", { exact: true }).click();
  await page.getByLabel("전체 예산 (원, 선택)").fill("10000");
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 1 이름", { exact: true }).fill("산책");
  await page.getByLabel("활동 1 시간", { exact: true }).fill("14:00");
  await page
    .locator(".activity-editor-disclosure")
    .nth(0)
    .getByText("비용 (선택)", { exact: true })
    .click();
  await page.getByLabel("활동 1 예상 비용 (원, 선택)", { exact: true }).fill("12000");
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 2 이름", { exact: true }).fill("카페");
  await page.getByLabel("활동 2 시간", { exact: true }).fill("13:00");
  await expect(checks).toContainText("보다 일러요");
  await expect(checks).toContainText("비용 미정 1개");
  await expect(checks).toContainText("예산보다 2,000원 많아요");
  await page.screenshot({
    path: testInfo.outputPath("plan-review-warning-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("button", { name: "확정 내용 확인", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
  await confirmPlanAndReopen(page);
  await expect(
    page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }),
  ).toBeVisible();
  await page.locator(".activity-editor-disclosure > summary").nth(1).click();
  await page.getByLabel("활동 2 시간", { exact: true }).fill("14:00");
  await expect(checks).toContainText("과 같아요");
  await page.getByLabel("활동 2 시간", { exact: true }).fill("13:00");
  await page.getByRole("button", { name: "활동 2 위로", exact: true }).click();
  await expect(checks).not.toContainText("보다 일러요");
  await page
    .locator(".activity-editor-disclosure")
    .nth(0)
    .getByText("비용 (선택)", { exact: true })
    .click();
  await page.getByLabel("활동 1 예상 비용 (원, 선택)", { exact: true }).fill("0");
  await page.locator(".activity-editor-disclosure > summary").nth(1).click();
  await page
    .locator(".activity-editor-disclosure")
    .nth(1)
    .getByText("비용 (선택)", { exact: true })
    .click();
  await page.getByLabel("활동 2 예상 비용 (원, 선택)", { exact: true }).fill("8000");
  await expect(checks).toContainText("예상 비용 합계 8,000원");
  await expect(checks).toContainText("전체 예산 이내예요");
  await expect(checks).not.toContainText("비용 미정");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }),
  ).toBeEnabled();
  await page.goto("/plans");
  await page.getByRole("button", { name: /시간·예산 점검 예시/ }).click();
  await expect(checks).toContainText("예상 비용 합계 8,000원");
  await expect(page.getByLabel("활동 1 이름", { exact: true })).toHaveValue("카페");
});
