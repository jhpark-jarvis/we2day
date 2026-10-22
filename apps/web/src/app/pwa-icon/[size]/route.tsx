import { ImageResponse } from "next/og";
export async function GET(_request: Request, { params }: { params: Promise<{ size: string }> }) {
  const { size: value } = await params;
  if (value !== "192" && value !== "512" && value !== "180")
    return new Response(null, { status: 404 });
  const size = Number(value);
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        alignItems: "center",
        justifyContent: "center",
        background: "#fcf9f4",
        color: "#46392f",
        fontSize: size * 0.36,
        fontWeight: 600,
        letterSpacing: -size * 0.025,
      }}
    >
      W2
    </div>,
    { width: size, height: size, headers: { "Cache-Control": "public, max-age=86400" } },
  );
}
