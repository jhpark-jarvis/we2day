"use client";

import { useActionState, useEffect, useState } from "react";
import { useFormStatus } from "react-dom";
import { saveAppointment } from "@/app/actions/appointments";
import { PlaceSearch } from "@/components/place-search";
import Link from "@/components/progress-link";
import type { Appointment } from "@/lib/shared-calendar";

export function AppointmentForm({
  date,
  appointment,
  requestId,
  onSaved,
  onCancel,
  onReload,
}: {
  date: string;
  appointment?: Appointment;
  requestId: string;
  onSaved: (value: Appointment) => void;
  onCancel: () => void;
  onReload: () => void;
}) {
  const [state, action] = useActionState(saveAppointment, { error: "" });
  const [fields, setFields] = useState({
    title: appointment?.title || "",
    date: appointment?.date || date,
    time: appointment?.time?.slice(0, 5) || "",
    place: appointment?.place || "",
    note: appointment?.note || "",
  });
  useEffect(() => {
    if (state.appointment) onSaved(state.appointment);
  }, [state.appointment, onSaved]);
  const change = (key: keyof typeof fields, value: string) =>
    setFields((previous) => ({ ...previous, [key]: value }));
  return (
    <section className="appointment-editor" aria-label="약속 입력">
      <h1>{appointment ? "약속 수정" : "새 약속"}</h1>
      <p className="muted">둘이 함께 보는 약속이에요. 날짜와 시간은 한국 시간을 기준으로 해요.</p>
      {!appointment && (
        <div className="note-panel">
          <p>여러 장소를 방문하는 데이트인가요?</p>
          <Link className="text-button" href={`/plans?date=${fields.date}&new=1`}>
            코스 등록
          </Link>
          <p className="settings-hint">
            방문 순서와 운전 목적지를 미리 정하고, 확정하면 달력 약속도 함께 생겨요.
          </p>
        </div>
      )}
      <PlaceSearch initialQuery={fields.place} />
      <form action={action} className="username-login">
        <input type="hidden" name="id" value={appointment?.id || ""} />
        <input type="hidden" name="version" value={appointment?.version || ""} />
        <input type="hidden" name="request_id" value={requestId} />
        <div className="auth-field">
          <label htmlFor="appointment-title">약속 이름</label>
          <input
            id="appointment-title"
            name="title"
            required
            maxLength={100}
            value={fields.title}
            onChange={(event) => change("title", event.target.value)}
          />
        </div>
        <div className="form-columns">
          <div className="auth-field">
            <label htmlFor="appointment-date">날짜</label>
            <input
              id="appointment-date"
              type="date"
              name="date"
              required
              min="2000-01-01"
              max="2100-12-31"
              value={fields.date}
              onChange={(event) => change("date", event.target.value)}
            />
          </div>
          <div className="auth-field">
            <label htmlFor="appointment-time">시간 (선택)</label>
            <input
              id="appointment-time"
              type="time"
              name="time"
              value={fields.time}
              onChange={(event) => change("time", event.target.value)}
            />
          </div>
        </div>
        <div className="auth-field">
          <label htmlFor="appointment-place">만날 장소 (선택)</label>
          <input
            id="appointment-place"
            name="place"
            maxLength={200}
            value={fields.place}
            onChange={(event) => change("place", event.target.value)}
          />
        </div>
        <div className="auth-field">
          <label htmlFor="appointment-note">메모 (선택)</label>
          <textarea
            id="appointment-note"
            name="note"
            rows={4}
            maxLength={2000}
            value={fields.note}
            onChange={(event) => change("note", event.target.value)}
          />
        </div>
        {state.error && (
          <p className="error-message" role="alert">
            {state.error}
          </p>
        )}
        {state.conflict && (
          <button className="text-button" type="button" onClick={onReload}>
            최신 일정 다시 불러오기 (입력한 내용은 저장되지 않아요)
          </button>
        )}
        <SaveButtons onCancel={onCancel} />
      </form>
    </section>
  );
}

function SaveButtons({ onCancel }: { onCancel: () => void }) {
  const { pending } = useFormStatus();
  return (
    <>
      <button type="submit" className="auth-button" disabled={pending} aria-busy={pending}>
        {"약속 저장하기"}
      </button>
      <button type="button" className="text-button" onClick={onCancel} disabled={pending}>
        취소
      </button>
    </>
  );
}
