export type PhotoSearchQuery = {
  start_date: string;
  end_date: string;
  query: string;
  field: "caption" | "filename" | "device";
  uploader: "all" | "mine" | "partner";
};
export type PhotoSearchHit = {
  id: string;
  date: string;
  caption: string;
  filename: string;
  device: string | null;
  captured_at: string | null;
  uploaded_at: string;
  uploaded_by_me: boolean;
};
export type PhotoSearchPage = { items: PhotoSearchHit[]; next_offset: number | null };
