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
  const trash = new URL(request.url).searchParams.get("trash") === "true";
  const result = await callImageApi(`/photos/${id}/image${trash ? "?trash=true" : ""}`);
  return new Response(result.body, {
    status: result.status,
    headers: { ...headers, ...(result.ok ? { "Content-Type": "image/webp" } : {}) },
  });
}
