import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import type { MeetingDay } from "@/lib/meetings";

export async function GET(request: NextRequest) {
  const month = request.nextUrl.searchParams.get("month") || "";
  const headers = { "Cache-Control": "private, no-store" };
  if (!/^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(month))
    return NextResponse.json({ error: "날짜를 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<MeetingDay[]>(`/meetings?month=${month}`);
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
