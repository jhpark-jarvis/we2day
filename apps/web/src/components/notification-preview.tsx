import Link from "next/link";
import type { AnniversaryNotificationPreview } from "@/lib/reminders";

export function NotificationPreview({
  result,
  days,
}: {
  result: { data: AnniversaryNotificationPreview | null; error: string | null; status: number };
  days: 7 | 30;
}) {
  return (
    <details className="settings-section">
      <summary>기념일 알림 시점 미리보기</summary>
      <p className="muted">기념일 7일 전·1일 전·당일, 한국 시간 오전 9시를 기준으로 살펴봐요.</p>
      <p className="settings-hint">
        미리보기만 제공해요. 이 목록으로 알림이 예약되거나 발송되지는 않아요.
      </p>
      {result.error && (
        <>
          <p role="alert" className="error-message">
            {result.error}
          </p>
          <Link
            className="text-button"
            href={result.status === 401 ? "/login" : `/reminders?days=${days}`}
          >
            {result.status === 401 ? "로그인하기" : "미리보기 다시 확인하기"}
          </Link>
        </>
      )}
      {result.data && (
        <>
          <p className="settings-hint">
            계산 기준 {result.data.as_of.slice(0, 19).replace("T", " ")} (한국 시간)
            <br />
            {result.data.through_date}까지 · {result.data.items.length}개 시점
          </p>
          <ul className="upcoming-list" aria-label="기념일 알림 미리보기">
            {result.data.items.map((item) => (
              <li key={`${item.anniversary_id}:${item.occurrence_date}:${item.lead_days}`}>
                <span className="countdown-tag">
                  {item.lead_days === 0 ? "당일" : `${item.lead_days}일 전`}
                </span>
                <div>
                  <time dateTime={item.scheduled_at}>
                    {item.scheduled_at.slice(0, 10)} · 오전 9:00
                  </time>
                  <h3>{item.title}</h3>
                  <p className="muted">기념일 {item.occurrence_date}</p>
                </div>
              </li>
            ))}
          </ul>
          {!result.data.items.length && (
            <p className="empty-state">선택한 기간에 남아 있는 알림 시점이 없어요.</p>
          )}
          <Link className="text-button" href="/anniversaries">
            기념일 확인·수정하기
          </Link>
        </>
      )}
    </details>
  );
}
