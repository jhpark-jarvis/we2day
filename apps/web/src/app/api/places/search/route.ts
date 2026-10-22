import { NextResponse } from "next/server";

// Compatibility response for clients opened before the Maps-link transition.
export async function POST() {
  return NextResponse.json(
    { error: "장소 검색은 네이버 지도에서 이용해 주세요." },
    {
      status: 410,
      headers: { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" },
    },
  );
}
