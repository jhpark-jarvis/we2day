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

export type WishView = "planned" | "done" | "archived";
export type WishOverview = {
  items: Wish[];
  counts: Record<WishView, number>;
  has_more: boolean;
};
