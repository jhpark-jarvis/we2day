"use client";
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
          {content.transport || "교통수단 미정"} · 예산{" "}
          {content.budget === null ? "미정" : `${content.budget.toLocaleString()}원`}
        </p>
        <p className="settings-hint">
          {content.activities.length
            ? `입력한 활동 비용 ${budget.known.toLocaleString()}원${budget.unknown ? ` + 비용 미정 ${budget.unknown}개` : ""}`
            : "아직 활동이 없어요."}
          {budget.total !== null && content.budget !== null && budget.total > content.budget
            ? " · 계획 예산을 초과해요."
            : ""}
        </p>
        {JSON.stringify(plan.content) !== JSON.stringify(content) && (
          <p className="settings-hint">
            수정 중인 변경안이 있어요. 여기에는 마지막 확정 내용을 표시해요.
          </p>
        )}
      </header>
      {current && (
        <section className="timeline-focus" aria-label="살펴보는 활동">
          <p className="eyebrow">
            {step + 1} / {content.activities.length} · {current.time || "시간 미정"}
          </p>
          <h2>{current.title}</h2>
          <LocalAppointmentTime date={content.date} time={current.time} zones={zones} />
          <p className="preserve-lines">{current.place || "장소 없는 활동"}</p>
          {current.place && (
            <button type="button" className="text-button" onClick={() => copyPlace(current.place)}>
              이 장소 이름 복사
            </button>
          )}
          <p className="preserve-lines">{current.note || "추가 메모가 없어요."}</p>
          <NaverAppHandoff
            key={`${plan.id}:${plan.published_revision}:${step}`}
            place={current.place}
            site={site}
          />
          <div className="calendar-toolbar">
            <button
              type="button"
              className="text-button"
              disabled={step === 0}
              onClick={() => {
                setStep(step - 1);
                setNotice("");
              }}
            >
              이전 활동 보기
            </button>
            <button
              type="button"
              className="text-button"
              disabled={step === content.activities.length - 1}
              onClick={() => {
                setStep(step + 1);
                setNotice("");
              }}
            >
              다음 활동 보기
            </button>
          </div>
        </section>
      )}
      {notice && (
        <p role="status" className="settings-hint">
          {notice}
        </p>
      )}
      <p className="settings-hint">
        활동을 살펴보거나 장소를 복사해도 방문 완료로 기록되지 않아요.
      </p>
      <ol className="day-timeline">
        {content.activities.map((a, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: Read-only published snapshot keeps this order for the page lifetime.
          <li key={`${plan.id}:activity:${index}`}>
            <button
              className="timeline-item"
              type="button"
              aria-pressed={step === index}
              onClick={() => {
                setStep(index);
                setNotice("");
              }}
            >
              <span>{a.time || "시간 미정"}</span>
              <strong>{a.title}</strong>
              <small>
                {a.place || "장소 없는 활동"} ·{" "}
                {a.cost === null ? "비용 미정" : `${a.cost.toLocaleString()}원`}
              </small>
            </button>
          </li>
        ))}
      </ol>
      <section className="plan-review">
        <h2>준비물</h2>
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
      </section>
      <VisitProgressPanel key={`${plan.id}:${plan.published_revision}`} plan={plan} today={today} />
      <div className="calendar-toolbar">
        <Link className="text-button" href={`/plans/${plan.id}/report`}>
          이 플랜의 리포트 작성·보기
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
