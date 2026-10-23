"use client";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { LocalAppointmentTime } from "@/components/local-appointment-time";
import Link from "@/components/progress-link";
import type { TimezoneView } from "@/lib/timezones";
import { type NextAppointment as Data, remainingAppointment } from "@/lib/upcoming";
export function NextAppointment({
  data,
  error,
  zones,
  hideCalendarOnMobile = false,
}: {
  data: Data | null;
  error: string;
  zones: TimezoneView | null;
  hideCalendarOnMobile?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [now, setNow] = useState(() => (data ? Date.parse(data.as_of) : 0));
  useEffect(() => {
    if (!data) return;
    const baseline = Date.parse(data.as_of),
      start = performance.now();
    setNow(baseline);
    const id = setInterval(() => setNow(baseline + performance.now() - start), 30000);
    return () => clearInterval(id);
  }, [data]);
  const item = data?.item;
  return (
    <aside className="plan-review" aria-label="다음 약속">
      <header className="next-appointment-header">
        <h2 className="next-appointment-chip">다음 약속</h2>
        <button
          className="icon-button next-appointment-refresh"
          type="button"
          aria-label="다음 약속 새로고침"
          title="다음 약속 새로고침"
          aria-busy={pending}
          disabled={pending}
          onClick={() => startTransition(() => router.refresh())}
        >
          <RefreshCw size={18} aria-hidden="true" />
        </button>
      </header>
      {error ? (
        <p role="alert">{error}</p>
      ) : item ? (
        <>
          <h3>{item.title}</h3>
          <p>
            {item.date} · {item.time?.slice(0, 5) || "시간 미정"} · 한국 기준
          </p>
          <p>{remainingAppointment(item.date, item.time, now)}</p>
          <p>{item.place || "장소 미정"}</p>
          <LocalAppointmentTime date={item.date} time={item.time} zones={zones} />
          <Link className="text-button" href={`/today?date=${item.date}`}>
            데이트 코스
          </Link>
          <Link
            className={`text-button${hideCalendarOnMobile ? " next-appointment-calendar" : ""}`}
            href={`/?date=${item.date}`}
          >
            달력에서 약속 보기
          </Link>
        </>
      ) : (
        <p>앞으로 예정된 약속이 없어요. 달력에서 다음 약속을 정해 보세요.</p>
      )}
      <p className="settings-hint">
        시간 있는 오늘의 약속부터 날짜순으로 보여요. 시간이 없는 오늘 약속도 포함해요. 만남 완료는
        직접 기록해요.
      </p>
    </aside>
  );
}
