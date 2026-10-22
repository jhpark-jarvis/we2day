import { type NextRequest, NextResponse } from "next/server";
import { callApi, callBinaryApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
export async function recordProxy(
  request: NextRequest,
  path: "/routes/history" | "/routes/export" | "/records/export",
) {
  const headers = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
  if (
    request.headers.get("origin") !== getAuthConfig()?.site ||
    request.headers.get("content-type")?.split(";")[0].trim() !== "application/json"
  )
    return NextResponse.json({ error: "요청한 화면을 확인해 주세요." }, { status: 403, headers });
  const reader = request.body?.getReader();
  if (!reader)
    return NextResponse.json({ error: "조건을 확인해 주세요." }, { status: 422, headers });
  let body = "",
    bytes = 0;
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 4096) {
        await reader.cancel();
        return NextResponse.json({ error: "요청이 너무 커요." }, { status: 413, headers });
      }
      body += decoder.decode(value, { stream: true });
    }
    body += decoder.decode();
    JSON.parse(body);
    if (path === "/routes/history") {
      const result = await callApi(path, { method: "POST", body });
      return NextResponse.json(result.error ? { error: result.error } : result.data, {
        status: result.status,
        headers,
      });
    }
    const type = path === "/routes/export" ? "application/geo+json" : "application/json";
    const response = await callBinaryApi(path, { method: "POST", body }, type);
    if (!response.ok)
      return NextResponse.json(
        {
          error:
            response.status === 413
              ? "한 번에 내보낼 수 있는 양을 넘었어요. 기간을 줄이거나 다른 종류를 선택해 주세요."
              : response.status === 422
                ? "최대 366일 범위와 내보낼 종류를 확인해 주세요."
                : response.status === 401
                  ? "다시 로그인해 주세요."
                  : "파일을 만들지 못했어요. 공간 연결과 데이터베이스 설정을 확인해 주세요.",
        },
        { status: response.status, headers },
      );
    return new Response(response.body, {
      headers: {
        ...headers,
        "Content-Type": type,
        "Content-Disposition": `attachment; filename="${path === "/routes/export" ? "we2day-routes.geojson" : "we2day-records.json"}"`,
      },
    });
  } catch {
    return NextResponse.json(
      { error: "요청을 읽지 못했어요. 다시 시도해 주세요." },
      { status: 422, headers },
    );
  } finally {
    reader.releaseLock();
  }
}
