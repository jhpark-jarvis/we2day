import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { isSupportedDate } from "@/lib/calendar";
import type { MeetingRoute } from "@/lib/routes";
export async function GET(request: NextRequest) {
  const date = request.nextUrl.searchParams.get("date") || "";
  const headers = { "Cache-Control": "private, no-store" };
  if (!isSupportedDate(date))
    return NextResponse.json({ error: "날짜를 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<MeetingRoute[]>(`/routes?date=${date}`);
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
