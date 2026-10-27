"use client";

import { ArrowRight, Check, Plus, SlidersHorizontal } from "lucide-react";
import { useRef, useState } from "react";
import {
  briefError,
  currentBrief,
  emptyBrief,
  type IntakeContext,
  type PlanningBrief,
} from "@/lib/ai-intake";

export function BriefDetails({ brief }: { brief: PlanningBrief }) {
  return (
    <dl className="we2-brief-details">
      <div>
        <dt>일정</dt>
        <dd>
          {brief.date || "날짜 미정"} · {brief.start_time || "미정"} ~ {brief.end_time || "미정"}
        </dd>
      </div>
      <div>
        <dt>이동</dt>
        <dd>
          {brief.region || "선택한 저장 장소"} · {brief.transport || "수단 미정"}
        </dd>
      </div>
      <div>
        <dt>활동</dt>
        <dd>{brief.activities.join(" → ") || "추천"}</dd>
      </div>
      <div>
        <dt>예산</dt>
        <dd>{brief.budget === null ? "미정" : `${brief.budget.toLocaleString("ko-KR")}원`}</dd>
      </div>
      {brief.requirements && (
        <div>
          <dt>조건</dt>
          <dd>{brief.requirements}</dd>
        </div>
      )}
    </dl>
  );
}

export function IntakeSummary({ context }: { context: IntakeContext }) {
  const brief = currentBrief(context);
  if (!brief.date && !brief.region && !brief.activities.length && !context.intake) return null;
  return (
    <details className="we2-brief-summary">
      <summary>
        <SlidersHorizontal size={15} aria-hidden="true" />
        <span>조건</span>
        <small>
          {brief.date || "날짜 미정"} · {brief.region || "선택 장소"}
        </small>
      </summary>
      <BriefDetails brief={brief} />
    </details>
  );
}

export function AiIntake({
  disabled,
  selectedPlaces,
  onSubmit,
  onFreeChat,
}: {
  disabled: boolean;
  selectedPlaces: number;
  onSubmit: (brief: PlanningBrief) => void;
  onFreeChat: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [step, setStep] = useState(0);
  const [brief, setBrief] = useState<PlanningBrief>(emptyBrief);
  const [budget, setBudget] = useState("");
  const [custom, setCustom] = useState("");
  const [error, setError] = useState("");
  function goToStep(value: number) {
    setStep(value);
    setError("");
    // Keep the new group's heading visible after a taller previous group.
    formRef.current?.closest(".we2-messages")?.scrollTo({ top: 0 });
  }
  function update(values: Partial<PlanningBrief>) {
    setBrief((previous) => ({ ...previous, ...values }));
    setError("");
  }
  function next() {
    const prepared = {
      ...brief,
      region: brief.region.trim(),
      requirements: brief.requirements.trim(),
      budget:
        budget.trim() === "" ? null : /^\d+$/.test(budget.trim()) ? Number(budget) : Number.NaN,
    };
    const problem = briefError(prepared, step, selectedPlaces);
    setError(problem);
    if (problem) return;
    setBrief(prepared);
    if (step < 3) goToStep(step + 1);
    else onSubmit(prepared);
  }
  function addActivity(activity: string) {
    const value = activity.trim();
    if (!value || value.length > 60) return;
    const exists = brief.activities.includes(value);
    if (!exists && brief.activities.length === 8) {
      setError("활동은 8개까지 선택할 수 있어요.");
      return;
    }
    update({
      recommend: false,
      activities: exists
        ? brief.activities.filter((a) => a !== value)
        : [...brief.activities, value],
    });
    setCustom("");
  }
  return (
    <form
      ref={formRef}
      className="we2-intake"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        next();
      }}
      aria-label="코스 조건 입력"
    >
      <div className="we2-intake-heading">
        <h2>{step === 3 ? "조건 요약" : "어떤 하루를 보낼까요?"}</h2>
        <button type="button" className="text-button" disabled={disabled} onClick={onFreeChat}>
          바로 대화
        </button>
      </div>
      <nav className="we2-intake-steps" aria-label="조건 입력 단계">
        {["일정", "이동", "활동"].map((label, index) => (
          <button
            type="button"
            key={label}
            disabled={disabled || index > step}
            aria-current={step === index ? "step" : undefined}
            onClick={() => {
              goToStep(index);
            }}
          >
            <span>{step > index ? <Check size={13} aria-hidden="true" /> : index + 1}</span>
            {label}
          </button>
        ))}
      </nav>
      <fieldset disabled={disabled}>
        <legend className="sr-only">{["일정", "이동", "활동", "조건 요약"][step]}</legend>
        {step === 0 && (
          <div className="we2-intake-fields">
            <label>
              날짜 <small>선택</small>
              <input
                type="date"
                value={brief.date || ""}
                min="2000-01-01"
                max="2100-12-31"
                onChange={(e) => update({ date: e.target.value || null })}
              />
            </label>
            <div className="we2-intake-row">
              <label>
                시작 시간 <small>선택</small>
                <input
                  type="time"
                  value={brief.start_time || ""}
                  onChange={(e) => update({ start_time: e.target.value || null })}
                />
              </label>
              <label>
                종료 시간 <small>선택</small>
                <input
                  type="time"
                  value={brief.end_time || ""}
                  onChange={(e) => update({ end_time: e.target.value || null })}
                />
              </label>
            </div>
            <p className="we2-intake-hint">날짜가 미정이면 장소 후보부터 찾아요.</p>
          </div>
        )}
        {step === 1 && (
          <div className="we2-intake-fields">
            <label>
              지역
              <input
                type="text"
                autoComplete="off"
                maxLength={100}
                value={brief.region}
                placeholder="예: 중랑구, 성수동"
                onChange={(e) => update({ region: e.target.value })}
              />
            </label>
            <div>
              <span className="we2-intake-label">이동수단</span>
              <div className="we2-intake-choices">
                {["자동차", "대중교통", "도보", "미정"].map((label) => {
                  const value = label === "미정" ? "" : (label as PlanningBrief["transport"]);
                  return (
                    <button
                      type="button"
                      key={label}
                      aria-pressed={brief.transport === value}
                      onClick={() => update({ transport: value })}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>
            {selectedPlaces > 0 && (
              <p className="we2-intake-hint">지역 대신 직접 선택한 저장 장소를 사용할 수 있어요.</p>
            )}
          </div>
        )}
        {step === 2 && (
          <div className="we2-intake-fields">
            <div>
              <span className="we2-intake-label">
                활동 <small>선택 순서로 구성</small>
              </span>
              <div className="we2-intake-choices">
                {[
                  "산책",
                  "카페",
                  "식사",
                  "도서관",
                  "전시회",
                  "영화",
                  ...brief.activities.filter(
                    (a) => !["산책", "카페", "식사", "도서관", "전시회", "영화"].includes(a),
                  ),
                ].map((label) => (
                  <button
                    type="button"
                    key={label}
                    aria-pressed={brief.activities.includes(label)}
                    onClick={() => addActivity(label)}
                  >
                    {brief.activities.includes(label) && (
                      <small>{brief.activities.indexOf(label) + 1}</small>
                    )}
                    {label}
                  </button>
                ))}
                <button
                  type="button"
                  aria-pressed={brief.recommend}
                  onClick={() => update({ recommend: !brief.recommend, activities: [] })}
                >
                  추천
                </button>
              </div>
            </div>
            <div className="we2-intake-custom">
              <input
                aria-label="다른 활동"
                placeholder="다른 활동"
                maxLength={60}
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addActivity(custom);
                  }
                }}
              />
              <button
                type="button"
                className="icon-button"
                aria-label="활동 추가"
                disabled={!custom.trim()}
                onClick={() => addActivity(custom)}
              >
                <Plus size={19} />
              </button>
            </div>
            <label>
              예산 <small>선택 · 원</small>
              <input
                type="text"
                inputMode="numeric"
                value={budget}
                maxLength={10}
                placeholder="미정"
                onChange={(e) => {
                  setBudget(e.target.value);
                  setError("");
                }}
              />
            </label>
            <label>
              추가 조건 <small>선택</small>
              <textarea
                rows={2}
                maxLength={300}
                value={brief.requirements}
                placeholder="예: 걷기 적게, 시끄러운 곳 제외"
                onChange={(e) => update({ requirements: e.target.value })}
              />
            </label>
          </div>
        )}
        {step === 3 && <BriefDetails brief={brief} />}
      </fieldset>
      <p className="we2-intake-error" role={error ? "alert" : undefined}>
        {error}
      </p>
      <div className="we2-intake-footer">
        {step === 3 && (
          <button
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() => goToStep(0)}
          >
            조건 수정
          </button>
        )}
        <button type="submit" className="primary-button" disabled={disabled}>
          {step === 3 ? (brief.date ? "코스 생성" : "후보 검색") : step === 2 ? "요약" : "다음"}
          <ArrowRight size={15} aria-hidden="true" />
        </button>
      </div>
    </form>
  );
}
