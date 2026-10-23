import assert from "node:assert/strict";
import test from "node:test";
import { projectRoutes } from "../src/lib/route-playback.ts";

const item = (date, start_lat, start_lng, end_lat, end_lng) => ({
  date,
  start_name: "시작",
  end_name: "끝",
  start_lat,
  start_lng,
  end_lat,
  end_lng,
});
test("playback sorts copies without changing source; one identical point stays centered", () => {
  const source = [item("2026-10-20", 37, 127, 37, 127), item("2026-10-01", 37, 127, 37, 127)];
  assert.deepEqual(projectRoutes([]), []);
  const result = projectRoutes(source);
  assert.equal(result[0].date, "2026-10-01");
  assert.equal(source[0].date, "2026-10-20");
  assert.deepEqual(result[0].start, [180, 108]);
  assert.deepEqual(result[0].end, [180, 108]);
});
test("common coordinate frame keeps north up, fits poles/date line and never connects days", () => {
  for (const rows of [
    [item("2026-10-01", 37, 127, 37.1, 127.1), item("2026-10-02", 37.2, 127.2, 37.3, 127.3)],
    [item("2026-10-01", 90, 179.9, 89.9, -179.9)],
    [item("2026-10-01", -90, -180, 90, 180)],
  ]) {
    const projected = projectRoutes(rows);
    assert.equal(projected.length, rows.length);
    for (const row of projected)
      for (const [x, y] of [row.start, row.end]) {
        assert.ok(Number.isFinite(x) && Number.isFinite(y));
        assert.ok(x >= 27.99 && x <= 332.01 && y >= 27.99 && y <= 188.01);
      }
  }
  const [north] = projectRoutes([item("2026-10-01", 37, 127, 38, 128)]);
  assert.ok(north.end[1] < north.start[1]);
});
