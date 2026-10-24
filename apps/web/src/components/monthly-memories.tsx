"use client";
import { Search } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import { LoadingRegion } from "@/components/loading-region";
import Link from "@/components/progress-link";
import type { MonthlyMemories as MonthData } from "@/lib/monthly";

export function MonthlyMemories({ initialMonth }: { initialMonth: string }) {
  const [month, setMonth] = useState(initialMonth);
  const [data, setData] = useState<MonthData | null>(null);
  const [loaded, setLoaded] = useState("");
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  const load = useCallback(async (value: string) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    try {
      const response = await fetch(`/api/records/search?month=${value}`, {
        cache: "no-store",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "월간 추억을 불러오지 못했어요.");
      if (controller.signal.aborted) return;
      setData(body);
      setLoaded(value);
      setError("");
    } catch {
      if (!controller.signal.aborted)
        setError(
          "월간 추억을 불러오지 못했어요. 선택한 월과 이전 결과는 유지돼요. 다시 조회해 주세요.",
        );
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }, []);
  useEffect(() => {
    void load(initialMonth);
    return () => active.current?.abort();
  }, [initialMonth, load]);
  return (
    <section aria-label="월간 추억">
      <form
        className="calendar-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          void load(month);
        }}
      >
        <div className="auth-field">
          <label htmlFor="memory-month">돌아볼 월</label>
          <input
            id="memory-month"
            type="month"
            min="2000-01"
            max="2100-12"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
            required
          />
        </div>
        <button
          type="submit"
          className="icon-button"
          aria-label="이 달 보기"
          title="월간 추억 검색"
          disabled={pending}
        >
          <Search size={20} aria-hidden="true" />
        </button>
      </form>
      <p className="settings-hint">
        {loaded || initialMonth}의 기록
        {loaded && loaded !== month ? " · 조건을 바꿨어요. 검색하면 반영돼요." : ""}
      </p>
      <LoadingRegion busy={pending} label="월간 추억을 불러오는 중" className="loading-results">
        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {data && (
          <>
            <dl className="memory-counts" aria-label="선택한 달의 기록 합계">
              <div>
                <dt>만난 날</dt>
                <dd>{data.meeting_count}일</dd>
              </div>
              <div>
                <dt>남긴 사진</dt>
                <dd>{data.photo_count}장</dd>
              </div>
            </dl>
            <details className="compact-help">
              <summary>집계 기준</summary>
              <p className="settings-hint">
                만난 날은 직접 체크한 날짜만 세어요. 사진·약속만으로 만남이나 실제 방문을 추정하지
                않아요. 휴지통·저장 미완료 사진은 제외해요.
              </p>
            </details>
            {data.photo_count > 6 && (
              <p className="settings-hint">
                날짜별 카드에 최근 사진 6장을 나눠 보여요. 해당 날짜의 앨범에서 나머지도 볼 수
                있어요.
              </p>
            )}
            <ul className="memory-day-list">
              {data.days
                .filter((day) => day.met || day.photo_count > 0)
                .map((day) => (
                  <li key={day.date}>
                    <strong>{day.date}</strong>
                    <div className="monthly-day-photos">
                      {(data?.photos || [])
                        .filter((photo) => photo.date === day.date)
                        .map((photo) => (
                          <Link
                            className="monthly-photo"
                            aria-label={`${day.date}의 사진 보기`}
                            key={photo.id}
                            href={`/memories?date=${day.date}`}
                          >
                            <Image
                              src={`/api/photos/${photo.id}/image`}
                              alt={photo.caption || `${photo.date}에 남긴 사진`}
                              width={600}
                              height={450}
                              unoptimized
                            />
                          </Link>
                        ))}
                    </div>
                    <p>
                      {day.met ? "만난 날" : "만남 표시 없음"} · 사진 {day.photo_count}장
                    </p>
                    <div className="calendar-toolbar">
                      <Link className="text-button" href={`/?date=${day.date}`}>
                        일정 보기
                      </Link>
                      <Link className="text-button" href={`/memories?date=${day.date}`}>
                        이 날짜의 사진
                      </Link>
                    </div>
                  </li>
                ))}
            </ul>
            {!data.days.some((day) => day.met || day.photo_count > 0) && (
              <p className="empty-state">이 달에는 아직 남긴 기록이 없어요.</p>
            )}
          </>
        )}
      </LoadingRegion>
    </section>
  );
}
