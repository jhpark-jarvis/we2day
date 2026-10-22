export type TimezonePreference = {
  user_id: string;
  timezone: string | null;
  version: number;
  updated_at: string;
};
export type TimezoneView = { mine: TimezonePreference | null; partner: TimezonePreference | null };

export function localAppointmentTime(date: string, time: string | null, timezone: string | null) {
  if (!time || !timezone) return null;
  return zonedTimestamp(`${date}T${time}+09:00`, timezone);
}

export function zonedTimestamp(value: string, timezone: string) {
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) return null;
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(instant);
    const part = (name: string) => parts.find((p) => p.type === name)?.value;
    return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`;
  } catch {
    return null;
  }
}
