import { NextResponse } from "next/server";
import { callApi } from "@/lib/api";
export async function GET() {
  const result = await callApi("/push/config");
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers: { "Cache-Control": "private, no-store" },
  });
}
