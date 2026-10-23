import { expect, type Page, test } from "@playwright/test";

test("photo reference search shares active photos and preserves conditions after network failure", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const partnerContext = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  try {
    const partner = await partnerContext.newPage();
    for (const [view, username] of [
      [page, "member"],
      [partner, "partner"],
    ] as const) {
      await open(view, "/login");
      await view.getByLabel("아이디", { exact: true }).fill(username);
      await view.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await view.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(view).toHaveURL(/\/account$/);
      const name = username === "member" ? "가상 사진 작성자 가" : "가상 사진 작성자 나";
      await view.getByLabel("사용자 이름", { exact: true }).fill(name);
      await view.getByRole("button", { name: "이름 저장", exact: true }).click();
      await expect(view.locator(".detail-list").getByText(name, { exact: true })).toBeVisible();
    }
    await open(page, "/couple");
    await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
    await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
    await open(partner, "/couple");
    await partner.getByLabel("받은 초대 코드").fill(code);
    await partner.getByRole("button", { name: "초대 수락하기", exact: true }).click();
    await expect(partner.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await open(page, "/memories");
    await page.getByRole("button", { name: "사진 업로드", exact: true }).click();
    const image = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 320;
      canvas.height = 240;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Canvas unavailable");
      context.fillStyle = "#c9b095";
      context.fillRect(0, 0, 320, 240);
      context.fillStyle = "#a4553f";
      context.fillRect(80, 90, 160, 150);
      return canvas.toDataURL("image/jpeg").split(",")[1];
    });
    await page.getByLabel("만난 날짜").fill("2026-10-24");
    await page.getByLabel("사진 선택").setInputFiles({
      name: "synthetic-search.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from(image, "base64"),
    });
    await page.getByLabel("이 사진의 한마디").fill("합성 산책 100%");
    await page.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
    await expect(
      page.getByText("둘의 사진으로 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요."),
    ).toBeVisible({ timeout: 30_000 });
    for (const view of [page, partner]) {
      await open(view, "/memories/search");
      await view.getByLabel("시작 날짜", { exact: true }).fill("2026-10-01");
      await view.getByLabel("마지막 날짜", { exact: true }).fill("2026-10-31");
      await view.getByLabel("사진 한마디 검색어 (선택)").fill("100%");
      await view.getByRole("button", { name: "사진 검색", exact: true }).click();
      await expect(view.getByRole("region", { name: "사진 검색 결과" })).toContainText(
        "합성 산책 100%",
      );
      await expect(view.getByRole("img", { name: "합성 산책 100%" })).toBeVisible();
      expect(view.url()).toBe("http://127.0.0.1:3100/memories/search");
    }
    await expect
      .poll(() =>
        page
          .getByRole("img", { name: "합성 산책 100%" })
          .evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    await page.getByText("상세 필터", { exact: true }).click();
    await page.getByLabel("검색 대상", { exact: true }).selectOption("filename");
    await page.getByLabel("원래 파일명 검색어 (선택)").fill("SYNTHETIC-SEARCH");
    await page.getByLabel("올린 사람", { exact: true }).selectOption("mine");
    await page.getByRole("button", { name: "사진 검색", exact: true }).click();
    await expect(page.getByRole("region", { name: "사진 검색 결과" })).toContainText(
      "합성 산책 100%",
    );
    await page.getByText("휴대폰에서 원본 찾기", { exact: true }).click();
    await expect(page.locator(".photo-reference")).toContainText("가상 사진 작성자 가");
    await expect(page.locator(".photo-reference")).toContainText("synthetic-search.jpg");
    await expect(page.locator(".photo-reference")).toContainText("제공된 정보 없음");
    await partner.getByText("상세 필터", { exact: true }).click();
    await partner.getByLabel("올린 사람", { exact: true }).selectOption("mine");
    await partner.getByRole("button", { name: "사진 검색", exact: true }).click();
    await expect(partner.getByText("이 조건에 맞는 사진이 없어요.", { exact: true })).toBeVisible();
    await partner.getByLabel("올린 사람", { exact: true }).selectOption("partner");
    await partner.getByRole("button", { name: "사진 검색", exact: true }).click();
    await expect(partner.getByRole("region", { name: "사진 검색 결과" })).toContainText(
      "합성 산책 100%",
    );
    await page.getByLabel("검색 대상", { exact: true }).selectOption("caption");
    await page.getByLabel("사진 한마디 검색어 (선택)").fill("연결 실패 중 작성한 조건");
    await page.context().setOffline(true);
    await page.getByRole("button", { name: "사진 검색", exact: true }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: "입력한 조건은 유지돼요" }),
    ).toBeVisible();
    await expect(page.getByLabel("사진 한마디 검색어 (선택)")).toHaveValue(
      "연결 실패 중 작성한 조건",
    );
    await expect(page.getByRole("region", { name: "사진 검색 결과" })).toContainText(
      "이전에 검색한 결과",
    );
    await page.context().setOffline(false);
    await page.getByRole("button", { name: "사진 검색", exact: true }).click();
    await expect(page.getByText("이 조건에 맞는 사진이 없어요.", { exact: true })).toBeVisible();
    await page.getByLabel("사진 한마디 검색어 (선택)").fill("%");
    await page.getByRole("button", { name: "사진 검색", exact: true }).click();
    await expect(page.getByRole("region", { name: "사진 검색 결과" })).toContainText(
      "합성 산책 100%",
    );
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath("photo-search-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    await page.getByRole("link", { name: "2026-10-24 앨범 보기", exact: true }).click();
    await expect(page).toHaveURL(/\/memories\?date=2026-10-24$/);
    await expect(page.locator(".shared-photo-card")).toContainText("합성 산책 100%");
    expect(errors).toEqual([]);
  } finally {
    await page.context().setOffline(false);
    await partnerContext.close();
  }
});

async function open(page: Page, url: string) {
  await page.waitForLoadState("networkidle");
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}
