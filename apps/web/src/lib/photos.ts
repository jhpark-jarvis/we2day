export type SharedPhoto = {
  id: string;
  date: string;
  caption: string;
  filename: string;
  device: string | null;
  captured_at: string | null;
  file_modified: string | null;
  width: number;
  height: number;
  bytes: number;
  created_by: string;
  uploaded_at: string;
  trashed_at: string | null;
  trashed_by: string | null;
  purge_after: string | null;
  purging_at: string | null;
  lifecycle_version: number;
};

export type PhotoPage = { items: SharedPhoto[]; next_after: string | null };

export function koreanTimestamp(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Seoul",
  }).format(new Date(value));
}
