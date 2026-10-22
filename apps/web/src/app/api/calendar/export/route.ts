import { type NextRequest, NextResponse } from "next/server";
import { callBinaryApi } from "@/lib/api";
export async function GET(request: NextRequest) {
  const month = request.nextUrl.searchParams.get("month") || "";
  const anniversaries = request.nextUrl.searchParams.get("anniversaries") || "true";
  const notes = request.nextUrl.searchParams.get("notes") || "false";
  const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
  if (
    !/^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(month) ||
    !["true", "false"].includes(anniversaries) ||
    !["true", "false"].includes(notes)
  )
    return NextResponse.json(
      { error: "내보낼 월과 포함할 내용을 확인해 주세요." },
      { status: 422, headers },
    );
  const response = await callBinaryApi(
    `/calendar/export?month=${month}&anniversaries=${anniversaries}&notes=${notes}`,
    {},
    "text/calendar; charset=utf-8",
  );
  if (!response.ok)
    return NextResponse.json(
      {
        error:
          response.status === 401
            ? "로그인이 필요해요."
            : response.status === 413
              ? "한 번에 내보낼 수 있는 일정을 초과했어요. 범위를 줄여 주세요."
              : "파일을 만들지 못했어요. 공간 연결과 서버 상태를 확인해 주세요.",
      },
      { status: response.status, headers },
    );
  return new Response(response.body, {
    headers: {
      ...headers,
      "Content-Type": "text/calendar; charset=utf-8",
      "Content-Disposition": `attachment; filename="we2day-calendar-${month}.ics"`,
    },
  });
}
