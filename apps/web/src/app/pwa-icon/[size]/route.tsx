import { readFile } from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
export const runtime = "nodejs";
export async function GET(_request: Request, { params }: { params: Promise<{ size: string }> }) {
  const { size: value } = await params;
  if (value !== "192" && value !== "512" && value !== "180")
    return new Response(null, { status: 404 });
  const size = Number(value);
  const icon = await readFile(path.join(process.cwd(), "public", "brand", "icon.png"));
  return new ImageResponse(
    // biome-ignore lint/performance/noImgElement: local brand raster rendered into platform icon sizes
    <img
      src={`data:image/png;base64,${icon.toString("base64")}`}
      width={size}
      height={size}
      alt=""
    />,
    { width: size, height: size, headers: { "Cache-Control": "public, max-age=86400" } },
  );
}
