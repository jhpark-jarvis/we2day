export type GoalStep = {
  id: string;
  title: string;
  done: boolean;
};
export type GoalContent = {
  title: string;
  target_date: string | null;
  steps: GoalStep[];
  completed: boolean;
  archived: boolean;
};
export type Goal = GoalContent & {
  id: string;
  version: number;
  updated_by: string;
  updated_at: string;
};

export function goalProgress(steps: readonly Pick<GoalStep, "done">[]) {
  const done = steps.filter((step) => step.done).length;
  return {
    done,
    total: steps.length,
    percent: steps.length ? Math.round((done / steps.length) * 100) : null,
  };
}
