import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import sharp from "sharp";

test("compressed photo survives retry and is shared through API, SQL and private Storage contract", async ({
  browser,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const first = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    serviceWorkers: "block",
    viewport: { width: 390, height: 844 },
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
    viewport: { width: 390, height: 844 },
  });
  const third = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    serviceWorkers: "block",
  });
  try {
    for (const size of [180, 192, 512]) {
      const response = await request.get(`http://127.0.0.1:3100/pwa-icon/${size}?v=brand2`);
      expect(response.status()).toBe(200);
      expect(response.headers()["content-type"]).toContain("image/png");
      const png = await response.body();
      expect(png.readUInt32BE(16)).toBe(size);
      expect(png.readUInt32BE(20)).toBe(size);
      const { data, info } = await sharp(png)
        .ensureAlpha()
        .raw()
        .toBuffer({ resolveWithObject: true });
      // All platform icons must be opaque and dark right up to the square edge.
      // The supplied pre-rounded artwork's white surround must never survive.
      let minimumAlpha = 255,
        maximumEdge = 0;
      for (let y = 0; y < size; y++)
        for (let x = 0; x < size; x++) {
          const offset = (y * size + x) * info.channels;
          minimumAlpha = Math.min(minimumAlpha, data[offset + 3]);
          if (x < size * 0.025 || x >= size * 0.975 || y < size * 0.025 || y >= size * 0.975)
            maximumEdge = Math.max(maximumEdge, data[offset], data[offset + 1], data[offset + 2]);
        }
      expect(minimumAlpha).toBe(255);
      expect(maximumEdge).toBeLessThan(140);
      if (size === 192)
        await import("node:fs/promises").then((fs) =>
          fs.writeFile(testInfo.outputPath("brand-icon-192.png"), png),
        );
    }
    expect((await request.get("http://127.0.0.1:3100/pwa-icon/193")).status()).toBe(404);
    const a = await first.newPage(),
      b = await second.newPage(),
      outsider = await third.newPage();
    for (const [page, username] of [
      [a, "member"],
      [b, "partner"],
      [outsider, "outsider"],
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
    await expect(a.getByLabel("사진 선택")).toBeEnabled();
    const data = await a.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1800;
      canvas.height = 1200;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas unavailable");
      ctx.fillStyle = "#eee1ce";
      ctx.fillRect(0, 0, 1800, 1200);
      ctx.fillStyle = "#a7ae8b";
      ctx.fillRect(0, 600, 1800, 600);
      ctx.fillStyle = "#a4553f";
      ctx.fillRect(700, 440, 240, 420);
      return canvas.toDataURL("image/jpeg").split(",")[1];
    });
    await a.getByLabel("만난 날짜").fill("2026-10-24");
    await a.getByLabel("사진 선택").setInputFiles({
      name: "camera-day.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from(data, "base64"),
    });
    await expect(a.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
    await a.getByLabel("이 사진의 한마디").fill("가을날의 작은 산책");
    await a.getByRole("button", { name: "사진 업로드 닫기", exact: true }).click();
    await expect(a.getByRole("button", { name: "사진 업로드", exact: true })).toBeFocused();
    await a.getByRole("button", { name: "사진 업로드", exact: true }).click();
    await expect(a.getByLabel("이 사진의 한마디")).toHaveValue("가을날의 작은 산책");
    await expect(a.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
    for (const [width, height] of [
      [320, 568],
      [393, 852],
      [1280, 800],
    ]) {
      await a.setViewportSize({ width, height });
      const popup = a.getByRole("dialog", { name: "사진 업로드", exact: true });
      expect(
        await popup.evaluate((el) => {
          const r = el.getBoundingClientRect();
          return (
            r.left >= 0 &&
            r.right <= innerWidth &&
            r.top >= 0 &&
            r.bottom <= innerHeight &&
            el.scrollWidth <= el.clientWidth
          );
        }),
      ).toBe(true);
      await a.screenshot({ path: testInfo.outputPath(`photo-upload-${width}.png`) });
    }
    await a.setViewportSize({ width: 390, height: 844 });

    await a.getByLabel("만난 날짜", { exact: true }).fill("");
    await expect(a.getByLabel("만난 날짜", { exact: true })).toHaveValue("");
    await expect(a.getByRole("button", { name: "둘의 사진으로 저장", exact: true })).toBeDisabled();
    await a.getByLabel("만난 날짜", { exact: true }).fill("2026-10-24");
    await expect(a.getByLabel("이 사진의 한마디")).toHaveValue("가을날의 작은 산책");
    await request.post("http://127.0.0.1:54329/__lose-photo-upload-response");
    await a.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
    await expect(a.getByRole("main").getByRole("alert")).toContainText("연결하지 못했어요");
    await expect(a.getByLabel("이 사진의 한마디")).toHaveValue("가을날의 작은 산책");
    await b.goto("/memories?date=2026-10-24");
    await expect(b.getByText("아직 이 날의 사진이 없어요. 첫 장면을 남겨보세요.")).toBeVisible();
    await a.getByRole("button", { name: "같은 사진 다시 저장", exact: true }).click();
    await expect(
      a.getByText("둘의 사진으로 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요."),
    ).toBeVisible();
    await a.getByRole("button", { name: "사진 업로드 닫기", exact: true }).click();
    await b.getByLabel("사진 도구", { exact: true }).click();
    await b.getByRole("button", { name: "사진 새로고침" }).click();
    const monthResponse = await b.request.get("/api/photos?month=2026-10");
    expect(monthResponse.headers()["cache-control"]).toContain("no-store");
    expect(await monthResponse.json()).toEqual({
      month: "2026-10",
      days: [{ date: "2026-10-24", count: 1 }],
    });
    expect((await b.request.get("/api/photos?month=2026-13")).status()).toBe(422);
    expect((await b.request.get("/api/photos?month=2026-10&date=2026-10-24")).status()).toBe(422);
    expect((await third.request.get("/api/photos?month=2026-10")).status()).toBe(409);
    await b.route("**/api/photos?month=2026-10", (route) =>
      route.fulfill({ status: 503, json: { error: "합성 날짜 조회 실패" } }),
    );
    await b.getByRole("button", { name: "앨범 날짜", exact: true }).click();
    await expect(
      b.getByRole("dialog", { name: "앨범 날짜", exact: true }).getByRole("alert"),
    ).toContainText("합성 날짜 조회 실패");
    await expect(
      b.getByRole("button", { name: "2026-10-24 · 사진 1장", exact: true }),
    ).toBeDisabled();
    await b.unroute("**/api/photos?month=2026-10");
    await b.getByRole("button", { name: "앨범 날짜 다시 불러오기", exact: true }).click();

    const picker = b.getByRole("dialog", { name: "앨범 날짜", exact: true });
    await expect(
      picker.getByRole("button", { name: "2026-10-24 · 사진 1장", exact: true }),
    ).toBeEnabled();
    await expect(
      picker.getByRole("button", { name: "2026-10-23 · 사진 0장", exact: true }),
    ).toBeDisabled();
    await picker.getByRole("button", { name: "이전 앨범 월", exact: true }).click();
    await expect(picker.getByLabel("앨범 월", { exact: true })).toHaveValue("2026-09");
    await expect(picker.getByText("이 달에는 사진이 없어요.", { exact: true })).toBeVisible();
    await picker.getByRole("button", { name: "다음 앨범 월", exact: true }).click();
    await picker.getByRole("button", { name: "2026-10-24 · 사진 1장", exact: true }).click();
    await expect(picker).not.toBeVisible();
    const albumActions = b.locator(".photo-album-actions");
    await expect(
      albumActions.getByRole("link", { name: "기록 검색", exact: true }),
    ).toHaveAttribute("href", "/memories/search");
    await expect(b.locator(".record-browse-toolbar")).toHaveCount(0);
    const more = albumActions.getByLabel("사진 도구", { exact: true });
    await more.click();
    await expect(b.getByRole("group", { name: "사진 도구 목록" })).toBeVisible();
    await b.keyboard.press("Escape");
    await expect(b.getByRole("group", { name: "사진 도구 목록" })).not.toBeVisible();
    await expect(more).toBeFocused();
    await more.click();
    await b.getByRole("heading", { name: "함께한 날들", exact: true }).click();
    await expect(b.getByRole("group", { name: "사진 도구 목록" })).not.toBeVisible();
    for (const width of [320, 393, 1280]) {
      await b.setViewportSize({ width, height: 844 });
      await more.click();
      const menu = await b.getByRole("group", { name: "사진 도구 목록" }).boundingBox();
      if (!menu) throw new Error("Album tools missing");
      expect(menu.x).toBeGreaterThanOrEqual(0);
      expect(menu.x + menu.width).toBeLessThanOrEqual(width);
      expect(
        await b.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await b.screenshot({ path: testInfo.outputPath(`album-tools-${width}.png`) });
      await b.keyboard.press("Escape");
    }
    await b.setViewportSize({ width: 390, height: 844 });
    await more.click();
    await b.getByRole("button", { name: "사진 내보내기", exact: true }).click();
    await expect(b.getByRole("group", { name: "사진 도구 목록" })).not.toBeVisible();
    const card = b.locator(".shared-photo-card");
    await expect(card).toHaveCount(1);
    await expect(card.getByText("가을날의 작은 산책", { exact: true })).toBeVisible();
    await expect(card.getByRole("img")).toBeVisible();
    await card.scrollIntoViewIfNeeded();
    await expect
      .poll(() =>
        card
          .getByRole("img")
          .evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    await card.getByText("휴대폰에서 원본 찾기", { exact: true }).click();
    await expect(card.getByText("이름 미설정", { exact: true })).toBeVisible();
    await expect(card.getByText("camera-day.jpg", { exact: true })).toBeVisible();
    const imageUrl = await card.getByRole("img").getAttribute("src");
    const canonical = await second.request.get(imageUrl || "");
    expect(canonical.headers()["content-type"]).toContain("image/webp");
    const canonicalBytes = await canonical.body();
    expect(canonicalBytes.toString("ascii", 0, 4)).toBe("RIFF");
    expect(canonicalBytes.toString("ascii", 8, 12)).toBe("WEBP");

    // A second view-only fixture isolates swipe/dialog layout from the real Storage lifecycle below.
    const album = await (await b.request.get("/api/photos?date=2026-10-24")).json();
    const secondId = "77777777-7777-4777-8777-777777777777";
    await b.route("**/api/photos?date=2026-10-24", (route) =>
      route.fulfill({
        json: {
          items: [...album.items, { ...album.items[0], id: secondId, caption: "가로 탐색 예시" }],
          next_after: null,
        },
      }),
    );
    await b.route(`**/api/photos/${secondId}/image*`, (route) =>
      route.fulfill({ body: canonicalBytes, contentType: "image/webp" }),
    );
    if (await b.getByLabel("사진 도구", { exact: true }).count())
      await b.getByLabel("사진 도구", { exact: true }).click();
    await b.getByRole("button", { name: "사진 새로고침", exact: true }).click();
    await expect(b.locator(".shared-photo-card")).toHaveCount(2);
    await expect(b.getByRole("button", { name: "앨범", exact: true })).toHaveCount(0);
    await expect(b.getByRole("button", { name: "휴지통", exact: true })).toHaveCount(0);
    await expect(b.getByRole("heading", { name: "2026년 10월 24일", exact: true })).toBeVisible();
    for (const width of [320, 393, 1425]) {
      await b.setViewportSize({ width, height: 852 });
      await b.getByRole("button", { name: "다음 사진", exact: true }).click();
      await expect(b.locator(".photo-slide-navigation")).toContainText("2 / 2");
      expect(await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const active = b.locator('.photo-slide[aria-hidden="false"]');
      for (const name of ["사진 크게 보기", "사진 휴지통으로 이동"])
        await expect(active.getByRole("button", { name, exact: true })).toHaveCSS(
          "border-top-width",
          "0px",
        );
      await active.getByRole("button", { name: "사진 크게 보기", exact: true }).click();
      await expect(b.getByRole("dialog", { name: "사진 크게 보기", exact: true })).toBeVisible();
      const bounds = await b.getByRole("dialog").evaluate((el) => {
        const r = el.getBoundingClientRect();
        return {
          x: r.x,
          y: r.y,
          width: r.width,
          height: r.height,
          viewportWidth: innerWidth,
          viewportHeight: innerHeight,
        };
      });
      expect(Math.abs(bounds.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(bounds.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(bounds.width - bounds.viewportWidth)).toBeLessThanOrEqual(18);
      expect(Math.abs(bounds.height - bounds.viewportHeight)).toBeLessThanOrEqual(1);
      await expect(b.locator("dialog img")).toHaveCSS("object-fit", "contain");
      await b
        .getByRole("dialog")
        .screenshot({ path: testInfo.outputPath(`expanded-${width}.png`) });
      await b.getByRole("button", { name: "사진 크게 보기 닫기", exact: true }).press("Escape");
      await expect(b.getByRole("dialog")).toHaveCount(0);
      await expect(
        active.getByRole("button", { name: "사진 크게 보기", exact: true }),
      ).toBeFocused();
      if (width === 393) {
        const download = b.waitForEvent("download");
        await active.getByRole("link", { name: "저장된 압축본 내려받기", exact: true }).click();
        expect((await download).suggestedFilename()).toBe("we2day-2026-10-24.webp");
      }
      await b.getByRole("button", { name: "이전 사진", exact: true }).click();
      await expect(b.locator(".photo-slide-navigation")).toContainText("1 / 2");
    }
    await b.setViewportSize({ width: 393, height: 852 });
    await b
      .locator('.photo-slide[aria-hidden="false"] .photo-image-actions')
      .screenshot({ path: testInfo.outputPath("photo-icons.png") });
    await b.unroute("**/api/photos?date=2026-10-24");
    await b.unroute(`**/api/photos/${secondId}/image*`);
    if (await b.getByLabel("사진 도구", { exact: true }).count())
      await b.getByLabel("사진 도구", { exact: true }).click();
    await b.getByRole("button", { name: "사진 새로고침", exact: true }).click();
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    const hidden = await third.request.get("/api/photos?date=2026-10-24");
    expect((await hidden.json()).items).toEqual([]);
    expect((await third.request.get(imageUrl as string)).status()).toBe(404);
    expect(
      (
        await first.request.post("/api/photos", {
          headers: { Origin: "https://other.invalid", "Content-Type": "application/json" },
          data: {},
        })
      ).status(),
    ).toBe(403);
    await b.screenshot({ path: testInfo.outputPath("photo-sharing-mobile.png"), fullPage: true });
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await b.reload();
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    await a.getByRole("button", { name: "사진 업로드", exact: true }).click();
    await a.getByRole("button", { name: "선택 해제" }).click();
    await a.getByRole("button", { name: "사진 업로드 닫기", exact: true }).click();
    await a.setViewportSize({ width: 1100, height: 900 });
    await a.screenshot({ path: testInfo.outputPath("photo-sharing-desktop.png"), fullPage: true });
    await a.getByLabel("사진 도구", { exact: true }).click();
    await a.getByRole("button", { name: "사진 내보내기", exact: true }).click();
    await a.getByLabel("이 사진 내보내기 선택", { exact: true }).check();
    const exporting = a.waitForEvent("download");
    await a.getByRole("button", { name: "선택한 사진 1장 ZIP 내보내기", exact: true }).click();
    const exported = await exporting;
    expect(exported.suggestedFilename()).toBe("we2day-photos-2026-10-24.zip");
    const zip = await readFile((await exported.path()) as string);
    expect(zip.subarray(0, 4)).toEqual(Buffer.from([80, 75, 3, 4]));
    expect(zip.includes(Buffer.from("manifest.json"))).toBe(true);
    expect(zip.includes(Buffer.from("가을날의 작은 산책"))).toBe(true);
    await a.getByRole("button", { name: "사진 휴지통으로 이동", exact: true }).click();
    await expect(a.getByText("사진을 휴지통으로 옮겼어요.", { exact: true })).toBeVisible();
    await expect(a.locator(".shared-photo-card")).toHaveCount(0);
    expect((await first.request.get(imageUrl as string)).status()).toBe(404);
    await b.getByLabel("사진 도구", { exact: true }).click();
    await b.getByRole("button", { name: "사진 새로고침" }).click();
    await expect(b.locator(".shared-photo-card")).toHaveCount(0);
    await b.goto("/settings/trash");
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    await expect(b.getByText(/휴지통 이동:/)).toBeVisible();
    await b.getByLabel("기록 날짜 (선택)").fill("2026-10-25");
    await expect(b.locator(".shared-photo-card")).toHaveCount(0);
    await b.getByLabel("기록 날짜 (선택)").fill("2026-10-24");
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    const recordId = (await (await b.request.get("/api/photos?trash=true&date=2026-10-24")).json())
      .items[0].id;
    await b.getByLabel("사진 기록", { exact: true }).selectOption(recordId);
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    await b.locator(".shared-photo-card").scrollIntoViewIfNeeded();
    await expect
      .poll(() =>
        b
          .locator(".shared-photo-card img")
          .evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    await expect(b.getByText("영구 삭제 확인 열기", { exact: true })).toHaveCount(0);
    await b.screenshot({ path: testInfo.outputPath("photo-trash-mobile.png"), fullPage: true });
    await b.getByRole("button", { name: "원래 앨범으로 복구", exact: true }).click();
    await expect(
      b.getByText("사진을 원래 날짜의 앨범으로 복구했어요.", { exact: true }),
    ).toBeVisible();
    await expect(b.locator(".shared-photo-card")).toHaveCount(0);
    await b.goto("/memories?date=2026-10-24");
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    if (await a.getByLabel("사진 도구", { exact: true }).count())
      await a.getByLabel("사진 도구", { exact: true }).click();
    await a.getByRole("button", { name: "사진 새로고침" }).click();
    await expect(a.locator(".shared-photo-card")).toHaveCount(1);
    await a.getByRole("button", { name: "사진 휴지통으로 이동", exact: true }).click();
    await expect(a.getByText("사진을 휴지통으로 옮겼어요.", { exact: true })).toBeVisible();
    await expect(a.locator(".shared-photo-card")).toHaveCount(0);
    await a.goto("/settings/trash");
    expect((await request.post("http://127.0.0.1:54329/__age-photo-trash")).ok()).toBe(true);
    if (await a.getByLabel("사진 도구", { exact: true }).count())
      await a.getByLabel("사진 도구", { exact: true }).click();
    await a.getByRole("button", { name: "사진 새로고침" }).click();
    await a.getByText("영구 삭제 확인 열기", { exact: true }).click();
    await a.getByLabel("확인 문구 ‘영구 삭제’ 입력").fill("영구 삭제");
    await request.post("http://127.0.0.1:54329/__lose-photo-delete-response");
    await a.getByRole("button", { name: "이 사진 영구 삭제하기", exact: true }).click();
    await expect(a.getByRole("main").getByRole("alert")).toContainText("연결하지 못했어요");
    await a.getByRole("button", { name: "이 사진 영구 삭제하기", exact: true }).click();
    await expect(a.getByText("사진 파일과 기록을 영구 삭제했어요.", { exact: true })).toBeVisible();
    await expect(a.locator(".shared-photo-card")).toHaveCount(0);
    expect((await first.request.get(imageUrl as string)).status()).toBe(404);
    // One focused meeting flow reuses this pair and the same temporary SQL environment.
    await a.goto("/");
    await b.goto("/");
    await expect(a.getByLabel("함께한 날의 메모")).toBeVisible();
    await expect(b.getByLabel("함께한 날의 메모")).toBeVisible();
    await a.getByLabel("이 날 만났어요", { exact: true }).check();
    await a.getByLabel("함께한 날의 메모").fill("산책하고 따뜻한 차 마시기");
    await a.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(a.getByText("만남 기록을 저장했어요.", { exact: true })).toBeVisible();
    await expect(a.locator('.calendar-day[aria-current="date"]')).toHaveAccessibleName(/만난 날/);
    await b.getByLabel("함께한 날의 메모").fill("저장 전 상대의 메모");
    await b.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(b.getByRole("main").getByRole("alert")).toContainText("만남 기록이 바뀌었어요");
    await expect(b.getByLabel("함께한 날의 메모")).toHaveValue("저장 전 상대의 메모");
    await b.getByRole("button", { name: "최신 만남 기록 불러오기" }).click();
    await expect(b.getByLabel("함께한 날의 메모")).toHaveValue("산책하고 따뜻한 차 마시기");
    await expect(b.getByLabel("이 날 만났어요", { exact: true })).toBeChecked();
    await b.screenshot({ path: testInfo.outputPath("meeting-days-mobile.png"), fullPage: true });
    await b.getByLabel("이 날 만났어요", { exact: true }).uncheck();
    await b.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
    await expect(b.getByText("만남 기록을 저장했어요.", { exact: true })).toBeVisible();
    await a.reload();
    await expect(a.getByLabel("이 날 만났어요", { exact: true })).not.toBeChecked();
    await expect(a.getByLabel("함께한 날의 메모")).toHaveValue("산책하고 따뜻한 차 마시기");
  } finally {
    await Promise.race([
      Promise.allSettled([first.close(), second.close(), third.close()]),
      new Promise((resolve) => setTimeout(resolve, 5_000)),
    ]);
  }
});
