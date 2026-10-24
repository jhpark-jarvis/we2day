import { expect, test } from "@playwright/test";

test("explicit key issuance, scoped draft access, human review and revocation", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  page.setDefaultTimeout(15000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await page.goto("/settings/agents");
  await expect(page.getByText("발급한 연결 키가 없어요.")).toBeVisible();
  await page.getByLabel("연결 이름").fill("Synthetic connection");
  await page.getByRole("button", { name: "연결 키 발급", exact: true }).click();
  const token = await page.getByLabel("발급된 연결 키").inputValue();
  expect(token).toMatch(/^w2d_agent_[0-9a-f]{64}$/);
  await page.getByRole("button", { name: "연결 키 닫기" }).click();
  await expect(page.getByLabel("발급된 연결 키")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Synthetic connection", { exact: true })).toBeVisible();
  await expect(page.getByLabel("발급된 연결 키")).toHaveCount(0);
  const date = "2026-11-08";
  const headers = { Authorization: `Bearer ${token}` };
  const api = "/api/agent/v1";
  // Cookie login alone must never authenticate the external channel.
  expect((await page.request.get(`${api}/calendar?start=${date}&end=${date}`)).status()).toBe(401);
  expect(
    (
      await page.request.get(`${api}/calendar?start=${date}&end=${date}&key=${token}`, { headers })
    ).status(),
  ).toBe(422);
  const content = {
    title: "Synthetic agent draft",
    date,
    budget: null,
    transport: "",
    activities: [
      {
        title: "산책",
        time: "14:00",
        place: "직접 확인할 장소",
        cost: null,
        note: "사용자 검토 전 초안",
      },
    ],
    preparation: [],
  };
  const body = { id: crypto.randomUUID(), request_id: crypto.randomUUID(), content };
  const created = await page.request.post(`${api}/drafts`, { headers, data: body });
  expect(created.status()).toBe(200);
  expect((await created.json()).created).toBe(true);
  expect(
    (await (await page.request.post(`${api}/drafts`, { headers, data: body })).json()).created,
  ).toBe(false);
  const calendar = await page.request.get(`${api}/calendar?start=${date}&end=${date}`, { headers });
  const result = await calendar.json();
  expect(result.appointments).toHaveLength(0);
  expect(result.plans).toHaveLength(1);
  expect(result.plans[0].published_content).toBeNull();
  expect(
    (
      await page.request.post(`${api}/plans/${body.id}`, { headers, data: { action: "confirm" } })
    ).status(),
  ).toBe(404);
  expect(
    (
      await page.request.post(`${api}/drafts`, {
        headers,
        data: { ...body, content: { ...content, title: "Overwrite" } },
      })
    ).status(),
  ).toBe(409);
  await page.goto(`/plans?item=${body.id}`);
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue(content.title);
  await page.goto("/settings/agents");
  await page.screenshot({
    path: testInfo.outputPath("agent-connections-mobile.png"),
    fullPage: true,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "폐기", exact: true }).click();
  await expect(page.getByText(/폐기됨/)).toBeVisible();
  expect((await page.request.get(`${api}/plans/${body.id}`, { headers })).status()).toBe(401);
});
