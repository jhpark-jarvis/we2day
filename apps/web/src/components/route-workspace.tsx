"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState, useTransition } from "react";
import { saveRoute } from "@/app/actions/routes";
import type { MeetingRoute, RouteContent } from "@/lib/routes";

const RouteMap = dynamic(() => import("./route-map").then((module) => module.RouteMap), {
  ssr: false,
});
type Fields = Record<keyof RouteContent, string>;
const empty: Fields = {
  start_name: "",
  start_lat: "",
  start_lng: "",
  end_name: "",
  end_lat: "",
  end_lng: "",
};
export function RouteWorkspace({
  date,
  today,
  apiKey,
}: {
  date: string;
  today: string;
  apiKey: string;
}) {
  const [opened, setOpened] = useState(false);
  return (
    <section className="route-workspace">
      <h2>함께한 동선</h2>
      <p className="settings-hint">이 날 직접 지정한 출발점과 도착점을 기록해요.</p>
      {date > today ? (
        <p className="settings-hint">오늘과 지난 날짜에 남길 수 있어요.</p>
      ) : (
        <>
          <button
            type="button"
            className="text-button"
            aria-expanded={opened}
            onClick={() => setOpened(!opened)}
          >
            {opened ? "동선 접기" : "동선 기록 열기"}
          </button>
          {opened && <RouteEditor key={date} date={date} apiKey={apiKey} />}
        </>
      )}
    </section>
  );
}
function RouteEditor({ date, apiKey }: { date: string; apiKey: string }) {
  const [fields, setFields] = useState<Fields>(empty);
  const [record, setRecord] = useState<MeetingRoute | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [mapOpened, setMapOpened] = useState(false);
  const [revision, setRevision] = useState(0);
  const [pending, startTransition] = useTransition();
  const request = useRef("");
  useEffect(() => {
    void revision;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetch(`/api/routes?date=${date}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (controller.signal.aborted) return;
        const row: MeetingRoute | null = data[0] || null;
        setRecord(row);
        setFields(
          row
            ? (Object.fromEntries(
                Object.keys(empty).map((key) => [key, String(row[key as keyof RouteContent])]),
              ) as Fields)
            : empty,
        );
        request.current = crypto.randomUUID();
        setConflict(false);
        setNotice("");
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message || "동선을 불러오지 못했어요.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [date, revision]);
  const change = (values: Partial<Fields>) => {
    setFields((current) => ({ ...current, ...values }));
    request.current = crypto.randomUUID();
    setNotice("");
  };
  const points = Object.fromEntries(
    Object.entries(fields)
      .filter(([key, value]) => !key.endsWith("name") && value.trim() !== "")
      .map(([key, value]) => [key, Number(value)]),
  );
  if (loading)
    return (
      <p role="status" className="settings-hint">
        동선을 불러오는 중…
      </p>
    );
  return (
    <form
      className="route-form"
      onSubmit={(event) => {
        event.preventDefault();
        setError("");
        setNotice("");
        if (Object.values(fields).some((value) => !value.trim())) {
          setError("두 장소의 이름과 좌표를 모두 지정해 주세요.");
          return;
        }
        const content = {
          ...fields,
          start_lat: Number(fields.start_lat),
          start_lng: Number(fields.start_lng),
          end_lat: Number(fields.end_lat),
          end_lng: Number(fields.end_lng),
        };
        startTransition(async () => {
          const result = await saveRoute(
            date,
            content,
            record?.version || 0,
            request.current || crypto.randomUUID(),
          );
          if (result.error) {
            setConflict(result.status === 409);
            setError(
              result.status === 409
                ? "동선이 바뀌었어요. 작성 내용을 확인하고 최신 동선을 다시 불러와 주세요."
                : result.error,
            );
          } else if (result.data) {
            setRecord(result.data);
            request.current = crypto.randomUUID();
            setConflict(false);
            setNotice("동선을 저장했어요. 두 사람이 함께 볼 수 있어요.");
          }
        });
      }}
    >
      <fieldset
        className="meeting-fields"
        disabled={pending || Boolean(error && !record && !request.current)}
      >
        {apiKey ? (
          <>
            <button
              type="button"
              className="text-button"
              onClick={() => setMapOpened(!mapOpened)}
              aria-expanded={mapOpened}
            >
              {mapOpened ? "지도 닫기" : "지도에서 두 점 지정하기"}
            </button>
            {mapOpened && (
              <RouteMap
                apiKey={apiKey}
                points={points}
                onPoint={(role, lat, lng) =>
                  change({ [`${role}_lat`]: lat.toFixed(7), [`${role}_lng`]: lng.toFixed(7) })
                }
              />
            )}
          </>
        ) : (
          <p className="settings-hint">
            지도 설정 후 지도에서 두 점을 찍을 수 있어요. 지금은 직접 알고 있는 좌표를 입력할 수
            있어요.
          </p>
        )}
        {(["start", "end"] as const).map((side) => (
          <fieldset key={side} className="route-point">
            <legend>{side === "start" ? "출발점" : "도착점"}</legend>
            <div className="auth-field">
              <label htmlFor={`${side}-name`}>
                직접 정한 {side === "start" ? "출발" : "도착"} 장소 이름
              </label>
              <input
                id={`${side}-name`}
                value={fields[`${side}_name`]}
                maxLength={100}
                required
                onChange={(event) => change({ [`${side}_name`]: event.target.value })}
              />
            </div>
            <div className="coordinate-fields">
              {(["lat", "lng"] as const).map((axis) => (
                <div className="auth-field" key={axis}>
                  <label htmlFor={`${side}-${axis}`}>
                    {side === "start" ? "출발" : "도착"} {axis === "lat" ? "위도" : "경도"}
                  </label>
                  <input
                    id={`${side}-${axis}`}
                    type="number"
                    min={axis === "lat" ? -90 : -180}
                    max={axis === "lat" ? 90 : 180}
                    step="any"
                    value={fields[`${side}_${axis}`]}
                    required
                    onChange={(event) => change({ [`${side}_${axis}`]: event.target.value })}
                  />
                </div>
              ))}
            </div>
          </fieldset>
        ))}
        <p className="settings-hint">
          저장한 두 점은 둘의 공간에 남아요. 플랜·지도 열람만으로 실제 방문 기록이 생기지는 않아요.
        </p>
        <button type="submit" className="primary-button" disabled={conflict}>
          {pending ? "저장 중…" : "동선 저장"}
        </button>
      </fieldset>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="settings-hint">
          {notice}
        </p>
      )}
      {(error || conflict) && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() => setRevision((value) => value + 1)}
        >
          작성 내용을 버리고 최신 동선 불러오기
        </button>
      )}
    </form>
  );
}
