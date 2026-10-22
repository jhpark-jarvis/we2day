import { localAppointmentTime, type TimezoneView } from "@/lib/timezones";
export function LocalAppointmentTime({
  date,
  time,
  zones,
}: {
  date: string;
  time: string | null;
  zones: TimezoneView | null;
}) {
  if (!time || !zones) return null;
  const mine = localAppointmentTime(date, time, zones.mine?.timezone || null);
  const partner = localAppointmentTime(date, time, zones.partner?.timezone || null);
  if (!mine && !partner) return null;
  return (
    <aside className="settings-hint" aria-label="현지 시각 보조">
      <p>일정 기준: 한국 시간</p>
      {mine && (
        <p>
          나의 현지 시각 · {mine} ({zones.mine?.timezone})
        </p>
      )}
      {partner && (
        <p>
          상대의 현지 시각 · {partner} ({zones.partner?.timezone})
        </p>
      )}
    </aside>
  );
}
