import fs from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("route history and private record copies support explicit download and failed reads", async ({
  browser,
}, testInfo) => {
  test.setTimeout(240_000);
  const first = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  const second = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  try {
    const a = await first.newPage(),
      b = await second.newPage();
    for (const [page, username] of [
      [a, "member"],
      [b, "partner"],
    ] as const) {
      await page.goto("/login");
      await page.getByLabel("아이디", { exact: true }).fill(username);
      await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(page).toHaveURL(/\/account$/);
    }
    await a.goto("/couple");
    await a.getByRole("button", { name: "새 공간 만들기" }).click();
    await a.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await a.getByLabel("상대에게 전달할 코드").inputValue();
    await b.goto("/couple");
    await b.getByLabel("받은 초대 코드").fill(code);
    await b.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(b.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await a.goto("/?date=2026-10-01");
    await a.getByRole("button", { name: "동선 기록 열기", exact: true }).click();
    for (const [label, value] of [
      ["직접 정한 출발 장소 이름", "합성 출발"],
      ["출발 위도", "37.5"],
      ["출발 경도", "127"],
      ["직접 정한 도착 장소 이름", "합성 도착"],
      ["도착 위도", "37.6"],
      ["도착 경도", "127.1"],
    ])
      await a.getByLabel(label, { exact: true }).fill(value);
    await a.getByRole("button", { name: "동선 저장", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "동선을 저장했어요" })).toBeVisible();
    await b.goto("/memories/routes");
    await b.getByLabel("동선 시작일").fill("2026-10-01");
    await b.getByLabel("동선 종료일").fill("2026-10-31");
    await b.getByRole("button", { name: "동선 조회", exact: true }).click();
    const results = b.getByRole("region", { name: "기간별 동선 결과" });
    await expect(results).toContainText("합성 출발 → 합성 도착");
    await b.screenshot({
      path: testInfo.outputPath("route-history-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    const geoWait = b.waitForEvent("download");
    await b.getByRole("button", { name: "이 기간 직선 기록 내보내기", exact: true }).click();
    const geo = await geoWait;
    const geoPath = await geo.path();
    expect(geoPath).not.toBeNull();
    const data = JSON.parse(await fs.readFile(geoPath || "", "utf8"));
    expect(data.features).toHaveLength(1);
    expect(data.features[0].geometry.coordinates).toEqual([
      [127, 37.5],
      [127.1, 37.6],
    ]);
    await second.setOffline(true);
    await b.getByRole("button", { name: "동선 조회", exact: true }).click();
    await expect(b.getByRole("alert").filter({ hasText: "이전 결과" })).toBeVisible();
    await expect(results).toContainText("합성 출발");
    await second.setOffline(false);
    await b.goto("/memories/export");
    await expect(b.getByRole("button", { name: "기록 사본 다운로드", exact: true })).toBeDisabled();
    await b.getByLabel("내보낼 기록 종류").selectOption("meeting_routes");
    await b.getByLabel("사본 시작일").fill("2026-10-01");
    await b.getByLabel("사본 종료일").fill("2026-10-31");
    await b.getByRole("checkbox", { name: /파일에 메모/ }).check();
    const copyWait = b.waitForEvent("download");
    await b.getByRole("button", { name: "기록 사본 다운로드", exact: true }).click();
    const copy = await copyWait;
    await copy.saveAs(testInfo.outputPath("synthetic-records.json"));
    const copyPath = await copy.path();
    const snapshot = JSON.parse(await fs.readFile(copyPath || "", "utf8"));
    expect(snapshot.format).toBe("we2day-record-snapshot");
    expect(snapshot.payload.records).toHaveLength(1);
    expect(snapshot.payload.records[0].start_name).toBe("합성 출발");
    expect(snapshot.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(snapshot)).not.toMatch(/fingerprint|request_id|couple_id/);
    await b.getByLabel("내보낼 기록 종류").selectOption("date_reports");
    await expect(b.getByLabel("나의 비공개 초안도 포함")).not.toBeChecked();
    await expect(b.getByRole("button", { name: "기록 사본 다운로드", exact: true })).toBeDisabled();
    await b.screenshot({
      path: testInfo.outputPath("record-export-mobile.png"),
      fullPage: true,
      caret: "initial",
    });
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // Cross-origin requests must not bypass the browser bridge.
    const denied = await second.request.post("/api/records/export", {
      data: {},
      headers: { Origin: "https://unrelated.example" },
    });
    expect(denied.status()).toBe(403);
  } finally {
    await first.close();
    await second.close();
  }
});
