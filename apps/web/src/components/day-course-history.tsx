"use client";

import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LoadingRegion } from "@/components/loading-region";
import { NaverAppHandoff } from "@/components/naver-app-handoff";
import Link from "@/components/progress-link";
import type { DatePlan } from "@/lib/plans";

export function DayCourseHistory({ initialDate, site }: { initialDate: string; site: string }) {
  const [date, setDate] = useState(initialDate);
  const [query, setQuery] = useState({ date: initialDate, offset: 0, revision: 0 });
  const [result, setResult] = useState<{ date: string; plans: DatePlan[]; more: boolean } | null>(
    null,
  );
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError("");
    fetch(`/api/plans?date=${query.date}&offset=${query.offset}`, {
      cache: "no-store",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
    })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error("course_read_failed");
        if (controller.signal.aborted) return;
        const plans = body as DatePlan[];
        setResult((previous) => ({
          date: query.date,
          plans:
            query.offset && previous?.date === query.date ? [...previous.plans, ...plans] : plans,
          more: plans.length === 50,
        }));
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("동선을 불러오지 못했어요. 이전 결과를 유지했으니 다시 조회해 주세요.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [query]);
  return (
    <section aria-label="날짜별 하루 동선">
      <form
        className="date-filter"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery((previous) => ({ date, offset: 0, revision: previous.revision + 1 }));
          const url = new URL(window.location.href);
          url.searchParams.set("date", date);
          window.history.replaceState(null, "", url);
        }}
      >
        <div className="auth-field">
          <label htmlFor="day-course-date">동선 날짜</label>
          <input
            id="day-course-date"
            type="date"
            min="2000-01-01"
            max="2100-12-31"
            required
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </div>
        <button type="submit" className="icon-button" aria-label="동선 조회" title="동선 조회">
          <Search size={19} aria-hidden="true" />
        </button>
      </form>
      <p className="settings-hint">
        확정한 코스의 모든 장소를 등록 순서대로 보여요. 실제 방문 여부는 코스에서 확인할 수 있어요.
      </p>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      <LoadingRegion busy={pending} label="하루 동선을 불러오는 중">
        <div className="day-course-results">
          {result && <h2>{result.date} 동선</h2>}
          {result?.plans.map((plan) => {
            const content = plan.published_content;
            if (!content) return null;
            return (
              <article key={plan.id} className="plan-review">
                <div className="section-heading">
                  <h3>{content.title}</h3>
                  <Link className="text-button" href={`/today?date=${result.date}`}>
                    코스 상세
                  </Link>
                </div>
                <ol className="day-course-stops" aria-label={`${content.title} 장소 순서`}>
                  {content.activities.map((activity, index) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: Position is stable within an immutable published revision.
                    <li key={`${plan.id}:${plan.published_revision}:${index}`}>
                      <strong>
                        {index + 1}. {activity.title}
                      </strong>
                      {activity.time && <time>{activity.time}</time>}
                      <p>{activity.place || "장소 미정"}</p>
                      {(activity.place || activity.map_url) && (
                        <NaverAppHandoff
                          place={activity.place}
                          mapUrl={activity.map_url}
                          site={site}
                          compact
                        />
                      )}
                    </li>
                  ))}
                </ol>
                {!content.activities.length && <p>등록한 활동이 없어요.</p>}
              </article>
            );
          })}
          {result && !result.plans.length && (
            <p className="empty-state">이 날짜에 확정한 코스가 없어요.</p>
          )}
          {result?.more && (
            <button
              type="button"
              className="text-button"
              onClick={() =>
                setQuery({
                  date: result.date,
                  offset: result.plans.length,
                  revision: query.revision + 1,
                })
              }
            >
              코스 더 보기
            </button>
          )}
        </div>
      </LoadingRegion>
    </section>
  );
}
