export type UpcomingItem = {
  source: "appointment" | "anniversary";
  id: string;
  title: string;
  date: string;
  time: string | null;
  place: string;
  days_until: number;
};
export type UpcomingList = { as_of: string; until: string; items: UpcomingItem[] };

export type AnniversaryNotificationPreview = {
  as_of: string;
  through_date: string;
  timezone: "Asia/Seoul";
  preview_only: true;
  items: {
    anniversary_id: string;
    title: string;
    occurrence_date: string;
    lead_days: 7 | 1 | 0;
    scheduled_at: string;
  }[];
};
