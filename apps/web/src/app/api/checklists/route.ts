import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import type { Checklist } from "@/lib/checklists";

export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id");
  const archived = request.nextUrl.searchParams.get("archived") === "true";
  const offset = request.nextUrl.searchParams.get("offset") || "0";
  const headers = { "Cache-Control": "private, no-store" };
  if (
    (id && !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id)) ||
    !/^\d{1,6}$/.test(offset) ||
    Number(offset) > 100000
  )
    return NextResponse.json({ error: "목록을 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<Checklist | Checklist[]>(
    id ? `/checklists/${id}` : `/checklists?archived=${archived}&offset=${offset}`,
  );
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
