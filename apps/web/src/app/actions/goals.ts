"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Goal, GoalContent } from "@/lib/goals";

export async function saveGoal(
  id: string,
  content: GoalContent,
  version: number,
  requestId: string,
) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { data: null, status: 422, error: "목표를 확인해 주세요." };
  const result = await callApi<Goal>(`/goals/${id}`, {
    method: "POST",
    body: JSON.stringify({ ...content, expected_version: version, request_id: requestId }),
  });
  if (!result.error) revalidatePath("/goals");
  return result;
}
