import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";
import { authCookieOptions, authFetch, getAuthConfig } from "@/lib/auth/config";

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const settings = request.nextUrl.pathname.startsWith("/api/agent/") ? null : getAuthConfig();
  if (settings) {
    const client = createServerClient(settings.url, settings.key, {
      global: { fetch: authFetch },
      cookieOptions: authCookieOptions(settings.site),
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll(values) {
          for (const { name, value } of values) request.cookies.set(name, value);
          response = NextResponse.next({ request });
          for (const { name, value, options } of values) response.cookies.set(name, value, options);
        },
      },
    });
    // Refresh cookies before Server Components run. Authorization still happens in the API.
    try {
      await client.auth.getClaims();
    } catch {
      // Malformed cookies and upstream outages cannot bypass the page/API identity checks.
    }
  }
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  matcher: [
    "/",
    "/login",
    "/settings/:path*",
    "/together",
    "/account/:path*",
    "/auth/:path*",
    "/couple",
    "/anniversaries",
    "/memories/:path*",
    "/plans/:path*",
    "/wishlist",
    "/checklists",
    "/goals",
    "/questions/:path*",
    "/timezones",
    "/roulette/:path*",
    "/today",
    "/reminders",
    "/calendar/:path*",
    "/api/:path*",
  ],
};
