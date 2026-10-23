"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { FavoriteContent, FavoritePlace } from "@/lib/favorite-places";
export async function saveFavoritePlace(
  id: string,
  content: FavoriteContent,
  version: number,
  requestId: string,
) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { data: null, status: 422, error: "장소 항목을 확인해 주세요." };
  const result = await callApi<FavoritePlace>(`/favorite-places/${id}`, {
    method: "POST",
    body: JSON.stringify({ ...content, expected_version: version, request_id: requestId }),
  });
  if (!result.error) revalidatePath("/settings/places");
  return result;
}
