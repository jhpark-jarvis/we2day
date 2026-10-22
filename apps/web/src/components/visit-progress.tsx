"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { LoadingRegion } from "@/components/loading-region";
import { RefreshButton } from "@/components/workspace-controls";
import type { DatePlan } from "@/lib/plans";
import { zonedTimestamp } from "@/lib/timezones";
import { changeVisit, readVisits } from "@/lib/visit-requests";
import { type VisitChange, type VisitProgress, type VisitState, visitLabels } from "@/lib/visits";

export function VisitProgressPanel({ plan, today }: { plan: DatePlan; today: string }) {
  const router = useRouter();
  const [records, setRecords] = useState<VisitProgress[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState<VisitChange | null>(null);
  const [more, setMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [changing, run] = useTransition();
  const [refreshing, refreshPlan] = useTransition();
  const pending = changing || refreshing;
  const content = plan.published_content;
  const current = records.find((r) => r.publication === plan.published_revision);
  const states = current?.states || content?.activities.map(() => "planned" as const) || [];
  const writable = loaded && !!content && content.date <= today && !plan.archived;
  useEffect(() => {
    let active = true;
    readVisits(plan.id)
      .then((response) => {
        if (!active) return;
        if (response.data) {
          setRecords(response.data);
          setLoaded(true);
          setMore(response.data.length === 20);
        } else setError(response.error);
      })
      .catch(() => {
        if (active) setError("방문 진행을 불러오지 못했어요. 연결을 확인해 주세요.");
      });
    return () => {
      active = false;
    };
  }, [plan.id]);
  function load(next = 0) {
    run(async () => {
      try {
        const response = await readVisits(plan.id, next);
        if (!response.data) {
          setError(response.error);
          return;
        }
        const rows = response.data;
        setRecords((old) =>
          next
            ? [...old, ...rows].filter(
                (r, i, all) => all.findIndex((a) => a.publication === r.publication) === i,
              )
            : rows,
        );
        setLoaded(true);
        setMore(response.data.length === 20);
        setOffset(next);
        setError("");
        setAttempt(null);
        setNotice("");
      } catch {
        setError("방문 진행을 불러오지 못했어요. 연결을 확인해 주세요.");
      }
    });
  }
  function save(change: VisitChange) {
    setAttempt(change);
    setError("");
    setNotice("");
    run(async () => {
      try {
        const response = await changeVisit(plan.id, change);
        if (!response.data) {
          setError(response.error);
          return;
        }
        const saved = response.data;
        setRecords((old) => [saved, ...old.filter((r) => r.publication !== saved.publication)]);
        setAttempt(null);
        setNotice("둘의 방문 진행을 저장했어요.");
      } catch {
        setError(
          "저장 결과를 확인하지 못했어요. 같은 변경을 다시 시도하거나 최신 진행을 확인해 주세요.",
        );
      }
    });
  }
  function choose(index: number, state: VisitState) {
    save({
      publication: plan.published_revision,
      activity: index,
      state,
      expected_version: current?.version || 0,
      request_id: crypto.randomUUID(),
    });
  }
  return (
    <LoadingRegion busy={pending || (!loaded && !error)} label="방문 진행을 불러오는 중">
      <section className="plan-review" aria-label="공동 방문 진행" aria-busy={pending}>
        <h2>둘의 방문 진행</h2>
        <p className="settings-hint">
          확정안 {plan.published_revision} · 직접 표시한 상태를 둘이 함께 봐요. 방문 완료도 다시
          예정으로 되돌릴 수 있어요.
        </p>
        <div className="calendar-toolbar">
          <button
            className="text-button"
            type="button"
            disabled={pending || (!loaded && !error)}
            onClick={() => load()}
          >
            최신 방문 진행 불러오기
          </button>
          <RefreshButton
            label="확정 플랜 새로고침"
            pending={pending}
            onClick={() => refreshPlan(() => router.refresh())}
          />
        </div>
        {content && content.date > today && (
          <p className="settings-hint">방문 진행은 플랜 당일이나 지난 날짜에 표시할 수 있어요.</p>
        )}
        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {attempt && error && (
          <button
            type="button"
            className="text-button"
            disabled={pending}
            onClick={() => save(attempt)}
          >
            같은 변경 다시 시도
          </button>
        )}
        {content && (
          <ol className="plan-list">
            {content?.activities.map((activity, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: Publication identity freezes activity order.
              <li className="plan-card" key={index}>
                <p>
                  {index + 1}. {activity.title} ·{" "}
                  <strong>
                    {loaded ? visitLabels[states[index]] : error ? "확인 필요" : "확인 중"}
                  </strong>
                </p>
                <fieldset className="calendar-toolbar" aria-label={`${activity.title} 방문 상태`}>
                  {(["planned", "visited", "skipped"] as const).map((state) => (
                    <button
                      type="button"
                      className="text-button"
                      key={state}
                      aria-pressed={loaded && states[index] === state}
                      disabled={pending || !writable || !!attempt}
                      onClick={() => choose(index, state)}
                    >
                      {visitLabels[state]}
                    </button>
                  ))}
                </fieldset>
              </li>
            ))}
          </ol>
        )}
        {current && (
          <p className="settings-hint">
            마지막 변경 (한국) {zonedTimestamp(current.updated_at, "Asia/Seoul")}
          </p>
        )}
        {records
          .filter((r) => r.publication !== plan.published_revision)
          .map((record) => (
            <details key={record.publication}>
              <summary>
                이전 확정안 {record.publication} · {record.snapshot.title} · {record.snapshot.date}
              </summary>
              <ol>
                {record.snapshot.activities.map((activity, index) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: Historical publication order is immutable.
                  <li key={index}>
                    {activity.title} · {visitLabels[record.states[index]]}
                  </li>
                ))}
              </ol>
              <p className="settings-hint">
                당시 확정안의 기록이에요. 현재 확정안의 진행과 별도로 보존돼요.
              </p>
            </details>
          ))}
        {more && (
          <button
            className="text-button"
            type="button"
            disabled={pending}
            onClick={() => load(offset + 20)}
          >
            이전 진행 기록 더 보기
          </button>
        )}
        <p className="settings-hint">상태 변경으로 만난 날이나 직선 동선을 자동 등록하지 않아요.</p>
      </section>
    </LoadingRegion>
  );
}
