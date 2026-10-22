export function calendarDate(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function parseDate(date: string): [number, number, number] {
  const [year, month, day] = date.split("-").map(Number);
  return [year, month - 1, day];
}

export function isSupportedDate(value: string) {
  if (!/^(20\d{2}|2100)-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = parseDate(value);
  return month >= 0 && month < 12 && day >= 1 && day <= daysInMonth(year, month);
}

export function previousYearDate(value: string): string | null {
  if (!isSupportedDate(value)) return null;
  const candidate = `${Number(value.slice(0, 4)) - 1}${value.slice(4)}`;
  return isSupportedDate(candidate) ? candidate : null;
}

export function seoulToday(): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const part = (name: string) => {
    const value = parts.find((item) => item.type === name)?.value;
    if (!value) throw new Error(`Missing calendar field: ${name}`);
    return value;
  };
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
}
