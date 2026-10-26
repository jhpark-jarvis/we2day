import { expect, type Page, test } from "@playwright/test";

async function open(page: Page, path: string) {
  await page.waitForLoadState("networkidle");
  await page.goto(path);
}

test("browser traversal follows inline screens rather than the previously visited section", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await open(page, "/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await open(page, "/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await open(page, "/");
  await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
  await page.getByLabel("약속 이름", { exact: true }).fill("History fixture appointment");
  await page.getByLabel("날짜", { exact: true }).fill("2026-10-24");
  await page.getByLabel("메모 (선택)", { exact: true }).fill("Synthetic private note");
  await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
  await expect(page.locator(".month-calendar")).toBeVisible();
  await open(page, "/roulette");
  await page
    .getByRole("navigation", { name: "주요 메뉴", exact: true })
    .getByRole("link", { name: "일정", exact: true })
    .click();
  await expect(page.locator(".month-calendar")).toBeVisible();
  await page.locator('[data-date="2026-10-24"]').click();
  await page.getByRole("button", { name: /History fixture appointment/ }).click();
  await expect(page.getByRole("heading", { name: "약속 정보", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "약속 수정하기", exact: true }).click();
  await page.getByLabel("약속 이름", { exact: true }).fill("Unsaved private text");
  const nav = await page.evaluate(() => JSON.stringify(history.state.we2dayView));
  expect(nav).not.toContain("Synthetic private note");
  expect(nav).not.toContain("Unsaved private text");
  expect(nav).not.toContain("History fixture appointment");
  await page.goBack();
  await expect(page.getByRole("heading", { name: "약속 정보", exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByLabel("약속 이름", { exact: true })).toHaveValue(
    "History fixture appointment",
  );
  await page.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("heading", { name: "약속 정보", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "약속 정보", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.locator('.calendar-day[aria-pressed="true"]')).toHaveAttribute(
    "data-date",
    "2026-10-24",
  );
  await expect(page.locator(".month-calendar")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/roulette$/);
  await page.goForward();
  await expect(page.locator(".month-calendar")).toBeVisible();

  for (const [path, create, label] of [
    ["/checklists", "목록 만들기", "목록 이름"],
    ["/goals", "목표 만들기", "목표 이름"],
    ["/wishlist", "위시 추가", "위시 이름"],
    ["/anniversaries", "기념일 추가하기", "기념일 이름"],
    ["/plans", "플랜 만들기", "플랜 이름"],
  ]) {
    await open(page, path);
    await page.getByRole("button", { name: create, exact: true }).click();
    const input = page.getByLabel(label, { exact: true });
    await expect(input).toBeVisible();
    await input.fill("Unsaved fixture");
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(input).toHaveCount(0);
    await page.goForward();
    await expect(input).toBeVisible();
    await page.reload();
    await expect(input).toBeVisible();
    await page.goBack();
    await expect(input).toHaveCount(0);
  }
  await open(page, "/checklists");
  await page.getByRole("button", { name: "목록 만들기", exact: true }).click();
  await page.getByLabel("목록 이름", { exact: true }).fill("Saved history fixture");
  await page.getByRole("button", { name: "목록 저장", exact: true }).click();
  await page
    .getByRole("button", { name: "목록 열기 · Saved history fixture", exact: true })
    .click();
  await page.reload();
  await expect(page.getByLabel("목록 이름", { exact: true })).toHaveValue("Saved history fixture");
  await page.goBack();
  await expect(page.getByLabel("목록 이름", { exact: true })).toHaveCount(0);
  await page.evaluate(() => {
    history.replaceState(
      {
        ...history.state,
        we2dayView: {
          scope: "checklists",
          url: location.pathname + location.search,
          value: { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", mode: "edit" },
        },
      },
      "",
    );
    dispatchEvent(new PopStateEvent("popstate", { state: history.state }));
  });
  await expect(page.locator("p[role=alert]")).toContainText("항목을 불러오지 못했어요");
  await expect(page.getByLabel("목록 이름", { exact: true })).toHaveCount(0);
  await open(page, "/memories/search?type=photos");
  await page.getByLabel("검색 대상", { exact: true }).selectOption("records");
  await expect(page).toHaveURL(/type=records/);
  await page
    .getByRole("navigation", { name: "주요 메뉴", exact: true })
    .getByRole("link", { name: "함께", exact: true })
    .click();
  await expect(page).toHaveURL(/\/together$/);
  await page.goBack();
  await expect(page.getByLabel("검색 대상", { exact: true })).toHaveValue("records");
  await page.reload();
  await expect(page.getByLabel("검색 대상", { exact: true })).toHaveValue("records");
});
