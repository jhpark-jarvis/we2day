"use client";

import { useState } from "react";
import { LoadingRegion } from "@/components/loading-region";
import Link from "@/components/progress-link";
import { RouteMap } from "@/components/route-map";
import { RoutePlayback } from "@/components/route-playback";
import { downloadRecord } from "@/lib/file-download";
import type { RouteContent } from "@/lib/routes";

type Hit = RouteContent & { date: string; version: number; updated_at: string };
type Page = { items: Hit[]; next_offset: number | null; signature: string };
export function RouteHistory({
  today,
  apiKey,
  active = true,
}: {
  today: string;
  apiKey: string;
  active?: boolean;
}) {
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`),
    [end, setEnd] = useState(today);
  const [result, setResult] = useState<Page | null>(null),
    [selected, setSelected] = useState<Hit | null>(null);
  const [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const signature = JSON.stringify({ start_date: start, end_date: end });
  async function load(offset = 0) {
    setPending(true);
    try {
      const response = await fetch("/api/routes/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...JSON.parse(signature), offset }),
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "동선을 읽지 못했어요.");
      setError("");
      setNotice("");
      setResult({
        items:
          offset && result?.signature === signature
            ? [...result.items, ...data.items].filter(
                (item, index, array) => array.findIndex((v) => v.date === item.date) === index,
              )
            : data.items,
        next_offset: data.next_offset,
        signature,
      });
      setSelected(null);
    } catch {
      setError("동선을 읽지 못했어요. 기간과 이전 결과를 유지했으니 다시 조회해 주세요.");
    } finally {
      setPending(false);
    }
  }
  async function download() {
    setPending(true);
    try {
      await downloadRecord(
        "/api/routes/export",
        JSON.parse(signature),
        `we2day-routes-${start}-${end}.geojson`,
        "application/geo+json",
      );
      setError("");
      setNotice("선택한 기간의 직선 기록 다운로드를 요청했어요.");
    } catch (cause) {
      setError(
        cause instanceof Error && cause.name === "Error"
          ? cause.message
          : "파일을 만들지 못했어요. 기간을 확인하고 다시 시도해 주세요.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <LoadingRegion busy={pending} label="동선을 불러오는 중">
      <section className="today-workspace">
        <p className="settings-hint">
          직접 남긴 출발점·도착점을 찾아요. 날짜 사이를 연결하거나 실제 주행 경로를 추정하지 않아요.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void load();
          }}
        >
          <fieldset className="record-search-fields" disabled={pending}>
            <label>
              동선 시작일
              <input
                type="date"
                required
                min="2000-01-01"
                max="2100-12-31"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              동선 종료일
              <input
                type="date"
                required
                min="2000-01-01"
                max="2100-12-31"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            <button className="primary-button" type="submit" aria-busy={pending}>
              {"동선 조회"}
            </button>
          </fieldset>
        </form>
        <details className="compact-help">
          <summary>내보내기 안내</summary>
          <p className="settings-hint">
            최대 366일씩 조회해요. GeoJSON 파일에는 선택 기간 전체의 날짜·장소명·정밀 좌표·수정
            시각이 포함돼요. 실제 주행이나 방문 완료의 증거는 아니에요.
          </p>
        </details>

        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {result && (
          <section aria-label="기간별 동선 결과">
            <div className="section-heading">
              <h2>저장한 두 점 기록</h2>{" "}
              <button
                type="button"
                className="text-button"
                disabled={pending || !result || result.signature !== signature}
                onClick={() => void download()}
              >
                이 기간 직선 기록 내보내기
              </button>
            </div>
            {result.signature !== signature && (
              <p role="status">기간이 바뀌었어요. 동선 조회를 눌러 주세요.</p>
            )}
            {!result.items.length && <p>이 기간에 직접 남긴 동선이 없어요.</p>}
            <RoutePlayback
              key={`${result.signature}:${result.items.length}:${active}:${pending}:${signature}`}
              items={result.items}
              active={active && !pending && result.signature === signature}
              hasMore={result.next_offset !== null}
            />
            {result.items.map((item) => (
              <article className="plan-review" key={item.date}>
                <h3>{item.date}</h3>
                <p>
                  {item.start_name} → {item.end_name}
                </p>
                <p className="settings-hint">직접 기록한 두 점</p>
                <Link className="text-button" href={`/?date=${item.date}`}>
                  이 날짜의 기록 열기
                </Link>
                {apiKey && (
                  <button
                    className="text-button"
                    type="button"
                    disabled={pending}
                    onClick={() => setSelected(selected?.date === item.date ? null : item)}
                  >
                    {selected?.date === item.date
                      ? "동선 지도 접기"
                      : `${item.date} 직선 지도 보기`}
                  </button>
                )}
              </article>
            ))}
            {selected && (
              <RouteMap
                key={`${selected.date}:${selected.version}`}
                apiKey={apiKey}
                points={selected}
              />
            )}
            {result.next_offset !== null && (
              <button
                className="text-button"
                type="button"
                disabled={pending || result.signature !== signature}
                onClick={() => void load(result.next_offset || 0)}
              >
                동선 더 보기
              </button>
            )}
          </section>
        )}
      </section>
    </LoadingRegion>
  );
}
