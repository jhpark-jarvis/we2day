import type { Appointment } from "@/lib/shared-calendar";
export type Activity = {
  title: string;
  time: string | null;
  place: string;
  map_url?: string;
  cost: number | null;
  note: string;
};
export type PlanContent = {
  title: string;
  date: string;
  budget: number | null;
  transport: string;
  activities: Activity[];
  preparation: string[];
};
export type DatePlan = {
  id: string;
  content: PlanContent;
  published_content: PlanContent | null;
  published_revision: number;
  appointment_id: string | null;
  appointment: Appointment | null;
  archived: boolean;
  version: number;
  updated_by: string;
  updated_at: string;
};
export type PlanAction = "save" | "confirm" | "archive" | "restore";
export type PlanSummary = {
  id: string;
  title: string;
  date: string;
  transport: string;
  activity_count: number;
  status: "draft" | "confirmed" | "changed" | "archived";
  archived: boolean;
};
export const summaryLabels = {
  draft: "초안",
  confirmed: "확정됨",
  changed: "변경안 · 다시 확정 필요",
  archived: "보관됨",
} as const;
export function summarizePlan(plan: DatePlan): PlanSummary {
  return {
    id: plan.id,
    title: plan.content.title,
    date: plan.content.date,
    transport: plan.content.transport,
    activity_count: plan.content.activities.length,
    archived: plan.archived,
    status: plan.archived
      ? "archived"
      : !plan.published_content
        ? "draft"
        : JSON.stringify(plan.content) === JSON.stringify(plan.published_content)
          ? "confirmed"
          : "changed",
  };
}
export function planStatus(plan: DatePlan) {
  if (plan.archived) return "보관됨";
  if (!plan.published_content) return "초안";
  return JSON.stringify(plan.content) === JSON.stringify(plan.published_content)
    ? "확정됨"
    : "변경안 · 다시 확정 필요";
}
