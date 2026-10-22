import { expect, test } from "@playwright/test";

test("anniversary notification preview is scoped and refreshes after edits", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/reminders");
  await page.getByText("기념일 알림 시점 미리보기", { exact: true }).click();
  const panel = page.locator("details").filter({ hasText: "기념일 알림 시점 미리보기" });
  async function openPreview() {
    if ((await panel.getAttribute("open")) === null)
      await page.getByText("기념일 알림 시점 미리보기", { exact: true }).click();
  }
  await expect(panel.getByRole("alert")).toContainText("로그인이 필요해요");
  await panel.getByRole("link", { name: "로그인하기", exact: true }).click();
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/anniversaries");
  await page.getByRole("button", { name: "기념일 추가하기", exact: true }).click();
  await page.getByLabel("종류").selectOption("custom");
  await page.getByLabel("기념일 이름").fill("미리보기 검증용 기념일");
  const future = new Date(Date.now() + (9 + 8 * 24) * 3600 * 1000).toISOString().slice(0, 10);
  await page.getByLabel("기준 날짜").fill(future);
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "미리보기 검증용 기념일", exact: true }),
  ).toBeVisible();
  await page.goto("/reminders?days=7");
  await openPreview();
  await expect(panel.getByText("7일 전", { exact: true })).toBeVisible();
  await expect(panel.getByText("기념일 7일 전·1일 전·당일", { exact: false })).toBeVisible();
  await expect(
    panel.getByText("알림이 예약되거나 발송되지는 않아요", { exact: false }),
  ).toBeVisible();
  await expect(panel.getByLabel("기념일 알림 미리보기").getByRole("listitem")).toHaveCount(2);
  await page.getByRole("link", { name: "30일 안", exact: true }).click();
  await openPreview();
  await expect(panel.getByLabel("기념일 알림 미리보기").getByRole("listitem")).toHaveCount(3);
  await page.screenshot({
    path: testInfo.outputPath("notification-preview-mobile.png"),
    fullPage: true,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.reload();
  await openPreview();
  await expect(panel.getByLabel("기념일 알림 미리보기").getByRole("listitem")).toHaveCount(3);
  await page.goto("/anniversaries");
  await page.getByRole("button", { name: "미리보기 검증용 기념일 수정", exact: true }).click();
  const distant = new Date(Date.now() + (9 + 100 * 24) * 3600 * 1000).toISOString().slice(0, 10);
  await page.getByLabel("기준 날짜").fill(distant);
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "미리보기 검증용 기념일", exact: true }),
  ).toBeVisible();
  await page.goto("/reminders?days=30");
  await openPreview();
  await expect(panel.getByText("선택한 기간에 남아 있는 알림 시점이 없어요.")).toBeVisible();
});
