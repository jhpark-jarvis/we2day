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
    <div style={{ display: "flex", width: size, height: size, backgroundColor: "#3e2b23" }}>
      <div
        style={{
          display: "flex",
          width: size,
          height: size,
          borderRadius: "24%",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* The supplied artwork has a white margin and pre-rounded corners. Keep the mark,
            crop that margin, and fill the platform icon square before the OS applies its mask. */}
        {/* biome-ignore lint/performance/noImgElement: local brand raster rendered into platform icon sizes */}
        <img
          src={`data:image/png;base64,${icon.toString("base64")}`}
          width={Math.ceil(size * 1.06)}
          height={Math.ceil(size * 1.06)}
          style={{ position: "absolute", left: -size * 0.03, top: -size * 0.03 }}
          alt=""
        />
      </div>
    </div>,
    { width: size, height: size, headers: { "Cache-Control": "public, max-age=86400" } },
  );
}
