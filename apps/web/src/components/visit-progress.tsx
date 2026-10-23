"use client";
import { Check, ListRestart, SkipForward } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { LoadingRegion } from "@/components/loading-region";
import { RefreshButton } from "@/components/workspace-controls";
import type { DatePlan } from "@/lib/plans";
import { changeVisit, readVisits } from "@/lib/visit-requests";
import { type VisitChange, type VisitProgress, type VisitState, visitLabels } from "@/lib/visits";

export function VisitProgressPanel({
  plan,
  today,
  selectedActivity,
  onSelectActivity,
}: {
  plan: DatePlan;
  today: string;
  selectedActivity: number;
  onSelectActivity: (index: number) => void;
}) {
  const router = useRouter();
  const [current, setCurrent] = useState<VisitProgress | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState<VisitChange | null>(null);
  const [changing, run] = useTransition();
  const [refreshing, refreshPlan] = useTransition();
  const pending = changing || refreshing;
  const content = plan.published_content;
  const states = current?.states || content?.activities.map(() => "planned" as const) || [];
  const writable = loaded && !!content && content.date <= today && !plan.archived;
  useEffect(() => {
    let active = true;
    readVisits(plan.id)
      .then((response) => {
        if (!active) return;
        if (response.data) {
          setCurrent(
            response.data.find((record) => record.publication === plan.published_revision) || null,
          );
          setLoaded(true);
        } else setError(response.error);
      })
      .catch(() => {
        if (active) setError("방문 진행을 불러오지 못했어요. 연결을 확인해 주세요.");
      });
    return () => {
      active = false;
    };
  }, [plan.id, plan.published_revision]);
  function load() {
    run(async () => {
      try {
        const response = await readVisits(plan.id);
        if (!response.data) {
          setError(response.error);
          return;
        }
        setCurrent(
          response.data.find((record) => record.publication === plan.published_revision) || null,
        );
        setLoaded(true);
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
        setCurrent(saved);
        setAttempt(null);
        setNotice("방문 상태를 저장했어요.");
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
    <LoadingRegion busy={pending || (!loaded && !error)} label="방문 상태를 불러오는 중">
      <section className="visit-progress" aria-label="데이트 활동" aria-busy={pending}>
        <div className="section-heading">
          <h2>데이트 활동</h2>
          <div className="section-actions">
            <button
              className="icon-button"
              aria-label="최신 방문 진행 불러오기"
              title="방문 상태 새로고침"
              type="button"
              disabled={pending || (!loaded && !error)}
              onClick={() => load()}
            >
              <ListRestart size={19} aria-hidden="true" />
            </button>
            <RefreshButton
              label="확정 플랜 새로고침"
              pending={pending}
              onClick={() => refreshPlan(() => router.refresh())}
            />
          </div>
        </div>
        {content && content.date > today && (
          <p className="settings-hint">방문 상태는 플랜 당일부터 표시할 수 있어요.</p>
        )}
        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="sr-only">
            {notice}
          </p>
        )}
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
        <ol className="day-timeline">
          {content?.activities.map((activity, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: Publication identity freezes activity order.
            <li className="activity-card" key={index} data-selected={selectedActivity === index}>
              <button
                className="timeline-item"
                type="button"
                aria-pressed={selectedActivity === index}
                onClick={() => onSelectActivity(index)}
              >
                <span>{activity.time || "시간 미정"}</span>
                <strong>{activity.title}</strong>
                <small>
                  {activity.place || "장소 없는 활동"}
                  {!!activity.cost && ` · ${activity.cost.toLocaleString()}원`}
                </small>
              </button>
              <div className="activity-progress">
                <span className="visit-state">
                  {loaded ? visitLabels[states[index]] : error ? "확인 필요" : "확인 중"}
                </span>
                <fieldset className="visit-actions" aria-label={`${activity.title} 방문 상태`}>
                  {(["visited", "skipped"] as const).map((state) => {
                    const active = loaded && states[index] === state;
                    const Icon = state === "visited" ? Check : SkipForward;
                    return (
                      <button
                        type="button"
                        className="icon-button visit-action"
                        key={state}
                        aria-label={visitLabels[state]}
                        title={`${visitLabels[state]}${active ? " 취소" : ""}`}
                        aria-pressed={active}
                        disabled={pending || !writable || !!attempt}
                        onClick={() => choose(index, active ? "planned" : state)}
                      >
                        <Icon size={20} aria-hidden="true" />
                      </button>
                    );
                  })}
                </fieldset>
              </div>
            </li>
          ))}
        </ol>
        <p className="settings-hint">
          완료·건너뜀은 다시 누르면 취소돼요. 만난 날은 별도로 기록해요.
        </p>
      </section>
    </LoadingRegion>
  );
}
