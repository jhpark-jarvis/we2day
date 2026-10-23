import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import type { FavoritePage } from "@/lib/favorite-places";
export async function GET(request: NextRequest) {
  const archived = request.nextUrl.searchParams.get("archived") || "false";
  const offset = request.nextUrl.searchParams.get("offset") || "0";
  const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
  if (!["true", "false"].includes(archived) || !/^\d{1,6}$/.test(offset) || Number(offset) > 100000)
    return NextResponse.json(
      { error: "장소 목록 조건을 확인해 주세요." },
      { status: 422, headers },
    );
  const result = await callApi<FavoritePage>(
    `/favorite-places?archived=${archived}&offset=${offset}`,
  );
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
