import { type NextRequest, NextResponse } from "next/server";
import { callApi } from "@/lib/api";
import type { Wish, WishOverview } from "@/lib/wishlist";
export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id");
  const archived = request.nextUrl.searchParams.get("archived") === "true";
  const offset = request.nextUrl.searchParams.get("offset") || "0";
  const view = request.nextUrl.searchParams.get("view");
  const headers = { "Cache-Control": "private, no-store" };
  if (
    (id && !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id)) ||
    !/^\d{1,6}$/.test(offset) ||
    Number(offset) > 100000 ||
    (view !== null && !["planned", "done", "archived"].includes(view))
  )
    return NextResponse.json({ error: "위시 항목을 확인해 주세요." }, { status: 422, headers });
  const result = await callApi<Wish | Wish[] | WishOverview>(
    id
      ? `/wishlist/${id}`
      : view
        ? `/wishlist/overview?view=${view}&offset=${offset}`
        : `/wishlist?archived=${archived}&offset=${offset}`,
  );
  return NextResponse.json(result.error ? { error: result.error } : result.data, {
    status: result.status,
    headers,
  });
}
