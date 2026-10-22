"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { Checklist, ChecklistContent } from "@/lib/checklists";

export async function saveChecklist(
  id: string,
  content: ChecklistContent,
  version: number,
  requestId: string,
) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { data: null, status: 422, error: "목록을 확인해 주세요." };
  const result = await callApi<Checklist>(`/checklists/${id}`, {
    method: "POST",
    body: JSON.stringify({ ...content, expected_version: version, request_id: requestId }),
  });
  if (!result.error) revalidatePath("/checklists");
  return result;
}
