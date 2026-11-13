import { NextResponse } from "next/server";
import { callApi, timingHeaders } from "@/lib/api";
import type { DatePlan } from "@/lib/plans";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const headers = { "Cache-Control": "private, no-store" };
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return NextResponse.json({ error: "약속을 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<DatePlan | null>(`/appointments/${id}/course`);
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers: { ...headers, ...timingHeaders(result) },
  });
}
