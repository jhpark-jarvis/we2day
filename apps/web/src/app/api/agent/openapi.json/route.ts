import { NextResponse } from "next/server";
import { getAuthConfig } from "@/lib/auth/config";

export async function GET() {
  const headers = { "Cache-Control": "no-store" };
  const site = getAuthConfig()?.site;
  if (!site)
    return NextResponse.json({ error: "configuration_required" }, { status: 503, headers });
  try {
    const response = await fetch(
      `${process.env.WE2DAY_API_URL || "http://127.0.0.1:8000"}/agent/openapi.json`,
      {
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!response.ok) throw new Error("Unavailable");
    const schema = await response.json();
    schema.servers = [{ url: `${site.replace(/\/$/, "")}/api/agent/v1` }];
    return NextResponse.json(schema, { headers });
  } catch {
    return NextResponse.json({ error: "agent_unavailable" }, { status: 503, headers });
  }
}
