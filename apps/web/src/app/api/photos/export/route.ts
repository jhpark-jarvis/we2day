import { type NextRequest, NextResponse } from "next/server";
import { callBinaryApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";

const headers = {
  "Cache-Control": "private, no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

export async function POST(request: NextRequest) {
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
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 4096) {
        await reader.cancel();
        return NextResponse.json(
          { error: "선택한 사진을 확인해 주세요." },
          { status: 413, headers },
        );
      }
      chunks.push(value);
    }
    const body = Buffer.concat(chunks).toString("utf8");
    const input = JSON.parse(body);
    if (!Array.isArray(input.ids) || input.ids.length < 1 || input.ids.length > 20)
      return NextResponse.json({ error: "사진을 1~20장 선택해 주세요." }, { status: 422, headers });
    const result = await callBinaryApi(
      "/photos/export",
      { method: "POST", body },
      "application/zip",
    );
    if (!result.ok)
      return NextResponse.json(
        {
          error:
            result.status === 401
              ? "다시 로그인해 주세요."
              : "사진이 바뀌었거나 파일을 읽지 못했어요. 목록을 새로고침한 뒤 다시 선택해 주세요.",
        },
        { status: result.status, headers },
      );
    return new Response(result.body, {
      headers: {
        ...headers,
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="we2day-photos.zip"',
      },
    });
  } catch {
    return NextResponse.json(
      { error: "사진 내보내기 요청을 읽지 못했어요." },
      { status: 422, headers },
    );
  } finally {
    reader.releaseLock();
  }
}
