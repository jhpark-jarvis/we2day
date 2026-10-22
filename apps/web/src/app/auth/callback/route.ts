import { type NextRequest, NextResponse } from "next/server";
import { getAuthConfig } from "@/lib/auth/config";
import { createAuthClient } from "@/lib/auth/server";

export async function GET(request: NextRequest) {
  const config = getAuthConfig();
  const origin = config?.site || "http://127.0.0.1:3000";
  const code = request.nextUrl.searchParams.get("code");
  let destination = "/login?error=callback";
  if (config && config.providers.length > 0 && code && !request.nextUrl.searchParams.has("error")) {
    const client = await createAuthClient();
    const result = await client?.auth.exchangeCodeForSession(code);
    if (result && !result.error && result.data.session) {
      const provider = result.data.session.user.app_metadata.provider;
      if (config.providers.some((allowed) => allowed === provider)) {
        destination = "/account";
      } else {
        await client?.auth.signOut({ scope: "local" });
      }
    }
  }
  // Never forward provider descriptions, tokens, or an arbitrary `next` URL.
  const target = new URL(destination, origin);
  // An explicit empty fragment prevents browsers inheriting the provider's error fragment.
  target.hash = "#";
  const response = NextResponse.redirect(target, 303);
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}
