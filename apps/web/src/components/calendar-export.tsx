"use client";
import { useState } from "react";
export function CalendarExport({ month: initialMonth }: { month: string }) {
  const [month, setMonth] = useState(initialMonth);
  const [anniversaries, setAnniversaries] = useState(true);
  const [notes, setNotes] = useState(false);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  async function download() {
    setPending(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `/api/calendar/export?month=${month}&anniversaries=${anniversaries}&notes=${notes}`,
        { cache: "no-store" },
      );
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.error || "파일을 만들지 못했어요.");
      }
      if (!response.headers.get("content-type")?.startsWith("text/calendar"))
        throw new Error("파일을 확인하지 못했어요. 다시 시도해 주세요.");
      const file = await response.blob();
      const url = URL.createObjectURL(file);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `we2day-calendar-${month}.ics`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("캘린더 파일 다운로드를 요청했어요.");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "파일을 만들지 못했어요. 다시 시도해 주세요.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <form
      className="export-form"
      onSubmit={(event) => {
        event.preventDefault();
        download();
      }}
    >
      <fieldset className="meeting-fields" disabled={pending}>
        <div className="auth-field">
          <label htmlFor="export-month">내보낼 월</label>
          <input
            id="export-month"
            type="month"
            required
            min="2000-01"
            max="2100-12"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          />
        </div>
        <label className="check-field">
          <input
            type="checkbox"
            checked={anniversaries}
            onChange={(e) => setAnniversaries(e.target.checked)}
          />
          이 달의 기념일 포함
        </label>
        <label className="check-field">
          <input type="checkbox" checked={notes} onChange={(e) => setNotes(e.target.checked)} />
          약속 메모도 파일에 포함
        </label>
        <button className="primary-button" type="submit" aria-busy={pending}>
          {"캘린더 파일 다운로드"}
        </button>
      </fieldset>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="settings-hint">
          {notice}
        </p>
      )}
    </form>
  );
}
