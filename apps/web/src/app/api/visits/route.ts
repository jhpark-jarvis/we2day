import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import type { VisitProgress } from "@/lib/visits";

const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
const validId = (id: string) => /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id);

export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id") || "";
  const offset = request.nextUrl.searchParams.get("offset") || "0";
  if (!validId(id) || !/^\d{1,6}$/.test(offset) || Number(offset) > 100000)
    return NextResponse.json(
      { error: "플랜과 이전 기록 범위를 확인해 주세요." },
      { status: 422, headers },
    );
  const result = await callApi<VisitProgress[]>(`/plans/${id}/visits?offset=${offset}`);
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}

export async function POST(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id") || "";
  if (!validId(id))
    return NextResponse.json({ error: "플랜을 확인해 주세요." }, { status: 422, headers });
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "변경할 상태를 확인해 주세요." }, { status: 422, headers });
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
        return NextResponse.json({ error: "변경 요청이 너무 커요." }, { status: 413, headers });
      }
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode();
    JSON.parse(content);
    const result = await callApi<VisitProgress>(`/plans/${id}/visits`, {
      method: "POST",
      body: content,
    });
    return NextResponse.json(result.error ? { error: result.error } : result.data, {
      status: result.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "변경 요청을 읽지 못했어요." }, { status: 422, headers });
  } finally {
    reader.releaseLock();
  }
}
