import type { NextRequest } from "next/server";
import { oauthProxy } from "@/lib/agent-oauth-proxy";
export const dynamic = "force-dynamic";
export const GET = (request: NextRequest) => oauthProxy(request, "/agent/oauth/resource");
