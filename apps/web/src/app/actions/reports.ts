"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { DateReport, ReportContent } from "@/lib/reports";
export async function saveReport(
  id: string,
  content: ReportContent,
  shared: boolean,
  version: number,
  requestId: string,
) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { data: null, status: 422, error: "플랜을 확인해 주세요." };
  const result = await callApi<DateReport>(`/reports/${id}`, {
    method: "POST",
    body: JSON.stringify({ content, shared, expected_version: version, request_id: requestId }),
  });
  if (!result.error) revalidatePath(`/plans/${id}/report`);
  return result;
}
