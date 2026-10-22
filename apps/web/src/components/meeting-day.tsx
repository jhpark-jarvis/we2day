"use client";

import type { ReactNode } from "react";
import { useActionState, useEffect, useState } from "react";
import { useFormStatus } from "react-dom";
import { saveMeeting } from "@/app/actions/meetings";
import type { MeetingDay } from "@/lib/meetings";

function SubmitMeeting() {
  const { pending } = useFormStatus();
  return (
    <button className="primary-button" type="submit" disabled={pending} aria-busy={pending}>
      {"만남 기록 저장"}
    </button>
  );
}

function MeetingFields({ children }: { children: ReactNode }) {
  const { pending } = useFormStatus();
  return (
    <fieldset className="meeting-fields" disabled={pending}>
      {children}
    </fieldset>
  );
}

export function MeetingDayEditor({
  date,
  today,
  record,
  onSaved,
  onReload,
}: {
  date: string;
  today: string;
  record?: MeetingDay;
  onSaved: (meeting: MeetingDay) => void;
  onReload: () => void;
}) {
  const [met, setMet] = useState(record?.met || false);
  const [note, setNote] = useState(record?.note || "");
  const [requestId, setRequestId] = useState("");
  const [state, action] = useActionState(saveMeeting, { error: "" });
  useEffect(() => {
    setRequestId(crypto.randomUUID());
  }, []);
  useEffect(() => {
    if (state.meeting) onSaved(state.meeting);
  }, [state.meeting, onSaved]);
  if (date > today)
    return <p className="settings-hint">만난 날은 오늘과 지난 날짜에 기록할 수 있어요.</p>;
  return (
    <section className="meeting-day-editor" aria-label="선택한 날짜의 만남 기록">
      <h2>이 날의 만남</h2>
      <form action={action} className="meeting-day-form">
        <input type="hidden" name="date" value={date} />
        <input type="hidden" name="version" value={record?.version || 0} />
        <input type="hidden" name="request_id" value={requestId} />
        <MeetingFields>
          <label className="annual-option">
            <input
              type="checkbox"
              name="met"
              checked={met}
              onChange={(event) => {
                setMet(event.target.checked);
                setRequestId(crypto.randomUUID());
              }}
            />
            이 날 만났어요
          </label>
          <div className="auth-field">
            <label htmlFor="meeting-note">함께한 날의 메모</label>
            <textarea
              id="meeting-note"
              name="note"
              rows={3}
              maxLength={2000}
              value={note}
              placeholder="함께한 일이나 기억하고 싶은 순간을 남겨보세요."
              onChange={(event) => {
                setNote(event.target.value);
                setRequestId(crypto.randomUUID());
              }}
            />
          </div>
          <SubmitMeeting />
        </MeetingFields>
        <p className="settings-hint">저장을 눌러야 반영돼요. 만남 표시를 해제해도 메모는 남아요.</p>
        {state.error && (
          <p className="error-message" role="alert">
            {state.error}
          </p>
        )}
        {state.conflict && (
          <button type="button" className="text-button" onClick={onReload}>
            최신 만남 기록 불러오기
          </button>
        )}
      </form>
    </section>
  );
}
