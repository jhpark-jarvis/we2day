// Loopback-only synthetic SSE upstream for the real authenticated Next BFF.
import http from "node:http";

const pending = new Map();
const closed = new Set();
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const server = http.createServer(async (req, res) => {
  if (req.url === "/health") return res.end("ok");
  if (req.url?.startsWith("/fixture/")) {
    const url = new URL(req.url, "http://127.0.0.1:8101");
    const mode = url.searchParams.get("case");
    const item = pending.get(mode);
    res.setHeader("Content-Type", "application/json");
    if (url.pathname === "/fixture/state")
      return res.end(JSON.stringify({ pending: Boolean(item), closed: closed.has(mode) }));
    if (!item) {
      res.statusCode = 409;
      return res.end("{}");
    }
    if (url.pathname === "/fixture/advance") {
      const stage = url.searchParams.get("stage");
      if (!["model", "validate", "persist"].includes(stage)) {
        res.statusCode = 422;
        return res.end("{}");
      }
      item.res.write(frame("progress", { stage }));
    } else if (url.pathname === "/fixture/finish") {
      if (mode === "실패") item.res.end(frame("error", { code: "ai_timeout", status: 503 }));
      else if (mode === "끊김") item.res.destroy();
      else {
        const result = {
          reply: "합성 장소 후보를 확인해 주세요.",
          version: item.body.version + 1,
          conversation_id: item.body.conversation_id,
          plan: null,
          checks: [],
          context: { region: "중랑구", search_scope: { area: "중랑구", kinds: ["cafe"] } },
          tools: [{ name: "search_places", status: "ok", count: 5 }],
          candidates: Array.from({ length: 5 }, (_, i) => ({
            ref: `naver:stream${i}`,
            source: "naver",
            title: `합성 SSE 카페 ${i + 1}`,
            address: "서울특별시 중랑구 신내동 1",
            destination: `합성 SSE 카페 ${i + 1} (서울특별시 중랑구 신내동 1)`,
          })),
        };
        // Deliberately split a Korean UTF-8 character and SSE delimiter across writes.
        const bytes = Buffer.from(frame("result", result));
        const split = bytes.indexOf(Buffer.from("합성")) + 1;
        item.res.write(bytes.subarray(0, split));
        item.res.write(bytes.subarray(split, bytes.length - 1));
        item.res.end(bytes.subarray(bytes.length - 1));
      }
    }
    return res.end("{}");
  }
  const chunks = [];
  let length = 0;
  for await (const chunk of req) {
    length += chunk.length;
    if (length > 24000) {
      res.statusCode = 413;
      return res.end();
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks);
  const body = raw.length ? JSON.parse(raw.toString()) : null;
  const mode = body?.messages
    ?.at(-1)
    ?.content?.match(/^합성 SSE (정상|실패|끊김|중단|구버전)$/)?.[1];
  if (req.url === "/ai/planner" && mode) {
    if (
      req.headers.accept !== "text/event-stream" ||
      !req.headers.authorization?.startsWith("Bearer ")
    ) {
      res.statusCode = 403;
      return res.end();
    }
    if (mode === "구버전") {
      res.setHeader("Content-Type", "application/json");
      return res.end(
        JSON.stringify({
          reply: "합성 구버전 응답",
          version: body.version + 1,
          plan: null,
          context: {},
          candidates: [],
          checks: [],
        }),
      );
    }
    if (pending.has(mode) || pending.size >= 8) {
      res.statusCode = 409;
      return res.end();
    }
    closed.delete(mode);
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "private, no-store",
    });
    res.write(frame("progress", { stage: "search" }));
    const timeout = setTimeout(() => res.destroy(), 30000);
    pending.set(mode, { res, body });
    res.on("close", () => {
      clearTimeout(timeout);
      pending.delete(mode);
      closed.add(mode);
    });
    return;
  }
  // Ordinary fixture API requests retain the real FastAPI + temporary RLS DB flow.
  const upstream = http.request(
    { hostname: "127.0.0.1", port: 8100, path: req.url, method: req.method, headers: req.headers },
    (reply) => {
      res.writeHead(reply.statusCode || 502, reply.headers);
      reply.pipe(res);
    },
  );
  upstream.on("error", () => {
    res.statusCode = 502;
    res.end();
  });
  res.on("close", () => upstream.destroy());
  upstream.end(raw);
});
server.listen(8101, "127.0.0.1");
