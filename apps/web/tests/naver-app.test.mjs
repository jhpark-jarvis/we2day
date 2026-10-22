import assert from "node:assert/strict";
import { test } from "node:test";
import { naverAppLinks } from "../src/lib/naver-app.ts";

test("fixed app identity and literal destination encoding never accept injected actions", () => {
  const name = "강남역 #Intent;scheme=evil;end & café";
  const links = naverAppLinks("https://we2day.example/", name);
  assert.equal(new URL(links.ios).searchParams.get("query"), name);
  assert.equal(new URL(links.ios).searchParams.get("appname"), "https://we2day.example/");
  assert.equal(links.android.split("#Intent;").length, 2);
  for (const site of [
    "javascript:alert(1)",
    "https://x.example/private?token=a",
    "https://user:secret@x.example/",
  ])
    assert.equal(naverAppLinks(site, name), null);
  for (const invalid of ["", "x\ny", "x".repeat(201)])
    assert.equal(naverAppLinks("https://x.example", invalid), null);
});
test("routes use only supplied destination, supported modes and documented coordinate bounds", () => {
  for (const mode of ["car", "public", "walk", "bicycle", "navigation"]) {
    const links = naverAppLinks("http://127.0.0.1:3000", "공공 예시", {
      lat: "37.4979502",
      lng: "127.0276368",
      mode,
    });
    const url = new URL(links.ios);
    assert.equal(url.searchParams.get("dlat"), "37.4979502");
    assert.equal(url.searchParams.has("slat"), false);
    assert.equal(url.host + url.pathname, mode === "navigation" ? "navigation" : `route/${mode}`);
  }
  for (const lat of ["NaN", "Infinity", "", "31.42", "44.36", "37&dlng=1"])
    assert.equal(
      naverAppLinks("https://x.example", "장소", { lat, lng: "127", mode: "car" }),
      null,
    );
});
