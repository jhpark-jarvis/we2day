export type MeetingDay = {
  date: string;
  met: boolean;
  note: string;
  version: number;
  updated_by: string;
  updated_at: string;
};

export type MeetingSaveState = { error: string; meeting?: MeetingDay; conflict?: boolean };
