import { expect, test } from "@playwright/test";
import type { PlanningBrief } from "../src/lib/ai-intake";
import type { PlanContent } from "../src/lib/plans";

test("starter examples provide a region and activity and remain editable before sending", async ({
  page,
}) => {
  await fixtureLogin(page);
  let posts = 0;
  await page.route("**/api/ai/planner**", async (route) => {
    if (route.request().method() !== "GET") posts++;
    await route.fulfill({ json: [] });
  });
  await page.goto("/plans/ai");
  await page.getByRole("button", { name: "바로 대화", exact: true }).click();
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  for (const label of ["산책과 카페", "비 오는 날", "가벼운 하루"]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    const text = await input.inputValue();
    expect(text).toMatch(/성수동|연남동/);
    expect(text).toMatch(/카페/);
    expect(text).toMatch(/\d{4}-\d{2}-\d{2}|날짜는 미정/);
    expect(posts).toBe(0);
    await expect(input).toBeFocused();
  }
  await input.fill("내 지역과 예산으로 바꾼 문장");
  await expect(input).toHaveValue("내 지역과 예산으로 바꾼 문장");
});

test("a pending anchor replaces old candidates even when the category and area stay equal", async ({
  page,
}) => {
  await fixtureLogin(page);
  let posts = 0;
  await page.route("**/api/ai/planner**", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: historyItems });
    posts++;
    return route.fulfill({
      json: {
        reply: posts === 1 ? "합성 시설 후보" : "어느 장소를 기준으로 찾을까요?",
        plan: null,
        checks: [],
        version: posts,
        context: {
          region: "합성구",
          search_scope: { area: "합성구", kinds: ["any"] },
          place_search: {
            semantic: 1,
            version: 1,
            targets: [{ kind: "any", query: "합성시설" }],
            anchor_pending: posts > 1,
          },
          dialogue: { pending: posts > 1 ? { field: "target", resume: "search" } : null },
        },
        candidates:
          posts === 1
            ? [
                {
                  ref: "p1",
                  title: "합성 시설",
                  address: "합성구 1",
                  destination: "합성 시설 (합성구 1)",
                  source: "naver",
                },
              ]
            : [],
        candidates_available: true,
      },
    });
  });
  await page.goto("/plans/ai");
  await page.getByRole("button", { name: "바로 대화", exact: true }).click();
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  await input.fill("합성시설 찾아줘");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: "합성 시설 선택", exact: true })).toBeVisible();
  await input.fill("그 장소 주변 합성시설 찾아줘");
  await input.press("Enter");
  await expect(page.getByText("어느 장소를 기준으로 찾을까요?", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "합성 시설 선택", exact: true })).toHaveCount(0);
  expect(posts).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("real BFF streams progress before a final card response and keeps failures recoverable", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await fixtureLogin(page);
  await page.goto("/plans/ai");
  await page.getByRole("button", { name: "바로 대화", exact: true }).click();
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  await input.fill("합성 SSE 정상");
  await input.press("Enter");
  await expect(page.getByRole("status")).toContainText("네이버에서 장소 후보를 검색하고 있어요.");
  expect(
    (await (await request.get("http://127.0.0.1:8101/fixture/state?case=정상")).json()).pending,
  ).toBe(true);
  await expect(page.locator(".we2-assistant")).toHaveCount(0);
  for (const [stage, label] of [
    ["model", "답변을 구성"],
    ["validate", "코스 조건을 검사"],
    ["persist", "결과를 저장"],
  ]) {
    await request.post(`http://127.0.0.1:8101/fixture/advance?case=정상&stage=${stage}`);
    await expect(page.getByRole("status")).toContainText(label);
  }
  await request.post("http://127.0.0.1:8101/fixture/finish?case=정상");
  const cards = page.getByRole("region", { name: "답변의 장소 후보", exact: true });
  await expect(
    cards.getByRole("button", { name: "합성 SSE 카페 1 선택", exact: true }),
  ).toBeVisible();
  const map = cards.getByRole("link", { name: "합성 SSE 카페 1 네이버 지도", exact: true });
  await expect(map).toHaveAttribute(
    "href",
    /^(?:https:\/\/map\.naver\.com\/p\/search\/|nmap:\/\/search\?)/,
  );
  await expect(map).toHaveAttribute("referrerpolicy", "no-referrer");
  await expect(
    cards.getByRole("button", { name: "합성 SSE 카페 1 선택", exact: true }),
  ).toHaveClass("icon-button");
  await input.fill("후보 선택과 별개인 미전송 입력");
  await page.getByRole("button", { name: "후보 5개 전체", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "장소 후보", exact: true });
  await expect(
    dialog.getByRole("link", { name: "합성 SSE 카페 5 네이버 지도", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 320, height: 568 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await dialog.getByRole("button", { name: "장소 후보 닫기", exact: true }).click();
  await expect(input).toHaveValue("후보 선택과 별개인 미전송 입력");
  for (const mode of ["실패", "끊김", "중단"]) {
    await input.fill(`합성 SSE ${mode}`);
    await input.press("Enter");
    await expect(page.getByRole("status")).toContainText("네이버에서 장소 후보를 검색하고 있어요.");
    if (mode === "중단") await page.getByRole("button", { name: "요청 중단", exact: true }).click();
    else await request.post(`http://127.0.0.1:8101/fixture/finish?case=${mode}`);
    await expect(page.locator(".we2-status [role=alert]")).toContainText(
      mode === "실패"
        ? "오래 걸려 중단"
        : mode === "끊김"
          ? "연결이 끊겼어요"
          : "요청을 중단했어요",
    );
    await expect(input).toHaveValue(`합성 SSE ${mode}`);
    await expect(page.getByRole("button", { name: "메시지 다시 전송", exact: true })).toBeEnabled();
    await expect
      .poll(
        async () =>
          (await (await request.get(`http://127.0.0.1:8101/fixture/state?case=${mode}`)).json())
            .pending,
      )
      .toBe(false);
  }
  await input.fill("합성 SSE 구버전");
  await input.press("Enter");
  await expect(page.locator(".we2-assistant").last()).toContainText("합성 구버전 응답");
});

test("cleared dates and pending changes cannot save an old proposal after reload", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await fixtureLogin(page);
  const id = historyIds[0];
  let version = 1;
  let context: Record<string, unknown> = {
    date: "2030-01-05",
    dialogue: { cleared_date: false, pending: null },
  };
  let plan = screenPlan();
  await page.route("**/api/ai/planner**", async (route) => {
    const request = route.request(),
      query = new URL(request.url()).searchParams;
    if (request.method() === "GET") {
      return route.fulfill({
        json: query.has("conversation_id")
          ? {
              version,
              proposal: plan,
              turns: [
                {
                  request_id: id,
                  version,
                  user_text: "합성 이전 질문",
                  result: { reply: "합성 이전 응답", plan, context },
                },
              ],
            }
          : [{ id, title: "합성 날짜 변경", version, updated_at: "2030-01-05T00:00:00Z" }],
      });
    }
    const latest = request.postDataJSON().messages.at(-1).content;
    let changed: PlanContent | null = null;
    if (latest.includes("미정"))
      context = { date: null, dialogue: { cleared_date: true, pending: null } };
    else if (latest.includes("2030-02-03")) {
      context = { date: "2030-02-03", dialogue: { cleared_date: false, pending: null } };
      plan = changed = { ...plan, date: "2030-02-03" };
    } else if (latest.includes("제목"))
      context = { ...context, dialogue: { cleared_date: false, pending: { resume: "edit" } } };
    else context = { ...context, dialogue: { cleared_date: false, pending: null } };
    version++;
    return route.fulfill({
      json: {
        version,
        reply: `합성 조건 변경 ${version}`,
        context,
        plan: changed,
        candidates: [],
        checks: [],
      },
    });
  });
  await page.goto("/plans/ai");
  await page.setViewportSize({ width: 1280, height: 720 });
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  const save = page.getByRole("button", { name: "초안 저장", exact: true });
  await expect(save).toBeEnabled();
  await input.fill("날짜는 미정으로 바꿔줘");
  await page.getByRole("button", { name: "메시지 전송", exact: true }).click();
  await expect(save).toBeDisabled();
  await expect(page.locator(".we2-proposal-date")).toContainText("날짜 미정");
  await expect(
    page.getByText("초안을 저장하려면 날짜를 정해 주세요.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await page.setViewportSize({ width: 320, height: 568 });
  await expect(save).toBeDisabled();
  await input.fill("날짜는 2030-02-03으로 바꿔줘");
  await page.getByRole("button", { name: "메시지 전송", exact: true }).click();
  await expect(save).toBeEnabled();
  await expect(page.locator(".we2-proposal-date")).toContainText("2030-02-03");
  await input.fill("제목 바꿔줘");
  await page.getByRole("button", { name: "메시지 전송", exact: true }).click();
  await expect(save).toBeDisabled();
  await expect(
    page.getByText("진행 중인 변경을 마치거나 취소한 뒤 저장해 주세요.", { exact: true }),
  ).toBeVisible();
  await input.fill("취소해줘");
  await page.getByRole("button", { name: "메시지 전송", exact: true }).click();
  await expect(save).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("selected roles, grounded candidates and reload retry preserve the draft", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await fixtureLogin(page);
  const posts: Record<string, unknown>[] = [];
  const identifier = "44444444-4444-4444-8444-444444444444";
  const candidate = {
    ref: "p1",
    source: "naver",
    title: "합성 카페",
    address: "서울 중랑구",
    destination: "합성 카페 (서울 중랑구)",
  };
  const state = {
    date: null,
    region: "중랑구",
    activities: ["카페"],
    search_scope: { area: "중랑구", kinds: ["cafe"], search_only: true },
    control: { last_action: { operation: "search" }, outcome: "ready" },
  };
  let record: { id: string; version: number; turns: unknown[] } | null = null;
  await page.route("**/api/ai/planner**", async (route) => {
    const request = route.request(),
      query = new URL(request.url()).searchParams;
    if (request.method() === "GET") {
      const data =
        query.get("view") === "places"
          ? [{ source: "favorite", id: identifier, title: "합성 기준점", address: "서울 중랑구" }]
          : query.has("conversation_id") && record
            ? {
                version: record.version,
                proposal: null,
                turns: JSON.parse(
                  JSON.stringify(record.turns, (key, value) =>
                    key === "search_scope"
                      ? Object.fromEntries(Object.entries(value).reverse())
                      : value,
                  ),
                ),
              }
            : record
              ? [
                  {
                    id: record.id,
                    title: "합성 장소 대화",
                    version: record.version,
                    updated_at: new Date().toISOString(),
                  },
                ]
              : [];
      return route.fulfill({ json: data });
    }
    const body = request.postDataJSON();
    posts.push(body);
    const isChat = body.messages.at(-1).content === "고마워";
    const result = {
      reply: isChat ? "합성 감사 응답" : `합성 검색 결과 ${posts.length}`,
      plan: null,
      context: state,
      tools: isChat ? [] : [{ name: "search_places", status: "ok", count: 1 }],
      candidates: isChat ? [] : [candidate],
      checks: [],
      version: posts.length,
    };
    const turn = {
      request_id: body.request_id,
      version: posts.length,
      user_text: body.messages.at(-1).content,
      result,
    };
    record = {
      id: body.conversation_id,
      version: posts.length,
      turns: [...(record?.turns || []), turn],
    };
    return route.fulfill({ json: result });
  });
  await page.goto("/plans/ai");
  await page.getByRole("button", { name: "바로 대화", exact: true }).click();
  await page.getByRole("button", { name: "저장한 장소", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "저장한 장소" });
  await dialog.getByRole("checkbox", { name: /합성 기준점/ }).check();
  await dialog.getByRole("combobox", { name: "합성 기준점 사용 방식" }).selectOption("anchor");
  await expect(dialog.getByRole("combobox")).toHaveValue("anchor");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await dialog.getByRole("button", { name: "완료", exact: true }).click();
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  await input.fill("카페 검색");
  await input.press("Enter");
  await expect(page.getByText("합성 검색 결과 1", { exact: true })).toBeVisible();
  expect(posts[0].selected_places).toEqual([
    { source: "favorite", id: identifier, usage: "anchor" },
  ]);
  await input.fill("고마워");
  await input.press("Enter");
  await expect(page.getByText("합성 감사 응답", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "장소 후보 1개 보기", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("합성 감사 응답", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "후보 다시 검색", exact: true })).toBeVisible();
  await input.fill("고마워");
  await input.press("Enter");
  await expect(page.getByText("합성 감사 응답", { exact: true })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "후보 다시 검색", exact: true })).toBeVisible();
  await input.fill("아직 보내지 않은 조건");
  await page.getByRole("button", { name: "후보 다시 검색", exact: true }).click();
  await expect(page.getByText("합성 검색 결과 4", { exact: true })).toBeVisible();
  expect(posts[3].selected_places).toEqual([]);
  await expect(input).toHaveValue("아직 보내지 않은 조건");
  await page.setViewportSize({ width: 320, height: 568 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

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
  await expect(page.getByRole("alert").filter({ hasText: "합성 일시 오류" })).toBeVisible();
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

const historyIds = ["10000000-0000-4000-8000-000000000001", "10000000-0000-4000-8000-000000000002"];
const historyItems = historyIds.map((id, index) => ({
  id,
  title: `합성 대화 ${index + 1}`,
  version: 1,
  updated_at: "2026-10-27T01:00:00Z",
}));
function screenPlan(zero = false): PlanContent {
  return {
    title: "합성 코스 미리보기",
    date: "2030-01-05",
    transport: "도보",
    budget: zero ? 0 : 30000,
    preparation: ["우산"],
    activities: [
      {
        title: "공공 도서관",
        time: null,
        place: "합성구 공공장소",
        cost: zero ? 0 : 6000,
        note: "실제 장소가 아닌 합성 UI 확인용 메모입니다. ".repeat(5),
      },
    ],
  };
}
function screenHistory(id: string) {
  return {
    version: 1,
    proposal: screenPlan(),
    turns: [
      {
        request_id: id,
        version: 1,
        user_text: "합성 이전 질문",
        prompt_version: "fixture",
        result: {
          reply: "합성 이전 응답",
          plan: screenPlan(),
          context: { date: "2030-01-05", region: "합성구", activities: ["도서관"] },
        },
      },
    ],
  };
}
async function fixtureLogin(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  if (await page.getByRole("button", { name: "새 공간 만들기" }).isVisible())
    await page.getByRole("button", { name: "새 공간 만들기" }).click();
}

test("place and candidate dialogs preserve composer space, selection and conversation drafts", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await fixtureLogin(page);
  let placeFailure = true;
  let acceptedVersion = 1;
  const posts: Record<string, unknown>[] = [];
  let releaseReply = () => {};
  const firstReply = new Promise<void>((resolve) => {
    releaseReply = resolve;
  });
  const candidates = [1, 2].map((number) => ({
    ref: `naver:fixture${number}`,
    source: "naver",
    title: `합성 후보 ${number}`,
    address: "합성구 공공장소",
  }));
  await page.route("**/api/ai/planner**", async (route) => {
    const request = route.request(),
      query = new URL(request.url()).searchParams;
    if (request.method() === "GET") {
      if (query.get("view") === "places") {
        if (placeFailure)
          return route.fulfill({ status: 503, json: { error: "합성 장소 조회 실패" } });
        const source = query.get("source") || "favorite",
          offset = Number(query.get("offset") || 0);
        return route.fulfill({
          json: Array.from({ length: source === "wish" ? 3 : offset ? 2 : 50 }, (_, index) => ({
            source,
            id: `20000000-0000-4000-8000-${String(offset + index).padStart(12, "0")}`,
            title: `합성 ${source === "wish" ? "위시" : "장소"} ${offset + index}`,
            address: "합성구 공공장소",
          })),
        });
      }
      return route.fulfill({
        json: query.has("conversation_id")
          ? screenHistory(query.get("conversation_id") || "")
          : historyItems,
      });
    }
    const body = request.postDataJSON();
    posts.push(body);
    if (posts.length === 1) await firstReply;
    return route.fulfill({
      json: {
        reply: "합성 후보 응답",
        plan: screenPlan(),
        candidates,
        checks: [],
        version: ++acceptedVersion,
        context: { date: "2030-01-05", region: "합성구", activities: ["도서관"] },
      },
    });
  });
  await page.goto("/plans/ai");
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  await expect(input).toBeEditable();
  await input.fill("첫 대화의 미전송 문장");
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 320, height: 568 },
    { width: 393, height: 420 },
  ]) {
    await page.setViewportSize(viewport);
    const conditions = page.locator(".we2-brief-summary summary");
    await conditions.click();
    await expect(conditions).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await conditions.hover();
    await expect(conditions).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await conditions.click();
    const before = await page.locator(".we2-chat").boundingBox();
    const composer = await page.locator(".we2-composer").boundingBox();
    expect(composer && before && composer.y + composer.height <= before.y + before.height + 1).toBe(
      true,
    );
    await page.getByRole("button", { name: "저장한 장소", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "저장한 장소", exact: true });
    await expect(dialog).toBeVisible();
    const rect = await dialog.boundingBox();
    expect(
      rect &&
        rect.x >= 0 &&
        rect.y >= 0 &&
        rect.x + rect.width <= viewport.width + 1 &&
        rect.y + rect.height <= viewport.height + 1,
    ).toBe(true);
    expect((await page.locator(".we2-chat").boundingBox())?.height).toBe(before?.height);
    await expect(dialog.getByRole("alert")).toContainText("합성 장소 조회 실패");
    await expect(dialog.getByText("저장한 장소가 없어요.", { exact: true })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "저장한 장소", exact: true })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.getByRole("button", { name: "저장한 장소", exact: true }).click();
  const picker = page.getByRole("dialog", { name: "저장한 장소", exact: true });
  await expect(picker.getByRole("alert")).toContainText("합성 장소 조회 실패");
  placeFailure = false;
  await picker.getByRole("button", { name: "다시 불러오기", exact: true }).click();
  await expect(picker.locator("input[type=checkbox]")).toHaveCount(50);
  for (let index = 0; index < 8; index++)
    await picker.locator("input[type=checkbox]").nth(index).check();
  await expect(picker.locator("input[type=checkbox]").nth(8)).toBeDisabled();
  await picker.getByRole("button", { name: "더 보기", exact: true }).click();
  await expect(picker.locator("input[type=checkbox]")).toHaveCount(52);
  await picker.getByRole("button", { name: "위시", exact: true }).click();
  await expect(picker.locator("input[type=checkbox]")).toHaveCount(3);
  await expect(picker.locator("input[type=checkbox]").first()).toBeDisabled();
  await picker.locator(".we2-selected-places button").first().click();
  await picker.locator("input[type=checkbox]").first().check();
  await expect(picker.getByText("8 / 8개 선택", { exact: true })).toBeVisible();
  await picker.getByRole("button", { name: "완료", exact: true }).click();
  await expect(input).toHaveValue("첫 대화의 미전송 문장");
  await page.getByRole("button", { name: "대화 기록", exact: true }).click();
  await expect(page.getByRole("region", { name: "저장한 대화", exact: true })).toBeFocused();
  await page.getByRole("button", { name: /합성 대화 2/ }).click();
  await expect(input).toBeEditable();
  await expect(input).toHaveValue("");
  await input.fill("둘째 대화의 미전송 문장");
  await page.getByRole("button", { name: /합성 대화 1/ }).click();
  await expect(input).toHaveValue("첫 대화의 미전송 문장");
  await input.fill("후보를 찾아줘");
  await input.press("Enter");
  try {
    await expect.poll(() => posts.length).toBe(1);
    await expect(input).toHaveAttribute("readonly", "");
    await expect(input).toBeFocused();
  } finally {
    releaseReply();
  }
  await expect(page.getByText("합성 후보 응답", { exact: true })).toBeVisible();
  await expect(input).toBeEditable();
  await input.fill("후보 선택과 별도로 작성 중인 문장");
  await page.getByRole("button", { name: "장소 후보 2개 보기", exact: true }).click();
  const candidateDialog = page.getByRole("dialog", { name: "장소 후보", exact: true });
  await candidateDialog.getByRole("button", { name: "합성 후보 1 선택", exact: true }).click();
  await expect(candidateDialog).toHaveCount(0);
  await expect.poll(() => posts.length).toBe(2);
  await expect(input).toBeEditable();
  await expect(input).toHaveValue("후보 선택과 별도로 작성 중인 문장");
  await expect(page.locator(".we2-messages")).toContainText("선택한 장소: 합성 후보 1");
  await expect(page.locator(".we2-proposal")).toContainText("예산 30,000원");
  await expect(page.locator(".we2-proposal")).toContainText("예상 6,000원");
  expect(browserErrors).toEqual([]);
});

test("history recovery, new-conversation scroll, ephemeral drafts and message retry", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await fixtureLogin(page);
  let historyFailure = true,
    replyFailure = true;
  const posts: Record<string, unknown>[] = [];
  await page.route("**/api/ai/planner**", async (route) => {
    const request = route.request(),
      query = new URL(request.url()).searchParams;
    if (request.method() === "GET") {
      if (historyFailure) return route.fulfill({ status: 503, json: { error: "합성 조회 실패" } });
      return route.fulfill({
        json: query.has("conversation_id")
          ? screenHistory(query.get("conversation_id") || "")
          : historyItems,
      });
    }
    posts.push(request.postDataJSON());
    if (replyFailure) return route.fulfill({ status: 503, json: { error: "합성 응답 실패" } });
    return route.fulfill({
      json: {
        reply: "합성 재시도 성공",
        plan: screenPlan(true),
        candidates: [],
        checks: [],
        version: 2,
        context: { date: "2030-01-05", region: "합성구", activities: ["도서관"] },
      },
    });
  });
  await page.goto("/plans/ai");
  const history = page.getByRole("region", { name: "저장한 대화", exact: true });
  await expect(history.getByRole("alert")).toContainText("불러오지 못했어요");
  await expect(history.getByText("저장한 대화가 없어요.", { exact: true })).toHaveCount(0);
  historyFailure = false;
  await history.getByRole("button", { name: "다시 불러오기", exact: true }).click();
  await page.getByRole("button", { name: /합성 대화 1/ }).click();
  const input = page.getByLabel("위투 AI에게 보낼 내용", { exact: true });
  await expect(input).toBeEditable();
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole("button", { name: "새 대화", exact: true }).click();
  const form = page.getByRole("form", { name: "코스 조건 입력", exact: true });
  await expect(form.getByRole("heading")).toBeFocused();
  expect(await page.locator(".we2-messages").evaluate((element) => element.scrollTop)).toBe(0);
  const top = await form.getByRole("heading").boundingBox(),
    log = await page.locator(".we2-messages").boundingBox();
  expect(top && log && top.y >= log.y).toBe(true);
  for (const field of await form.locator("input").all())
    expect((await field.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await form.getByRole("button", { name: "바로 대화", exact: true }).click();
  await input.fill("새 대화의 미전송 문장");
  await page.getByRole("button", { name: "대화 기록", exact: true }).click();
  await page.getByRole("button", { name: /합성 대화 2/ }).click();
  await expect(input).toBeEditable();
  await page.getByRole("button", { name: "새 대화", exact: true }).click();
  await expect(input).toHaveValue("새 대화의 미전송 문장");
  await expect(input).toBeFocused();
  await page.reload();
  await expect(input).toBeEditable();
  await expect(input).toHaveValue("");
  const originalHeight = (await page.locator(".we2-chat").boundingBox())?.height;
  await input.fill("합성 재시도 요청");
  await input.press("Enter");
  await expect(page.locator(".we2-status").getByRole("alert")).toContainText("합성 응답 실패");
  await expect(input).toHaveValue("합성 재시도 요청");
  await expect(input).toBeFocused();
  expect((await page.locator(".we2-chat").boundingBox())?.height).toBe(originalHeight);
  replyFailure = false;
  await page.getByRole("button", { name: "메시지 다시 전송", exact: true }).click();
  await expect(page.getByText("합성 재시도 성공", { exact: true })).toBeVisible();
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(posts[0]);
  await expect(input).toBeFocused();
  await expect(page.locator(".we2-costs")).toHaveCount(0);
  await page.setViewportSize({ width: 320, height: 568 });
  const title = await page.locator(".we2-chat-header strong").boundingBox();
  expect(title?.height).toBeLessThan(30);
  await page.getByRole("button", { name: "코스 보기", exact: true }).click();
  await expect(page.getByRole("region", { name: "코스 초안", exact: true })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(browserErrors).toEqual([]);
});
