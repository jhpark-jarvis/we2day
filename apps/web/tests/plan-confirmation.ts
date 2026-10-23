import { expect, type Page } from "@playwright/test";

// Existing editor scenarios resume explicitly after checking the new completion destination.
export async function confirmPlanAndReopen(page: Page) {
  const title = await page.getByLabel("플랜 이름", { exact: true }).inputValue();
  const date = await page.getByLabel("플랜 날짜", { exact: true }).inputValue();
  const response = await page.request.get("/api/plans");
  expect(response.ok()).toBe(true);
  const plans: { id: string; content: { title: string; date: string } }[] = await response.json();
  const matching = plans.filter(
    (plan) => plan.content.title === title && plan.content.date === date,
  );
  expect(matching).toHaveLength(1);
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(page).toHaveURL(
    (url) => url.pathname === "/" && url.searchParams.get("date") === date,
  );
  await expect(page.getByRole("region", { name: "선택한 날짜의 약속", exact: true })).toContainText(
    title,
  );
  await page.goto(`/plans?item=${matching[0].id}`);
  await expect(page.getByLabel("플랜 이름", { exact: true })).toHaveValue(title);
}
