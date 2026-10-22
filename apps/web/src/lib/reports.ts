import type { PlanContent } from "@/lib/plans";
export type ReportContent = {
  summary: string;
  visits: string[];
  actual_cost: number | null;
  highlights: string;
  next_time: string;
  revisit: boolean | null;
};
export type DateReport = {
  plan_id: string;
  author_id: string;
  observed_plan_version: number;
  plan_snapshot: PlanContent;
  content: ReportContent;
  shared: boolean;
  version: number;
  updated_at: string;
};
