"use client";
import { Pencil, Route } from "lucide-react";
import { useEffect, useState } from "react";
import { LoadingRegion } from "@/components/loading-region";
import Link from "@/components/progress-link";
import { VisitProgressPanel } from "@/components/visit-progress";
import type { DatePlan } from "@/lib/plans";
import type { TimezoneView } from "@/lib/timezones";

export function AppointmentCourse({
  id,
  date,
  today,
  site,
  zones,
}: {
  id: string;
  date: string;
  today: string;
  site: string;
  zones: TimezoneView | null;
}) {
  const [read, setRead] = useState<{ id: string; plan: DatePlan | null } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    void revision;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetch(`/api/appointments/${encodeURIComponent(id)}/course`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "코스를 불러오지 못했어요.");
        if (!controller.signal.aborted) setRead({ id, plan: result });
      })
      .catch((failure) => {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : "코스를 불러오지 못했어요.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [id, revision]);
  const plan = read?.id === id && read.plan?.appointment_id === id ? read.plan : null;
  return (
    <LoadingRegion busy={loading} label="코스를 불러오는 중">
      <div className="appointment-course-container">
        {error && (
          <div className="note-panel">
            <p role="alert" className="error-message">
              {error}
            </p>
            <button
              className="text-button"
              type="button"
              onClick={() => setRevision((value) => value + 1)}
            >
              다시 불러오기
            </button>
          </div>
        )}
        {plan ? (
          <>
            {plan.published_content?.date !== date && (
              <p className="settings-hint">
                확정 코스의 날짜가 약속 날짜와 달라요. 코스 수정에서 확인해 주세요.
              </p>
            )}
            <VisitProgressPanel
              key={`${plan.id}:${plan.published_revision}:${revision}`}
              plan={plan}
              today={today}
              expanded
              site={site}
              zones={zones}
              onRefreshPlan={() => setRevision((value) => value + 1)}
              extraActions={
                <Link
                  className="icon-button"
                  href={`/plans?item=${plan.id}`}
                  aria-label="코스 수정"
                  title="코스 수정"
                >
                  <Pencil size={19} aria-hidden="true" />
                </Link>
              }
            />
            {JSON.stringify(plan.content) !== JSON.stringify(plan.published_content) && (
              <p className="settings-hint">
                아직 확정하지 않은 변경사항이 있어요. 마지막 확정 코스를 보여줘요.
              </p>
            )}
          </>
        ) : loading ? (
          <div className="course-loading-placeholder" aria-hidden="true" />
        ) : (
          !error && (
            <section className="empty-course" aria-label="코스">
              <h2>
                <Route size={18} aria-hidden="true" /> 코스
              </h2>
              <p className="muted">아직 연결된 확정 코스가 없어요.</p>
            </section>
          )
        )}
      </div>
    </LoadingRegion>
  );
}
