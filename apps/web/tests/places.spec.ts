import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

test("all appointment place lookups open NAVER Maps without provider requests or changing drafts", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  let searchCalls = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/places/search") || request.url().includes("naverapihub"))
      searchCalls++;
  });
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("내 공간이 준비되었어요");
  await page.goto("/");
  await page.getByRole("button", { name: "약속 추가하기", exact: true }).click();
  await page.getByLabel("약속 이름", { exact: true }).fill("직접 작성 중인 약속");
  await page.getByLabel("만날 장소 (선택)", { exact: true }).fill("직접 기록한 만남 장소");
  await page.getByRole("button", { name: "네이버 지도 검색", exact: true }).click();
  const query = page.getByLabel("장소명 또는 주소", { exact: true });
  const link = page.getByRole("link", { name: "지도 검색", exact: true });
  await expect(query).toHaveValue("직접 기록한 만남 장소");
  await expect(link).toHaveAttribute("href", /^nmap:\/\/search\?/);
  await query.fill("가상 카페 & <img src=x onerror=alert(1)>");
  expect(new URL((await link.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "가상 카페 & <img src=x onerror=alert(1)>",
  );
  await expect(page.locator(".place-search img")).toHaveCount(0);
  await expect(page.getByLabel("약속 이름", { exact: true })).toHaveValue("직접 작성 중인 약속");
  await expect(page.getByLabel("만날 장소 (선택)", { exact: true })).toHaveValue(
    "직접 기록한 만남 장소",
  );
  await query.fill("");
  await expect(link).toHaveCount(0);
  await page.getByRole("button", { name: "검색 닫기", exact: true }).click();
  await page.getByRole("button", { name: "네이버 지도 검색", exact: true }).click();
  await expect(query).toHaveValue("직접 기록한 만남 장소");
  for (const width of [320, 393]) {
    await page.setViewportSize({ width, height: 852 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`map-search-${width}.png`), fullPage: true });
  }
  const retired = await page.request.post("/api/places/search", {
    data: { query: "retired fixture" },
  });
  expect(retired.status()).toBe(410);
  expect(retired.headers()["cache-control"]).toContain("no-store");
  await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
  await page.getByRole("button", { name: /직접 작성 중인 약속/ }).click();
  await page.getByRole("button", { name: "네이버 지도 검색", exact: true }).click();
  await expect(query).toHaveValue("직접 기록한 만남 장소");
  expect(new URL((await link.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "직접 기록한 만남 장소",
  );
  expect(searchCalls).toBe(0); // APIRequestContext calls do not emit page request events.
});
