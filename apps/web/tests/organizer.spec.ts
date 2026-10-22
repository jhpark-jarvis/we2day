import fs from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("upcoming dates, selected-day links, calendar download and monthly originals", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기" }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.goto("/");
  await page.getByRole("button", { name: "약속 추가하기" }).click();
  await page.getByLabel("약속 이름").fill("알림함 검증용 산책");
  await page.getByLabel("시간 (선택)").fill("14:30");
  await page.getByLabel("만날 장소 (선택)").fill("직접 정한 산책길");
  await page.getByLabel("메모 (선택)").fill("선택해야 내보내는 메모");
  const date = await page.getByLabel("날짜", { exact: true }).inputValue();
  await page.getByRole("button", { name: "약속 저장하기", exact: true }).click();
  await expect(page.getByRole("button", { name: /알림함 검증용 산책/ })).toBeVisible();
  await page.getByLabel("이 날 만났어요", { exact: true }).check();
  await page.getByRole("button", { name: "만남 기록 저장", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "만남 기록을 저장했어요" }),
  ).toBeVisible();
  await page.goto("/anniversaries");
  await page.getByRole("button", { name: "기념일 추가하기" }).click();
  await page.getByLabel("기념일 이름").fill("알림함 검증용 기념일");
  await page.getByRole("button", { name: "기념일 저장하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "알림함 검증용 기념일", exact: true }),
  ).toBeVisible();
  await page.goto("/reminders?days=30");
  await expect(
    page.getByRole("heading", { name: "알림함 검증용 산책", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "알림함 검증용 기념일", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("reminders-mobile.png"), fullPage: true });
  await page.getByRole("link", { name: "이 날짜의 일정 보기", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`date=${date}`));
  await expect(page.getByRole("button", { name: /알림함 검증용 산책/ })).toBeVisible();
  await page.goto("/calendar/export");
  await page.getByLabel("내보낼 월").fill(date.slice(0, 7));
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "캘린더 파일 다운로드", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe(`we2day-calendar-${date.slice(0, 7)}.ics`);
  const path = await download.path();
  expect(path).not.toBeNull();
  const content = await fs.readFile(path as string, "utf8");
  expect(content).toContain("BEGIN:VCALENDAR");
  expect(content).toContain("알림함 검증용 산책");
  expect(content).toContain("알림함 검증용 기념일");
  expect(content).not.toContain("선택해야 내보내는 메모");
  await page.getByLabel("약속 메모도 파일에 포함").check();
  const [withNotes] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "캘린더 파일 다운로드", exact: true }).click(),
  ]);
  expect(await fs.readFile((await withNotes.path()) as string, "utf8")).toContain(
    "선택해야 내보내는 메모",
  );
  await page.goto(`/memories/month?month=${date.slice(0, 7)}`);
  const totals = page.getByLabel("선택한 달의 기록 합계");
  await expect(totals).toContainText("만난 날1일");
  await expect(totals).toContainText("남긴 사진0장");
  await expect(totals).toContainText("직선 동선0일");
  await page.screenshot({ path: testInfo.outputPath("monthly-mobile.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("link", { name: "일정·동선 보기", exact: true }).click();
  await expect(page.getByLabel("이 날 만났어요", { exact: true })).toBeChecked();
  await page.goto("/memories/month?month=2000-01");
  await expect(page.getByText("이 달에는 아직 남긴 기록이 없어요.")).toBeVisible();
});
