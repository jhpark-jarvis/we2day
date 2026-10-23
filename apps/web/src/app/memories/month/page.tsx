import Image from "next/image";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { MonthlyMemories } from "@/lib/monthly";
export default async function MonthlyPage({
  searchParams,
}: {
  searchParams: Promise<{ month?: string }>;
}) {
  const { month: query } = await searchParams;
  const month =
    typeof query === "string" && /^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(query)
      ? query
      : seoulToday().slice(0, 7);
  const result = await callApi<MonthlyMemories>(`/memories/month?month=${month}`);
  return (
    <section className="monthly-workspace">
      <Link className="text-button" href="/memories">
        ← 날짜별 사진으로
      </Link>
      <PageHeading>
        <div>
          <p className="eyebrow">A MONTH OF US</p>
          <h1>월간 추억</h1>
          <p className="muted">직접 남긴 기록으로 한 달을 돌아봐요.</p>
        </div>
      </PageHeading>
      <form className="calendar-toolbar" action="/memories/month">
        <div className="auth-field">
          <label htmlFor="memory-month">돌아볼 월</label>
          <input
            id="memory-month"
            name="month"
            type="month"
            min="2000-01"
            max="2100-12"
            defaultValue={month}
            key={month}
            required
          />
        </div>
        <button className="text-button" type="submit">
          이 달 보기
        </button>
      </form>
      {result.error && (
        <>
          <p role="alert" className="error-message">
            {result.error}
          </p>
          <Link className="text-button" href={result.status === 401 ? "/login" : "/couple"}>
            공간 연결 확인하기
          </Link>
        </>
      )}
      {result.data && (
        <>
          <dl className="memory-counts" aria-label="선택한 달의 기록 합계">
            <div>
              <dt>만난 날</dt>
              <dd>{result.data.meeting_count}일</dd>
            </div>
            <div>
              <dt>남긴 사진</dt>
              <dd>{result.data.photo_count}장</dd>
            </div>
            <div>
              <dt>직선 동선</dt>
              <dd>{result.data.route_count}일</dd>
            </div>
          </dl>
          <details className="compact-help">
            <summary>집계 기준</summary>
            <p className="settings-hint">
              만난 날은 직접 체크한 날짜만 세어요. 사진·약속·동선만으로 만남이나 실제 방문을
              추정하지 않아요. 휴지통·저장 미완료 사진은 제외해요.
            </p>
          </details>
          {result.data.photo_count > 6 && (
            <p className="settings-hint">
              날짜별 카드에 최근 사진 6장을 나눠 보여요. 해당 날짜의 앨범에서 나머지도 볼 수 있어요.
            </p>
          )}
          <ul className="memory-day-list">
            {result.data.days.map((day) => (
              <li key={day.date}>
                <strong>{day.date}</strong>
                <div className="monthly-day-photos">
                  {(result.data?.photos || [])
                    .filter((photo) => photo.date === day.date)
                    .map((photo) => (
                      <Link
                        className="monthly-photo"
                        aria-label={`${day.date}의 사진 보기`}
                        key={photo.id}
                        href={`/memories?date=${day.date}`}
                      >
                        <Image
                          src={`/api/photos/${photo.id}/image`}
                          alt={photo.caption || `${photo.date}에 남긴 사진`}
                          width={600}
                          height={450}
                          unoptimized
                        />
                      </Link>
                    ))}
                </div>
                <p>
                  {day.met ? "만난 날" : "만남 표시 없음"} · 사진 {day.photo_count}장
                  {day.route_recorded ? " · 직선 기록 있음" : ""}
                </p>
                <div className="calendar-toolbar">
                  <Link className="text-button" href={`/?date=${day.date}`}>
                    일정·동선 보기
                  </Link>
                  <Link className="text-button" href={`/memories?date=${day.date}`}>
                    이 날짜의 사진
                  </Link>
                </div>
              </li>
            ))}
          </ul>
          {!result.data.days.length && (
            <p className="empty-state">이 달에는 아직 남긴 기록이 없어요.</p>
          )}
        </>
      )}
    </section>
  );
}
