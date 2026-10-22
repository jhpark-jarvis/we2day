import assert from "node:assert/strict";
import { test } from "node:test";
import { localAppointmentTime } from "../src/lib/timezones.ts";

test("Korean source date stays fixed while local dates and DST change", () => {
  assert.equal(
    localAppointmentTime("2026-01-01", "00:30", "America/Los_Angeles"),
    "2025-12-31 07:30",
  );
  assert.equal(localAppointmentTime("2026-03-08", "15:30", "America/New_York"), "2026-03-08 01:30");
  assert.equal(localAppointmentTime("2026-03-08", "16:30", "America/New_York"), "2026-03-08 03:30");
  assert.equal(localAppointmentTime("2026-10-19", null, "UTC"), null);
  assert.equal(localAppointmentTime("2026-10-19", "시간 미정", "UTC"), null);
  assert.equal(localAppointmentTime("2026-10-19", "14:00", "invalid/zone"), null);
});
