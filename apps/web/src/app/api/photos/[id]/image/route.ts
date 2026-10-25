import { callImageApi } from "@/lib/api";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const headers = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))
    return new Response(null, { status: 404, headers });
  const query = new URL(request.url).searchParams;
  const trash = query.get("trash") === "true";
  const thumbnail = query.get("thumbnail") === "true";
  const conditions = new URLSearchParams();
  if (trash) conditions.set("trash", "true");
  if (thumbnail) conditions.set("thumbnail", "true");
  const result = await callImageApi(
    `/photos/${id}/image${conditions.size ? `?${conditions}` : ""}`,
  );
  const serverTiming = result.headers.get("Server-Timing");
  return new Response(result.body, {
    status: result.status,
    headers: {
      ...headers,
      ...(result.ok ? { "Content-Type": "image/webp" } : {}),
      ...(serverTiming ? { "Server-Timing": serverTiming } : {}),
    },
  });
}
