"use client";

import { useState } from "react";
import { LoadingRegion } from "@/components/loading-region";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import {
  type RecordKind,
  type RecordPage,
  recordHref,
  recordKinds,
  recordStates,
  recordVisibility,
} from "@/lib/records";

export function RecordSearch({ today }: { today: string }) {
  const [kind, setKind] = useState<RecordKind>("appointment");
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`),
    [end, setEnd] = useState(today);
  const [query, setQuery] = useState(""),
    [archived, setArchived] = useState(false);
  const [result, setResult] = useState<
    (RecordPage & { kind: RecordKind; signature: string }) | null
  >(null);
  const [error, setError] = useState(""),
    [pending, setPending] = useState(false);
  const signature = JSON.stringify({
    kind,
    start_date: start,
    end_date: end,
    query,
    include_archived: archived,
  });
  async function search(offset = 0) {
    if (pending) return;
    setPending(true);
    try {
      const response = await fetch("/api/records/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...JSON.parse(signature), offset }),
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "검색하지 못했어요.");
      setError("");
      setResult({
        items:
          offset && result?.signature === signature ? [...result.items, ...data.items] : data.items,
        next_offset: data.next_offset,
        kind,
        signature,
      });
    } catch (cause) {
      setError(
        cause instanceof Error && cause.name !== "TimeoutError" && cause.name !== "TypeError"
          ? cause.message
          : "연결하지 못했어요. 조건과 이전 결과를 유지했으니 다시 검색해 주세요.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <LoadingRegion busy={pending} label="기록을 찾는 중">
      <section className="today-workspace">
        <Link className="text-button" href="/memories">
          ← 기록으로
        </Link>
        <PageHeading>
          <p className="eyebrow">FIND OUR RECORDS</p>
          <h1>약속·플랜·회고·위시 찾기</h1>
          <p className="muted">
            같은 공간의 기록을 최대 366일씩 찾아요. 회고는 나의 원문과 상대가 직접 공유한 내용만
            보여요.
          </p>
        </PageHeading>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void search();
          }}
        >
          <fieldset className="record-search-fields" disabled={pending}>
            <label>
              기록 종류
              <select value={kind} onChange={(event) => setKind(event.target.value as RecordKind)}>
                {Object.entries(recordKinds).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              검색 시작일
              <input
                type="date"
                required
                min="2000-01-01"
                max="2100-12-31"
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label>
              검색 종료일
              <input
                type="date"
                required
                min="2000-01-01"
                max="2100-12-31"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
            <label>
              기록 검색어
              <input
                maxLength={100}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            {(kind === "plan" || kind === "wish") && (
              <label>
                <input
                  type="checkbox"
                  checked={archived}
                  onChange={(event) => setArchived(event.target.checked)}
                />
                보관한 기록 포함
              </label>
            )}
            <button className="primary-button" type="submit" aria-busy={pending}>
              {"기록 검색"}
            </button>
          </fieldset>
        </form>
        <p className="settings-hint">
          날짜 기준: 약속 날짜 · 플랜의 현재 초안 날짜 · 회고에 보존된 확정 날짜 · 위시를 만든 한국
          날짜. 플랜의 미확정 변경은 달력에 반영되기 전 내용이에요.
        </p>
        {error && <p role="alert">{error}</p>}
        {result && (
          <section aria-label="기록 검색 결과" aria-busy={pending}>
            <h2>{recordKinds[result.kind]} 검색 결과</h2>
            <p className="settings-hint">
              마지막 검색 시점의 결과예요. 공유 철회·수정은 다시 검색하면 반영돼요. 원본을 열 때
              접근 권한을 다시 확인해요.
            </p>
            {result.signature !== signature && (
              <p role="status">검색 조건이 바뀌었어요. 기록 검색을 눌러 갱신해 주세요.</p>
            )}
            {!result.items.length && <p>조건에 맞는 기록이 없어요.</p>}
            {result.items.map((item) => (
              <article className="plan-review" key={`${item.id}:${item.visibility || ""}`}>
                <p className="eyebrow">
                  {item.date} · {recordStates[item.state] || item.state}
                </p>
                <h3>{item.title}</h3>
                {item.visibility && <p>{recordVisibility[item.visibility]}</p>}
                <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.excerpt}</p>
                <Link className="text-button" href={recordHref(result.kind, item)}>
                  원본 열기 · {item.title}
                </Link>
              </article>
            ))}
            {result.next_offset !== null && (
              <button
                className="text-button"
                disabled={pending || result.signature !== signature}
                type="button"
                onClick={() => void search(result.next_offset || 0)}
              >
                기록 더 보기
              </button>
            )}
          </section>
        )}
      </section>
    </LoadingRegion>
  );
}
