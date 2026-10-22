import { readFile } from "node:fs/promises";
import { expect, type Page, test } from "@playwright/test";
import { parse } from "exifr";

async function image(page: Page, format = "image/jpeg") {
  const base64 = await page.evaluate((mime) => {
    const canvas = document.createElement("canvas");
    canvas.width = 2000;
    canvas.height = 1200;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas unavailable");
    context.fillStyle = "#dfcbb5";
    context.fillRect(0, 0, 2000, 1200);
    context.fillStyle = "#8d9a80";
    context.fillRect(0, 650, 2000, 550);
    return canvas.toDataURL(mime).split(",")[1];
  }, format);
  return Buffer.from(base64, "base64");
}

function withExif(jpeg: Buffer) {
  // Synthetic TIFF: Make/Model, capture time, GPS ref and a private comment sentinel.
  const tiff = Buffer.alloc(300);
  tiff.write("II");
  tiff.writeUInt16LE(42, 2);
  tiff.writeUInt32LE(8, 4);
  tiff.writeUInt16LE(4, 8);
  const entry = (at: number, tag: number, type: number, count: number, value: number) => {
    tiff.writeUInt16LE(tag, at);
    tiff.writeUInt16LE(type, at + 2);
    tiff.writeUInt32LE(count, at + 4);
    tiff.writeUInt32LE(value, at + 8);
  };
  entry(10, 0x010f, 2, 9, 62);
  tiff.write("Example\0\0", 62);
  entry(22, 0x0110, 2, 14, 71);
  tiff.write("Test Phone 01\0", 71);
  entry(34, 0x8769, 4, 1, 86);
  entry(46, 0x8825, 4, 1, 150);
  tiff.writeUInt16LE(2, 86);
  entry(88, 0x9003, 2, 20, 116);
  tiff.write("2026:10:18 15:42:00\0", 116);
  entry(100, 0x9286, 7, 27, 180);
  tiff.write("ASCII\0\0\0PRIVATE_SENTINEL\0\0\0", 180);
  tiff.writeUInt16LE(1, 150);
  entry(152, 1, 2, 2, 78);
  const exif = Buffer.concat([Buffer.from("Exif\0\0"), tiff]);
  const marker = Buffer.alloc(4);
  marker[0] = 255;
  marker[1] = 225;
  marker.writeUInt16BE(exif.length + 2, 2);
  return Buffer.concat([jpeg.subarray(0, 2), marker, exif, jpeg.subarray(2)]);
}

test("photo preparation preserves allowed references locally and strips original metadata", async ({
  page,
}, testInfo) => {
  if (testInfo.project.name === "mobile") {
    await page.goto("/settings");
    await page.getByRole("button", { name: /화이트/ }).click();
    await expect(page.getByRole("status")).toContainText("1년");
  }
  await page.goto("/memories");
  await expect(page.getByLabel("\uc0ac\uc9c4 \uc120\ud0dd")).toBeEnabled();
  const transmissions: string[] = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "PATCH"].includes(request.method())) transmissions.push(request.url());
  });
  const source = withExif(await image(page));
  const original = await parse(source, { reviveValues: false, userComment: true });
  expect(original.GPSLatitudeRef).toBe("N");
  expect(original.DateTimeOriginal).toBe("2026:10:18 15:42:00");
  await page.getByLabel("만난 날짜").fill("2026-10-10");
  await page
    .getByLabel("사진 선택")
    .setInputFiles({ name: "together.jpg", mimeType: "image/jpeg", buffer: source });
  await expect(page.getByRole("img", { name: "선택한 사진의 압축 미리보기" })).toBeVisible();
  await expect(page.getByText("Example · Test Phone 01", { exact: true })).toBeVisible();
  await expect(page.getByText(/2026-10-18 15:42:00/)).toBeVisible();
  await expect(page.getByText(/1,?600 × 960/)).toBeVisible();
  await expect(page.locator("figcaption")).toContainText("2026-10-10");
  await page.getByLabel("만난 날짜").fill("1999-12-31");
  await expect(page.getByRole("link", { name: "압축본 내려받기" })).toHaveCount(0);
  await page.getByLabel("만난 날짜").fill("2026-10-10");
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "압축본 내려받기" }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("we2day-2026-10-10.webp");
  const output = await readFile((await download.path()) as string);
  expect(output.toString("ascii", 0, 4)).toBe("RIFF");
  expect(output.toString("ascii", 8, 12)).toBe("WEBP");
  expect(output.length).toBeLessThanOrEqual(1024 * 1024);
  expect(output.includes(Buffer.from("PRIVATE_SENTINEL"))).toBe(false);
  for (let offset = 12; offset + 8 <= output.length; ) {
    expect(["EXIF", "XMP "]).not.toContain(output.toString("ascii", offset, offset + 4));
    const length = output.readUInt32LE(offset + 4);
    offset += 8 + length + (length % 2);
  }
  expect(transmissions).toEqual([]);
  await page.setViewportSize({ width: 320, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("photo-preparation.png"), fullPage: true });
  await page.getByRole("button", { name: "선택 해제" }).click();
  await expect(
    page.getByRole("img", {
      name: "\uc120\ud0dd\ud55c \uc0ac\uc9c4\uc758 \uc555\ucd95 \ubbf8\ub9ac\ubcf4\uae30",
    }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: "압축본 내려받기" })).toHaveCount(0);
});

test("invalid files recover to a photo without invented device or capture data", async ({
  page,
}) => {
  await page.goto("/memories");
  await expect(page.getByLabel("\uc0ac\uc9c4 \uc120\ud0dd")).toBeEnabled();
  const input = page.getByLabel("사진 선택");
  await input.setInputFiles({
    name: "fake.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("<svg></svg>"),
  });
  await expect(page.getByRole("main").getByRole("alert")).toContainText("JPEG·PNG·WebP");
  await input.setInputFiles({
    name: "large.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.alloc(20 * 1024 * 1024 + 1),
  });
  await expect(page.getByRole("main").getByRole("alert")).toContainText("20MB");
  const huge = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(huge);
  huge.write("IHDR", 12);
  huge.writeUInt32BE(10000, 16);
  huge.writeUInt32BE(10000, 20);
  await input.setInputFiles({ name: "huge.png", mimeType: "image/png", buffer: huge });
  await expect(page.getByRole("main").getByRole("alert")).toContainText("4,000만");
  huge.writeUInt32BE(1, 16);
  huge.writeUInt32BE(1, 20);
  await input.setInputFiles({ name: "broken.png", mimeType: "image/png", buffer: huge });
  await expect(page.getByRole("main").getByRole("alert")).toContainText("읽지 못했어요");
  await input.setInputFiles({
    name: "plain.png",
    mimeType: "image/png",
    buffer: await image(page, "image/png"),
  });
  await expect(
    page.getByRole("img", {
      name: "\uc120\ud0dd\ud55c \uc0ac\uc9c4\uc758 \uc555\ucd95 \ubbf8\ub9ac\ubcf4\uae30",
    }),
  ).toBeVisible();
  await expect(page.getByText("사진에 기기 정보가 없어요", { exact: true })).toBeVisible();
  await expect(page.getByText("사진에 촬영 시각이 없어요", { exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "압축본 내려받기" }).click();
  const output = await readFile((await (await downloading).path()) as string);
  await input.setInputFiles({ name: "compressed.webp", mimeType: "image/webp", buffer: output });
  await expect(page.getByText("compressed.webp", { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("img", {
      name: "\uc120\ud0dd\ud55c \uc0ac\uc9c4\uc758 \uc555\ucd95 \ubbf8\ub9ac\ubcf4\uae30",
    }),
  ).toHaveCount(0);
});

test("clearing during decode cannot restore an obsolete photo", async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.createImageBitmap.bind(window);
    window.createImageBitmap = (async (...args: unknown[]) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      return Reflect.apply(original, window, args);
    }) as typeof createImageBitmap;
  });
  await page.goto("/memories");
  await expect(page.getByLabel("\uc0ac\uc9c4 \uc120\ud0dd")).toBeEnabled();
  await page.getByLabel("사진 선택").setInputFiles({
    name: "cancel.png",
    mimeType: "image/png",
    buffer: await image(page, "image/png"),
  });
  await expect(page.getByRole("status")).toContainText("압축하고 있어요");
  await page.getByRole("button", { name: "선택 해제" }).click();
  await page.waitForTimeout(650); // Let the deliberately delayed decode finish after cancellation.
  await expect(
    page.getByRole("img", {
      name: "\uc120\ud0dd\ud55c \uc0ac\uc9c4\uc758 \uc555\ucd95 \ubbf8\ub9ac\ubcf4\uae30",
    }),
  ).toHaveCount(0);
  await expect(page.getByRole("status")).toHaveCount(0);
});
