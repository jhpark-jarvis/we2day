import "server-only";
import { type NextRequest, NextResponse } from "next/server";

export async function oauthProxy(request: NextRequest, path: string) {
  const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
  let body: Uint8Array | undefined;
  if (request.method === "POST") {
    const reader = request.body?.getReader();
    if (!reader) return NextResponse.json({ error: "invalid_request" }, { status: 400, headers });
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
      body = Buffer.concat(chunks);
    } finally {
      reader.releaseLock();
    }
  }
  try {
    const response = await fetch(
      `${process.env.WE2DAY_API_URL || "http://127.0.0.1:8000"}${path}${request.nextUrl.search}`,
      {
        method: request.method,
        body: body as BodyInit | undefined,
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(15000),
        headers: {
          "Content-Type": request.headers.get("content-type") || "application/json",
          Authorization: request.headers.get("authorization") || "",
          Accept: "application/json, text/event-stream",
          ...(request.headers.has("origin") ? { Origin: request.headers.get("origin") || "" } : {}),
          ...(request.headers.has("mcp-protocol-version")
            ? { "MCP-Protocol-Version": request.headers.get("mcp-protocol-version") || "" }
            : {}),
        },
      },
    );
    if (response.status === 303) {
      const location = response.headers.get("location") || "";
      const target = new URL(location);
      if (
        target.origin !== new URL(process.env.WE2DAY_SITE_URL || "http://127.0.0.1:3000").origin ||
        target.pathname !== "/settings/agents/authorize"
      )
        throw new Error("Invalid redirect");
      return new NextResponse(null, { status: 303, headers: { ...headers, Location: location } });
    }
    return new NextResponse(await response.arrayBuffer(), {
      status: response.status,
      headers: {
        ...headers,
        "Content-Type": "application/json",
        ...(response.headers.has("www-authenticate")
          ? { "WWW-Authenticate": response.headers.get("www-authenticate") || "" }
          : {}),
      },
    });
  } catch {
    return NextResponse.json({ error: "agent_unavailable" }, { status: 503, headers });
  }
}
