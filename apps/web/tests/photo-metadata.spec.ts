import { expect, test } from "@playwright/test";

test("shared photo edits move albums, preserve files and reject stale changes", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
  const other = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 393, height: 852 },
    serviceWorkers: "block",
  });
  try {
    const partner = await other.newPage();
    for (const [view, name] of [
      [page, "member"],
      [partner, "partner"],
    ] as const) {
      await view.goto("/login");
      await view.getByLabel("아이디", { exact: true }).fill(name);
      await view.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await view.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(view).toHaveURL(/\/account$/);
    }
    await page.goto("/couple");
    await page.getByRole("button", { name: "새 공간 만들기" }).click();
    await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
    await partner.goto("/couple");
    await partner.getByLabel("받은 초대 코드").fill(code);
    await partner.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(partner.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await page.goto("/memories");
    await page.getByRole("button", { name: "사진 업로드", exact: true }).click();
    const data = await page.evaluate(() => {
      const c = document.createElement("canvas");
      c.width = 1600;
      c.height = 1200;
      const ctx = c.getContext("2d");
      if (!ctx) throw Error("canvas");
      ctx.fillStyle = "#ab8c76";
      ctx.fillRect(0, 0, 1600, 1200);
      return c.toDataURL("image/jpeg").split(",")[1];
    });
    await page.getByLabel("사진 선택").setInputFiles({
      name: "synthetic.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from(data, "base64"),
    });
    await page.getByLabel("만난 날짜", { exact: true }).fill("2026-10-25");
    await page.getByLabel("이 사진의 한마디", { exact: true }).fill("원래 설명");
    await page.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
    await expect(
      page.getByText("둘의 사진으로 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요."),
    ).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "사진 업로드 닫기", exact: true }).click();
    await partner.goto("/memories?date=2026-10-25");
    const download = page.getByRole("link", { name: "저장된 압축본 내려받기" });
    const href = await download.getAttribute("href");
    if (!href) throw new Error("Missing download URL");
    const original = await (await page.request.get(href)).body();
    for (const view of [page, partner])
      await view.getByRole("button", { name: "사진 정보 수정", exact: true }).click();
    const dialog = partner.getByRole("dialog", { name: "사진 정보", exact: true });
    await dialog.getByLabel("앨범 날짜", { exact: true }).fill("2026-10-24");
    await dialog.getByLabel("설명", { exact: true }).fill("둘이 고친 설명");
    for (const width of [320, 393]) {
      await partner.setViewportSize({ width, height: 852 });
      expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect(await partner.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
    const saveButton = await dialog
      .getByRole("button", { name: "저장", exact: true })
      .boundingBox();
    const dateInput = await dialog.getByLabel("앨범 날짜", { exact: true }).boundingBox();
    expect(
      saveButton &&
        dateInput &&
        Math.abs(saveButton.x + saveButton.width - dateInput.x - dateInput.width) < 2,
    ).toBe(true);
    await partner.screenshot({ path: testInfo.outputPath("photo-edit-mobile.png") });
    await dialog.getByRole("button", { name: "저장", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await expect(partner.locator(".shared-photo-card")).toContainText("둘이 고친 설명");
    expect((await (await partner.request.get(href)).body()).equals(original)).toBe(true);
    const stale = page.getByRole("dialog", { name: "사진 정보", exact: true });
    await stale.getByLabel("설명", { exact: true }).fill("덮어쓰기 금지");
    await stale.getByRole("button", { name: "저장", exact: true }).click();
    await expect(stale.getByRole("alert")).toContainText("바뀌었어요");
    await expect(stale.getByLabel("설명", { exact: true })).toHaveValue("덮어쓰기 금지");
    await stale.getByRole("button", { name: "사진 정보 닫기" }).click();
    const dates = await (await partner.request.get("/api/photos?month=2026-10")).json();
    expect(dates.days).toEqual([{ date: "2026-10-24", count: 1 }]);
    await page.goto("/memories?date=2026-10-24");
    await expect(page.locator(".shared-photo-card")).toContainText("둘이 고친 설명");
    await page.getByRole("button", { name: "사진 휴지통으로 이동" }).click();
    await expect(page.locator(".shared-photo-card")).toHaveCount(0);
    await page.goto("/settings/trash");
    await expect(page.locator(".shared-photo-card")).toBeVisible();
    await expect(page.getByRole("button", { name: "사진 정보 수정", exact: true })).toHaveCount(0);
  } finally {
    await other.close();
  }
});
