// WE2DAY offline notice v1. Deliberately no response cache or background writes.
const offlineDocument = `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>연결 확인 · WE2DAY</title><style>body{margin:0;background:#fcf9f4;color:#46392f;font:16px/1.8 system-ui,sans-serif}main{max-width:440px;margin:12vh auto;padding:28px}strong{font:600 30px Arial,sans-serif;letter-spacing:-2px}h1{font-size:24px;font-weight:500}a{display:inline-block;padding:12px 0;color:inherit}</style><main><strong>WE2DAY</strong><h1>인터넷 연결을 확인해 주세요</h1><p>연결이 돌아오면 일정과 기록을 다시 불러올 수 있어요.</p><p>이 화면에는 두 사람의 기록이 저장되어 있지 않아요.</p><a href="/">연결 후 다시 열기</a></main></html>`;

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("message", (event) => {
  if (event.data?.type === "WE2DAY_APPLY_UPDATE") event.waitUntil(self.skipWaiting());
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    request.method !== "GET" ||
    request.mode !== "navigate" ||
    url.origin !== self.location.origin ||
    /^\/(?:api|auth)(?:\/|$)/.test(url.pathname)
  )
    return;
  event.respondWith(
    fetch(request).catch(
      () =>
        new Response(offlineDocument, {
          status: 503,
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "Content-Security-Policy":
              "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
          },
        }),
    ),
  );
});

// Payloads never choose visible text, navigation targets, or external resources.
self.addEventListener("push", (event) => {
  event.waitUntil(
    self.registration.showNotification("WE2DAY", {
      body: "알림이 도착했어요. 앱에서 확인해 주세요.",
      icon: "/pwa-icon/192?v=brand1",
      tag: "we2day-notice",
      data: { path: "/reminders" },
    }),
  );
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL("/reminders", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin) {
          await client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })(),
  );
});
