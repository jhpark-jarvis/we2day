"use server";
import { redirect } from "next/navigation";
import { callApi } from "@/lib/api";
export async function approveAgentOAuth(values: Record<string, string>, form: FormData) {
  if (form.get("consent") !== "on") return;
  const result = await callApi<{ redirect: string }>("/agent/oauth/approve", {
    method: "POST",
    body: JSON.stringify(values),
  });
  if (!result.data || result.error) redirect("/settings/agents/authorize?error=approval_failed");
  const url = new URL(result.data.redirect);
  if (url.origin !== "https://chatgpt.com" || url.pathname !== "/connector_platform_oauth_redirect")
    redirect("/settings/agents/authorize?error=invalid_callback");
  redirect(url.toString());
}
