export type Couple = { id: string; member_count: number };
export type Appointment = {
  kind?: "shared" | "personal";
  id: string;
  title: string;
  date: string;
  time: string | null;
  place: string;
  note: string;
  version: number;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};
export type SaveState = { error: string; appointment?: Appointment; conflict?: boolean };
export type CoupleState = { error: string; token?: string; expires_at?: string };
