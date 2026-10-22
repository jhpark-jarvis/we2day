export type NextAppointment = {
  as_of: string;
  item: { id: string; title: string; date: string; time: string | null; place: string } | null;
};
export function remainingAppointment(date: string, time: string | null, now: number) {
  const current = new Date(now + 9 * 3600000).toISOString().slice(0, 10);
  const days = Math.round(
    (Date.parse(`${date}T00:00:00Z`) - Date.parse(`${current}T00:00:00Z`)) / 86400000,
  );
  if (!time)
    return days === 0
      ? "오늘 · 시간 미정"
      : days > 0
        ? `D-${days} · 시간 미정`
        : "지난 날짜 · 최신 약속을 확인해 주세요";
  const minutes = Math.ceil((Date.parse(`${date}T${time}+09:00`) - now) / 60000);
  if (minutes <= 0) return "약속 시각이 지났어요 · 최신 약속을 확인해 주세요";
  return `${days === 0 ? "오늘" : `D-${days}`} · ${Math.floor(minutes / 60)}시간 ${minutes % 60}분 남음`;
}
