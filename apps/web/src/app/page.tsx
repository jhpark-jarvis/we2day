import { AnniversarySummary } from "@/components/anniversary-summary";
import { CalendarWorkspace } from "@/components/calendar-workspace";
import { NextAppointment } from "@/components/next-appointment";
import type { AnniversaryList } from "@/lib/anniversaries";
import { callApi } from "@/lib/api";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import type { ProfileView } from "@/lib/profiles";
import type { Appointment, Couple } from "@/lib/shared-calendar";
import type { TimezoneView } from "@/lib/timezones";
import type { NextAppointment as NextData } from "@/lib/upcoming";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const today = seoulToday();
  const { date } = await searchParams;
  const selectedDate = typeof date === "string" && isSupportedDate(date) ? date : today;
  const couple = await callApi<Couple | null>("/couple");
  const status = couple.error
    ? couple.status === 401
      ? "guest"
      : "unavailable"
    : couple.data
      ? "ready"
      : "unlinked";
  const [appointments, next, zoneResult, anniversaries, profiles] =
    status === "ready"
      ? await Promise.all([
          callApi<Appointment[]>(`/appointments?month=${selectedDate.slice(0, 7)}`),
          callApi<NextData>("/appointments/next"),
          callApi<TimezoneView>("/timezones"),
          callApi<AnniversaryList>("/anniversaries"),
          callApi<ProfileView>("/profiles"),
        ])
      : [null, null, null, null, null];
  const zones = zoneResult?.data || null;
  return (
    <>
      {status === "ready" && <AnniversarySummary data={anniversaries?.data || null} />}
      {status === "ready" && (
        <NextAppointment
          data={next?.data || null}
          error={next?.error || ""}
          zones={zones}
          hideCalendarOnMobile
        />
      )}
      <CalendarWorkspace
        key={selectedDate}
        today={today}
        initialDate={selectedDate}
        zones={zones}
        mapsKey={
          /^[a-zA-Z0-9_-]{3,128}$/.test(process.env.WE2DAY_NAVER_MAPS_CLIENT_ID || "")
            ? process.env.WE2DAY_NAVER_MAPS_CLIENT_ID || ""
            : ""
        }
        status={status}
        memberCount={couple.data?.member_count}
        participantNames={
          profiles?.data
            ? [
                profiles.data.mine?.display_name || "이름 미설정",
                ...(couple.data?.member_count === 2
                  ? [profiles.data.partner?.display_name || "이름 미설정"]
                  : []),
              ]
            : []
        }
        initialEvents={appointments?.data || []}
        initialError={appointments?.error || couple.error}
      />
    </>
  );
}
