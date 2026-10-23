import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import type { RecordPage } from "@/lib/records";

const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
export async function POST(request: NextRequest) {
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "검색 조건을 확인해 주세요." }, { status: 422, headers });
  let content = "";
  const decoder = new TextDecoder();
  let bytes = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 4096) {
        await reader.cancel();
        return NextResponse.json({ error: "검색 요청이 너무 커요." }, { status: 413, headers });
      }
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode();
    JSON.parse(content);
    const result = await callApi<RecordPage>("/records/search", {
      method: "POST",
      body: content,
    });
    return NextResponse.json(result.error ? { error: result.error } : result.data, {
      status: result.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "검색 요청을 읽지 못했어요." }, { status: 422, headers });
  } finally {
    reader.releaseLock();
  }
}

export async function GET(request: NextRequest) {
  const month = request.nextUrl.searchParams.get("month") || "";
  if (!/^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(month))
    return NextResponse.json({ error: "조회할 월을 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<import("@/lib/monthly").MonthlyMemories>(
    `/memories/month?month=${month}`,
  );
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
