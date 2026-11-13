import { expect, test } from "@playwright/test";
import { resetCourseFixture } from "./course-fixture";
import { confirmPlanAndReopen } from "./plan-confirmation";

test.beforeEach(async ({ request }) => resetCourseFixture(request));

test.use({ serviceWorkers: "block" });
test("appointment detail keeps the complete linked course and met-day completion in sync", async ({
  page,
}, info) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(15_000);
  const day = "2026-01-01";
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  for (const [title, count] of [
    ["합성 전체 코스", 3],
    ["같은 날 다른 약속", 1],
  ] as const) {
    await page.goto("/plans");
    await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
    await page.getByLabel("플랜 이름", { exact: true }).fill(title);
    await page.getByLabel("플랜 날짜", { exact: true }).fill(day);
    for (let index = 1; index <= count; index++) {
      await page.getByRole("button", { name: "활동 추가", exact: true }).click();
      await page.getByLabel(`활동 ${index} 이름`, { exact: true }).fill(`${title} 활동 ${index}`);
      await page
        .getByLabel(`활동 ${index} 장소`, { exact: true })
        .fill(`합성 장소 ${index} 긴 이름과 주소`);
      await page.getByLabel(`활동 ${index} 시간`, { exact: true }).fill(`${12 + index}:00`);
    }
    await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
    await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
    await confirmPlanAndReopen(page);
  }
  async function calendar() {
    await page
      .getByRole("navigation", { name: "주요 메뉴", exact: true })
      .getByRole("link", { name: "일정", exact: true })
      .click();
    await page.goto(`/?date=${day}`);
    await expect(
      page.getByRole("region", { name: "선택한 날짜의 약속", exact: true }),
    ).toBeVisible();
  }
  async function detail(title: string) {
    await calendar();
    await page
      .getByRole("button")
      .filter({ has: page.getByText(title, { exact: true }) })
      .click();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  }
  await detail("합성 전체 코스");
  const course = page.getByRole("region", { name: "코스", exact: true });
  await expect(course.locator(".course-stop")).toHaveCount(3, { timeout: 20_000 });
  await expect(course.getByText("같은 날 다른 약속 활동 1", { exact: true })).toHaveCount(0);
  for (let index = 1; index <= 3; index++) {
    await expect(
      course.getByRole("heading", { name: `합성 전체 코스 활동 ${index}`, exact: true }),
    ).toBeVisible();
    await expect(
      course.getByRole("link", {
        name: `합성 장소 ${index} 긴 이름과 주소 네이버 지도`,
        exact: true,
      }),
    ).toHaveAttribute("href", /^nmap:\/\/search\?/);
  }
  await expect(course.locator(".visit-state").first()).toHaveText("예정");
  await page.screenshot({ path: info.outputPath("appointment-course.png"), fullPage: true });
  if (info.project.name.includes("safari")) {
    await page.setViewportSize({ width: 320, height: 780 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: info.outputPath("appointment-course-320.png"), fullPage: true });
  }
  await course.getByRole("button", { name: "건너뜀", exact: true }).first().click();
  await expect(course.locator(".visit-state").first()).toHaveText("건너뜀");
  await detail("같은 날 다른 약속");
  await expect(course.locator(".course-stop")).toHaveCount(1);
  await calendar();
  await page.getByRole("button", { name: "만남 기록", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "만남 기록", exact: true });
  await dialog.getByLabel("이 날 만났어요", { exact: true }).check();
  await dialog.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
  await expect(page.getByText("만남 기록을 저장했어요.", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "만남 기록 닫기", exact: true }).click();
  await detail("합성 전체 코스");
  await expect(course.locator(".visit-state")).toHaveText(["방문 완료", "방문 완료", "방문 완료"]);
  await course.getByRole("button", { name: "방문 완료", exact: true }).first().click();
  await expect(course.locator(".visit-state").first()).toHaveText("예정");
  await calendar();
  await page.getByRole("button", { name: "만남 기록", exact: true }).click();
  await dialog.getByLabel("이 날 만났어요", { exact: true }).uncheck();
  await dialog.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
  await expect(page.getByText("만남 기록을 저장했어요.", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "만남 기록 닫기", exact: true }).click();
  await detail("합성 전체 코스");
  await expect(course.locator(".visit-state")).toHaveText(["예정", "방문 완료", "방문 완료"]);
  await page.route("**/api/appointments/*/course", (route) =>
    route.fulfill({ status: 503, json: { error: "합성 코스 조회 실패" } }),
  );
  await detail("합성 전체 코스");
  await expect(page.getByRole("alert").filter({ hasText: "합성 코스 조회 실패" })).toBeVisible();
  await page.unroute("**/api/appointments/*/course");
  await page.getByRole("button", { name: "다시 불러오기", exact: true }).click();
  await expect(course.locator(".course-stop")).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
