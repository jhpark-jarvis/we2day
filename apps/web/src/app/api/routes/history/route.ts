import type { NextRequest } from "next/server";
import { recordProxy } from "@/lib/record-proxy";
export async function POST(request: NextRequest) {
  return recordProxy(request, "/routes/history");
}
