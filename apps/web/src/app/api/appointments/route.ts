import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import type { Appointment } from "@/lib/shared-calendar";

export async function GET(request: NextRequest) {
  const month = request.nextUrl.searchParams.get("month") || "";
  if (!/^(20[0-9]{2}|2100)-(0[1-9]|1[0-2])$/.test(month)) {
    return NextResponse.json(
      { error: "날짜를 확인해 주세요." },
      {
        status: 422,
        headers: { "Cache-Control": "private, no-store" },
      },
    );
  }
  const result = await callApi<Appointment[]>(`/appointments?month=${month}`);
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers: { "Cache-Control": "private, no-store" },
  });
}
