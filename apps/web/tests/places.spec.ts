import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test("in-app place lists preserve appointment and activity drafts, loading geometry and safe links", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("status")).toContainText("내 공간이 준비되었어요");
  await page.goto("/");
  await page.getByRole("button", { name: "약속 추가하기" }).click();
  await page.getByLabel("약속 이름").fill("직접 작성 중인 약속");
  await page.getByLabel("만날 장소 (선택)").fill("직접 기록한 만남 장소");
  await page.getByRole("button", { name: "장소 검색", exact: true }).click();
  await page.getByLabel("장소 검색어").fill("가상 카페");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  const lookup = page.getByRole("region", { name: "네이버 장소 검색", exact: true });
  await expect(lookup.getByRole("alert")).toContainText("아직 설정되지 않았어요");
  await expect(page.getByLabel("약속 이름")).toHaveValue("직접 작성 중인 약속");

  const rejected = await page.request.post("/api/places/search", {
    data: { query: "test" },
    headers: { origin: "https://untrusted.invalid" },
  });
  expect(rejected.status()).toBe(403);
  const oversize = await page.request.post("/api/places/search", {
    data: "x".repeat(2049),
    headers: { origin: "http://127.0.0.1:3100", "content-type": "application/json" },
  });
  expect(oversize.status()).toBe(413);

  let calls = 0;
  let release: () => void = () => {};
  const waiting = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/places/search", async (route) => {
    calls++;
    if (calls === 4) {
      await waiting;
      await route.fulfill({ json: { items: [] } }).catch(() => {});
      return;
    }
    if (calls === 2) return route.fulfill({ json: { items: [] } });
    if (calls === 3)
      return route.fulfill({ status: 429, json: { error: "장소 검색 이용 한도에 도달했어요." } });
    return route.fulfill({
      json: {
        items: [
          {
            title: "<b>가상</b> 카페 &amp; 정원",
            link: "https://example.com/cafe",
            category: "예시 분류",
            description: "직접 작성한 가상 결과",
            roadAddress: "예시 거리",
            address: "예시 주소",
          },
          {
            title: '<img src=x onerror="alert(1)">가상 두 번째',
            link: "javascript:alert(1)",
            category: "",
            description: "",
            roadAddress: "",
            address: "",
          },
        ],
      },
    });
  });
  await page.getByLabel("장소 검색어").press("Enter");
  await expect(page.getByRole("heading", { name: "가상 카페 & 정원" })).toBeVisible();
  expect(await page.locator(".place-results img").count()).toBe(0);
  expect(await page.locator(".place-results a").count()).toBe(1);
  await expect(page.getByRole("link", { name: "상세 보기" })).toHaveAttribute(
    "rel",
    "noopener noreferrer",
  );
  await expect(page.getByLabel("만날 장소 (선택)")).toHaveValue("직접 기록한 만남 장소");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: testInfo.outputPath("place-search-mobile.png"), fullPage: true });
  await page.getByLabel("장소 검색어").fill("다른 가상 검색");
  await expect(page.getByLabel("네이버 장소 검색 결과")).toHaveCount(0);
  expect(calls).toBe(1);
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(lookup.getByRole("status")).toContainText("찾은 장소가 없어요");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(lookup.getByRole("alert")).toContainText("이용 한도");
  await expect(page.getByLabel("장소 검색어")).toHaveValue("다른 가상 검색");
  const save = page.getByRole("button", { name: "약속 저장하기", exact: true });
  const before = await save.boundingBox();
  await lookup.getByRole("button", { name: "검색", exact: true }).click();
  await expect(lookup.getByRole("status").filter({ hasText: "장소를 찾는 중" })).toBeVisible();
  const during = await save.boundingBox();
  if (!before || !during) throw new Error("Appointment form must stay visible while searching");
  expect(Math.abs(during.y - before.y)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "검색 닫기" }).click();
  release();
  await page.getByRole("button", { name: "장소 검색", exact: true }).click();
  await expect(page.getByLabel("장소 검색어")).toHaveValue("직접 기록한 만남 장소");
  await expect(page.getByLabel("네이버 장소 검색 결과")).toHaveCount(0);
  await expect(page.getByLabel("약속 이름")).toHaveValue("직접 작성 중인 약속");
  for (const width of [320, 393]) {
    await page.setViewportSize({ width, height: 852 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await save.click();
  await page.getByRole("button", { name: /직접 작성 중인 약속/ }).click();
  await lookup.getByRole("button", { name: "장소 검색", exact: true }).click();
  await lookup.getByRole("button", { name: "검색", exact: true }).click();
  await expect(lookup.locator(".place-results li")).toHaveCount(2);
  await page.goto("/plans?date=2026-10-23&new=1");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("플랜 이름", { exact: true }).fill("입력 중인 코스");
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue("입력 중인 코스");
  await page.getByLabel("활동 1 이름", { exact: true }).fill("함께 쉴 곳");
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue("입력 중인 코스");
  await page.getByLabel("활동 1 장소", { exact: true }).fill("직접 작성한 코스 장소");
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue("입력 중인 코스");
  const activity = page.getByRole("region", { name: "활동 1 장소 검색", exact: true });
  await activity.getByRole("button", { name: "장소 검색", exact: true }).click();
  await expect(activity.getByLabel("장소 검색어")).toHaveValue("직접 작성한 코스 장소");
  await activity.getByLabel("장소 검색어").press("Enter");
  await expect(activity.locator(".place-results li")).toHaveCount(2);
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue("입력 중인 코스");
  await expect(page.getByLabel("활동 1 장소", { exact: true })).toHaveValue(
    "직접 작성한 코스 장소",
  );
  expect(new URL(page.url()).pathname).toBe("/plans");
  expect(await page.locator("form form").count()).toBe(0);
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  const second = page.getByRole("region", { name: "활동 2 장소 검색", exact: true });
  await second.getByRole("button", { name: "장소 검색", exact: true }).click();
  await expect(second.getByRole("button", { name: "검색", exact: true })).toBeDisabled();
  await second.getByLabel("장소 검색어").fill("두 번째 가상 장소");
  await second.getByRole("button", { name: "검색", exact: true }).click();
  await expect(second.locator(".place-results li")).toHaveCount(2);
  await expect(activity.locator(".place-results li")).toHaveCount(2);
  for (const width of [320, 393]) {
    await page.setViewportSize({ width, height: 852 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.screenshot({ path: testInfo.outputPath("activity-place-list.png"), fullPage: true });
});
