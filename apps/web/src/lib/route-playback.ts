import type { RouteContent } from "./routes";

export type PlaybackRoute = RouteContent & { date: string };

/** Shared fixed frame for an approximate coordinate diagram, not a road map. */
export function projectRoutes(items: readonly PlaybackRoute[]) {
  const ordered = [...items].sort((a, b) => a.date.localeCompare(b.date));
  if (!ordered.length) return [];
  const longitudes = ordered.flatMap((item) => [item.start_lng, item.end_lng]);
  const anchor = longitudes[0];
  const longitude = (value: number) => ((value - anchor + 540) % 360) - 180;
  const latitudes = ordered.flatMap((item) => [item.start_lat, item.end_lat]);
  const cosine = Math.max(
    0.01,
    Math.cos(((Math.min(...latitudes) + Math.max(...latitudes)) * Math.PI) / 360),
  );
  const xs = longitudes.map((value) => longitude(value) * cosine);
  const left = Math.min(...xs),
    right = Math.max(...xs);
  const bottom = Math.min(...latitudes),
    top = Math.max(...latitudes);
  const scale = Math.min(
    304 / Math.max(right - left, 0.00001),
    160 / Math.max(top - bottom, 0.00001),
  );
  const point = (lat: number, lng: number): [number, number] => [
    180 + (longitude(lng) * cosine - (left + right) / 2) * scale,
    108 - (lat - (bottom + top) / 2) * scale,
  ];
  return ordered.map((item) => ({
    ...item,
    start: point(item.start_lat, item.start_lng),
    end: point(item.end_lat, item.end_lng),
  }));
}
