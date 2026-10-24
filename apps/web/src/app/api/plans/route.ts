import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { isSupportedDate } from "@/lib/calendar";
import type { DatePlan } from "@/lib/plans";
export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id");
  const date = request.nextUrl.searchParams.get("date");
  const archived = request.nextUrl.searchParams.get("archived") === "true";
  const offset = request.nextUrl.searchParams.get("offset") || "0";
  const headers = { "Cache-Control": "private, no-store" };
  if (
    (date !== null && (!isSupportedDate(date) || Boolean(id))) ||
    (id && !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id)) ||
    !/^\d{1,6}$/.test(offset) ||
    Number(offset) > 100000
  )
    return NextResponse.json({ error: "플랜을 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<DatePlan[] | DatePlan>(
    date
      ? `/timeline?date=${date}&offset=${offset}`
      : id
        ? `/plans/${id}`
        : `/plans?archived=${archived}&offset=${offset}`,
  );
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
