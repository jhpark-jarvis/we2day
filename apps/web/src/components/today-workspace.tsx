"use client";
import { ChevronLeft, ChevronRight, Copy } from "lucide-react";
import { useState } from "react";
import { LocalAppointmentTime } from "@/components/local-appointment-time";
import { NaverAppHandoff } from "@/components/naver-app-handoff";
import Link from "@/components/progress-link";
import { VisitProgressPanel } from "@/components/visit-progress";
import type { DatePlan } from "@/lib/plans";
import { planBudget } from "@/lib/timeline";
import type { TimezoneView } from "@/lib/timezones";
export function TodayWorkspace({
  plans,
  date,
  zones = null,
  today,
  site,
}: {
  plans: DatePlan[];
  date: string;
  zones?: TimezoneView | null;
  today: string;
  site: string;
}) {
  const [selected, setSelected] = useState(plans[0]?.id || "");
  const [step, setStep] = useState(0);
  const [notice, setNotice] = useState("");
  const plan = plans.find((p) => p.id === selected);
  const content = plan?.published_content;
  if (!plan || !content)
    return (
      <div className="empty-state">
        <p>이 날짜에 확정한 플랜이 없어요.</p>
        <Link className="text-button" href={`/plans?date=${date}&new=1`}>
          코스 등록
        </Link>
      </div>
    );
  const budget = planBudget(content);
  const current = content.activities[step];
  async function copyPlace(place: string) {
    try {
      await navigator.clipboard.writeText(place);
      setNotice("장소 이름을 복사했어요. 지도 앱에서 검색할 수 있어요.");
    } catch {
      setNotice("복사하지 못했어요. 표시된 장소 이름을 직접 복사해 주세요.");
    }
  }
  return (
    <div className="today-workspace">
      {plans.length > 1 && (
        <section className="calendar-toolbar" aria-label="이 날짜의 플랜 선택">
          {plans.map((p) => (
            <button
              className="timeline-choice"
              type="button"
              key={p.id}
              aria-pressed={selected === p.id}
              onClick={() => {
                setSelected(p.id);
                setStep(0);
                setNotice("");
              }}
            >
              {p.published_content?.title}
            </button>
          ))}
        </section>
      )}
      <header className="plan-review">
        <p className="eyebrow">확정한 하루 · {content.date}</p>
        <h2>{content.title}</h2>
        <p>
          {content.transport || "교통수단 미정"}
          {!!content.budget && ` · 예산 ${content.budget.toLocaleString()}원`}
        </p>
        {budget.known > 0 && (
          <p className="settings-hint">
            입력한 활동 비용 {budget.known.toLocaleString()}원
            {budget.total !== null && content.budget && budget.total > content.budget
              ? " · 계획 예산을 초과해요."
              : ""}
          </p>
        )}
        {JSON.stringify(plan.content) !== JSON.stringify(content) && (
          <div className="note-panel">
            <p>
              저장한 변경사항이 아직 코스에 반영되지 않았어요. 현재는 마지막 확정 내용을 보여줘요.
            </p>
            <Link className="text-button" href={`/plans?item=${plan.id}#plan-publication`}>
              변경안 확인·반영
            </Link>
          </div>
        )}
      </header>
      <VisitProgressPanel
        key={`${plan.id}:${plan.published_revision}`}
        plan={plan}
        today={today}
        selectedContent={
          current && (
            <section className="timeline-focus" aria-label="살펴보는 활동">
              <p className="eyebrow">
                {step + 1} / {content.activities.length} · {current.time || "시간 미정"}
              </p>

              <LocalAppointmentTime date={content.date} time={current.time} zones={zones} />

              {current.note && <p className="preserve-lines">{current.note}</p>}
              <NaverAppHandoff
                key={`${plan.id}:${plan.published_revision}:${step}`}
                place={current.place}
                site={site}
                extraAction={
                  current.place && (
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="이 장소 이름 복사"
                      title="장소 복사"
                      onClick={() => copyPlace(current.place)}
                    >
                      <Copy size={18} aria-hidden="true" />
                    </button>
                  )
                }
              />
              {notice && (
                <p role="status" className="settings-hint">
                  {notice}
                </p>
              )}
              <nav className="timeline-step-navigation" aria-label="활동 이동">
                <button
                  type="button"
                  className="icon-button"
                  aria-label="이전 활동 보기"
                  title="이전 활동"
                  disabled={step === 0}
                  onClick={() => {
                    setStep(step - 1);
                    setNotice("");
                  }}
                >
                  <ChevronLeft size={21} aria-hidden="true" />
                </button>
                <span className="muted" aria-hidden="true">
                  {step + 1} / {content.activities.length}
                </span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="다음 활동 보기"
                  title="다음 활동"
                  disabled={step === content.activities.length - 1}
                  onClick={() => {
                    setStep(step + 1);
                    setNotice("");
                  }}
                >
                  <ChevronRight size={21} aria-hidden="true" />
                </button>
              </nav>
            </section>
          )
        }
        selectedActivity={step}
        onSelectActivity={(index) => {
          setStep(index);
          setNotice("");
        }}
      />
      <details className="plan-review">
        <summary>준비물</summary>
        {content.preparation.length ? (
          <ul>
            {content.preparation.map((item, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: Read-only published snapshot has no preparation IDs.
              <li key={`${plan.id}:prep:${index}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">아직 적어둔 준비물이 없어요.</p>
        )}
      </details>
      <div className="calendar-toolbar">
        <Link className="text-button" href={`/plans/${plan.id}/report`}>
          회고
        </Link>
        <Link className="text-button" href={`/memories?date=${date}`}>
          이 날짜의 사진
        </Link>
        <Link className="text-button" href={`/plans?item=${plan.id}`}>
          코스 수정
        </Link>
      </div>
    </div>
  );
}
