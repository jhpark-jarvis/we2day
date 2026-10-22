import type { PlanContent } from "@/lib/plans";
export function planBudget(content: PlanContent) {
  let known = 0,
    unknown = 0;
  for (const activity of content.activities) {
    if (activity.cost === null) unknown++;
    else known += activity.cost;
  }
  return { known, unknown, total: unknown === 0 && content.activities.length > 0 ? known : null };
}

export function reviewPlan(content: PlanContent) {
  const costs = planBudget(content);
  const timing: { index: number; previous: number; same: boolean }[] = [];
  let previous = -1;
  let unknownTimes = 0;
  content.activities.forEach((activity, index) => {
    if (!activity.time) {
      unknownTimes++;
      return;
    }
    if (previous >= 0) {
      const before = content.activities[previous].time as string;
      if (activity.time <= before) timing.push({ index, previous, same: activity.time === before });
    }
    previous = index;
  });
  return {
    ...costs,
    timing,
    unknownTimes,
    overBudget: content.budget === null ? null : Math.max(0, costs.known - content.budget),
    budgetIsComplete: costs.total !== null && content.budget !== null,
  };
}
