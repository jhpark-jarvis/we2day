export type RouletteWheel = {
  id: string;
  title: string;
  candidates: string[];
  archived: boolean;
  version: number;
  updated_by: string;
  updated_at: string;
};
export type RouletteDraw = {
  id: string;
  wheel_id: string;
  wheel_version: number;
  candidates: string[];
  selected_index: number;
  drawn_by: string;
  drawn_at: string;
};
