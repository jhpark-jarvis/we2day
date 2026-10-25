"use client";
import dynamic from "next/dynamic";
import { useState } from "react";

function PanelLoading() {
  return (
    <div className="explorer-loading" role="status">
      <span className="loading-spinner" aria-hidden="true" />
      <span className="sr-only">검색 화면 준비 중</span>
    </div>
  );
}
const DayCourseHistory = dynamic(
  () => import("@/components/day-course-history").then((m) => m.DayCourseHistory),
  { loading: PanelLoading },
);
const MonthlyMemories = dynamic(
  () => import("@/components/monthly-memories").then((m) => m.MonthlyMemories),
  { loading: PanelLoading },
);
const PhotoSearch = dynamic(() => import("@/components/photo-search").then((m) => m.PhotoSearch), {
  loading: PanelLoading,
});
const RecordSearch = dynamic(
  () => import("@/components/record-search").then((m) => m.RecordSearch),
  { loading: PanelLoading },
);

const kinds = { photos: "사진", records: "기록", routes: "동선", monthly: "월간 추억" } as const;
type Kind = keyof typeof kinds;
export function RecordExplorer({
  today,
  initialType,
  initialMonth,
  initialDate,
  site,
  names,
}: {
  today: string;
  initialType: Kind;
  initialMonth: string;
  initialDate: string;
  site: string;
  names: { mine: string; partner: string };
}) {
  const [kind, setKind] = useState(initialType);
  const [visited, setVisited] = useState<Kind[]>([initialType]);
  return (
    <div className="record-explorer">
      <div className="auth-field explorer-condition">
        <label htmlFor="record-target">검색 대상</label>
        <select
          id="record-target"
          value={kind}
          onChange={(event) => {
            const next = event.target.value as Kind;
            if (!(next in kinds)) return;
            setKind(next);
            setVisited((previous) => (previous.includes(next) ? previous : [...previous, next]));
            const url = new URL(window.location.href);
            url.search = "";
            url.searchParams.set("type", next);
            if (next === "monthly") url.searchParams.set("month", initialMonth);
            window.history.replaceState(null, "", url);
          }}
        >
          {Object.entries(kinds).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {visited.map((type) => (
        <div className="explorer-panel" key={type} hidden={kind !== type}>
          {type === "photos" ? (
            <PhotoSearch start={`${today.slice(0, 8)}01`} end={today} names={names} />
          ) : type === "records" ? (
            <RecordSearch today={today} />
          ) : type === "routes" ? (
            <DayCourseHistory initialDate={initialDate} site={site} />
          ) : (
            <MonthlyMemories initialMonth={initialMonth} />
          )}
        </div>
      ))}
    </div>
  );
}
