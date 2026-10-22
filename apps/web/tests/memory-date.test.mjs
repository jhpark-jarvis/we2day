import assert from "node:assert/strict";
import { test } from "node:test";
import { previousYearDate } from "../src/lib/calendar.ts";

test("last-year memories preserve the exact original day without leap-day substitution", () => {
  assert.equal(previousYearDate("2026-10-21"), "2025-10-21");
  assert.equal(previousYearDate("2025-02-28"), "2024-02-28");
  assert.equal(previousYearDate("2028-02-29"), null);
  assert.equal(previousYearDate("2000-01-01"), null);
  assert.equal(previousYearDate("2100-12-31"), "2099-12-31");
  for (const value of ["2026-02-29", "2026-13-01", "x", "1999-01-01", "2101-01-01"]) {
    assert.equal(previousYearDate(value), null);
  }
});
