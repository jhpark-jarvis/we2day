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
  await page.request.get("http://127.0.0.1:54329/__anniversary-read-delay?enabled=true");
  try {
    await page.goto("/", { waitUntil: "commit" });
    const calendar = page.locator(".calendar-workspace");
    await expect(calendar).toBeVisible();
    await expect(page.getByRole("status", { name: "기념일 불러오는 중" })).toBeVisible();
    const before = await calendar.boundingBox();
    await expect(summary).toContainText("함께한 1일");
    const after = await calendar.boundingBox();
    if (!before || !after) throw new Error("calendar geometry is missing");
    expect(Math.abs(before.y - after.y)).toBeLessThanOrEqual(1);
  } finally {
    await page.request.get("http://127.0.0.1:54329/__anniversary-read-delay?enabled=false");
  }
});

test("direct plan editors skip list reads and load the list on archive return", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("audit");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/settings");
  const account = page.getByRole("region", { name: "계정 설정", exact: true });
  await expect(account).toContainText("로그인한 상태예요.");
  await expect(account.getByRole("link", { name: "로그인", exact: true })).toHaveCount(0);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  const reads = async () => (await page.request.get("http://127.0.0.1:54329/__plan-reads")).json();
  const initial = await reads();
  await page.goto("/plans?new=1&date=2026-11-01");
  await expect(page.getByLabel("플랜 날짜", { exact: true })).toHaveValue("2026-11-01");
  await page.getByLabel("플랜 이름", { exact: true }).fill("직접 진입 예시");
  await page.getByLabel("활동 1 이름", { exact: true }).fill("산책");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByText("초안", { exact: true })).toBeVisible();
  expect((await reads()).list).toBe(initial.list);
  const list = await page.request.get("/api/plans?summary=true");
  expect(list.headers()["server-timing"]).toContain("auth;dur=");
  const items = await list.json();
  const plan = items.find((item: { title: string }) => item.title === "직접 진입 예시");
  expect(plan).toBeTruthy();
  expect(plan.content).toBeUndefined();
  const before = await reads();
  await page.goto(`/plans?item=${plan.id}`);
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue("직접 진입 예시");
  expect((await reads()).list).toBe(before.list);
  await page.getByRole("button", { name: "플랜 보관", exact: true }).click();
  await expect(page.getByText("첫 데이트 플랜을 함께 만들어 보세요.")).toBeVisible();
  expect((await reads()).list).toBe(before.list + 1);
});
