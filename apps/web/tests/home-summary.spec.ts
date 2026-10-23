import { expect, test } from "@playwright/test";

test("home distinguishes recorded anniversaries and places accessible refresh beside the next chip", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/");
  const summary = page.getByRole("region", { name: "디데이와 기념일 요약", exact: true });
  await expect(summary).toContainText("기념일을 등록해 보세요");
  await summary.getByRole("link", { name: "기념일 관리", exact: true }).click();
  await page.getByRole("button", { name: "기념일 추가하기", exact: true }).click();
  await page.getByLabel("종류").selectOption("custom");
  await page.getByLabel("기념일 이름").fill("함께 기억할 예시 기념일");
  const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const future = new Date(Date.now() + (9 + 8 * 24) * 3600 * 1000).toISOString().slice(0, 10);
  await page.getByLabel("기준 날짜").fill(future);
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "함께 기억할 예시 기념일", exact: true }),
  ).toBeVisible();
  await page.goto("/");
  await expect(summary).toContainText("우리의 기념일");
  await expect(summary).toContainText("함께 기억할 예시 기념일");
  await expect(summary).not.toContainText("우리의 시작을 기록");
  const next = page.getByRole("complementary", { name: "다음 약속", exact: true });
  const chip = next.getByRole("heading", { name: "다음 약속", exact: true });
  const refresh = next.getByRole("button", { name: "다음 약속 새로고침", exact: true });
  await expect(refresh).toHaveText("");
  await expect(refresh).toHaveAttribute("title", "다음 약속 새로고침");
  const labelBox = await chip.boundingBox(),
    refreshBox = await refresh.boundingBox();
  if (!labelBox || !refreshBox) throw new Error("next appointment header is not visible");
  expect(refreshBox.x).toBeGreaterThan(labelBox.x + labelBox.width);
  expect(refreshBox.y).toBeLessThan(labelBox.y + labelBox.height);
  expect(refreshBox.width).toBeGreaterThanOrEqual(44);
  expect(refreshBox.height).toBeGreaterThanOrEqual(44);
  let refreshRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/" && request.headers().rsc === "1") refreshRequests++;
  });
  await refresh.click();
  await expect.poll(() => refreshRequests).toBeGreaterThan(0);
  await expect(refresh).toBeEnabled();
  await expect(next).toContainText("앞으로 예정된 약속이 없어요");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath("home-summary-mobile.png"), fullPage: true });
  await summary.getByRole("link", { name: "기념일 관리", exact: true }).click();
  await page.getByRole("button", { name: "기념일 추가하기", exact: true }).click();
  await page.getByLabel("종류").selectOption("relationship");
  await page.getByLabel("기념일 이름").fill("함께한 첫날 예시");
  await page.getByLabel("기준 날짜").fill(today);
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "함께한 첫날 예시", exact: true })).toBeVisible();
  await page.goto("/");
  await expect(summary).toContainText("함께한 1일");
});
