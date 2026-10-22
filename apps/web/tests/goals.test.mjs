import assert from "node:assert/strict";
import { test } from "node:test";
import { goalProgress } from "../src/lib/goals.ts";

test("zero steps stay undecided; progress counts checked steps without altering manual completion", () => {
  assert.deepEqual(goalProgress([]), { done: 0, total: 0, percent: null });
  const goal = { steps: [{ done: true }, { done: false }, { done: false }], completed: false };
  assert.deepEqual(goalProgress(goal.steps), { done: 1, total: 3, percent: 33 });
  goal.steps.forEach((step) => {
    step.done = true;
  });
  assert.deepEqual(goalProgress(goal.steps), { done: 3, total: 3, percent: 100 });
  assert.equal(goal.completed, false);
});
