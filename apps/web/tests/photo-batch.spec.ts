import { expect, test } from "@playwright/test";

test("batch photos keep successes and retry an ambiguous save without duplicates", async ({
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
  const first = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
    serviceWorkers: "block",
  });
  if (process.env.WE2DAY_TEST_WEBP_FALLBACK === "1") {
    await first.addInitScript(() => {
      const encode = HTMLCanvasElement.prototype.toBlob;
      HTMLCanvasElement.prototype.toBlob = function (callback, type, quality) {
        return encode.call(this, callback, type === "image/webp" ? "image/png" : type, quality);
      };
    });
  }
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
    await a.goto("/memories");
    await a.getByRole("button", { name: "사진 업로드", exact: true }).click();
    const input = a.getByLabel("사진 선택");
    await expect(input).toBeEnabled();
    expect(await input.getAttribute("multiple")).not.toBeNull();
    const data = await a.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1800;
      canvas.height = 1200;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas unavailable");
      ctx.fillStyle = "#ac9b88";
      ctx.fillRect(0, 0, 1800, 1200);
      return canvas.toDataURL("image/jpeg").split(",")[1];
    });
    const photo = (name: string) => ({
      name,
      mimeType: "image/jpeg",
      buffer: Buffer.from(data, "base64"),
    });
    await input.setInputFiles(
      Array.from({ length: 21 }, (_, index) => photo(`limit-${index}.jpg`)),
    );
    await expect(
      a.getByRole("dialog", { name: "사진 업로드", exact: true }).getByRole("alert"),
    ).toContainText("20장까지");
    await input.setInputFiles([
      photo("first.jpg"),
      { name: "bad.jpg", mimeType: "image/jpeg", buffer: Buffer.from("not an image") },
      photo("second.jpg"),
      photo("third.jpg"),
    ]);
    await expect(a.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toHaveCount(3);
    await expect(
      a.getByRole("dialog", { name: "사진 업로드", exact: true }).getByRole("alert"),
    ).toContainText("JPEG·PNG·WebP");
    await a.getByRole("button", { name: "bad.jpg 선택 해제", exact: true }).click();
    await a.getByLabel("만난 날짜", { exact: true }).fill("2026-10-25");
    for (let index = 1; index <= 3; index++)
      await a.getByLabel(`${index}번째 사진의 한마디`).fill(`합성 사진 ${index}`);
    await a.getByRole("button", { name: "사진 업로드 닫기", exact: true }).click();
    await a.getByRole("button", { name: "사진 업로드", exact: true }).click();
    await expect(a.getByLabel("2번째 사진의 한마디")).toHaveValue("합성 사진 2");
    for (const width of [320, 393, 1280]) {
      await a.setViewportSize({ width, height: 852 });
      expect(
        await a
          .getByRole("dialog", { name: "사진 업로드", exact: true })
          .evaluate((el) => el.scrollWidth <= el.clientWidth),
      ).toBe(true);
      expect(await a.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await a.setViewportSize({ width: 393, height: 852 });
    const sent: { filename: string; request_id: string; date: string; caption: string }[] = [];
    let lost = false,
      inflight = 0,
      peak = 0;
    await a.route("**/api/photos", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const body = route.request().postDataJSON();
      sent.push(body);
      inflight++;
      peak = Math.max(peak, inflight);
      try {
        const response = await route.fetch();
        expect(response.ok()).toBe(true);
        if (body.filename === "second.jpg" && !lost) {
          lost = true;
          await route.abort("failed");
        } else await route.fulfill({ response });
      } finally {
        inflight--;
      }
    });
    await a.getByRole("button", { name: "3장 함께 저장", exact: true }).click();
    await expect(
      a.getByRole("button", { name: "실패한 사진 다시 저장", exact: true }),
    ).toBeEnabled();
    await expect(a.getByText("3장 선택 · 2장 저장")).toBeVisible();
    await expect(
      a.getByRole("dialog", { name: "사진 업로드", exact: true }).getByRole("alert"),
    ).toContainText("저장 결과를 확인하지 못했어요");
    await expect(a.getByLabel("만난 날짜", { exact: true })).toBeDisabled();
    await expect(a.getByLabel("2번째 사진의 한마디")).toBeDisabled();
    await a.getByRole("button", { name: "실패한 사진 다시 저장", exact: true }).click();
    await expect(
      a.getByText("3장을 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요."),
    ).toBeVisible();
    expect(sent.map((item) => item.filename)).toEqual([
      "first.jpg",
      "second.jpg",
      "third.jpg",
      "second.jpg",
    ]);
    expect(sent[1].request_id).toBe(sent[3].request_id);
    expect(new Set(sent.map((item) => item.request_id)).size).toBe(3);
    expect(peak).toBe(1);
    expect(sent.every((item) => item.date === "2026-10-25")).toBe(true);
    expect(sent.map((item) => item.caption)).toEqual([
      "합성 사진 1",
      "합성 사진 2",
      "합성 사진 3",
      "합성 사진 2",
    ]);
    await b.goto("/memories?date=2026-10-25");
    const response = await b.request.get("/api/photos?date=2026-10-25");
    const result = await response.json();
    expect(response.ok()).toBe(true);
    expect(result.items).toHaveLength(3);
    expect(new Set(result.items.map((item: { id: string }) => item.id)).size).toBe(3);
    await a.screenshot({ path: testInfo.outputPath("batch-completed-mobile.png") });
    await a.getByRole("button", { name: "선택 해제", exact: true }).click();
    await expect(a.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toHaveCount(0);
    await expect(input).toBeEnabled();
  } finally {
    await first.close();
    await second.close();
  }
});
