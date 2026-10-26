import { type NextRequest, NextResponse } from "next/server";
import { oauthProxy } from "@/lib/agent-oauth-proxy";

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (
    !(
      (request.method === "GET" && path === "authorize") ||
      (request.method === "POST" && path === "token")
    )
  )
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  return oauthProxy(request, `/agent/oauth/${path}`);
}
export const GET = forward;
export const POST = forward;
