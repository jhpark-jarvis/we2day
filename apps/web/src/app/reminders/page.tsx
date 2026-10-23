import { NotificationPreview } from "@/components/notification-preview";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { ServerRefresh } from "@/components/workspace-controls";
import { countdown } from "@/lib/anniversaries";
import { callApi } from "@/lib/api";
import type { AnniversaryNotificationPreview, UpcomingList } from "@/lib/reminders";
export default async function RemindersPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const query = await searchParams;
  const days = query.days === "30" ? 30 : 7;
  const [result, preview] = await Promise.all([
    callApi<UpcomingList>(`/reminders?days=${days}`),
    callApi<AnniversaryNotificationPreview>(`/reminders/anniversary-preview?days=${days}`),
  ]);
  return (
    <section className="reminder-workspace">
      <PageHeading>
        <div>
          <p className="eyebrow">COMING UP TOGETHER</p>
          <h1>다가오는 일정</h1>
          <p className="muted">약속과 기념일을 미리 살펴봐요.</p>
        </div>
      </PageHeading>
      <div className="calendar-toolbar">
        <ServerRefresh label="일정 새로고침" />
        <Link
          className="timeline-choice"
          aria-current={days === 7 ? "page" : undefined}
          href="/reminders?days=7"
        >
          7일 안
        </Link>
        <Link
          className="timeline-choice"
          aria-current={days === 30 ? "page" : undefined}
          href="/reminders?days=30"
        >
          30일 안
        </Link>
        <Link className="text-button" href="/calendar/export">
          캘린더 파일 내보내기
        </Link>
      </div>
      <p className="settings-hint">
        다가오는 날짜를 모아 봐요. 기기별 알림은{" "}
        <Link className="inline-link" href="/settings">
          설정
        </Link>
        에서 직접 켤 수 있어요.
      </p>
      <NotificationPreview result={preview} days={days} />
      {result.error && (
        <>
          <p role="alert" className="error-message">
            {result.error}
          </p>
          <Link className="text-button" href={result.status === 401 ? "/login" : "/couple"}>
            {result.status === 401 ? "로그인하기" : "공간 연결 확인하기"}
          </Link>
        </>
      )}
      {result.data && (
        <>
          <p className="settings-hint">
            한국 기준 {result.data.as_of} ~ {result.data.until}
          </p>
          <ul className="upcoming-list">
            {result.data.items.map((item) => (
              <li key={`${item.source}:${item.id}`}>
                <span className="countdown-tag">{countdown(item.days_until)}</span>
                <div>
                  <p className="eyebrow">
                    {item.source === "anniversary" ? "기념일" : "약속"} · {item.date}
                    {item.time ? ` · ${item.time.slice(0, 5)}` : ""}
                  </p>
                  <h2>{item.title}</h2>
                  {item.place && <p className="muted">{item.place}</p>}
                  <Link
                    className="text-button"
                    href={item.source === "anniversary" ? "/anniversaries" : `/?date=${item.date}`}
                  >
                    {item.source === "anniversary" ? "기념일 관리" : "이 날짜의 일정 보기"}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
          {!result.data.items.length && (
            <p className="empty-state">이 기간에 예정된 약속이나 기념일이 없어요.</p>
          )}
        </>
      )}
    </section>
  );
}
