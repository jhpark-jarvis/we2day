import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";

export const maxDuration = 65;
const headers = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };

export async function POST(request: NextRequest) {
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "내용을 입력해 주세요." }, { status: 422, headers });
  try {
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 24000) {
        await reader.cancel();
        return NextResponse.json(
          { error: "대화가 길어요. 새 대화를 시작해 주세요." },
          { status: 413, headers },
        );
      }
      chunks.push(value);
    }
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    const result = await callApi("/ai/planner", {
      method: "POST",
      body: JSON.stringify(body),
      signal: request.signal,
    });
    return NextResponse.json(result.error ? { error: result.error } : result.data, {
      status: result.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "대화 요청을 읽지 못했어요." }, { status: 422, headers });
  } finally {
    reader.releaseLock();
  }
}
