"use server";
import { revalidatePath } from "next/cache";
import { callApi } from "@/lib/api";
import type { DatePlan, PlanAction, PlanContent } from "@/lib/plans";
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
  }
  return result;
}
