"use client";
import { useEffect, useRef, useState } from "react";
import { loadNaverMap, type MapInstance } from "@/lib/naver-map";
import type { RouteContent } from "@/lib/routes";
export function RouteMap({
  apiKey,
  points,
  onPoint,
}: {
  apiKey: string;
  points: Partial<RouteContent>;
  onPoint?: (role: "start" | "end", lat: number, lng: number) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const element = useRef<HTMLElement>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [role, setRole] = useState<"start" | "end">("start");
  const latest = useRef({ role, onPoint });
  latest.current = { role, onPoint };
  const map = useRef<MapInstance | null>(null);
  const initial = useRef(points);
  const editable = !!onPoint;
  useEffect(() => {
    let disposed = false;
    setReady(false);
    setError("");
    let clean = () => {};
    const authFailure = () =>
      setError("지도 인증을 확인하지 못했어요. 지도 키와 허용 주소를 확인해 주세요.");
    window.addEventListener("we2day-map-error", authFailure);
    loadNaverMap(apiKey)
      .then((maps) => {
        if (disposed || !element.current) return;
        const instance = new maps.Map(element.current, {
          center: new maps.LatLng(
            initial.current.start_lat ?? 37.5665,
            initial.current.start_lng ?? 126.978,
          ),
          zoom: 12,
        });
        map.current = instance;
        let width = 0,
          height = 0;
        const resize = () => {
          if (!frame.current) return;
          const nextWidth = frame.current.clientWidth,
            nextHeight = frame.current.clientHeight;
          if (!nextWidth || !nextHeight || (width === nextWidth && height === nextHeight)) return;
          width = nextWidth;
          height = nextHeight;
          instance.setSize({ width, height });
        };
        const observer = new ResizeObserver(resize);
        if (frame.current) observer.observe(frame.current);
        resize();
        const listener = editable
          ? maps.Event.addListener(instance, "click", (event) =>
              latest.current.onPoint?.(latest.current.role, event.coord.lat(), event.coord.lng()),
            )
          : null;
        clean = () => {
          observer.disconnect();
          if (listener) maps.Event.removeListener(listener);
          instance.destroy();
          map.current = null;
        };
        setReady(true);
      })
      .catch((failure) => {
        if (!disposed) setError(failure.message);
      });
    return () => {
      disposed = true;
      clean();
      window.removeEventListener("we2day-map-error", authFailure);
    };
  }, [apiKey, editable]);
  useEffect(() => {
    if (!ready || !map.current || !window.naver?.maps) return;
    const maps = window.naver.maps,
      instance = map.current;
    const overlays: { setMap(map: null): void }[] = [];
    const coordinates: { lat(): number; lng(): number }[] = [];
    for (const side of ["start", "end"] as const) {
      const lat = points[`${side}_lat`],
        lng = points[`${side}_lng`];
      if (lat === undefined || lng === undefined || !Number.isFinite(lat) || !Number.isFinite(lng))
        continue;
      const position = new maps.LatLng(lat, lng);
      coordinates.push(position);
      overlays.push(
        new maps.Marker({ map: instance, position, title: side === "start" ? "출발" : "도착" }),
      );
    }
    if (coordinates.length === 2) {
      overlays.push(
        new maps.Polyline({
          map: instance,
          path: coordinates,
          strokeColor: "#95765b",
          strokeWeight: 3,
        }),
      );
      const [a, b] = coordinates;
      if (a.lat() !== b.lat() || a.lng() !== b.lng())
        instance.fitBounds(
          new maps.LatLngBounds(
            new maps.LatLng(Math.min(a.lat(), b.lat()), Math.min(a.lng(), b.lng())),
            new maps.LatLng(Math.max(a.lat(), b.lat()), Math.max(a.lng(), b.lng())),
          ),
        );
    }
    return () => {
      for (const overlay of overlays) overlay.setMap(null);
    };
  }, [ready, points]);
  return (
    <div className="route-map-panel">
      {onPoint && (
        <fieldset className="map-role">
          <legend>지도에서 지정할 점</legend>
          {(["start", "end"] as const).map((value) => (
            <label key={value}>
              <input
                type="radio"
                name="map-role"
                checked={role === value}
                onChange={() => setRole(value)}
              />
              {value === "start" ? "출발점" : "도착점"}
            </label>
          ))}
        </fieldset>
      )}
      <p className="settings-hint">
        {onPoint
          ? "점을 선택한 뒤 지도를 눌러 주세요. 저장 전까지 화면에만 표시돼요."
          : "저장된 두 점을 읽기 전용으로 표시해요. 선은 실제 이동 경로가 아니에요."}
      </p>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      <div className="route-map-frame" ref={frame}>
        <section
          ref={element}
          className="route-map-canvas"
          aria-label={
            onPoint
              ? "출발점과 도착점을 지정하는 네이버 지도"
              : "저장한 두 점을 표시하는 네이버 지도"
          }
        />
      </div>
      <p className="settings-hint">
        두 점 사이의 직선입니다. 실제 이동 경로나 거리를 뜻하지 않아요.
      </p>
    </div>
  );
}
