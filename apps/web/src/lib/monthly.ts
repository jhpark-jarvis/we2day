export type MemoryDay = {
  date: string;
  met: boolean;
  photo_count: number;
  route_recorded: boolean;
};
export type MemoryPhoto = { id: string; date: string; caption: string };
export type MonthlyMemories = {
  month: string;
  meeting_count: number;
  photo_count: number;
  route_count: number;
  days: MemoryDay[];
  photos: MemoryPhoto[];
};
