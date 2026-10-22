import Link from "@/components/progress-link";
import { TodayWorkspace } from "@/components/today-workspace";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import type { DatePlan } from "@/lib/plans";
import type { Couple } from "@/lib/shared-calendar";
import type { TimezoneView } from "@/lib/timezones";
export default async function TodayPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; offset?: string }>;
}) {
  const query = await searchParams;
  const date =
    typeof query.date === "string" && isSupportedDate(query.date) ? query.date : seoulToday();
  const offset =
    typeof query.offset === "string" &&
    /^\d{1,6}$/.test(query.offset) &&
    Number(query.offset) <= 100000
      ? Number(query.offset)
      : 0;
  const [couple, timeline, zones] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<DatePlan[]>(`/timeline?date=${date}&offset=${offset}`),
    callApi<TimezoneView>("/timezones"),
  ]);
  const plans = couple.data ? timeline : { data: null, error: couple.error };
  return (
    <section>
      <Link className="text-button" href="/">
        ← 일정으로
      </Link>
      <header className="page-heading">
        <div>
          <p className="eyebrow">OUR DAY, STEP BY STEP</p>
          <h1>투데이 타임라인</h1>
          <p className="muted">함께 정한 하루를 순서대로 살펴봐요.</p>
        </div>
      </header>
      <form className="calendar-toolbar" action="/today">
        <div className="auth-field">
          <label htmlFor="timeline-date">살펴볼 날짜</label>
          <input
            id="timeline-date"
            type="date"
            name="date"
            defaultValue={date}
            key={date}
            min="2000-01-01"
            max="2100-12-31"
            required
          />
        </div>
        <button className="text-button" type="submit">
          이 날짜 보기
        </button>
      </form>
      {plans.error && (
        <p role="alert" className="error-message">
          {plans.error}
        </p>
      )}
      {couple.data ? (
        <TodayWorkspace
          key={`${date}:${offset}`}
          plans={plans.data || []}
          date={date}
          today={seoulToday()}
          site={getAuthConfig()?.site || ""}
          zones={zones.data}
        />
      ) : (
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      )}
      <div className="calendar-toolbar">
        {offset > 0 && (
          <Link
            className="text-button"
            href={`/today?date=${date}&offset=${Math.max(0, offset - 50)}`}
          >
            이전 플랜 목록
          </Link>
        )}
        {plans.data?.length === 50 && (
          <Link className="text-button" href={`/today?date=${date}&offset=${offset + 50}`}>
            다음 플랜 목록
          </Link>
        )}
      </div>
    </section>
  );
}
