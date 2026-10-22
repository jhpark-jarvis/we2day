"use server";

import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Profile } from "@/lib/profiles";

export async function saveDisplayName(name: string, version: number, requestId: string) {
  const result = await callApi<Profile>("/profiles", {
    method: "POST",
    body: JSON.stringify({
      display_name: name.trim(),
      expected_version: version,
      request_id: requestId,
    }),
  });
  if (result.data) {
    for (const path of ["/account", "/settings", "/memories"]) revalidatePath(path);
  }
  return result;
}
