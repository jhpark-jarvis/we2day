import { expect, test } from "@playwright/test";
import { confirmPlanAndReopen } from "./plan-confirmation";

test("shared routes and plan confirmation preserve calendar and actual records", async ({
  browser,
}, testInfo) => {
  test.setTimeout(180_000);
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
    a.setDefaultTimeout(15_000);
    b.setDefaultTimeout(15_000);
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
    let scripts = 0;
    await a.route("https://oapi.map.naver.com/openapi/v3/maps.js?**", async (route) => {
      scripts++;
      expect(route.request().headers().referer).toBe("http://127.0.0.1:3100/");
      expect(route.request().url()).toContain("ncpKeyId=synthetic-maps-key");
      await route.fulfill({
        contentType: "application/javascript",
        body: `
        const coordinates = class { constructor(lat,lng){this.y=lat;this.x=lng} lat(){return this.y} lng(){return this.x} };
        window.naver={maps:{LatLng:coordinates,LatLngBounds:class {},Map:class {constructor(el){this.el=el;el.textContent='합성 지도';}setSize(size){this.el.style.width=size.width+'px';this.el.style.height=size.height+'px';}fitBounds(){}destroy(){this.el.textContent='';}},Marker:class{setMap(){}},Polyline:class{constructor(o){this.el=document.createElement('span');this.el.className='fixture-straight-line';o.map.el.append(this.el);}setMap(){this.el.remove();}},Event:{addListener(map,name,fn){map.el.onclick=()=>fn({coord:new coordinates(37.55,127.05)});return map;},removeListener(map){map.el.onclick=null;}}}};/* SDK load event must also work without a repeated global callback. */
      `,
      });
    });
    await a.goto("/");
    expect(scripts).toBe(0);
    await a.getByRole("button", { name: "동선 기록 열기" }).click();
    await a.getByLabel("직접 정한 출발 장소 이름").fill("직접 지정한 출발");
    await a
      .locator(".route-point")
      .filter({ hasText: "출발점" })
      .getByText("좌표 직접 입력", { exact: true })
      .click();
    await a.getByLabel("출발 위도").fill("37.5");
    await a.getByLabel("출발 경도").fill("127");
    await a.getByLabel("직접 정한 도착 장소 이름").fill("직접 지정한 도착");
    await a
      .locator(".route-point")
      .filter({ hasText: "도착점" })
      .getByText("좌표 직접 입력", { exact: true })
      .click();
    await a.getByLabel("도착 위도").fill("37.6");
    await a.getByLabel("도착 경도").fill("127.1");
    await a.getByRole("button", { name: "지도에서 두 점 지정하기" }).click();
    await expect(a.locator(".fixture-straight-line")).toHaveCount(1);
    expect(scripts).toBe(1);
    const frame = a.locator(".route-map-frame");
    const canvas = a.locator(".route-map-canvas");
    for (const width of [320, 1024, 390]) {
      await a.setViewportSize({ width, height: 844 });
      await expect
        .poll(async () => {
          const f = await frame.boundingBox(),
            c = await canvas.boundingBox();
          return f && c ? Math.abs(f.width - 2 - c.width) : 100;
        })
        .toBeLessThan(1);
    }

    await a.getByRole("region", { name: "출발점과 도착점을 지정하는 네이버 지도" }).click();
    await expect(a.getByLabel("출발 위도")).toHaveValue("37.5500000");
    await a.getByRole("button", { name: "동선 저장", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "동선을 저장했어요" })).toBeVisible();
    await a.screenshot({ path: testInfo.outputPath("route-mobile.png"), fullPage: true });
    await b.goto("/");
    await b.getByRole("button", { name: "동선 기록 열기" }).click();
    await expect(b.getByLabel("출발 위도")).toHaveValue("37.55");
    await a.goto("/plans");
    await a.getByRole("button", { name: "플랜 만들기" }).click();
    await a.getByLabel("플랜 이름", { exact: true }).fill("함께하는 주말");
    const date = await a.getByLabel("플랜 날짜").inputValue();
    await a.getByRole("button", { name: "활동 추가", exact: true }).click();
    await a.getByLabel("활동 1 이름").fill("산책");
    await a.getByLabel("활동 1 시간").fill("14:00");
    await a.getByLabel("활동 1 장소", { exact: true }).fill("직접 정한 공원");
    await a.getByRole("button", { name: "활동 추가", exact: true }).click();
    await a.getByLabel("활동 2 이름").fill("카페");
    await a.getByRole("button", { name: "활동 2 위로", exact: true }).click();
    await expect(a.getByLabel("활동 1 이름")).toHaveValue("카페");
    await a.getByRole("button", { name: "활동 1 아래로", exact: true }).click();
    await a.getByText("준비물 (선택)", { exact: true }).click();
    await a.getByLabel("준비물 (한 줄에 하나, 최대 30개)").fill("물\n우산");
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByRole("heading", { name: "함께하는 주말", exact: true })).toBeVisible();
    const before = await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect(await before.json()).toEqual([]);
    await b.goto("/plans");
    await b.getByRole("button", { name: /함께하는 주말/ }).click();
    await expect(b.getByLabel("활동 1 이름")).toHaveValue("산책");
    await a.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await confirmPlanAndReopen(a);
    await expect(a.getByText("확정됨", { exact: true })).toBeVisible();
    const after = await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    const events = await after.json();
    expect(events).toHaveLength(1);
    expect(events[0].time).toBe("14:00:00");
    await b.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await b.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
    await expect(
      b.getByRole("alert").filter({ hasText: "플랜 또는 연결된 약속이 바뀌었어요" }),
    ).toBeVisible();
    await expect(b).toHaveURL(/\/plans$/);
    await expect(b.getByLabel("플랜 이름", { exact: true })).toHaveValue("함께하는 주말");
    // A rejected confirmation preserves the draft and freezes editing until an explicit reload.
    await expect(b.getByLabel("플랜 이름", { exact: true })).toBeDisabled();
    await b.getByRole("button", { name: "작성 내용을 버리고 최신 플랜 불러오기" }).click();
    await expect(b.getByLabel("플랜 이름", { exact: true })).toHaveValue("함께하는 주말");
    await b.getByLabel("플랜 이름", { exact: true }).fill("함께하는 주말 변경");
    await b.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(b.getByText("변경안 · 다시 확정 필요", { exact: true })).toBeVisible();
    const unchanged = await second.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect((await unchanged.json())[0].title).toBe("함께하는 주말");
    await b.getByRole("button", { name: "변경 내용 확인·재확정" }).click();
    await b.screenshot({ path: testInfo.outputPath("plan-mobile.png"), fullPage: true });
    await confirmPlanAndReopen(b);
    await expect(b.getByText("확정됨", { exact: true })).toBeVisible();
    await b.getByRole("button", { name: "플랜 보관", exact: true }).click();
    await expect(b.getByRole("status")).toContainText("플랜을 보관했어요");
    await b.getByRole("button", { name: "보관함" }).click();
    await b.getByRole("button", { name: /함께하는 주말 변경/ }).click();
    await b.getByRole("button", { name: "플랜 복원", exact: true }).click();
    await expect(b.getByRole("status")).toContainText("플랜을 복원했어요");
    const final = await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect(await final.json()).toHaveLength(1);
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
      true,
    );
    await b.goto("/");
    await b.getByRole("button", { name: "동선 기록 열기" }).click();
    await expect(b.getByLabel("직접 정한 출발 장소 이름")).toHaveValue("직접 지정한 출발");
    expect(scripts).toBe(1);
  } finally {
    await first.close();
    await second.close();
  }
});
