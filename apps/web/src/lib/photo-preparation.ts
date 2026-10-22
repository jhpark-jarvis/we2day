const MAX_INPUT = 20 * 1024 * 1024;
const MAX_OUTPUT = 1024 * 1024;
const MAX_PIXELS = 40_000_000;

export type PreparedPhoto = {
  blob: Blob;
  width: number;
  height: number;
  originalBytes: number;
  filename: string;
  fileModified: string | null;
  device: string | null;
  capturedAt: string | null;
};

function dimensions(bytes: Uint8Array): [number, number] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const text = (offset: number, count: number) =>
    String.fromCharCode(...bytes.slice(offset, offset + count));
  if (
    bytes.length >= 24 &&
    bytes[0] === 137 &&
    text(1, 7) === "PNG\r\n\x1a\n" &&
    text(12, 4) === "IHDR"
  ) {
    return [view.getUint32(16), view.getUint32(20)];
  }
  if (bytes[0] === 255 && bytes[1] === 216) {
    let offset = 2;
    while (offset + 9 <= bytes.length) {
      if (bytes[offset] !== 255) break;
      const marker = bytes[offset + 1];
      if (marker === 255) {
        offset++;
        continue;
      }
      const length = view.getUint16(offset + 2);
      if (length < 2 || offset + length + 2 > bytes.length) break;
      if ([192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207].includes(marker)) {
        return [view.getUint16(offset + 7), view.getUint16(offset + 5)];
      }
      offset += length + 2;
    }
  }
  if (bytes.length >= 30 && text(0, 4) === "RIFF" && text(8, 4) === "WEBP") {
    const format = text(12, 4);
    if (format === "VP8X")
      return [
        1 + bytes[24] + (bytes[25] << 8) + (bytes[26] << 16),
        1 + bytes[27] + (bytes[28] << 8) + (bytes[29] << 16),
      ];
    if (format === "VP8L" && bytes[20] === 47)
      return [
        1 + bytes[21] + ((bytes[22] & 63) << 8),
        1 + (bytes[22] >> 6) + (bytes[23] << 2) + ((bytes[24] & 15) << 10),
      ];
    if (format === "VP8 " && text(23, 3) === "\x9d\x01\x2a")
      return [view.getUint16(26, true) & 16383, view.getUint16(28, true) & 16383];
  }
  throw new Error("JPEG·PNG·WebP 사진을 선택해 주세요. HEIC·GIF·SVG는 아직 지원하지 않아요.");
}

function stripControls(value: string): string {
  return [...value]
    .filter((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
    .join("");
}

function clean(value: unknown): string | null {
  return typeof value === "string" && value.trim()
    ? stripControls(value).trim().slice(0, 120) || null
    : null;
}

export async function preparePhoto(file: File, signal: AbortSignal): Promise<PreparedPhoto> {
  if (!file.size || file.size > MAX_INPUT)
    throw new Error("20MB 이하의 사진 한 장을 선택해 주세요.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  signal.throwIfAborted();
  const [originalWidth, originalHeight] = dimensions(bytes);
  if (!originalWidth || !originalHeight || originalWidth * originalHeight > MAX_PIXELS) {
    throw new Error("사진이 너무 커요. 4,000만 화소 이하의 사진을 선택해 주세요.");
  }
  let tags: { Make?: unknown; Model?: unknown; DateTimeOriginal?: unknown } = {};
  try {
    const { parse } = await import("exifr");
    tags =
      (await parse(bytes, {
        pick: ["Make", "Model", "DateTimeOriginal"],
        gps: false,
        reviveValues: false,
        makerNote: false,
        userComment: false,
      })) || {};
  } catch {
    // Metadata can be missing or damaged while the image itself remains usable.
  }
  signal.throwIfAborted();
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error("사진을 읽지 못했어요. 다른 사진을 선택해 주세요.");
  }
  const canvas = document.createElement("canvas");
  try {
    signal.throwIfAborted();
    if (bitmap.width * bitmap.height > MAX_PIXELS) throw new Error("사진 크기를 확인해 주세요.");
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("이 브라우저에서 사진을 처리하지 못했어요.");
    for (let attempt = 0; attempt < 5; attempt++) {
      const shrink = 0.8 ** attempt;
      canvas.width = Math.max(1, Math.round(bitmap.width * scale * shrink));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale * shrink));
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/webp", 0.82 - attempt * 0.07),
      );
      signal.throwIfAborted();
      if (blob?.type !== "image/webp")
        throw new Error("WebP 압축을 지원하는 브라우저에서 다시 시도해 주세요.");
      if (blob.size <= MAX_OUTPUT) {
        const capture = clean(tags.DateTimeOriginal);
        return {
          blob,
          width: canvas.width,
          height: canvas.height,
          originalBytes: file.size,
          filename: stripControls(file.name).slice(0, 255),
          fileModified: file.lastModified > 0 ? new Date(file.lastModified).toISOString() : null,
          device: [clean(tags.Make), clean(tags.Model)].filter(Boolean).join(" · ") || null,
          capturedAt:
            capture && /^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$/.test(capture)
              ? capture.replace(/^(\d{4}):(\d{2}):(\d{2})/, "$1-$2-$3")
              : null,
        };
      }
    }
    throw new Error("사진을 충분히 줄이지 못했어요. 더 작은 사진을 선택해 주세요.");
  } finally {
    bitmap.close();
    canvas.width = canvas.height = 1;
  }
}
