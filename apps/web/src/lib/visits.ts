import type { PlanContent } from "@/lib/plans";
export type VisitState = "planned" | "visited" | "skipped";
export type VisitChange = {
  publication: number;
  activity: number;
  state: VisitState;
  expected_version: number;
  request_id: string;
};
export type VisitProgress = {
  plan_id: string;
  publication: number;
  snapshot: PlanContent;
  states: VisitState[];
  version: number;
  updated_by: string;
  updated_at: string;
};
export const visitLabels: Record<VisitState, string> = {
  planned: "예정",
  visited: "방문 완료",
  skipped: "건너뜀",
};
