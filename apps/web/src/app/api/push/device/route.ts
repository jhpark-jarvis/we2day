import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";

export async function POST(request: NextRequest) {
  const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "요청을 확인해 주세요." }, { status: 422, headers });
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 4096) {
        await reader.cancel();
        return NextResponse.json({ error: "요청이 너무 커요." }, { status: 413, headers });
      }
      chunks.push(value);
    }
    const body = Buffer.concat(chunks).toString("utf8");
    JSON.parse(body);
    const result = await callApi("/push/device", { method: "POST", body });
    return NextResponse.json(result.error ? { error: result.error } : result.data, {
      status: result.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "요청을 읽지 못했어요." }, { status: 422, headers });
  } finally {
    reader.releaseLock();
  }
}
