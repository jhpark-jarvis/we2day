import { expect, type Page, test } from "@playwright/test";

test("naver handoff encodes selected place and discards temporary coordinates without recording visits", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  let external = 0,
    visitWrites = 0;
  await page.route("**/*", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (
      ["naver.com", "google.com", "apple.com"].some(
        (host) => url.hostname === host || url.hostname.endsWith(`.${host}`),
      )
    ) {
      external++;
      await route.abort();
      return;
    }
    if (url.pathname === "/api/visits" && request.method() === "POST") visitWrites++;
    await route.continue();
  });
  await open(page, "/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await open(page, "/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await open(page, "/plans");
  await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
  await page.getByLabel("플랜 이름", { exact: true }).fill("합성 앱 이동 플랜");
  const date = await page.getByLabel("플랜 날짜").inputValue();
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 1 이름").fill("공공 장소 예시");
  await page.getByLabel("활동 1 장소", { exact: true }).fill("강남역 & 공공 예시");
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 2 이름").fill("장소 없는 합성 활동");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(page.getByText("확정됨", { exact: true })).toBeVisible();
  await open(page, `/today?date=${date}`);
  await page.getByRole("button", { name: "앱 연결 옵션", exact: true }).click();
  const search = page.getByRole("link", { name: "네이버 지도", exact: true });
  expect(new URL((await search.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "강남역 & 공공 예시",
  );
  await page.getByText("목적지 좌표로 바로 길찾기", { exact: true }).click();
  await page.getByLabel("길찾기 목적지 위도").fill("37.4979502");
  await page.getByLabel("길찾기 목적지 경도").fill("127.0276368");
  const handoff = page.getByRole("link", { name: "네이버 지도 앱으로 길찾기 요청", exact: true });
  await expect(handoff).toHaveAttribute("href", /^nmap:\/\/route\/car\?/);
  await page.getByLabel("이동할 휴대폰").selectOption("android");
  await expect(handoff).toHaveAttribute("href", /^intent:\/\/route\/car\?/);
  await page.getByLabel("길찾기 목적지 위도").fill("NaN");
  await expect(handoff).toHaveCount(0);
  await page.getByLabel("길찾기 목적지 위도").fill("37.4979502");
  await page.screenshot({
    path: testInfo.outputPath("naver-handoff-mobile.png"),
    fullPage: true,
    caret: "initial",
  });
  await page.getByRole("button", { name: "다음 활동 보기", exact: true }).click();
  await expect(
    page.getByText("이 활동에는 장소가 없어요. 플랜에서 장소를 직접 적어 주세요.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "이전 활동 보기", exact: true }).click();
  await page.getByRole("button", { name: "앱 연결 옵션", exact: true }).click();
  await page.getByText("목적지 좌표로 바로 길찾기", { exact: true }).click();
  await expect(page.getByLabel("길찾기 목적지 위도")).toHaveValue("");
  await expect(page.getByRole("region", { name: "데이트 활동" })).not.toContainText("마지막 변경");
  expect(external).toBe(0);
  expect(visitWrites).toBe(0);
});

test("saved date course opens stored places through direct map links without search API calls", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  let visits = 0,
    searches = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/visits") && request.method() === "POST") visits++;
    if (request.url().includes("/api/places/search")) searches++;
  });
  await open(page, "/login");
  await page.getByLabel("아이디", { exact: true }).fill("audit");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await open(page, "/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  const date = "2026-11-09";
  await open(page, `/?date=${date}`);
  const agenda = page.getByRole("region", { name: "선택한 날짜의 약속", exact: true });
  await expect(agenda.getByRole("link", { name: "데이트 코스", exact: true })).toBeVisible();
  await expect(agenda.getByRole("link", { name: "코스 등록", exact: true })).toHaveCount(0);
  await expect(
    page.locator("main > .calendar-toolbar").getByRole("link", { name: "코스 등록", exact: true }),
  ).toHaveCount(0);
  const anniversary = page.getByRole("region", { name: "디데이와 기념일 요약", exact: true });
  await expect(anniversary.getByRole("link", { name: "기념일 관리", exact: true })).toHaveClass(
    "icon-button",
  );
  await expect(anniversary).toHaveCSS("padding-top", "7px");
  await expect(anniversary.getByRole("link", { name: "기념일 관리", exact: true })).toHaveCSS(
    "border-top-width",
    "0px",
  );
  for (const width of [320, 393, 1425]) {
    await page.setViewportSize({ width, height: 852 });
    const compact = await anniversary.boundingBox();
    expect(compact?.height).toBeLessThanOrEqual(64);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await expect(
    page.getByRole("link", { name: "데이트 코스", exact: true }).first(),
  ).toHaveAttribute("href", `/today?date=${date}`);
  await agenda.getByRole("link", { name: "데이트 코스", exact: true }).click();
  await page.getByRole("link", { name: "코스 등록", exact: true }).click();
  await expect(page.getByLabel("플랜 날짜")).toHaveValue(date);
  await page.getByLabel("플랜 이름", { exact: true }).fill("미리 준비한 코스");
  for (const index of [1, 2]) {
    if (index === 2) await page.getByRole("button", { name: "활동 추가", exact: true }).click();
    await page.getByLabel(`활동 ${index} 이름`, { exact: true }).fill(`활동 ${index}`);
    await page
      .getByLabel(`활동 ${index} 장소`, { exact: true })
      .fill(`직접 정한 장소 ${index} & 예시 주소 ${index}`);
  }
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("region", { name: "플랜 확정 내용", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(page.getByText("확정됨", { exact: true })).toBeVisible();
  const saved = await (await page.request.get("/api/plans")).json();
  const id = saved.find(
    (p: { content: { title: string } }) => p.content.title === "미리 준비한 코스",
  ).id;
  await open(page, `/today?date=${date}`);
  const map = page.getByRole("link", { name: "네이버 지도", exact: true });
  await expect(map).toBeVisible();
  await expect(map).toHaveAttribute("href", /^nmap:\/\/search\?/);
  expect(new URL((await map.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "직접 정한 장소 1 & 예시 주소 1",
  );
  await expect(page.getByLabel("길찾기 목적지 위도")).toHaveCount(0);
  await expect(page.locator(".today-workspace")).not.toContainText("0원");
  await expect(page.locator(".today-workspace")).not.toContainText("비용 미정");
  await expect(page.getByText("입력한 활동 비용", { exact: false })).toHaveCount(0);
  const focus = page.getByRole("region", { name: "살펴보는 활동" });
  await expect(page.locator(".activity-card").filter({ has: focus })).toHaveCSS(
    "border-top-width",
    "1px",
  );
  await expect(page.getByRole("button", { name: "이 날짜 보기", exact: true })).toHaveClass(
    "icon-button",
  );
  for (const width of [320, 393, 1024, 1425]) {
    await page.setViewportSize({ width, height: 852 });
    const geometry = await page.evaluate(() => {
      const box = (selector: string) => {
        const el = document.querySelector(selector);
        if (!el) throw new Error(selector);
        const r = el.getBoundingClientRect();
        return {
          left: r.left,
          right: r.right,
          top: r.top,
          bottom: r.bottom,
          center: (r.left + r.right) / 2,
        };
      };
      return {
        shell: box(".app-shell"),
        menu: box(".app-navigation"),
        title: box(".page-title-slot"),
        logo: box(".app-header .wordmark"),
        prev: box(".timeline-step-navigation button:first-child"),
        next: box(".timeline-step-navigation button:last-child"),
        steps: box(".timeline-step-navigation"),
        actions: box(".section-actions"),
        section: box(".visit-progress"),
        heading: box(".section-heading h2"),
        placeActions: [...document.querySelectorAll(".handoff-actions > *")].map(
          (el) => el.getBoundingClientRect().top,
        ),
      };
    });
    if (width > 840) {
      expect(Math.abs(geometry.menu.center - geometry.shell.center)).toBeLessThanOrEqual(1);
      expect(geometry.logo.right).toBeLessThan(geometry.menu.left);
      expect(geometry.title.left).toBeGreaterThanOrEqual(geometry.menu.right);
    } else expect(geometry.menu.top).toBeGreaterThan(geometry.logo.bottom);
    expect(Math.abs(geometry.prev.left - geometry.steps.left)).toBeLessThanOrEqual(1);
    expect(Math.abs(geometry.next.right - geometry.steps.right)).toBeLessThanOrEqual(1);
    expect(geometry.actions.right).toBeLessThanOrEqual(geometry.section.right);
    expect(
      Math.abs(
        (geometry.actions.top + geometry.actions.bottom) / 2 -
          (geometry.heading.top + geometry.heading.bottom) / 2,
      ),
    ).toBeLessThanOrEqual(1);
    expect(
      Math.max(...geometry.placeActions) - Math.min(...geometry.placeActions),
    ).toBeLessThanOrEqual(1);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`saved-course-${width}.png`),
      fullPage: true,
    });
  }
  await page.getByRole("button", { name: "다음 활동 보기", exact: true }).click();
  expect(new URL((await map.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "직접 정한 장소 2 & 예시 주소 2",
  );
  // Unconfirmed place edits must not change the actual day's course.
  await open(page, `/plans?item=${id}`);
  await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("활동 1 장소", { exact: true })).toHaveValue(
    "직접 정한 장소 1 & 예시 주소 1",
  );
  await page.getByLabel("활동 1 장소", { exact: true }).fill("다른 장소 초안");
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 3 이름", { exact: true }).fill("새로 추가한 활동");
  await page.getByLabel("활동 3 장소", { exact: true }).fill("직접 지정한 새 장소");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await expect(page.getByRole("region", { name: "플랜 확정 내용", exact: true })).toBeVisible();
  await expect(page.getByText("변경안 · 다시 확정 필요", { exact: true })).toBeVisible();
  await open(page, `/today?date=${date}`);
  expect(new URL((await map.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "직접 정한 장소 1 & 예시 주소 1",
  );
  expect(visits).toBe(0);
  expect(searches).toBe(0);
  await expect(page.locator(".day-timeline")).not.toContainText("새로 추가한 활동");
  await page.getByRole("link", { name: "변경안 확인·반영", exact: true }).click();
  await expect(page.getByRole("region", { name: "플랜 확정 내용", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(page.getByText("확정됨", { exact: true })).toBeVisible();
  // Return through the actual link: the previously visited course must be invalidated.
  await page.getByRole("link", { name: "데이트 코스", exact: true }).click();
  await expect(page.locator(".day-timeline")).toContainText("새로 추가한 활동");
  expect(new URL((await map.getAttribute("href")) || "").searchParams.get("query")).toBe(
    "다른 장소 초안",
  );
  await expect(page.getByRole("link", { name: "변경안 확인·반영", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".day-timeline")).toContainText("새로 추가한 활동");

  // Optional amounts retain their stored zero/null semantics while read-only zero labels disappear.
  for (const positive of [false, true]) {
    await open(page, `/plans?item=${id}`);
    await page.waitForLoadState("networkidle");
    await page.getByText("예산 (선택)", { exact: true }).click();
    await page.locator(".activity-editor-disclosure").nth(1).locator("summary").first().click();
    await page.getByText("비용 (선택)", { exact: true }).nth(0).click();
    await page.getByText("비용 (선택)", { exact: true }).nth(1).click();
    await page.getByLabel("전체 예산 (원, 선택)").fill(positive ? "20000" : "0");
    await page.getByLabel("활동 1 예상 비용 (원, 선택)", { exact: true }).fill("0");
    await page
      .getByLabel("활동 2 예상 비용 (원, 선택)", { exact: true })
      .fill(positive ? "12000" : "0");
    await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }).click();
    await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "변경 내용 확인·재확정", exact: true }),
    ).toBeEnabled();
    await open(page, `/today?date=${date}`);
    await expect(page.locator(".day-timeline")).not.toContainText(/(?:^|\D)0원/);
    if (positive) {
      await expect(page.locator(".today-workspace > header")).toContainText(
        "입력한 활동 비용 12,000원",
      );
      await expect(page.locator(".today-workspace > header")).toContainText("예산 20,000원");
    } else {
      await expect(page.locator(".today-workspace")).not.toContainText("0원");
      await expect(page.locator(".today-workspace > header")).not.toContainText("예산");
    }
  }
  await page.getByLabel("살펴볼 날짜", { exact: true }).fill("2026-11-10");
  await page.getByRole("button", { name: "이 날짜 보기", exact: true }).click();
  await expect(page).toHaveURL(/date=2026-11-10/);
  await expect(page.getByText("이 날짜에 확정한 플랜이 없어요.", { exact: true })).toBeVisible();
  await open(page, "/anniversaries");
  await page.getByRole("button", { name: "기념일 추가하기", exact: true }).click();
  await page.getByLabel("종류", { exact: true }).selectOption("custom");
  const longAnniversary = "함께기억하는아주긴기념일이름".repeat(3);
  await page.getByLabel("기념일 이름", { exact: true }).fill(longAnniversary);
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(page.getByRole("button", { name: "기념일 추가하기", exact: true })).toBeVisible();
  for (const width of [320, 393, 1425]) {
    await page.setViewportSize({ width, height: 852 });
    await open(page, "/");
    await expect(anniversary).toContainText(longAnniversary);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await expect(anniversary.getByRole("link", { name: "기념일 관리", exact: true })).toHaveCSS(
      "width",
      "44px",
    );
  }
  for (const route of ["/settings", "/memories/records", "/today"]) {
    for (const width of [320, 393, 1024, 1425]) {
      await page.setViewportSize({ width, height: 852 });
      await open(page, route);
      await page.waitForLoadState("networkidle");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      if (width > 840) {
        const errors = await page.evaluate(() => {
          const nav = document.querySelector(".app-navigation")?.getBoundingClientRect();
          const title = document.querySelector(".page-title-slot")?.getBoundingClientRect();
          if (!nav || !title) throw new Error("Header is missing");
          return title.left < nav.right;
        });
        expect(errors).toBe(false);
      }
    }
  }
});

async function open(page: Page, url: string) {
  await page.waitForLoadState("networkidle");
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}
