import { expect, test } from "@playwright/test";
import type { PlanningBrief } from "../src/lib/ai-intake";

type Request = {
  request_id: string;
  conversation_id: string;
  messages: { role: string; content: string }[];
  brief: PlanningBrief;
};

test("guided conditions, failed retry, restore and free chat across narrow screens", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  if (await page.getByRole("button", { name: "새 공간 만들기" }).isVisible())
    await page.getByRole("button", { name: "새 공간 만들기" }).click();
  let recorded: Request | null = null;
  const requests: Request[] = [];
  await page.route("**/api/ai/planner**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      const query = new URL(request.url()).searchParams;
      const data =
        query.has("conversation_id") && recorded
          ? {
              version: 1,
              proposal: null,
              turns: [
                {
                  request_id: recorded.request_id,
                  version: 1,
                  user_text: recorded.messages[0].content,
                  result: {
                    reply: "후보를 확인했어요.",
                    plan: null,
                    context: { ...recorded.brief, intake: { data: recorded.brief } },
                  },
                },
              ],
            }
          : recorded
            ? [
                {
                  id: recorded.conversation_id,
                  title: "합성 대화",
                  version: 1,
                  updated_at: new Date().toISOString(),
                },
              ]
            : [];
      return route.fulfill({ json: data });
    }
    const body = request.postDataJSON();
    requests.push(body);
    if (requests.length === 1)
      return route.fulfill({ status: 503, json: { error: "합성 일시 오류" } });
    recorded = body;
    return route.fulfill({
      json: {
        reply: "후보를 확인했어요.",
        plan: null,
        version: 1,
        context: { ...body.brief, intake: { data: body.brief } },
        candidates: [],
        checks: [],
      },
    });
  });
  await page.goto("/plans/ai");
  const form = page.getByRole("form", { name: "코스 조건 입력" });
  await expect(form).toBeVisible();
  if (test.info().project.name === "ai-safari")
    await page.setViewportSize({ width: 320, height: 740 });
  const shell = page.locator(".we2-chat");
  const originalHeight = (await shell.boundingBox())?.height;
  await form.getByLabel("시작 시간").fill("15:00");
  await form.getByLabel("종료 시간").fill("14:00");
  await form.getByRole("button", { name: "다음" }).click();
  await expect(form.getByRole("alert")).toContainText("종료 시간");
  await form.getByLabel("종료 시간").fill("19:00");
  await form.getByRole("button", { name: "다음" }).click();
  await form.getByLabel("지역", { exact: true }).fill("중랑구");
  await form.getByRole("button", { name: "도보", exact: true }).click();
  await form.getByRole("button", { name: "다음" }).click();
  await form.getByRole("button", { name: "도서관", exact: true }).click();
  await form.getByRole("button", { name: "카페", exact: true }).click();
  await form.getByLabel("예산").fill("0");
  await form.getByLabel("추가 조건").fill("걷기 적게");
  await form.getByRole("button", { name: "요약", exact: true }).click();
  const headingTop = (await form.getByRole("heading").boundingBox())?.y;
  const logTop = (await page.locator(".we2-messages").boundingBox())?.y;
  expect(headingTop !== undefined && logTop !== undefined && headingTop >= logTop).toBe(true);
  await expect(form.locator("dl")).toContainText("도서관 → 카페");
  await expect(form.locator("dl")).toContainText("0원");
  expect(requests).toHaveLength(0);
  expect((await shell.boundingBox())?.height).toBe(originalHeight);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await form.getByRole("button", { name: "후보 검색", exact: true }).click();
  await expect(page.locator(".error-message[role=alert]")).toContainText("합성 일시 오류");
  await expect(form.locator("dl")).toContainText("도서관 → 카페");
  await form.getByRole("button", { name: "후보 검색", exact: true }).click();
  await expect(page.getByText("후보를 확인했어요.", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[1].brief).toMatchObject({
    date: null,
    budget: 0,
    start_time: "15:00",
    end_time: "19:00",
    activities: ["도서관", "카페"],
  });
  await page.reload();
  await expect(page.getByText("후보를 확인했어요.", { exact: true })).toBeVisible();
  await page.locator(".we2-brief-summary summary").click();
  await expect(page.locator(".we2-brief-summary")).toContainText("15:00 ~ 19:00");
  await page.getByRole("button", { name: "새 대화", exact: true }).click();
  await expect(form).toBeVisible();
  await form.getByRole("button", { name: "바로 대화", exact: true }).click();
  await expect(page.locator(".we2-composer textarea")).toBeVisible();
  await page.getByRole("button", { name: "조건 입력", exact: true }).click();
  await expect(form).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
