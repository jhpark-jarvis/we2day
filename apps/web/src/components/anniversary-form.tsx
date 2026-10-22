"use client";

import { useActionState, useEffect, useState } from "react";
import { useFormStatus } from "react-dom";
import { saveAnniversary } from "@/app/actions/anniversaries";
import { type Anniversary, kinds } from "@/lib/anniversaries";

export function AnniversaryForm({
  anniversary,
  requestId,
  today,
  hasRelationship,
  onSaved,
  onCancel,
  onReload,
}: {
  anniversary?: Anniversary;
  requestId: string;
  today: string;
  hasRelationship: boolean;
  onSaved: (value: Anniversary) => void;
  onCancel: () => void;
  onReload: () => void;
}) {
  const [state, action] = useActionState(saveAnniversary, { error: "" });
  const [fields, setFields] = useState({
    kind: anniversary?.kind || (hasRelationship ? "custom" : "relationship"),
    title: anniversary?.title || "",
    date: anniversary?.date || today,
    month: String(anniversary?.month || 1),
    day: String(anniversary?.day || 1),
    annual: anniversary?.annual ?? true,
  });
  const change = (key: keyof typeof fields, value: string | boolean) =>
    setFields((old) => ({ ...old, [key]: value }));
  useEffect(() => {
    if (state.anniversary) onSaved(state.anniversary);
  }, [state.anniversary, onSaved]);
  return (
    <section className="appointment-editor" aria-label="기념일 입력">
      <h1>{anniversary ? "기념일 수정" : "새 기념일"}</h1>
      <p className="muted">둘이 함께 보는 양력 기념일이에요.</p>
      <form action={action} className="username-login">
        <input type="hidden" name="id" value={anniversary?.id || ""} />
        <input type="hidden" name="version" value={anniversary?.version || ""} />
        <input type="hidden" name="request_id" value={requestId} />
        <div className="auth-field">
          {anniversary ? (
            <>
              <span>종류</span>
              <input type="hidden" name="kind" value={fields.kind} />
              <p>{kinds[anniversary.kind]}</p>
            </>
          ) : (
            <>
              <label htmlFor="anniversary-kind">종류</label>
              <select
                id="anniversary-kind"
                name="kind"
                value={fields.kind}
                onChange={(event) => change("kind", event.target.value)}
              >
                {!hasRelationship && <option value="relationship">우리의 시작</option>}
                <option value="birthday">생일</option>
                <option value="custom">기념일</option>
              </select>
            </>
          )}
        </div>
        <div className="auth-field">
          <label htmlFor="anniversary-title">기념일 이름</label>
          <input
            id="anniversary-title"
            name="title"
            required
            maxLength={100}
            value={fields.title}
            onChange={(event) => change("title", event.target.value)}
          />
        </div>
        {fields.kind === "birthday" ? (
          <>
            <div className="form-columns">
              <div className="auth-field">
                <label htmlFor="anniversary-month">월</label>
                <input
                  id="anniversary-month"
                  type="number"
                  name="month"
                  min={1}
                  max={12}
                  required
                  value={fields.month}
                  onChange={(event) => change("month", event.target.value)}
                />
              </div>
              <div className="auth-field">
                <label htmlFor="anniversary-day">일</label>
                <input
                  id="anniversary-day"
                  type="number"
                  name="day"
                  min={1}
                  max={31}
                  required
                  value={fields.day}
                  onChange={(event) => change("day", event.target.value)}
                />
              </div>
            </div>
            <p className="muted">출생연도는 저장하지 않아요.</p>
          </>
        ) : (
          <div className="auth-field">
            <label htmlFor="anniversary-date">기준 날짜</label>
            <input
              id="anniversary-date"
              type="date"
              name="date"
              required
              min="1900-01-01"
              max="2100-12-31"
              value={fields.date}
              onChange={(event) => change("date", event.target.value)}
            />
          </div>
        )}
        {fields.kind === "custom" && (
          <label className="annual-option">
            <input
              type="checkbox"
              name="annual"
              checked={fields.annual}
              onChange={(event) => change("annual", event.target.checked)}
            />
            매년 반복
          </label>
        )}
        <p className="muted">
          우리의 시작은 당일부터 1일로 세어요. 매년 반복하는 2월 29일은 평년에 2월 28일로 표시해요.
        </p>
        {state.error && (
          <p className="error-message" role="alert">
            {state.error}
          </p>
        )}
        {state.conflict && (
          <button className="text-button" type="button" onClick={onReload}>
            최신 기념일 불러오기 (입력한 내용은 저장되지 않아요)
          </button>
        )}
        <Buttons onCancel={onCancel} />
      </form>
    </section>
  );
}

function Buttons({ onCancel }: { onCancel: () => void }) {
  const { pending } = useFormStatus();
  return (
    <>
      <button type="submit" className="auth-button" disabled={pending} aria-busy={pending}>
        {"기념일 저장하기"}
      </button>
      <button type="button" className="text-button" disabled={pending} onClick={onCancel}>
        취소
      </button>
    </>
  );
}
