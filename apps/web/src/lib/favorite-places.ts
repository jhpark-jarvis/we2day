export type FavoritePlace = {
  id: string;
  label: string;
  destination: string;
  archived: boolean;
  version: number;
  updated_by: string;
  updated_at: string;
};
export type FavoritePage = { items: FavoritePlace[]; next_offset: number | null };
export type FavoriteContent = Pick<FavoritePlace, "label" | "destination" | "archived">;
