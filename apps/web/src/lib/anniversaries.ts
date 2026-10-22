export type Anniversary = {
  id: string;
  kind: "relationship" | "birthday" | "custom";
  title: string;
  date: string | null;
  month: number | null;
  day: number | null;
  annual: boolean;
  version: number;
  next_date: string;
  days_until: number;
  together_days: number | null;
};
export type AnniversaryList = { as_of: string; items: Anniversary[] };
export type AnniversaryState = { error: string; anniversary?: Anniversary; conflict?: boolean };
export const kinds = { relationship: "우리의 시작", birthday: "생일", custom: "기념일" };
export function countdown(days: number) {
  return days === 0 ? "D-DAY" : days > 0 ? `D-${days}` : `D+${Math.abs(days)}`;
}
