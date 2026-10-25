import { type NextRequest, NextResponse } from "next/server";
import { callApi, timingHeaders } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import type { PhotoPage, SharedPhoto } from "@/lib/photos";

const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(request: NextRequest) {
  const month = request.nextUrl.searchParams.get("month");
  if (month !== null) {
    if (
      !/^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(month) ||
      ["date", "trash", "after"].some((key) => request.nextUrl.searchParams.has(key))
    )
      return NextResponse.json({ error: "앨범 월을 확인해 주세요." }, { status: 422, headers });
    const result = await callApi<{ month: string; days: { date: string; count: number }[] }>(
      `/photos/dates?month=${month}`,
    );
    return NextResponse.json(result.error ? { error: result.error } : result.data, {
      status: result.status,
      headers: { ...headers, ...timingHeaders(result) },
    });
  }
  const date = request.nextUrl.searchParams.get("date") || "";
  const after = request.nextUrl.searchParams.get("after");
  const trash = request.nextUrl.searchParams.get("trash") === "true";
  if (
    ((!trash || date) && !/^(20\d{2}|2100)-\d{2}-\d{2}$/.test(date)) ||
    (after && !uuid.test(after))
  )
    return NextResponse.json({ error: "날짜를 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<PhotoPage>(
    `/photos?${trash ? `trash=true${date ? `&date=${date}` : ""}` : `date=${date}`}${after ? `&after=${after}` : ""}`,
  );
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers: { ...headers, ...timingHeaders(result) },
  });
}

export async function POST(request: NextRequest) {
  // Cookie-authenticated mutation: fixed configured origin, JSON only, bounded streamed body.
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "사진을 선택해 주세요." }, { status: 422, headers });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 1_410_000) {
        await reader.cancel();
        return NextResponse.json({ error: "사진 요청이 너무 커요." }, { status: 413, headers });
      }
      chunks.push(value);
    }
    const content = Buffer.concat(chunks).toString("utf8");
    JSON.parse(content);
    const result = await callApi<SharedPhoto>("/photos", { method: "POST", body: content });
    return NextResponse.json(result.error ? { error: result.error } : result.data, {
      status: result.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "사진 요청을 읽지 못했어요." }, { status: 422, headers });
  } finally {
    reader.releaseLock();
  }
}
