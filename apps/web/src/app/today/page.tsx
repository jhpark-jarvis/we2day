import { Search } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { TodayWorkspace } from "@/components/today-workspace";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import { section, type TodayRead } from "@/lib/page-reads";
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
  const read = await callApi<TodayRead>(`/bootstrap/today?date=${date}&offset=${offset}`);
  const couple = section(read.data?.couple, read.status);
  const timeline = section(read.data?.timeline, read.status);
  const zones = section(read.data?.zones, read.status);
  const plans = couple.data ? timeline : { data: null, error: couple.error };
  return (
    <section>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR DAY, STEP BY STEP</p>
          <h1>데이트 코스</h1>
          <p className="muted">오늘의 장소를 확인하고 네이버 지도로 출발해요.</p>
        </div>
      </PageHeading>
      <form className="date-filter" action="/today">
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
        <button className="icon-button" type="submit" aria-label="이 날짜 보기" title="날짜 조회">
          <Search size={19} aria-hidden="true" />
        </button>
      </form>
      {plans.error && (
        <p role="alert" className="error-message">
          {plans.error}
        </p>
      )}
      {couple.data ? (
        <TodayWorkspace
          key={`${date}:${offset}:${plans.data?.map((plan) => `${plan.id}:${plan.published_revision}`).join(",")}`}
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
