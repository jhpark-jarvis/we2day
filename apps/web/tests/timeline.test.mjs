import assert from "node:assert/strict";
import { test } from "node:test";
import { planBudget, reviewPlan } from "../src/lib/timeline.ts";

test("unknown expenses remain unknown and zero is an explicit known amount", () => {
  assert.deepEqual(planBudget({ activities: [] }), { known: 0, unknown: 0, total: null });
  assert.deepEqual(planBudget({ activities: [{ cost: null }, { cost: 0 }, { cost: 12000 }] }), {
    known: 12000,
    unknown: 1,
    total: null,
  });
  assert.deepEqual(planBudget({ activities: [{ cost: 0 }, { cost: 12000 }] }), {
    known: 12000,
    unknown: 0,
    total: 12000,
  });
});

test("plan review preserves order, compares known times and does not complete unknown budgets", () => {
  const content = {
    budget: 10000,
    activities: [
      { time: "14:00", cost: 12000 },
      { time: null, cost: null },
      { time: "13:00", cost: 0 },
      { time: "13:00", cost: null },
    ],
  };
  const before = structuredClone(content);
  assert.deepEqual(reviewPlan(content), {
    known: 12000,
    unknown: 2,
    total: null,
    timing: [
      { index: 2, previous: 0, same: false },
      { index: 3, previous: 2, same: true },
    ],
    unknownTimes: 1,
    overBudget: 2000,
    budgetIsComplete: false,
  });
  assert.deepEqual(content, before);
  assert.equal(reviewPlan({ activities: [], budget: 0 }).budgetIsComplete, false);
  const zero = reviewPlan({ activities: [{ time: "00:00", cost: 0 }], budget: 0 });
  assert.equal(zero.budgetIsComplete, true);
  assert.equal(zero.overBudget, 0);
  assert.equal(zero.unknownTimes, 0);
  const unknown = reviewPlan({ activities: [{ time: "23:59", cost: 5 }], budget: null });
  assert.equal(unknown.overBudget, null);
  assert.equal(unknown.budgetIsComplete, false);
});
