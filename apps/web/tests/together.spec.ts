import { expect, type Page, test } from "@playwright/test";

test("direct questions, chosen timezones and durable roulette results", async ({
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
    const pageErrors: string[] = [];
    const failedRequests: {
      url: string;
      error: string | null;
      prefetch: string | undefined;
      rsc: string | undefined;
    }[] = [];
    for (const page of [a, b]) {
      page.on("pageerror", (error) => pageErrors.push(error.message));
      page.on("requestfailed", (request) =>
        failedRequests.push({
          url: request.url(),
          error: request.failure()?.errorText || null,
          prefetch: request.headers()["next-router-prefetch"],
          rsc: request.headers().rsc,
        }),
      );
    }
    for (const [page, name] of [
      [a, "member"],
      [b, "partner"],
    ] as const) {
      await open(page, "/login");
      await page.getByLabel("아이디", { exact: true }).fill(name);
      await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(page).toHaveURL(/\/account$/);
    }
    await open(a, "/login");
    await expect(a.getByRole("link", { name: "계정 관리·전환", exact: true })).toBeVisible();
    await expect(a.getByLabel("아이디", { exact: true })).toHaveCount(0);
    await open(a, "/couple");
    await a.getByRole("button", { name: "새 공간 만들기" }).click();
    await a.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await a.getByLabel("상대에게 전달할 코드").inputValue();
    await open(b, "/couple");
    await b.getByLabel("받은 초대 코드").fill(code);
    await b.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(b.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await open(a, "/questions");
    await a
      .locator("summary")
      .filter({ hasText: /^질문 추가$/ })
      .click();
    await a.getByLabel("함께 나눌 질문").fill("다음에 같이 해볼 일은? · 합성 질문");
    await a.getByRole("button", { name: "질문 추가", exact: true }).click();
    await expect(a).toHaveURL(/\/questions\/[a-f0-9-]+$/);
    const questionUrl = a.url();
    await a.getByLabel("답변 내용", { exact: true }).fill("공유하기 전의 개인 답변 · 합성 예시");
    await a.getByRole("button", { name: "개인 답변 저장", exact: true }).click();
    await expect(
      a.getByRole("status").filter({ hasText: "개인 답변으로 저장했어요." }),
    ).toBeVisible();
    await open(b, questionUrl);
    await expect(b.getByText("공유하기 전의 개인 답변 · 합성 예시", { exact: true })).toHaveCount(
      0,
    );
    await a.getByRole("button", { name: "이 답변을 상대와 공유", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "답변을 공유했어요." })).toBeVisible();
    await b.getByLabel("답변 내용", { exact: true }).fill("새로고침 중 보존할 초안");
    await b.getByRole("button", { name: "공유 답변 새로고침", exact: true }).click();
    await expect(b.getByText("공유하기 전의 개인 답변 · 합성 예시", { exact: true })).toBeVisible();
    await expect(b.getByLabel("답변 내용", { exact: true })).toHaveValue("새로고침 중 보존할 초안");
    await b.screenshot({
      path: testInfo.outputPath("questions-mobile.png"),
      fullPage: true,
      caret: "initial",
      style: "nextjs-portal{display:none}",
    });
    await a.getByRole("button", { name: "이 질문 건너뛰기·공유 철회", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "질문을 건너뛰었어요" })).toBeVisible();
    await a.reload();
    await expect(a.getByLabel("답변 내용", { exact: true })).toHaveValue(
      "공유하기 전의 개인 답변 · 합성 예시",
    );
    await b.reload();
    await expect(b.getByText("공유하기 전의 개인 답변 · 합성 예시", { exact: true })).toHaveCount(
      0,
    );
    await expect(b.getByText("건너뛴 질문이에요", { exact: false })).toHaveCount(0);
    await open(a, "/timezones");
    await a.getByLabel("나의 시간대", { exact: true }).selectOption("America/Los_Angeles");
    await a.getByRole("button", { name: "시간대 저장", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "시간대를 저장했어요." })).toBeVisible();
    await open(b, "/timezones");
    await expect(b.getByText("상대의 시간대 · America/Los_Angeles", { exact: true })).toBeVisible();
    await b.getByLabel("나의 시간대", { exact: true }).selectOption("Asia/Seoul");
    await b.getByRole("button", { name: "시간대 저장", exact: true }).click();
    await expect(b.getByRole("status").filter({ hasText: "시간대를 저장했어요." })).toBeVisible();
    await open(a, "/?date=2026-01-01");
    await a.getByRole("button", { name: "약속 추가하기" }).click();
    await a.getByLabel("약속 이름").fill("현지 시각 확인용 약속");
    await a.getByLabel("날짜", { exact: true }).fill("2026-01-01");
    await a.getByLabel("시간 (선택)").fill("00:30");
    await a.getByRole("button", { name: "약속 저장하기", exact: true }).click();
    await a.getByRole("button", { name: /현지 시각 확인용 약속/ }).click();
    await expect(a.getByLabel("현지 시각 보조")).toContainText("2025-12-31 07:30");
    await expect(a.getByLabel("현지 시각 보조")).toContainText("2026-01-01 00:30");
    await a.screenshot({
      path: testInfo.outputPath("timezones-mobile.png"),
      fullPage: true,
      caret: "initial",
      style: "nextjs-portal{display:none}",
    });
    await open(a, "/roulette");
    await a.getByText("룰렛 만들기", { exact: true }).click();
    await a.getByLabel("룰렛 이름", { exact: true }).fill("둘이 고르는 시간 · 합성 룰렛");
    await a.getByLabel("후보 (한 줄에 하나, 2~20개)", { exact: true }).fill("산책\n집에서 영화");
    await a.getByRole("button", { name: "룰렛 저장", exact: true }).click();
    await expect(a).toHaveURL(/\/roulette\/[a-f0-9-]+$/);
    const wheelUrl = a.url();
    await a.getByRole("button", { name: "하나 뽑기", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "선택 결과" })).toBeVisible();
    const result = await a.getByRole("status").filter({ hasText: "선택 결과" }).textContent();
    await open(b, wheelUrl);
    await expect(b.getByRole("status").filter({ hasText: "선택 결과" })).toHaveText(result || "");
    await a.getByText("후보 수정", { exact: true }).click();
    await a.getByLabel("후보 (한 줄에 하나, 2~20개)", { exact: true }).fill("카페\n독서");
    await a.getByRole("button", { name: "최신 결과 불러오기", exact: true }).click();
    await expect(a.getByLabel("후보 (한 줄에 하나, 2~20개)", { exact: true })).toHaveValue(
      "카페\n독서",
    );
    await expect(a.getByRole("button", { name: "다시 뽑기", exact: true })).toBeDisabled();
    await a.getByRole("button", { name: "룰렛 저장", exact: true }).click();
    await expect(a.getByRole("button", { name: "다시 뽑기", exact: true })).toBeEnabled();
    await a.getByRole("button", { name: "다시 뽑기", exact: true }).click();
    await expect(a.getByRole("status").filter({ hasText: "선택 결과" })).toContainText(/카페|독서/);
    await a.locator(".roulette-history > li").last().getByText("당시 후보 2개 보기").click();
    await expect(a.locator(".roulette-history > li").last()).toContainText("집에서 영화");
    await a.screenshot({
      path: testInfo.outputPath("roulette-mobile.png"),
      fullPage: true,
      caret: "initial",
      style: "nextjs-portal{display:none}",
    });
    await import("node:fs/promises").then((fs) =>
      fs.writeFile(
        testInfo.outputPath("browser-network-errors.json"),
        JSON.stringify({ pageErrors, failedRequests }, null, 2),
      ),
    );
    expect(pageErrors).toEqual([]);
    for (const page of [a, b])
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
  } finally {
    await first.close();
    await second.close();
  }
});

async function open(page: Page, url: string) {
  await page.waitForLoadState("networkidle");
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}
