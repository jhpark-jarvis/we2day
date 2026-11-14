export type WishContent = {
  title: string;
  kind: "place" | "activity";
  note: string;
  place?: string;
  map_url?: string;
  done: boolean;
  archived: boolean;
};
export type Wish = WishContent & {
  id: string;
  version: number;
  updated_by: string;
  updated_at: string;
};
