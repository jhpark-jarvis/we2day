import assert from "node:assert/strict";
import { test } from "node:test";

// No browser, provider calls, credentials, or database. Exercise the SDK lifecycle only.
async function fixture(name) {
  const scripts = [];
  let timer;
  const maps = { Map: function SyntheticMap() {} };
  globalThis.window = {
    setTimeout(callback) {
      timer = callback;
      return 1;
    },
    clearTimeout() {},
    dispatchEvent() {},
  };
  globalThis.document = {
    createElement() {
      return {
        remove() {
          this.removed = true;
        },
      };
    },
    head: {
      append(script) {
        scripts.push(script);
      },
    },
  };
  const { loadNaverMap } = await import(`../src/lib/naver-map.ts?case=${name}`);
  return { scripts, maps, loadNaverMap, timeout: () => timer() };
}

test("an early callback waits for Map and the final script load", async () => {
  const f = await fixture("early");
  const pending = f.loadNaverMap("synthetic-key");
  window.naver = { maps: {} };
  window.we2dayMapReady();
  window.naver.maps = f.maps;
  f.scripts[0].onload();
  assert.equal(await pending, f.maps);
  assert.equal(f.scripts[0].referrerPolicy, "origin");
  assert.equal(await f.loadNaverMap("synthetic-key"), f.maps);
  assert.equal(f.scripts.length, 1);
});

test("the documented callback can finish before the load event", async () => {
  const f = await fixture("callback");
  const pending = f.loadNaverMap("synthetic-key");
  window.naver = { maps: f.maps };
  window.we2dayMapReady();
  assert.equal(await pending, f.maps);
});

test("missing SDK after load rejects and permits a fresh attempt", async () => {
  const f = await fixture("missing");
  const pending = f.loadNaverMap("synthetic-key");
  f.scripts[0].onload();
  await assert.rejects(pending, /구성 요소/);
  assert.equal(f.scripts[0].removed, true);
  const retry = f.loadNaverMap("synthetic-key");
  window.naver = { maps: f.maps };
  f.scripts[1].onload();
  assert.equal(await retry, f.maps);
});

test("network, timeout and auth failures reject without exposing keys", async () => {
  for (const mode of ["network", "timeout", "auth"]) {
    const f = await fixture(mode);
    const pending = f.loadNaverMap("synthetic-key");
    if (mode === "network") f.scripts[0].onerror();
    if (mode === "timeout") f.timeout();
    if (mode === "auth") window.navermap_authFailure();
    await assert.rejects(pending, (error) => !error.message.includes("synthetic-key"));
    assert.equal(f.scripts[0].removed, true);
  }
});
