import { type NextRequest, NextResponse } from "next/server";

const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  const valid =
    request.method === "GET"
      ? path === "calendar" || /^(?:plans|appointments)\/[0-9a-f-]{36}$/i.test(path)
      : request.method === "POST" &&
        (path === "drafts" || /^(?:plans|appointments)\/[0-9a-f-]{36}\/changes$/i.test(path));
  if (!valid) return NextResponse.json({ error: "not_found" }, { status: 404, headers });
  const authorization = request.headers.get("authorization") || "";
  if (!/^Bearer w2d_agent_[0-9a-f]{64}$/.test(authorization))
    return NextResponse.json(
      { error: "invalid_agent_key" },
      {
        status: 401,
        headers: { ...headers, "WWW-Authenticate": "Bearer" },
      },
    );
  // Header-only credentials. Browser sessions and URL credentials are never accepted.
  const allowed = path === "calendar" ? ["start", "end", "offset"] : [];
  if ([...request.nextUrl.searchParams.keys()].some((key) => !allowed.includes(key)))
    return NextResponse.json({ error: "invalid_query" }, { status: 422, headers });
  let body: string | undefined;
  if (request.method === "POST") {
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json")
      return NextResponse.json({ error: "json_required" }, { status: 415, headers });
    const reader = request.body?.getReader();
    if (!reader) return NextResponse.json({ error: "invalid_body" }, { status: 422, headers });
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 40000) {
          await reader.cancel();
          return NextResponse.json({ error: "body_too_large" }, { status: 413, headers });
        }
        chunks.push(value);
      }
      body = Buffer.concat(chunks).toString("utf8");
    } catch {
      return NextResponse.json({ error: "invalid_body" }, { status: 422, headers });
    } finally {
      reader.releaseLock();
    }
  }
  try {
    const result = await fetch(
      `${process.env.WE2DAY_API_URL || "http://127.0.0.1:8000"}/agent/v1/${path}${request.nextUrl.search}`,
      {
        method: request.method,
        headers: { Authorization: authorization, "Content-Type": "application/json" },
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      },
    );
    return NextResponse.json(await result.json(), {
      status: result.status,
      headers: result.status === 401 ? { ...headers, "WWW-Authenticate": "Bearer" } : headers,
    });
  } catch {
    return NextResponse.json({ error: "agent_unavailable" }, { status: 503, headers });
  }
}
export const GET = forward;
export const POST = forward;
