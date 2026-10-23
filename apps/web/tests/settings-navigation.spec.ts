import { expect, test } from "@playwright/test";

test("unexpected rendering failure keeps navigation and retries without disclosing the error", async ({
  page,
}, testInfo) => {
  await page.addInitScript(() => {
    const original = window.matchMedia.bind(window);
    let failed = false;
    window.matchMedia = (query) => {
      if (!failed && query === "(display-mode: standalone)") {
        failed = true;
        throw new Error("synthetic-private-render-error");
      }
      return original(query);
    };
  });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "화면을 불러오지 못했어요" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("synthetic-private-render-error");
  const navigation = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
  await expect(navigation.getByRole("link")).toHaveText(["일정", "함께", "기록", "설정"]);
  await page.screenshot({
    path: testInfo.outputPath("recoverable-error-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(page.getByRole("heading", { name: "설정", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "화면을 불러오지 못했어요" })).toHaveCount(0);
});

test("settings separates feature links and reflects the confirmed account", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/settings");
  const account = page.getByRole("region", { name: "계정 설정", exact: true });
  await expect(account.getByRole("link", { name: "로그인", exact: true })).toHaveAttribute(
    "href",
    "/login",
  );
  for (const name of ["함께 준비하기", "일정 챙기기", "기록 보관"]) {
    await expect(page.getByRole("heading", { name, exact: true })).toHaveCount(0);
  }
  await account.getByRole("link", { name: "로그인", exact: true }).click();
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/settings");
  await expect(account).toContainText("로그인한 상태예요.");
  await expect(account.getByRole("link", { name: "로그인", exact: true })).toHaveCount(0);
  await expect(account.getByRole("link", { name: "계정 관리", exact: true })).toHaveAttribute(
    "href",
    "/account",
  );
  await expect(page.getByRole("link", { name: "각자의 시간대", exact: true })).toHaveAttribute(
    "href",
    "/timezones",
  );
  await page.reload();
  await expect(account).toContainText("로그인한 상태예요.");
  await page.screenshot({
    path: testInfo.outputPath("settings-account-mobile.png"),
    fullPage: true,
  });
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "공동 활동", exact: true })).toHaveCount(0);
  const navigation = page.getByRole("navigation", { name: "주요 메뉴", exact: true });
  await expect(navigation.getByRole("link")).toHaveText(["일정", "함께", "기록", "설정"]);
  await page.locator(".schedule-tools summary").click();
  await page.getByRole("link", { name: "캘린더 내보내기", exact: true }).click();
  await expect(page).toHaveURL(/\/calendar\/export$/);
  await navigation.getByRole("link", { name: "함께", exact: true }).click();
  await expect(page).toHaveURL(/\/together$/);
  const shared = page.getByRole("navigation", { name: "공동 활동", exact: true });
  for (const [name, href] of [
    ["목록", "/checklists"],
    ["목표", "/goals"],
    ["질문", "/questions"],
    ["룰렛", "/roulette"],
  ]) {
    await expect(shared.getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
  }
  await page.screenshot({ path: testInfo.outputPath("together-mobile.png"), fullPage: true });
  let documentLoads = 0;
  const countDocuments = (request: import("@playwright/test").Request) => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documentLoads++;
  };
  page.on("request", countDocuments);
  await shared.getByRole("link", { name: "목표", exact: true }).click();
  await expect(page.getByRole("heading", { name: "목표", exact: true })).toBeVisible();
  expect(documentLoads).toBe(0);
  page.off("request", countDocuments);
  for (const href of ["/checklists", "/goals", "/questions", "/roulette", "/questions/search"]) {
    await page.goto(href);
    await expect(navigation.getByRole("link", { name: "함께", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);
  }
  await page.setViewportSize({ width: 320, height: 812 });
  await page.goto("/together");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(navigation.getByRole("link", { name: "함께", exact: true })).toBeVisible();
  await page.goto("/memories");
  const records = page.getByRole("navigation", { name: "기록 둘러보기", exact: true });
  await expect(records.getByRole("link")).toHaveCount(1);
  await records.getByRole("link", { name: "검색", exact: true }).click();
  await expect(page).toHaveURL(/\/memories\/search$/);
  await expect(page.getByLabel("검색 대상", { exact: true })).toBeVisible();
  await navigation.getByRole("link", { name: "설정", exact: true }).click();
  await page.getByRole("link", { name: "기록 내보내기", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/export$/);
  await expect(navigation.getByRole("link", { name: "설정", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
