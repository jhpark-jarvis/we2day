export type RecordKind = "appointment" | "plan" | "report" | "wish";
export type RecordHit = {
  id: string;
  date: string;
  title: string;
  excerpt: string;
  state: string;
  visibility: string | null;
};
export type RecordPage = { items: RecordHit[]; next_offset: number | null };
export const recordKinds: Record<RecordKind, string> = {
  appointment: "약속",
  plan: "플랜",
  report: "회고",
  wish: "위시",
};
export const recordStates: Record<string, string> = {
  appointment: "달력 약속",
  draft: "미확정 초안",
  confirmed: "확정됨",
  changed: "미확정 변경 있음",
  archived: "보관됨",
  report: "회고",
  done: "완료",
  active: "진행 중",
};
export const recordVisibility: Record<string, string> = {
  own_private: "나의 비공개 초안",
  own_shared: "내가 공유한 회고",
  partner_shared: "상대가 공유한 회고",
};
export function recordHref(kind: RecordKind, item: RecordHit) {
  return kind === "appointment"
    ? `/?date=${item.date}`
    : kind === "report"
      ? `/plans/${item.id}/report`
      : kind === "plan"
        ? `/plans?item=${item.id}`
        : `/wishlist?item=${item.id}`;
}
