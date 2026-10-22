import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { cache } from "react";
import { authCookieOptions, authFetch, getAuthConfig } from "@/lib/auth/config";

export const createAuthClient = cache(async () => {
  const config = getAuthConfig();
  if (!config) return null;
  const store = await cookies();
  return createServerClient(config.url, config.key, {
    global: { fetch: authFetch },
    cookieOptions: authCookieOptions(config.site),
    cookies: {
      getAll: () => store.getAll(),
      setAll(values) {
        try {
          for (const { name, value, options } of values) store.set(name, value, options);
        } catch {
          // Server Components cannot write cookies; Proxy persists refreshes before rendering.
        }
      },
    },
  });
});
