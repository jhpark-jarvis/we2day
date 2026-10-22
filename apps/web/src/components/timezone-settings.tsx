"use client";
import { useRef, useState, useTransition } from "react";
import { saveTimezone } from "@/app/actions/together";
import type { TimezoneView } from "@/lib/timezones";
export function TimezoneSettings({
  initial,
  options,
  error: initialError,
}: {
  initial: TimezoneView | null;
  options: string[];
  error: string;
}) {
  const [mine, setMine] = useState(initial?.mine || null);
  const [timezone, setTimezone] = useState(mine?.timezone || "");
  const [error, setError] = useState(initialError);
  const [message, setMessage] = useState("");
  const [pending, start] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const signature = JSON.stringify([timezone, mine?.version || 0]);
        if (request.current?.signature !== signature)
          request.current = { signature, id: crypto.randomUUID() };
        const id = request.current.id;
        start(async () => {
          const result = await saveTimezone(timezone || null, mine?.version || 0, id);
          if (result.data) {
            setMine(result.data);
            setError("");
            setMessage("시간대를 저장했어요.");
          } else setError(result.error);
        });
      }}
    >
      <fieldset className="meeting-fields" disabled={pending}>
        <div className="auth-field">
          <label htmlFor="my-timezone">나의 시간대</label>
          <select id="my-timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)}>
            <option value="">선택하지 않음</option>
            {options.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
        </div>
        <button className="primary-button" type="submit">
          시간대 저장
        </button>
      </fieldset>
      <p className="settings-hint">
        직접 선택한 시간대만 같은 공간의 상대에게 표시돼요. 위치는 수집하지 않아요.
      </p>
      {initial?.partner?.timezone && <p>상대의 시간대 · {initial.partner.timezone}</p>}
      {message && <p role="status">{message}</p>}
      {error && (
        <>
          <p role="alert" className="error-message">
            {error}
          </p>
          <button className="text-button" type="button" onClick={() => window.location.reload()}>
            작성 내용을 버리고 최신 설정 불러오기
          </button>
        </>
      )}
    </form>
  );
}
