"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { callApi } from "@/lib/api";
import { type AuthProvider, getAuthConfig } from "@/lib/auth/config";
import { createAuthClient } from "@/lib/auth/server";
import { normalizeUsername, usernameAddress } from "@/lib/auth/username";

export async function signInWithUsername(_previous: { error: string }, form: FormData) {
  const config = getAuthConfig();
  if (!config?.passwordEnabled) return { error: "지금은 아이디 로그인을 사용할 수 없어요." };
  const username = normalizeUsername(form.get("username"));
  const password = form.get("password");
  const invalid = { error: "아이디 또는 비밀번호를 확인해 주세요." };
  if (!username || typeof password !== "string" || !password || password.length > 256)
    return invalid;
  const client = await createAuthClient();
  if (!client) return { error: "로그인을 준비 중이에요. 잠시 후 다시 시도해 주세요." };
  let result: Awaited<ReturnType<typeof client.auth.signInWithPassword>>;
  try {
    result = await client.auth.signInWithPassword({ email: usernameAddress(username), password });
  } catch {
    return { error: "연결하지 못했어요. 잠시 후 다시 시도해 주세요." };
  }
  if (result.error) {
    if (result.error.status === 429) return { error: "시도가 많아요. 잠시 후 다시 시도해 주세요." };
    if (!result.error.status || result.error.status >= 500) {
      return { error: "연결하지 못했어요. 잠시 후 다시 시도해 주세요." };
    }
    return invalid;
  }
  if (!result.data.session) return invalid;
  redirect("/account");
}

export async function signIn(form: FormData) {
  const config = getAuthConfig();
  const provider = form.get("provider") as AuthProvider;
  if (!config?.providers.includes(provider)) redirect("/login?error=unavailable");
  // PKCE cookies and the callback must use the same host.
  if ((await headers()).get("host") !== new URL(config.site).host) {
    redirect(`${config.site}/login`);
  }
  const client = await createAuthClient();
  if (!client) redirect("/login?error=unavailable");
  const { data, error } = await client.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: `${config.site}/auth/callback`,
      skipBrowserRedirect: true,
      // Override the provider's default email scope for non-Biz Kakao apps.
      queryParams: provider === "kakao" ? { scope: "profile_nickname,profile_image" } : undefined,
    },
  });
  if (error || !data.url) redirect("/login?error=start");
  redirect(data.url);
}

export async function signOut() {
  const client = await createAuthClient();
  if (client) {
    const { data } = await client.auth.getSession();
    if (data.session) {
      const revoked = await callApi("/push/device", {
        method: "POST",
        body: JSON.stringify({ action: "remove_all" }),
      });
      if (revoked.error) redirect("/account?error=push-revoke");
    }
    const { error } = await client.auth.signOut({ scope: "local" });
    if (error) redirect("/account?error=signout");
  }
  redirect("/login?notice=signed-out");
}
