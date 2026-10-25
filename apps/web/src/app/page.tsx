import { Suspense } from "react";
import { AnniversarySummary } from "@/components/anniversary-summary";
import { CalendarWorkspace } from "@/components/calendar-workspace";
import { NextAppointment } from "@/components/next-appointment";
import type { AnniversaryList } from "@/lib/anniversaries";
import { callApi } from "@/lib/api";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import { type HomeRead, section } from "@/lib/page-reads";
import { profileNames } from "@/lib/profiles";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const today = seoulToday();
  const { date } = await searchParams;
  const selectedDate = typeof date === "string" && isSupportedDate(date) ? date : today;
  const anniversaryRead = callApi<AnniversaryList>("/anniversaries");
  const core = await callApi<HomeRead>(`/bootstrap/home?month=${selectedDate.slice(0, 7)}`);
  const couple = section(core.data?.couple, core.status);
  const status = couple.error
    ? couple.status === 401
      ? "guest"
      : "unavailable"
    : couple.data
      ? "ready"
      : "unlinked";
  const appointments = section(core.data?.appointments, core.status);
  const next = section(core.data?.next, core.status);
  const profiles = core.data?.profiles.data;
  const zones = core.data?.zones.data || null;
  return (
    <>
      {status === "ready" && (
        <div className="home-anniversary-slot">
          <Suspense
            fallback={
              <div
                className="anniversary-summary"
                role="status"
                aria-busy="true"
                aria-label="기념일 불러오는 중"
              >
                <span className="loading-spinner" aria-hidden="true" />
              </div>
            }
          >
            <AnniversaryRead result={anniversaryRead} />
          </Suspense>
        </div>
      )}
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
        userId={core.data?.user_id || null}
        names={profileNames(profiles || null)}
        initialDate={selectedDate}
        zones={zones}
        status={status}
        memberCount={couple.data?.member_count}
        participantNames={
          profiles
            ? [
                profiles.mine?.display_name || "이름 미설정",
                ...(couple.data?.member_count === 2
                  ? [profiles.partner?.display_name || "이름 미설정"]
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

async function AnniversaryRead({
  result,
}: {
  result: ReturnType<typeof callApi<AnniversaryList>>;
}) {
  const value = await result;
  return <AnniversarySummary data={value.data} />;
}
