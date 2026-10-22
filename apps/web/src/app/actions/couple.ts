"use server";

import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Couple, CoupleState } from "@/lib/shared-calendar";

export async function createCouple(_previous: CoupleState): Promise<CoupleState> {
  const result = await callApi<Couple>("/couple", { method: "POST" });
  if (!result.error) {
    revalidatePath("/couple");
    revalidatePath("/");
  }
  return { error: result.error };
}

export async function createInvite(_previous: CoupleState): Promise<CoupleState> {
  const result = await callApi<{ token: string; expires_at: string }>("/couple/invites", {
    method: "POST",
  });
  return { error: result.error, ...result.data };
}

export async function acceptInvite(_previous: CoupleState, form: FormData): Promise<CoupleState> {
  const token = form.get("token");
  if (typeof token !== "string" || !/^[0-9a-f]{64}$/.test(token.trim())) {
    return { error: "초대 코드를 확인해 주세요." };
  }
  const result = await callApi<Couple>("/couple/accept", {
    method: "POST",
    body: JSON.stringify({ token: token.trim() }),
  });
  if (!result.error) {
    revalidatePath("/couple");
    revalidatePath("/");
  }
  return { error: result.error };
}
