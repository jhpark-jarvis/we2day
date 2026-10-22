import "server-only";

export const providers = ["google", "kakao"] as const;
export type AuthProvider = (typeof providers)[number];

export function getAuthConfig() {
  const url = process.env.WE2DAY_SUPABASE_URL?.trim();
  const key = process.env.WE2DAY_SUPABASE_PUBLISHABLE_KEY?.trim();
  const site = process.env.WE2DAY_SITE_URL?.trim() || "http://127.0.0.1:3000";
  if (!url || !key || key.startsWith("sb_secret_")) return null;
  try {
    const project = new URL(url);
    const origin = new URL(site);
    if (!allowedUrl(project) || !allowedUrl(origin) || origin.pathname !== "/") return null;
    const enabled = (process.env.WE2DAY_AUTH_PROVIDERS ?? "password")
      .split(",")
      .map((s) => s.trim());
    return {
      url: project.origin,
      key,
      site: origin.origin,
      passwordEnabled: enabled.includes("password"),
      providers: providers.filter((provider) => enabled.includes(provider)),
    };
  } catch {
    return null;
  }
}

function allowedUrl(url: URL) {
  return (
    !url.username &&
    !url.password &&
    !url.search &&
    !url.hash &&
    (url.protocol === "https:" ||
      (url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname)))
  );
}

export function authCookieOptions(site: string) {
  // Auth is server-only: no browser Supabase client needs access to these cookies.
  return { httpOnly: true, sameSite: "lax" as const, secure: site.startsWith("https:"), path: "/" };
}

export const authFetch: typeof fetch = (input, init) =>
  fetch(input, { ...init, cache: "no-store", signal: AbortSignal.timeout(10_000) });
