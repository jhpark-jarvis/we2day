import { expect, test } from "@playwright/test";

test("사용자 이름 저장과 설정 표시 및 새로고침 유지", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByText("member", { exact: true })).toHaveCount(0);
  await page.getByLabel("사용자 이름", { exact: true }).fill("예시 별명");
  await page.getByRole("button", { name: "이름 저장", exact: true }).click();
  await expect(page.getByText("예시 별명님, 반가워요.", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("사용자 이름", { exact: true })).toHaveValue("예시 별명");
  await page.goto("/settings");
  await expect(page.getByRole("region", { name: "계정 설정" })).toContainText(
    "예시 별명님으로 로그인했어요.",
  );
  await page.goto("/account");
  await page.getByLabel("사용자 이름", { exact: true }).fill("새 별명");
  await page.getByRole("button", { name: "이름 저장", exact: true }).click();
  await expect(page.getByText("새 별명님, 반가워요.", { exact: true })).toBeVisible();
});

test("two users share appointments through real SQL and preserve edits on failures", async ({
  browser,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const first = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
  const second = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 390, height: 844 },
  });
  const third = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    viewport: { width: 320, height: 740 },
  });
  try {
    const a = await first.newPage(),
      b = await second.newPage(),
      outsider = await third.newPage();
    for (const [page, username] of [
      [a, "member"],
      [b, "partner"],
      [outsider, "outsider"],
    ] as const) {
      await page.goto("/login");
      await page.getByLabel("아이디", { exact: true }).fill(username);
      await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
      await page.getByRole("button", { name: "로그인", exact: true }).click();
      await expect(page).toHaveURL(/\/account$/);
    }
    for (const [page, name] of [
      [a, "가상 별명 가"],
      [b, "가상 별명 나"],
    ] as const) {
      await page.getByLabel("사용자 이름", { exact: true }).fill(name);
      await page.getByRole("button", { name: "이름 저장", exact: true }).click();
      await expect(page.getByText(`${name}님, 반가워요.`, { exact: true })).toBeVisible();
    }
    await a.goto("/couple");
    await a.getByRole("button", { name: "새 공간 만들기" }).click();
    await a.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
    const code = await a.getByLabel("상대에게 전달할 코드").inputValue();
    expect(code).toMatch(/^[a-f0-9]{64}$/);
    await b.goto("/couple");
    await b.getByLabel("받은 초대 코드").fill(code);
    await b.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(b.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await a.goto("/");
    await a.getByRole("button", { name: "다음 달" }).click();
    await a.getByRole("button", { name: "약속 추가하기" }).click();
    await a.getByLabel("약속 이름").fill("함께 산책");
    await a.getByLabel("시간 (선택)").fill("14:30");
    await a.getByLabel("만날 장소 (선택)").fill("강변 산책길");
    await a.getByLabel("메모 (선택)").fill("따뜻한 차 챙기기");
    const date = await a.getByLabel("날짜", { exact: true }).inputValue();
    await request.post("http://127.0.0.1:54329/__lose-calendar-write-response");
    await a.getByRole("button", { name: "약속 저장하기" }).click();
    await expect(a.getByRole("alert").filter({ hasText: "연결하지 못했어요" })).toBeVisible();
    await expect(a.getByLabel("약속 이름")).toHaveValue("함께 산책");
    await expect(a.getByLabel("메모 (선택)")).toHaveValue("따뜻한 차 챙기기");
    await a.getByRole("button", { name: "약속 저장하기" }).click();
    await expect(a.getByRole("button", { name: /함께 산책/ })).toHaveCount(1);
    await b.goto("/");
    await b.getByRole("button", { name: "다음 달" }).click();
    await expect(b.getByRole("button", { name: /함께 산책/ })).toBeVisible();
    for (const page of [a, b]) {
      await page.getByRole("button", { name: /함께 산책/ }).click();
      await expect(
        page.locator(".appointment-detail").getByText("강변 산책길", { exact: true }),
      ).toBeVisible();
      await expect(page.locator(".detail-list")).toContainText("가상 별명 가");
      await expect(page.locator(".detail-list")).toContainText("가상 별명 나");
      await expect(page.getByText("나 · 너", { exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "약속 수정하기" }).click();
    }
    await a.getByLabel("약속 이름").fill("一緒に 산책 · 변경");
    await a.getByRole("button", { name: "약속 저장하기" }).click();
    await expect(a.getByRole("button", { name: /一緒に 산책 · 변경/ })).toBeVisible();
    await b.getByLabel("메모 (선택)").fill("상대가 작성 중인 메모");
    await b.getByRole("button", { name: "약속 저장하기" }).click();
    await expect(
      b.getByRole("alert").filter({ hasText: "다른 곳에서 내용이 바뀌었어요" }),
    ).toBeVisible();
    await expect(b.getByLabel("메모 (선택)")).toHaveValue("상대가 작성 중인 메모");
    await b.getByRole("button", { name: /최신 일정 다시 불러오기/ }).click();
    await b.getByRole("button", { name: /一緒に 산책 · 변경/ }).click();
    await b.getByRole("button", { name: "약속 수정하기" }).click();
    await b.getByLabel("메모 (선택)").fill("함께 준비물 챙기기");
    await b.getByRole("button", { name: "약속 저장하기" }).click();
    await expect(b.getByRole("button", { name: /一緒に 산책 · 변경/ })).toBeVisible();
    await a.reload();
    await a.getByRole("button", { name: "다음 달" }).click();
    await a.getByRole("button", { name: /一緒に 산책 · 변경/ }).click();
    await expect(a.getByText("함께 준비물 챙기기", { exact: true })).toBeVisible();
    await a.getByRole("button", { name: "약속 수정하기" }).click();
    await a.getByLabel("약속 이름").fill("저장하지 않을 변경");
    await a.getByRole("button", { name: "취소", exact: true }).click();
    await expect(a.getByRole("heading", { name: "一緒に 산책 · 변경", level: 1 })).toBeVisible();
    await outsider.goto("/");
    await expect(outsider.getByRole("button", { name: "약속 추가하기" })).toHaveCount(0);
    const hidden = await third.request.get(`/api/appointments?month=${date.slice(0, 7)}`);
    expect(await hidden.json()).toEqual([]);
    await outsider.goto("/couple");
    await outsider.getByLabel("받은 초대 코드").fill(code);
    await outsider.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(
      outsider.getByRole("alert").filter({ hasText: "초대 코드를 확인해 주세요" }),
    ).toBeVisible();
    // The same pair also shares original Gregorian dates through migration 002.
    await a.goto("/anniversaries");
    await a.getByRole("button", { name: "기념일 추가하기" }).click();
    await a.getByLabel("기념일 이름").fill("처음 만난 날");
    const today = await a.getByLabel("기준 날짜").inputValue();
    await request.post("http://127.0.0.1:54329/__lose-calendar-write-response");
    await a.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(a.getByRole("main").getByRole("alert")).toContainText("연결하지 못했어요");
    await expect(a.getByLabel("기념일 이름")).toHaveValue("처음 만난 날");
    await a.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(a.getByRole("heading", { name: "처음 만난 날", exact: true })).toHaveCount(1);
    await expect(a.getByText("함께한 1일", { exact: true })).toBeVisible();
    await b.goto("/anniversaries");
    await expect(b.getByText("함께한 1일", { exact: true })).toBeVisible();
    for (const page of [a, b]) {
      await page.getByRole("button", { name: "처음 만난 날 수정" }).click();
    }
    await a.getByLabel("기념일 이름").fill("우리의 첫날");
    await a.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(a.getByRole("heading", { name: "우리의 첫날" })).toBeVisible();
    await b.getByLabel("기념일 이름").fill("저장할 수 없는 충돌");
    await b.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(b.getByRole("main").getByRole("alert")).toContainText(
      "다른 곳에서 내용이 바뀌었어요",
    );
    await expect(b.getByLabel("기념일 이름")).toHaveValue("저장할 수 없는 충돌");
    await b.getByRole("button", { name: /최신 기념일 불러오기/ }).click();
    await expect(b.getByRole("heading", { name: "우리의 첫날" })).toBeVisible();
    await b.getByRole("button", { name: "기념일 추가하기" }).click();
    await expect(b.getByLabel("종류").locator("option[value=relationship]")).toHaveCount(0);
    await b.getByLabel("종류").selectOption("birthday");
    await b.getByLabel("기념일 이름").fill("특별한 생일");
    await b.getByLabel("월", { exact: true }).fill("2");
    await b.getByLabel("일", { exact: true }).fill("30");
    await b.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(b.getByRole("main").getByRole("alert")).toBeVisible();
    await expect(b.getByLabel("기념일 이름")).toHaveValue("특별한 생일");
    await b.getByLabel("일", { exact: true }).fill("29");
    await b.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(b.getByText("2월 29일", { exact: false })).toBeVisible();
    await b.getByRole("button", { name: "기념일 추가하기" }).click();
    await b.getByLabel("기념일 이름").fill("한 번의 특별한 날");
    await b.getByLabel("기준 날짜").fill(today);
    await b.getByLabel("매년 반복").uncheck();
    await b.getByRole("button", { name: "기념일 저장하기" }).click();
    await expect(b.getByRole("heading", { name: "한 번의 특별한 날" })).toBeVisible();
    await b.getByRole("button", { name: "한 번의 특별한 날 수정" }).click();
    await b.getByLabel("기념일 이름").fill("취소한 기념일");
    await b.getByRole("button", { name: "취소", exact: true }).click();
    await b.reload();
    await expect(b.getByRole("heading", { name: "한 번의 특별한 날" })).toBeVisible();
    await expect(b.getByRole("heading", { name: "취소한 기념일" })).toHaveCount(0);
    await a.reload();
    await expect(a.getByRole("heading", { name: "특별한 생일" })).toBeVisible();
    await a.screenshot({ path: testInfo.outputPath("anniversaries-warm.png"), fullPage: true });
    await a.goto("/");
    await expect(a.getByRole("region", { name: "디데이와 기념일 요약" })).toContainText(
      "함께한 1일",
    );
    await expect(a.getByText(/일정을 불러오는 중/)).toHaveCount(0);
    await a.screenshot({ path: testInfo.outputPath("anniversaries-home.png"), fullPage: true });
    await b.goto("/settings");
    await b.getByRole("button", { name: /화이트/ }).click();
    await expect(b.getByRole("status").filter({ hasText: "1년" })).toBeVisible();
    await expect(b.locator("html")).toHaveAttribute("data-theme", "white");
    await b.goto("/anniversaries");
    await expect(b.locator("html")).toHaveAttribute("data-theme", "white");
    await expect(b.getByRole("heading", { name: "우리의 기념일", exact: true })).toBeVisible();
    await b.screenshot({
      path: testInfo.outputPath("anniversaries-white-mobile.png"),
      fullPage: true,
    });
    await outsider.goto("/anniversaries");
    await expect(outsider.getByRole("link", { name: "둘의 공간 연결하기" })).toBeVisible();
    for (const page of [a, b, outsider]) {
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBeTruthy();
    }
  } finally {
    await first.close();
    await second.close();
    await third.close();
  }
});
