// Local contract fixture only. This is not an OAuth provider or a production auth service.
import { createHash, createHmac, randomUUID } from "node:crypto";
import { createServer } from "node:http";

const origin = "http://127.0.0.1:54329";
const codes = new Map();
const sessions = new Map();
const users = new Map();
let pkceExchanges = 0;
let loseNextWriteResponse = false;
let loseNextPhotoResponse = false;
let loseNextPhotoDeleteResponse = false;
const photoObjects = new Map();

function issue(user, previous) {
  if (previous) sessions.delete(previous);
  const refresh = randomUUID();
  const part = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const payload = `${part({ alg: "HS256", typ: "JWT" })}.${part({ sub: user.id, aud: "authenticated", role: "authenticated", exp: Math.floor(Date.now() / 1000) + 3600, iss: `${origin}/auth/v1`, jti: randomUUID() })}`;
  const signature = process.env.WE2DAY_TEST_JWT_SECRET
    ? createHmac("sha256", process.env.WE2DAY_TEST_JWT_SECRET).update(payload).digest("base64url")
    : Buffer.from("synthetic-signature").toString("base64url");
  const token = `${payload}.${signature}`;
  users.set(token, user);
  sessions.set(refresh, { user, token });
  return {
    access_token: token,
    token_type: "bearer",
    expires_in: 3600,
    refresh_token: refresh,
    user,
  };
}

createServer(async (request, response) => {
  const url = new URL(request.url || "/", origin);
  response.setHeader("Content-Type", "application/json");
  response.setHeader("Cache-Control", "no-store");
  const send = (status, body) => {
    response.writeHead(status);
    response.end(JSON.stringify(body));
  };
  if (url.pathname === "/health") return send(200, { status: "fixture" });
  if (url.pathname === "/__auth-events") return send(200, { pkceExchanges });
  if (process.env.WE2DAY_TEST_PHOTO_STORAGE === "1" && process.env.WE2DAY_TEST_REST_URL) {
    if (url.pathname === "/__age-photo-trash") {
      // Disposable test database only. This helper never exists in product migrations.
      const result = await fetch(
        `${process.env.WE2DAY_TEST_REST_URL}/rpc/fixture_age_photo_trash`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${users.keys().next().value}`,
            "Content-Type": "application/json",
          },
          body: "{}",
        },
      );
      return send(result.status, { status: result.ok ? "aged" : "failed" });
    }
    if (url.pathname === "/__lose-photo-delete-response") {
      loseNextPhotoDeleteResponse = true;
      return send(200, { status: "armed" });
    }
    if (url.pathname === "/__lose-photo-upload-response") {
      loseNextPhotoResponse = true;
      return send(200, { status: "armed" });
    }
    if (url.pathname.startsWith("/storage/v1/object/")) {
      const token = request.headers.authorization?.replace(/^Bearer /, "");
      if (!users.has(token)) return send(401, { error: "invalid fixture token" });
      if (request.method === "DELETE" && url.pathname === "/storage/v1/object/we2day-photos") {
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        const { prefixes } = JSON.parse(Buffer.concat(chunks).toString());
        const name = prefixes[0];
        const result = await fetch(
          `${process.env.WE2DAY_TEST_REST_URL}/rpc/fixture_remove_object`,
          {
            method: "POST",
            headers: {
              Authorization: request.headers.authorization,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ p_name: name }),
          },
        );
        if (!result.ok) return send(403, { error: "fixture RLS denied" });
        const count = await result.json();
        if (count) photoObjects.delete(name);
        if (loseNextPhotoDeleteResponse) {
          loseNextPhotoDeleteResponse = false;
          return send(503, { error: "synthetic delete response lost" });
        }
        return send(200, []);
      }
      const upload = request.method === "POST";
      const prefix = upload
        ? "/storage/v1/object/we2day-photos/"
        : "/storage/v1/object/authenticated/we2day-photos/";
      if (!url.pathname.startsWith(prefix)) return send(404, { error: "not found" });
      const name = url.pathname.slice(prefix.length);
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const content = Buffer.concat(chunks);
      if (upload && photoObjects.has(name)) return send(409, { error: "Duplicate" });
      if (upload && (content.length > 1048576 || request.headers["content-type"] !== "image/webp"))
        return send(400, { error: "invalid fixture object" });
      const rpc = await fetch(
        `${process.env.WE2DAY_TEST_REST_URL}/rpc/${upload ? "fixture_put_object" : "fixture_read_object"}`,
        {
          method: "POST",
          headers: {
            Authorization: request.headers.authorization,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ p_name: name, ...(upload ? { p_bytes: content.length } : {}) }),
        },
      );
      if (!rpc.ok) return send(403, { error: "fixture RLS denied" });
      if (upload) {
        photoObjects.set(name, content);
        if (loseNextPhotoResponse) {
          loseNextPhotoResponse = false;
          return send(503, { error: "synthetic response lost after object write" });
        }
        return send(200, { Key: name });
      }
      if (!(await rpc.json()) || !photoObjects.has(name)) return send(404, { error: "not found" });
      response.setHeader("Content-Type", "image/webp");
      response.writeHead(200);
      return response.end(photoObjects.get(name));
    }
  }
  if (url.pathname === "/__lose-calendar-write-response" && process.env.WE2DAY_TEST_REST_URL) {
    loseNextWriteResponse = true;
    return send(200, { status: "armed" });
  }
  if (url.pathname.startsWith("/rest/v1/") && process.env.WE2DAY_TEST_REST_URL) {
    const token = request.headers.authorization?.replace(/^Bearer /, "");
    if (!users.has(token)) return send(401, { error: "invalid fixture token" });
    let body = "";
    for await (const chunk of request) body += chunk;
    try {
      const upstream = await fetch(
        `${process.env.WE2DAY_TEST_REST_URL}${url.pathname.slice(8)}${url.search}`,
        {
          method: request.method,
          headers: {
            Authorization: request.headers.authorization,
            "Content-Type": "application/json",
          },
          body: request.method === "GET" ? undefined : body,
        },
      );
      if (
        loseNextWriteResponse &&
        upstream.ok &&
        /\/(create_appointment|create_anniversary)$/.test(url.pathname)
      ) {
        loseNextWriteResponse = false;
        await upstream.text();
        return send(503, { error: "synthetic response lost after commit" });
      }
      response.writeHead(upstream.status);
      return response.end(await upstream.text());
    } catch {
      return send(503, { error: "fixture REST unavailable" });
    }
  }
  if (url.pathname === "/auth/v1/authorize") {
    const code = randomUUID();
    const provider = url.searchParams.get("provider");
    if (
      provider === "kakao" &&
      url.searchParams.get("scope") !== "profile_nickname,profile_image"
    ) {
      return send(400, { error: "Kakao must omit the email scope" });
    }
    const redirect = url.searchParams.get("redirect_to");
    const challenge = url.searchParams.get("code_challenge");
    if (!challenge || redirect !== "http://127.0.0.1:3100/auth/callback")
      return send(400, { error: "bad pkce request" });
    const user = {
      id:
        provider === "kakao"
          ? "22222222-2222-4222-8222-222222222222"
          : "11111111-1111-4111-8111-111111111111",
      aud: "authenticated",
      role: "authenticated",
      created_at: "2026-10-19T00:00:00Z",
      email: provider === "kakao" ? null : "synthetic@example.invalid",
      app_metadata: { provider },
      user_metadata: { full_name: "예시 사용자" },
      identities: [],
    };
    codes.set(code, { challenge, user });
    response.writeHead(302, { Location: `${redirect}?code=${code}` });
    return response.end();
  }
  if (url.pathname === "/auth/v1/token") {
    let body = "";
    for await (const chunk of request) body += chunk;
    const input = JSON.parse(body);
    if (url.searchParams.get("grant_type") === "password") {
      if (input.email === "throttled@login.we2day.invalid") {
        return send(429, { error_code: "over_request_rate_limit", msg: "synthetic throttle" });
      }
      if (input.email === "offline@login.we2day.invalid") {
        return send(503, { msg: "synthetic private upstream failure" });
      }
      const calendarUser =
        process.env.WE2DAY_TEST_REST_URL &&
        ["partner@login.we2day.invalid", "outsider@login.we2day.invalid"].includes(input.email);
      const accepted =
        (calendarUser && input.password === "fixture-password") ||
        (input.email === "member@login.we2day.invalid" && input.password === "fixture-password") ||
        (input.email === "spaced@login.we2day.invalid" &&
          input.password === "  fixture-password  ");
      if (!accepted)
        return send(400, { error_code: "invalid_credentials", msg: "synthetic invalid login" });
      return send(
        200,
        issue({
          id:
            input.email === "partner@login.we2day.invalid"
              ? "44444444-4444-4444-8444-444444444444"
              : input.email === "outsider@login.we2day.invalid"
                ? "55555555-5555-4555-8555-555555555555"
                : "33333333-3333-4333-8333-333333333333",
          aud: "authenticated",
          role: "authenticated",
          created_at: "2026-10-19T00:00:00Z",
          email: input.email,
          app_metadata: { provider: "email" },
          user_metadata: {},
          identities: [],
        }),
      );
    }
    if (url.searchParams.get("grant_type") === "pkce") {
      pkceExchanges += 1;
      const stored = codes.get(input.auth_code);
      codes.delete(input.auth_code);
      const challenge = createHash("sha256")
        .update(input.code_verifier || "")
        .digest("base64url");
      if (!stored || challenge !== stored.challenge)
        return send(400, { error_code: "bad_code_verifier", msg: "synthetic pkce failure" });
      return send(200, issue(stored.user));
    }
    const stored = sessions.get(input.refresh_token);
    if (!stored)
      return send(400, { error_code: "refresh_token_not_found", msg: "synthetic expired refresh" });
    users.delete(stored.token);
    return send(200, issue(stored.user, input.refresh_token));
  }
  const token = request.headers.authorization?.replace(/^Bearer /, "");
  const user = users.get(token);
  if (
    url.pathname === "/rest/v1/rpc/manage_push_subscription" &&
    !process.env.WE2DAY_TEST_REST_URL
  ) {
    return user
      ? send(404, { code: "PGRST202", message: "synthetic schema not installed" })
      : send(401, { error: "invalid fixture token" });
  }
  if (url.pathname === "/auth/v1/user") {
    return user
      ? send(200, user)
      : send(401, { error_code: "bad_jwt", msg: "synthetic invalid token" });
  }
  if (url.pathname === "/auth/v1/logout") {
    for (const [refresh, stored] of sessions) if (stored.token === token) sessions.delete(refresh);
    return send(204);
  }
  return send(404, { error: "fixture route not found" });
}).listen(54329, "127.0.0.1");
