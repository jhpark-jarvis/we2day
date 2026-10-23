import { expect, test } from "@playwright/test";

test("shared favorite destinations, retry, conflict, trash, address search and explicit course selection", async ({
  browser,
}, info) => {
  test.setTimeout(120_000);
  const selectedDestination = "합성 장소 (합성시 예시로 1)";
  const first = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 393, height: 852 },
    serviceWorkers: "block",
  });
  const second = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    serviceWorkers: "block",
  });
  try {
    const a = await first.newPage(),
      b = await second.newPage();
    for (const [page, username] of [
      [a, "member"],
      [b, "partner"],
    ] as const) {
      await page.goto("/login");
      await page.getByLabel("아이디", { exact: true }).fill(username);
      await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(page).toHaveURL(/\/account$/);
    }
    await a.goto("/couple");
    await a.getByRole("button", { name: "새 공간 만들기" }).click();
    await a.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await a.getByLabel("상대에게 전달할 코드").inputValue();
    await b.goto("/couple");
    await b.getByLabel("받은 초대 코드").fill(code);
    await b.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(b.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await a.goto("/settings/places");
    await a.getByRole("button", { name: "장소 추가", exact: true }).click();
    const dialog = a.getByRole("dialog");
    await dialog.getByLabel("장소 별칭").fill("합성 카페");
    await dialog.getByLabel("장소명·주소").fill("검색 전 직접 입력");
    let searchFailure = true;
    await a.route("**/api/places/search", (route) =>
      searchFailure
        ? route.abort()
        : route.fulfill({
            json: {
              items: [
                {
                  title: "합성 장소",
                  roadAddress: "합성시 예시로 1",
                  address: "합성동 1",
                  link: "",
                  category: "",
                  description: "",
                },
              ],
            },
          }),
    );
    await dialog.getByRole("button", { name: "장소 검색", exact: true }).click();
    await dialog.getByLabel("장소 검색어").fill("합성시 예시로 1");
    await dialog.getByLabel("장소 검색어").press("Enter");
    await expect(dialog.getByRole("alert")).toContainText("연결하지 못했어요");
    await expect(dialog.getByLabel("장소명·주소")).toHaveValue("검색 전 직접 입력");
    searchFailure = false;
    await dialog.getByRole("button", { name: "검색", exact: true }).click();
    await expect(dialog.getByRole("region", { name: "네이버 장소 검색 결과" })).toContainText(
      "합성시 예시로 1",
    );
    await a.setViewportSize({ width: 320, height: 852 });
    expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await a.screenshot({ path: info.outputPath("favorite-address-search.png"), fullPage: true });
    await dialog.getByRole("button", { name: "합성 장소 선택", exact: true }).click();
    await expect(dialog.getByLabel("장소명·주소")).toHaveValue(selectedDestination);
    await expect(dialog.getByLabel("장소 별칭")).toHaveValue("합성 카페");
    expect(
      (await (await first.request.get("/api/favorite-places?archived=false&offset=0")).json())
        .items,
    ).toEqual([]);

    for (const width of [320, 393, 1280]) {
      await a.setViewportSize({ width, height: 852 });
      expect(await a.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(
        await dialog.getByLabel("장소명·주소").evaluate((el) => {
          const box = el.getBoundingClientRect();
          return box.left >= 0 && box.right <= innerWidth;
        }),
      ).toBe(true);
      expect(
        await dialog.evaluate((el) => {
          const b = el.getBoundingClientRect();
          return (
            Math.abs(b.left + b.width / 2 - innerWidth / 2) < 2 &&
            Math.abs(b.top + b.height / 2 - innerHeight / 2) < 2
          );
        }),
      ).toBe(true);
    }
    await a.route("**/settings/places", (route) =>
      route.request().method() === "POST" ? route.abort() : route.continue(),
    );
    await dialog.getByRole("button", { name: "저장", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("작성 내용은 유지했어요");
    await expect(dialog.getByLabel("장소 별칭")).toHaveValue("합성 카페");
    await a.unroute("**/settings/places");
    await dialog.getByRole("button", { name: "저장", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await expect(a.getByRole("button", { name: "합성 카페 수정", exact: true })).toBeVisible();
    await b.goto("/settings/places");
    await b.getByRole("button", { name: "합성 카페 수정", exact: true }).click();
    await a.getByRole("button", { name: "합성 카페 수정", exact: true }).click();
    await dialog.getByLabel("장소 별칭").fill("공유 카페");
    await dialog.getByRole("button", { name: "저장", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await b.getByRole("dialog").getByLabel("장소 별칭").fill("오래된 초안");
    await b.getByRole("dialog").getByRole("button", { name: "저장", exact: true }).click();
    await expect(b.getByRole("dialog").getByRole("alert")).toContainText("작성 내용은 남아 있어요");
    await expect(b.getByLabel("장소 별칭")).toHaveValue("오래된 초안");
    await b.getByRole("button", { name: "장소 편집 닫기" }).click();
    await b.getByRole("button", { name: "자주 가는 곳 새로고침", exact: true }).click();
    await expect(b.getByRole("button", { name: "공유 카페 수정", exact: true })).toBeVisible();
    await a.route("**/settings/places", (route) =>
      route.request().method() === "POST" ? route.abort() : route.continue(),
    );
    await a.getByRole("button", { name: "공유 카페 삭제", exact: true }).click();
    await expect(a.getByRole("main").getByRole("alert")).toContainText("목록은 유지했어요");
    await expect(a.getByRole("button", { name: "공유 카페 삭제", exact: true })).toBeVisible();
    await a.unroute("**/settings/places");
    await a.getByRole("button", { name: "공유 카페 삭제", exact: true }).click();
    await expect(a.getByText("자주 쓰는 장소명이나 주소를 추가해 보세요.")).toBeVisible();
    await a.getByRole("button", { name: "휴지통", exact: true }).click();
    await a.getByRole("button", { name: "공유 카페 복원", exact: true }).click();
    await expect(a.getByText("휴지통이 비어 있어요.")).toBeVisible();
    await a.getByRole("button", { name: "장소", exact: true }).click();
    await expect(a.getByRole("button", { name: "공유 카페 수정", exact: true })).toBeVisible();
    await first.addCookies([
      { name: "we2day-theme", value: "white", url: "http://127.0.0.1:3100" },
    ]);
    await a.reload();
    await a.setViewportSize({ width: 320, height: 852 });
    await a.getByRole("button", { name: "공유 카페 수정", exact: true }).click();
    expect(
      await dialog
        .getByLabel("장소명·주소")
        .evaluate((el) => Number.parseFloat(getComputedStyle(el).fontSize)),
    ).toBeGreaterThanOrEqual(16);
    expect(await a.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await a.screenshot({ path: info.outputPath("favorite-white-editor.png"), fullPage: true });
    await a.getByRole("button", { name: "장소 편집 닫기" }).click();
    await first.addCookies([{ name: "we2day-theme", value: "warm", url: "http://127.0.0.1:3100" }]);
    await a.screenshot({ path: info.outputPath("shared-settings.png"), fullPage: true });
    await a.goto("/plans?new=1");
    await expect(a.getByRole("heading", { name: "새 데이트 플랜", exact: true })).toBeVisible();
    await a.getByLabel("플랜 이름", { exact: true }).fill("합성 공유 코스");
    await a.getByLabel("활동 1 이름", { exact: true }).fill("카페");
    const place = a.getByRole("region", { name: "활동 1 장소 검색", exact: true });
    await place.getByRole("button", { name: "자주 가는 곳", exact: true }).click();
    await place.getByRole("button", { name: "공유 카페 선택", exact: true }).click();
    await expect(a.getByLabel("활동 1 장소", { exact: true })).toHaveValue(selectedDestination);
    expect(await (await first.request.get("/api/plans")).json()).toEqual([]);
    await a.getByRole("button", { name: "활동 추가", exact: true }).click();
    await a.getByLabel("활동 2 이름", { exact: true }).fill("산책");
    await expect(a.getByLabel("활동 2 장소", { exact: true })).toHaveValue("");
    for (const width of [320, 393, 1280]) {
      await a.setViewportSize({ width, height: 852 });
      expect(await a.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await a.setViewportSize({ width: 393, height: 852 });
    await a.screenshot({ path: info.outputPath("favorite-course-mobile.png"), fullPage: true });
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByRole("heading", { name: "합성 공유 코스", exact: true })).toBeVisible();
    await expect(a.getByText("초안", { exact: true })).toBeVisible();
    const plans = await (await first.request.get("/api/plans")).json();
    expect(JSON.stringify(plans)).toContain(selectedDestination);
    // Removing a favorite must neither remove the stored course text nor offer it for new selections.
    await a.goto("/settings/places");
    await a.getByRole("button", { name: "공유 카페 삭제", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "휴지통에서 복원" })).toBeVisible();
    expect(JSON.stringify(await (await first.request.get("/api/plans")).json())).toContain(
      selectedDestination,
    );
    await b.reload();
    await expect(b.getByRole("button", { name: "공유 카페 수정", exact: true })).toHaveCount(0);
    await a.goto("/plans?new=1");
    await a
      .getByRole("region", { name: "활동 1 장소 검색", exact: true })
      .getByRole("button", { name: "자주 가는 곳", exact: true })
      .click();
    await expect(a.getByRole("button", { name: "공유 카페 선택", exact: true })).toHaveCount(0);
    await b.getByRole("button", { name: "휴지통", exact: true }).click();
    await b.getByRole("button", { name: "공유 카페 복원", exact: true }).click();
    await expect(b.getByText("휴지통이 비어 있어요.")).toBeVisible();
    await a.goto("/");
    await a.getByRole("button", { name: "약속 추가하기", exact: true }).click();
    const appointment = a.getByRole("region", { name: "네이버 장소 검색", exact: true });
    await appointment.getByRole("button", { name: "자주 가는 곳", exact: true }).click();
    await appointment.getByRole("button", { name: "공유 카페 선택", exact: true }).click();
    await expect(a.getByLabel("만날 장소 (선택)")).toHaveValue(selectedDestination);
  } finally {
    await first.close();
    await second.close();
  }
});
