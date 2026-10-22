"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Wish, WishContent } from "@/lib/wishlist";
export async function saveWish(
  id: string,
  content: WishContent,
  version: number,
  requestId: string,
) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { data: null, status: 422, error: "위시 항목을 확인해 주세요." };
  const result = await callApi<Wish>(`/wishlist/${id}`, {
    method: "POST",
    body: JSON.stringify({ ...content, expected_version: version, request_id: requestId }),
  });
  if (!result.error) revalidatePath("/wishlist");
  return result;
}
