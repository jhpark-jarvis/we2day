import { expect, type Page, test } from "@playwright/test";

test("personal schedules share read access, restrict edits and keep independent day markers", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(180_000);
  const context = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 393, height: 852 },
    serviceWorkers: "block",
  });
  const open = async (view: Page, path: string) => {
    await view.waitForLoadState("networkidle");
    await view.goto(path);
  };
  try {
    const partner = await context.newPage();
    for (const [view, id, name] of [
      [page, "member", "예시 작성자"],
      [partner, "partner", "예시 상대방"],
    ] as const) {
      await open(view, "/login");
      await view.getByLabel("아이디", { exact: true }).fill(id);
      await view.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await view.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(view).toHaveURL(/\/account$/);
      await view.getByLabel("사용자 이름", { exact: true }).fill(name);
      await view.getByRole("button", { name: "이름 저장", exact: true }).click();
      await expect(view.locator(".detail-list")).toContainText(name);
    }
    await open(page, "/couple");
    await page.getByRole("button", { name: "새 공간 만들기" }).click();
    await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
    await open(partner, "/couple");
    await partner.getByLabel("받은 초대 코드").fill(code);
    await partner.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(partner.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await open(page, "/");
    await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
    await page.getByRole("radio", { name: "개인 일정", exact: true }).check();
    await expect(page.getByRole("button", { name: "장소 검색", exact: true })).toHaveCount(0);
    await expect(page.getByLabel("만날 장소 (선택)")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "코스 등록", exact: true })).toHaveCount(0);
    await page.getByLabel("일정 이름", { exact: true }).fill("개인 일정 합성 예시");
    const date = await page.getByLabel("날짜", { exact: true }).inputValue();
    await page.getByRole("button", { name: "일정 저장", exact: true }).click();
    await expect(page.getByRole("button", { name: /개인 일정 합성 예시/ })).toBeVisible();
    const day = page.locator(`.calendar-day[data-date="${date}"]`);
    await expect(day).toHaveClass(/has-personal/);
    expect(
      await day.locator(".day-label").evaluate((el) => getComputedStyle(el).textDecorationLine),
    ).toBe("underline");
    await expect(day.locator(".day-dot.has-event")).toHaveCount(0);
    await page.getByLabel("이 날 만났어요", { exact: true }).check();
    await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(day.locator(".day-check")).toBeVisible();
    await expect(day).toHaveAttribute("aria-label", /만난 날.*개인 일정 있음/);
    await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
    await page.getByLabel("약속 이름", { exact: true }).fill("공동 약속 합성 예시");
    await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
    await expect(day.locator(".day-dot.has-event")).toHaveCount(1);
    await expect(day.locator(".day-check")).toBeVisible();
    await expect(day).toHaveClass(/has-personal/);
    for (const width of [320, 393, 1280]) {
      await page.setViewportSize({ width, height: 852 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
    await page.setViewportSize({ width: 393, height: 852 });
    await page.screenshot({
      path: info.outputPath("personal-calendar-mobile.png"),
      fullPage: true,
    });
    await open(partner, `/?date=${date}`);
    await partner.getByRole("button", { name: /개인 일정 합성 예시/ }).click();
    await expect(partner.locator(".detail-list")).toContainText("예시 작성자");
    await expect(partner.getByRole("button", { name: "개인 일정 수정", exact: true })).toHaveCount(
      0,
    );
    await expect(partner.getByRole("button", { name: "개인 일정 삭제", exact: true })).toHaveCount(
      0,
    );
    await expect(partner.getByText("장소", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: /개인 일정 합성 예시/ }).click();
    await page.getByRole("button", { name: "개인 일정 수정", exact: true }).click();
    await page.getByLabel("일정 이름", { exact: true }).fill("수정한 개인 일정");
    await page.getByRole("button", { name: "일정 저장", exact: true }).click();
    await expect(page.getByRole("button", { name: /수정한 개인 일정/ })).toBeVisible();
    await page.getByRole("button", { name: /수정한 개인 일정/ }).click();
    await page.getByRole("button", { name: "개인 일정 삭제", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "개인 일정 삭제 확인", exact: true });
    await dialog.getByRole("button", { name: "삭제 취소", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "수정한 개인 일정", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "개인 일정 삭제", exact: true }).click();
    await dialog.getByRole("button", { name: "삭제", exact: true }).click();
    await expect(page.getByRole("button", { name: /수정한 개인 일정/ })).toHaveCount(0);
    await expect(day).not.toHaveClass(/has-personal/);
    await expect(day.locator(".day-check")).toBeVisible();
    await expect(day.locator(".day-dot.has-event")).toHaveCount(1);
  } finally {
    await context.close();
  }
});
