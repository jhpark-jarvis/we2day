import { expect, type Page, test } from "@playwright/test";
import { resetCourseFixture } from "./course-fixture";

test.use({ serviceWorkers: "block" });

async function login(page: Page, name = "member") {
  await page.goto("/login");
  await page.getByLabel("아이디", { exact: true }).fill(name);
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
}

test("wish list, explicit saves, status counts and responsive editor retain drafts and reject stale edits", async ({
  page,
  request,
  browser,
}, info) => {
  test.setTimeout(150_000);
  await resetCourseFixture(request);
  await login(page);
  await page.goto("/couple");
  await page.getByRole("button", { name: "새 공간 만들기", exact: true }).click();
  await expect(page.getByRole("button", { name: "초대 코드 만들기", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "초대 코드 만들기", exact: true }).click();
  const code = await page.getByLabel("상대에게 전달할 코드").inputValue();
  const partner = await browser.newContext({
    baseURL: "http://127.0.0.1:3100",
    serviceWorkers: "block",
  });
  try {
    const other = await partner.newPage();
    await login(other, "partner");
    await other.goto("/couple");
    await other.getByLabel("받은 초대 코드").fill(code);
    await other.getByRole("button", { name: "초대 수락하기" }).click();
    await expect(other.getByRole("status")).toContainText("두 사람이 연결되었어요");
    await page.goto("/wishlist");
    const tab = (name: string) =>
      page
        .getByRole("group", { name: "위시 상태" })
        .getByRole("button", { name: new RegExp(`^${name}`) });
    await expect(tab("예정")).toHaveText("예정0");
    const add = page.getByRole("button", { name: "위시 추가", exact: true });
    const dialog = page.getByRole("dialog");
    await add.click();
    await page.getByRole("button", { name: "활동", exact: true }).click();
    await page.getByLabel("위시 이름").fill("함께 미술관");
    await page.locator(".wish-note-field summary").click();
    await page.getByLabel("위시 메모").fill("아직 저장하지 않은 메모");
    await page.goBack();
    await expect(dialog).toHaveCount(0);
    await expect(add).toBeFocused();
    await page.goForward();
    await expect(page.getByLabel("위시 이름")).toHaveValue("함께 미술관");
    await expect(page.getByLabel("위시 메모")).toHaveValue("아직 저장하지 않은 메모");
    await page.getByRole("button", { name: "작성 취소" }).click();
    await add.click();
    await expect(page.getByLabel("위시 이름")).toHaveValue("함께 미술관");
    await page.getByRole("button", { name: "위시 저장", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(tab("예정")).toHaveText("예정1");
    await expect(page.locator(".wish-row a").filter({ hasText: "네이버" })).toHaveCount(0);

    await page.route("**/api/places/search", (route) =>
      route.fulfill({
        json: {
          items: [
            {
              title: "합성 카페",
              link: "",
              category: "카페",
              description: "",
              address: "서울특별시 성동구 합성로 10",
              roadAddress: "서울특별시 성동구 합성로 10",
            },
          ],
        },
      }),
    );
    await add.click();
    await page.getByLabel("장소 검색어", { exact: true }).fill("합성 카페");
    await page.getByRole("button", { name: "검색", exact: true }).click();
    await page.getByRole("button", { name: "합성 카페 선택", exact: true }).click();
    await page.getByRole("button", { name: "링크", exact: true }).click();
    await page.getByLabel("네이버 지도 공유 링크").fill("https://naver.me/fixture123");
    await page.locator(".wish-note-field summary").click();
    await page.getByLabel("위시 메모").fill("산책 후 들를 곳");
    await page.screenshot({ path: info.outputPath("wish-editor.png") });
    const bounds = await dialog.boundingBox();
    const viewport = page.viewportSize();
    expect(bounds).not.toBeNull();
    if (bounds && viewport) {
      if (viewport.width >= 900)
        expect(
          Math.abs(
            bounds.x +
              bounds.width -
              (await page.evaluate(() => document.documentElement.clientWidth)),
          ),
        ).toBeLessThanOrEqual(20); // The app reserves the desktop scrollbar gutter to prevent layout shifts.
      else expect(Math.abs(bounds.y + bounds.height - viewport.height)).toBeLessThan(2);
    }
    await page.getByRole("button", { name: "위시 저장", exact: true }).click();
    await expect(tab("예정")).toHaveText("예정2");
    const row = page.locator(".wish-row").filter({ hasText: "합성 카페" });
    await expect(row.getByRole("link", { name: /네이버 지도/ }).first()).toHaveAttribute(
      "href",
      "https://naver.me/fixture123",
    );
    await page.reload();
    await expect(row).toBeVisible();
    await page.screenshot({ path: info.outputPath("wish-list.png"), fullPage: true });
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
    if (viewport) await page.setViewportSize(viewport);
    await row.getByRole("link", { name: /코스 초안/ }).click();
    await expect(page.getByLabel("활동 1 장소", { exact: true })).toHaveValue(/합성 카페/);
    await expect(page.getByLabel("네이버 지도 공유 링크", { exact: true })).toHaveValue(
      "https://naver.me/fixture123",
    );
    await page.goto("/wishlist");
    const menu = row.locator("summary");
    await menu.click();
    await row.getByRole("button", { name: "완료", exact: true }).click();
    await expect(tab("완료")).toHaveText("완료1");
    await tab("완료").click();
    await expect(row).toBeVisible();
    await menu.click();
    await row.getByRole("button", { name: "보관", exact: true }).click();
    await expect(tab("보관")).toHaveText("보관1");
    await tab("보관").click();
    await expect(row).toBeVisible();
    await menu.click();
    await row.getByRole("button", { name: "복원", exact: true }).click();
    await expect(tab("완료")).toHaveText("완료1");
    await tab("완료").click();
    await menu.click();
    await row.getByRole("button", { name: "예정으로", exact: true }).click();
    await expect(tab("예정")).toHaveText("예정2");
    await tab("예정").click();

    await page.route("**/api/wishlist?view=done&offset=0", (route) =>
      route.fulfill({ status: 503, json: { error: "synthetic unavailable" } }),
    );
    await tab("완료").click();
    await expect(page.locator('.wish-feedback[role="alert"]')).toContainText(
      "위시 목록을 불러오지 못했어요",
    );
    await expect(tab("예정")).toHaveAttribute("aria-pressed", "true");
    await expect(row).toBeVisible();
    await page.unroute("**/api/wishlist?view=done&offset=0");

    await page.getByRole("button", { name: "위시 수정 · 합성 카페", exact: true }).click();
    await other.goto("/wishlist");
    await other.getByRole("button", { name: "위시 수정 · 합성 카페", exact: true }).click();
    await other.getByLabel("위시 이름").fill("상대가 수정한 카페");
    await other.getByRole("button", { name: "위시 저장", exact: true }).click();
    await expect(other.getByRole("dialog")).toHaveCount(0);
    await page.getByLabel("위시 이름").fill("내가 작성 중인 카페");
    await page.getByRole("button", { name: "위시 저장", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("상대가 위시를 수정했어요");
    await expect(page.getByLabel("위시 이름")).toHaveValue("내가 작성 중인 카페");
    await expect(page.getByRole("button", { name: "위시 저장", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "작성 내용 폐기", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "상대가 수정한 카페", exact: true }),
    ).toBeVisible();
    const saved = await (await page.request.get("/api/wishlist?view=planned")).json();
    const wish = saved.items.find((item: { title: string }) => item.title === "상대가 수정한 카페");
    await page.goto(`/wishlist?item=${wish.id}`);
    await expect(page.getByLabel("위시 이름")).toHaveValue("상대가 수정한 카페");
    await page.getByRole("button", { name: "작성 취소" }).click();
    await expect(page).toHaveURL(/\/wishlist$/);
    await expect(dialog).toHaveCount(0);

    await page.route("**/api/favorite-places?*", (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: "00000000-0000-4000-8000-000000000123",
              label: "합성 저장 장소",
              destination: "합성 도서관 (서울특별시 중랑구 합성로 20)",
              archived: false,
              version: 1,
              updated_by: wish.updated_by,
              updated_at: wish.updated_at,
            },
          ],
          next_offset: null,
        },
      }),
    );
    await add.click();
    await page.getByRole("button", { name: "자주 가는 곳", exact: true }).click();
    await page.getByRole("button", { name: /합성 저장 장소/ }).click();
    await expect(page.getByLabel("장소", { exact: true })).toHaveValue(/합성 도서관/);
    await expect(page.getByLabel("위시 이름")).toHaveValue("합성 도서관");
    if (info.project.name === "safari")
      await expect(page.getByLabel("위시 이름")).toHaveCSS("font-size", "16px");
    await page.getByRole("button", { name: "작성 취소" }).click();
    expect(
      (await (await page.request.get("/api/wishlist?view=planned")).json()).counts.planned,
    ).toBe(2);
  } finally {
    await partner.close();
  }
});
