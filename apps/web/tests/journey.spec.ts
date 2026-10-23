import { expect, test } from "@playwright/test";

test("wishlist to published day and author-controlled report sharing", async ({
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
    for (const [page, name] of [
      [a, "member"],
      [b, "partner"],
    ] as const) {
      await page.goto("/login");
      await page.getByLabel("아이디", { exact: true }).fill(name);
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
    await a.goto("/wishlist");
    await a.getByRole("button", { name: "위시 추가", exact: true }).click();
    await a.getByLabel("위시 이름").fill("우리의 작은 산책");
    await a.getByLabel("위시 메모").fill("물과 우산 준비");
    await a.getByRole("button", { name: "위시 저장", exact: true }).click();
    await expect(a.getByRole("heading", { name: "우리의 작은 산책", exact: true })).toBeVisible();
    await b.goto("/wishlist");
    await expect(b.getByRole("heading", { name: "우리의 작은 산책", exact: true })).toBeVisible();
    await a.getByRole("link", { name: "이 위시로 플랜 초안 만들기" }).click();
    await expect(a.getByLabel("활동 1 장소", { exact: true })).toHaveValue("우리의 작은 산책");
    await expect(a.getByLabel("활동 1 메모")).toHaveValue("물과 우산 준비");
    const date = await a.getByLabel("플랜 날짜", { exact: true }).inputValue();
    await a.getByLabel("활동 1 시간").fill("14:00");
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByText("초안", { exact: true })).toBeVisible();
    const list = await (await first.request.get("/api/plans")).json();
    expect(list).toHaveLength(1);
    const id = list[0].id;
    await b.goto(`/today?date=${date}`);
    await expect(b.getByText("이 날짜에 확정한 플랜이 없어요.")).toBeVisible();
    await a.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await a.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
    await expect(a.getByText("확정됨", { exact: true })).toBeVisible();
    await a.getByLabel("플랜 이름", { exact: true }).fill("아직 확정하지 않은 변경안");
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByText("변경안 · 다시 확정 필요", { exact: true })).toBeVisible();
    await b.reload();
    await expect(
      b.getByRole("heading", { name: "우리의 작은 산책", exact: true }).first(),
    ).toBeVisible();
    await expect(b.getByText("아직 확정하지 않은 변경안", { exact: true })).toHaveCount(0);
    await expect(
      b.getByText("입력한 활동 비용 0원 + 비용 미정 1개", { exact: false }),
    ).toBeVisible();
    await b.screenshot({ path: testInfo.outputPath("today-mobile.png"), fullPage: true });
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
      true,
    );
    await a.goto(`/plans/${id}/report`);
    await a.getByLabel("오늘의 한 줄").fill("비공개 회고 원문");
    await a.getByLabel("직접 확인한 방문 장소", { exact: false }).fill("직접 확인한 산책길");
    await a.getByRole("button", { name: "개인 초안 저장", exact: true }).click();
    await expect(a.getByRole("status")).toContainText("나만 보는 초안");
    await b.goto(`/plans/${id}/report`);
    await expect(b.getByText("비공개 회고 원문", { exact: true })).toHaveCount(0);
    await expect(b.getByText("상대가 공유한 리포트가 아직 없어요.")).toBeVisible();
    await b.getByLabel("오늘의 한 줄").fill("상대 화면의 미저장 초안");
    await a.getByRole("button", { name: "이 내용을 상대와 공유", exact: true }).click();
    await expect(a.getByRole("status")).toContainText("상대와 공유");
    await b.getByRole("button", { name: "리포트 새로고침", exact: true }).click();
    await expect(b.getByRole("heading", { name: "비공개 회고 원문", exact: true })).toBeVisible();
    await expect(b.getByLabel("오늘의 한 줄")).toHaveValue("상대 화면의 미저장 초안");
    await b.screenshot({ path: testInfo.outputPath("report-mobile.png"), fullPage: true });
    await a.getByRole("button", { name: "공유 철회하고 개인 저장", exact: true }).click();
    await expect(a.getByRole("status")).toContainText("더 이상 표시되지 않아요");
    await b.getByRole("button", { name: "리포트 새로고침", exact: true }).click();
    await expect(b.getByRole("heading", { name: "비공개 회고 원문", exact: true })).toHaveCount(0);
    await expect(b.getByLabel("오늘의 한 줄")).toHaveValue("상대 화면의 미저장 초안");
    const mirror = await first.newPage();
    await mirror.goto(`/plans/${id}/report`);
    await mirror.getByLabel("오늘의 한 줄").fill("다른 탭에서 저장한 최신 회고");
    await mirror.getByRole("button", { name: "개인 초안 저장", exact: true }).click();
    await expect(mirror.getByRole("status")).toContainText("나만 보는 초안");
    await a.getByLabel("오늘의 한 줄").fill("현재 화면에서 작성 중인 내용");
    await a.getByRole("button", { name: "리포트 새로고침", exact: true }).click();
    await expect(a.getByRole("alert").filter({ hasText: "최신 리포트" })).toBeVisible();
    await expect(a.getByLabel("오늘의 한 줄")).toHaveValue("현재 화면에서 작성 중인 내용");
    await expect(a.getByRole("button", { name: "개인 초안 저장", exact: true })).toBeDisabled();
    await a.getByRole("link", { name: "작성 내용을 버리고 최신 페이지 불러오기" }).click();
    await expect(a.getByLabel("오늘의 한 줄")).toHaveValue("다른 탭에서 저장한 최신 회고");
    await expect(a.getByRole("button", { name: "개인 초안 저장", exact: true })).toBeEnabled();
    await mirror.close();
    await a.goto("/plans");
    await a.getByRole("button", { name: /아직 확정하지 않은 변경안/ }).click();
    await a.getByRole("button", { name: "저장한 내용으로 새 플랜 복제" }).click();
    await expect(a.getByLabel("플랜 이름", { exact: true })).toHaveValue(
      "아직 확정하지 않은 변경안 · 복사",
    );
    await a.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await expect(a.getByText("초안", { exact: true })).toBeVisible();
    const calendar = await (
      await first.request.get(`/api/appointments?month=${date.slice(0, 7)}`)
    ).json();
    expect(calendar).toHaveLength(1);
  } finally {
    await first.close();
    await second.close();
  }
});
