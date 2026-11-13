import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
function fixture(fetch) {
  const listeners = {};
  let skips = 0,
    claims = 0;
  const self = {
    location: { origin: "https://example.test" },
    addEventListener: (name, fn) => (listeners[name] = fn),
    clients: {
      claim: async () => {
        claims++;
      },
    },
    skipWaiting: async () => {
      skips++;
    },
  };
  // No CacheStorage or IndexedDB is supplied: accidental private caching fails the test.
  vm.runInNewContext(source, { self, fetch, URL, Response });
  const request = (path, mode = "navigate", method = "GET") => {
    let response;
    listeners.fetch({
      request: { url: new URL(path, self.location.origin).href, mode, method },
      respondWith: (value) => (response = value),
    });
    return response;
  };
  return { self, listeners, request, skips: () => skips, claims: () => claims };
}
test("offline document contains no private response and private subrequests pass untouched", async () => {
  let calls = 0;
  const f = fixture(async () => {
    calls++;
    throw new TypeError("offline");
  });
  const offline = await f.request("/plans?private-value=must-not-reflect");
  assert.equal(offline.status, 503);
  const body = await offline.text();
  assert.ok(body.includes("인터넷 연결"));
  assert.ok(!body.includes("private-value"));
  assert.equal(offline.headers.get("cache-control"), "no-store");
  for (const [path, mode, method] of [
    ["/api/photos", "navigate", "GET"],
    ["/auth/callback", "navigate", "GET"],
    ["/plans", "cors", "GET"],
    ["/plans", "navigate", "POST"],
    ["https://other.test/", "navigate", "GET"],
  ])
    assert.equal(f.request(path, mode, method), undefined);
  assert.equal(calls, 1);
});
test("online errors and successful private documents pass through without retention", async () => {
  for (const status of [200, 401, 503]) {
    const response = new Response("private", { status });
    const f = fixture(async () => response);
    assert.equal(await f.request("/"), response);
  }
});
test("worker activates and accepts only the explicit update message", async () => {
  const f = fixture(async () => new Response());
  let pending;
  const event = { waitUntil: (value) => (pending = value) };
  f.listeners.activate(event);
  await pending;
  assert.equal(f.claims(), 1);
  f.listeners.message({ ...event, data: { type: "other" } });
  assert.equal(f.skips(), 0);
  f.listeners.message({ ...event, data: { type: "WE2DAY_APPLY_UPDATE" } });
  await pending;
  assert.equal(f.skips(), 1);
});

test("new appointment notice uses fixed text and opens only its validated local date", async () => {
  const f = fixture(async () => new Response());
  const messages = [],
    opened = [];
  f.self.registration = {
    showNotification: async (title, value) => messages.push({ title, ...value }),
  };
  f.self.clients.matchAll = async () => [];
  f.self.clients.openWindow = async (path) => opened.push(path);
  const value = {
    type: "we2day-appointment-created-v1",
    date: "2026-11-13",
    event: "00000000-0000-0000-0000-000000000001",
    body: "must-not-reflect",
    path: "https://evil.test",
  };
  let task;
  f.listeners.push({
    data: { json: () => value },
    waitUntil: (p) => {
      task = p;
    },
  });
  await task;
  assert.equal(messages[0].body, "새 일정이 추가됐어요. 앱에서 확인해 주세요.");
  assert.equal(messages[0].data.path, "/?date=2026-11-13");
  f.listeners.notificationclick({
    notification: { ...messages[0], close() {} },
    waitUntil: (p) => {
      task = p;
    },
  });
  await task;
  assert.equal(opened[0], "https://example.test/?date=2026-11-13");
  for (const invalid of [
    { ...value, date: "2026-02-30" },
    { ...value, type: "unknown" },
    { ...value, event: "<script>" },
    null,
  ]) {
    f.listeners.push({
      data: { json: () => invalid },
      waitUntil: (p) => {
        task = p;
      },
    });
    await task;
    assert.equal(messages.at(-1).data.path, "/reminders");
    assert.equal(messages.at(-1).body.includes("must-not-reflect"), false);
  }
  f.listeners.notificationclick({
    notification: { data: { path: "https://evil.test" }, close() {} },
    waitUntil: (p) => {
      task = p;
    },
  });
  await task;
  assert.equal(opened.at(-1), "https://example.test/reminders");
});
