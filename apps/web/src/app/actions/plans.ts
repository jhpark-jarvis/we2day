"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { callApi } from "@/lib/api";
import type { DatePlan, PlanAction, PlanContent } from "@/lib/plans";
export async function deletePlanDraft(id: string, expectedVersion: number) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { error: "플랜을 확인해 주세요.", status: 422 };
  const result = await callApi(`/plans/${id}`, {
    method: "DELETE",
    body: JSON.stringify({ expected_version: expectedVersion }),
  });
  if (!result.error) revalidatePath("/plans");
  return result;
}
export async function changePlan(
  id: string,
  action: PlanAction,
  content: PlanContent | null,
  version: number,
  appointmentVersion: number,
  request: string,
) {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return { data: null, status: 422, error: "플랜을 확인해 주세요." };
  const result = await callApi<DatePlan>(`/plans/${id}`, {
    method: "POST",
    body: JSON.stringify({
      action,
      content,
      expected_version: version,
      expected_appointment_version: appointmentVersion,
      request_id: request,
    }),
  });
  if (!result.error) {
    revalidatePath("/");
    revalidatePath("/plans");
    revalidatePath("/today");
    if (action === "confirm" && result.data?.published_content)
      redirect(`/?date=${encodeURIComponent(result.data.published_content.date)}`);
  }
  return result;
}
