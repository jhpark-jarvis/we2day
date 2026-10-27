import assert from "node:assert/strict";
import test from "node:test";
import { briefError, briefMessage, currentBrief, emptyBrief } from "../src/lib/ai-intake.ts";

test("unknown values remain unknown and canonical message matches server contract", () => {
  const brief = { ...emptyBrief(), region: "성수동", recommend: true };
  assert.equal(briefError(brief), "");
  assert.equal(briefMessage(brief), [
    "입력한 조건으로 장소 후보만 찾아줘. 날짜는 미정이야.", "날짜: 미정",
    "시간대: 미정 ~ 미정", "지역: 성수동", "이동수단: 미정", "활동: 자유롭게 추천",
    "예산: 미정", "추가 조건: 없음",
  ].join("\n"));
});
test("local validation checks only reached groups and optional budget accepts zero", () => {
  const brief = emptyBrief();
  assert.equal(briefError(brief, 0), "");
  assert.ok(briefError(brief, 1));
  assert.equal(briefError(brief, 1, 1), "");
  assert.ok(briefError(brief, 3, 1));
  const valid = { ...brief, region: "중랑구", activities: ["도서관", "카페"], budget: 0 };
  assert.equal(briefError(valid), "");
  for (const patch of [{ date: "2030-02-30" }, { start_time: "24:00" },
    { start_time: "14:00", end_time: "13:00" }, { recommend: true },
    { activities: ["카페", "카페"] }, { budget: Number.NaN }, { budget: -1 }])
    assert.ok(briefError({ ...valid, ...patch }));
});
test("restored summary prefers current conditions over initial request", () => {
  const data = { ...emptyBrief(), region: "중랑구", date: "2030-01-05", activities: ["도서관"], budget: 50000 };
  const context = { intake: { data }, date: null, budget: 0, region: "성수동", activities: ["카페"] };
  assert.deepEqual(currentBrief(context), { ...data, date: null, budget: 0, region: "성수동", activities: ["카페"] });
  assert.equal(data.region, "중랑구");
});
