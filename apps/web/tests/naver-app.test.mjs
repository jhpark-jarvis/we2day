import assert from "node:assert/strict";
import { test } from "node:test";
import { naverAppLinks, naverShareLink } from "../src/lib/naver-app.ts";

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

test("native URI decoding preserves spaces and literal plus without form decoding", () => {
  const name = "예시 카페 A+B & #1 (본점)";
  const links = naverAppLinks("https://we2day.example/", name);
  for (const href of [links.ios, links.android.split("#Intent;")[0]]) {
    const raw = href
      .split("?")[1]
      .split("&")
      .find((entry) => entry.startsWith("query="))
      .slice(6);
    assert.equal(raw.includes("+"), false);
    assert.equal(raw.includes("%20"), true);
    assert.equal(raw.includes("%2B"), true);
    assert.equal(decodeURIComponent(raw), name);
  }
});

test("selected place display address is excluded only from the search keyword", () => {
  for (const address of [
    "경기도 예시시 평화로 220 상가",
    "서울특별시 예시구 예시로 12",
    "전북특별자치도 예시시 예시로 3",
  ]) {
    const title = `예시치킨 예시1점 (${address})`;
    const links = naverAppLinks("https://we2day.example/", title);
    assert.equal(new URL(links.ios).searchParams.get("query"), "예시치킨 예시1점");
    const route = naverAppLinks("https://we2day.example/", title, {
      lat: "37.5",
      lng: "127",
      mode: "car",
    });
    assert.equal(new URL(route.ios).searchParams.get("dname"), title);
  }
  for (const title of [
    "예시 카페 (본점)",
    "예시 카페 (서울역 1층)",
    "경기도 예시시 평화로 220",
    "예시 카페 (본점) (서울특별시 예시구 예시로 1)",
  ]) {
    const query = new URL(naverAppLinks("https://we2day.example/", title).ios).searchParams.get(
      "query",
    );
    assert.equal(query, title.endsWith("예시로 1)") ? "예시 카페 (본점)" : title);
  }
});

test("share links accept only the exact NAVER HTTPS short-link host", () => {
  assert.equal(naverShareLink("https://naver.me/Example12"), "https://naver.me/Example12");
  for (const value of [
    "javascript:alert(1)",
    "https://naver.me.evil.test/x",
    "https://user@naver.me/x",
    "http://naver.me/x",
    "https://naver.me/x?redirect=evil",
    "https://naver.me/x#evil",
  ])
    assert.equal(naverShareLink(value), null);
});
