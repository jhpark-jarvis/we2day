import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import type { PlaceResults } from "@/lib/places";

const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };

export async function POST(request: NextRequest) {
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "검색어를 입력해 주세요." }, { status: 422, headers });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 2048) {
        await reader.cancel();
        return NextResponse.json({ error: "검색어가 너무 길어요." }, { status: 413, headers });
      }
      chunks.push(value);
    }
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (
      !body ||
      typeof body !== "object" ||
      Array.isArray(body) ||
      Object.keys(body).length !== 1 ||
      typeof body.query !== "string" ||
      !body.query.trim() ||
      body.query.length > 100 ||
      Array.from(body.query as string).some(
        (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
      )
    )
      return NextResponse.json(
        { error: "검색어를 1~100자로 입력해 주세요." },
        { status: 422, headers },
      );
    const result = await callApi<PlaceResults>("/places/search", {
      method: "POST",
      body: JSON.stringify({ query: body.query.trim() }),
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
