import { expect, test } from "@playwright/test";

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
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill("member");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await page.goto("/plans");
  await page.getByRole("button", { name: "플랜 만들기", exact: true }).click();
  await page.getByLabel("플랜 이름", { exact: true }).fill("합성 앱 이동 플랜");
  const date = await page.getByLabel("플랜 날짜").inputValue();
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 1 이름").fill("공공 장소 예시");
  await page.getByLabel("활동 1 장소").fill("강남역 & 공공 예시");
  await page.getByRole("button", { name: "활동 추가", exact: true }).click();
  await page.getByLabel("활동 2 이름").fill("장소 없는 합성 활동");
  await page.getByRole("button", { name: "플랜 저장", exact: true }).click();
  await page.getByRole("button", { name: "확정 내용 확인", exact: true }).click();
  await page.getByRole("button", { name: "이 내용으로 확정하기", exact: true }).click();
  await expect(page.getByText("확정됨", { exact: true })).toBeVisible();
  await page.goto(`/today?date=${date}`);
  await page.getByRole("button", { name: "네이버 지도 앱 이동 준비", exact: true }).click();
  const search = page.getByRole("link", { name: "네이버 지도 앱에서 장소 검색", exact: true });
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
  await page.getByRole("button", { name: "네이버 지도 앱 이동 준비", exact: true }).click();
  await page.getByText("목적지 좌표로 바로 길찾기", { exact: true }).click();
  await expect(page.getByLabel("길찾기 목적지 위도")).toHaveValue("");
  await expect(page.getByRole("region", { name: "공동 방문 진행" })).not.toContainText(
    "마지막 변경",
  );
  expect(external).toBe(0);
  expect(visitWrites).toBe(0);
});
