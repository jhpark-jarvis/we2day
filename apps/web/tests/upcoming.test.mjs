import assert from "node:assert/strict";
import { test } from "node:test";
import { localAppointmentTime } from "../src/lib/timezones.ts";
import { remainingAppointment } from "../src/lib/upcoming.ts";

test("Korean date boundary and unknown time never fabricate a countdown", () => {
  const now = Date.parse("2026-10-20T15:30:00Z");
  assert.equal(remainingAppointment("2026-10-21", null, now), "오늘 · 시간 미정");
  assert.equal(remainingAppointment("2026-10-22", null, now), "D-1 · 시간 미정");
  assert.match(remainingAppointment("2026-10-21", "01:00:00", now), /0시간 30분/);
  assert.match(remainingAppointment("2026-10-21", "00:00:00", now), /지났어요/);
  assert.equal(
    localAppointmentTime("2026-03-09", "00:30:00", "America/New_York"),
    "2026-03-08 11:30",
  );
  assert.equal(localAppointmentTime("2026-03-09", null, "America/New_York"), null);
});
