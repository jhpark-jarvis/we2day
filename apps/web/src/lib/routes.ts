export type RouteContent = {
  start_name: string;
  start_lat: number;
  start_lng: number;
  end_name: string;
  end_lat: number;
  end_lng: number;
};
export type MeetingRoute = RouteContent & {
  date: string;
  version: number;
  updated_by: string;
  updated_at: string;
};
