import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("compressed photo survives retry and is shared through API, SQL and private Storage contract", async ({
  browser,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const first = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
  const second = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  const third = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
  try {
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
    await request.post("http://127.0.0.1:54329/__lose-photo-upload-response");
    await a.getByRole("button", { name: "둘의 사진으로 저장", exact: true }).click();
    await expect(a.getByRole("main").getByRole("alert")).toContainText("연결하지 못했어요");
    await expect(a.getByLabel("이 사진의 한마디")).toHaveValue("가을날의 작은 산책");
    await b.goto("/memories");
    await b.getByLabel("만난 날짜").fill("2026-10-24");
    await expect(b.getByText("아직 이 날의 사진이 없어요. 첫 장면을 남겨보세요.")).toBeVisible();
    await a.getByRole("button", { name: "같은 사진 다시 저장", exact: true }).click();
    await expect(
      a.getByText("둘의 사진으로 저장했어요. 아래 날짜별 앨범에서 확인할 수 있어요."),
    ).toBeVisible();
    await b.getByRole("button", { name: "사진 새로고침" }).click();
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
    await expect(card.getByText("상대방", { exact: true })).toBeVisible();
    await expect(card.getByText("camera-day.jpg", { exact: true })).toBeVisible();
    const imageUrl = await card.getByRole("img").getAttribute("src");
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
    await b.getByLabel("만난 날짜").fill("2026-10-24");
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    await a.getByRole("button", { name: "선택 해제" }).click();
    await a.setViewportSize({ width: 1100, height: 900 });
    await a.screenshot({ path: testInfo.outputPath("photo-sharing-desktop.png"), fullPage: true });
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
    await b.getByRole("button", { name: "사진 새로고침" }).click();
    await expect(b.locator(".shared-photo-card")).toHaveCount(0);
    await b.getByRole("button", { name: "휴지통", exact: true }).click();
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    await expect(b.getByText(/휴지통 이동:/)).toBeVisible();
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
    await b.getByRole("button", { name: "앨범", exact: true }).click();
    await expect(b.locator(".shared-photo-card")).toHaveCount(1);
    await a.getByRole("button", { name: "사진 새로고침" }).click();
    await expect(a.locator(".shared-photo-card")).toHaveCount(1);
    await a.getByRole("button", { name: "사진 휴지통으로 이동", exact: true }).click();
    await expect(a.getByText("사진을 휴지통으로 옮겼어요.", { exact: true })).toBeVisible();
    await expect(a.locator(".shared-photo-card")).toHaveCount(0);
    await a.getByRole("button", { name: "휴지통", exact: true }).click();
    expect((await request.post("http://127.0.0.1:54329/__age-photo-trash")).ok()).toBe(true);
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
