import { NextAppointment } from "@/components/next-appointment";
import Link from "@/components/progress-link";
import { TimezoneSettings } from "@/components/timezone-settings";
import { callApi } from "@/lib/api";
import type { TimezoneView } from "@/lib/timezones";
import type { NextAppointment as NextData } from "@/lib/upcoming";
export default async function TimezonesPage() {
  const [result, next] = await Promise.all([
    callApi<TimezoneView>("/timezones"),
    callApi<NextData>("/appointments/next"),
  ]);
  const options = [
    ...new Set([
      "UTC",
      ...Intl.supportedValuesOf("timeZone"),
      ...(result.data?.mine?.timezone ? [result.data.mine.timezone] : []),
    ]),
  ].sort();
  return (
    <section className="today-workspace">
      <Link className="text-button" href="/settings">
        ← 설정으로
      </Link>
      <p className="eyebrow">OUR LOCAL TIME</p>
      <h1>각자의 시간대</h1>
      <p className="muted">일정은 한국 시간으로 유지하고 현지 시각을 함께 봐요.</p>
      {result.data && (
        <NextAppointment data={next?.data || null} error={next?.error || ""} zones={result.data} />
      )}
      <TimezoneSettings initial={result.data} error={result.error} options={options} />
      <p className="settings-hint">
        시간 있는 약속·투데이 활동에만 현지 시각을 보조 표시해요. 종일 일정·날짜별 기록·달력 묶음은
        한국 기준이며 자동으로 바꾸지 않아요.
      </p>
    </section>
  );
}
