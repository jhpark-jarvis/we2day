"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import { isSupportedDate } from "@/lib/calendar";
import type { MeetingRoute, RouteContent } from "@/lib/routes";
export async function saveRoute(
  date: string,
  content: RouteContent,
  version: number,
  request: string,
) {
  if (!isSupportedDate(date)) return { data: null, status: 422, error: "날짜를 확인해 주세요." };
  const result = await callApi<MeetingRoute>(`/routes/${date}`, {
    method: "POST",
    body: JSON.stringify({ ...content, expected_version: version, request_id: request }),
  });
  if (!result.error) revalidatePath("/");
  return result;
}
