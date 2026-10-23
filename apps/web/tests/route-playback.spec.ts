import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });
test("route playback is chronological, explicit, pausable and stops across query changes", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  const create = page.getByRole("button", { name: "새 공간 만들기" });
  if (await create.count()) await create.click();
  let fail = false,
    empty = false,
    reads = 0,
    writes = 0;
  const items = [3, 2, 1].map((day) => ({
    date: `2026-10-0${day}`,
    start_name: `산책 출발 ${day}`,
    end_name: `카페 도착 ${day}`,
    start_lat: 37.5 + day / 100,
    start_lng: 127,
    end_lat: 37.6,
    end_lng: 127 + day / 100,
    version: 1,
    updated_at: "2026-10-03T00:00:00Z",
  }));
  page.on("request", (request) => {
    if (request.method() !== "GET" && !request.url().includes("/api/routes/history")) writes++;
  });
  await page.route("**/api/routes/history", async (route) => {
    reads++;
    if (fail) return route.abort();
    const offset = route.request().postDataJSON().offset;
    return route.fulfill({
      json: {
        items: empty ? [] : offset ? items.slice(2) : items.slice(0, 2),
        next_offset: empty || offset ? null : 2,
      },
    });
  });
  await page.goto("/memories/search?type=routes");
  await page.getByLabel("동선 시작일").fill("2026-10-01");
  await page.getByLabel("동선 종료일").fill("2026-10-03");
  await page.getByRole("button", { name: "동선 조회", exact: true }).click();
  const playback = page.getByRole("region", { name: "동선 재생", exact: true });
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-02/);
  await expect(playback).toContainText("아직 불러오지 않은 기록");
  await page.getByRole("button", { name: "동선 더 보기", exact: true }).click();
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-01/);
  await expect(playback).toContainText("1 / 3일");
  await page.getByLabel("동선 재생 속도").selectOption("1000");
  await page.getByRole("button", { name: "동선 재생 시작", exact: true }).click();
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-03/);
  await expect(page.getByRole("button", { name: "동선 재생 시작", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "이전 동선", exact: true }).click();
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-02/);
  await playback.getByRole("slider", { name: "재생 날짜" }).focus();
  await page.keyboard.press("Home");
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-01/);
  await page.getByRole("button", { name: "동선 재생 시작", exact: true }).click();
  await page.getByRole("button", { name: "동선 재생 멈춤", exact: true }).click();
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-01/);
  for (const width of [320, 393, 1280]) {
    await page.setViewportSize({ width, height: 852 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.setViewportSize({ width: 393, height: 852 });
  await playback.screenshot({ path: info.outputPath("playback-mobile.png") });
  await page.getByRole("button", { name: "동선 재생 시작", exact: true }).click();
  await page.getByLabel("검색 대상").selectOption("photos");
  await page.getByLabel("검색 대상").selectOption("routes");
  await expect(page.getByRole("button", { name: "동선 재생 시작", exact: true })).toBeVisible();
  await page.getByLabel("동선 종료일").fill("2026-10-04");
  await expect(page.getByRole("button", { name: "동선 재생 시작", exact: true })).toBeDisabled();
  fail = true;
  await page.getByRole("button", { name: "동선 조회", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("이전 결과");
  await expect(playback.getByRole("img")).toHaveAccessibleName(/2026-10-01/);
  fail = false;
  empty = true;
  await page.getByRole("button", { name: "동선 조회", exact: true }).click();
  await expect(playback).toHaveCount(0);
  expect(reads).toBe(4);
  expect(writes).toBe(0);
});
