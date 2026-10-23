import type { Metadata } from "next";
import { PageHeading } from "@/components/page-heading";
import { PhotoWorkspace } from "@/components/photo-workspace";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { isSupportedDate, previousYearDate, seoulToday } from "@/lib/calendar";
import { type ProfileView, profileNames } from "@/lib/profiles";
import type { Couple } from "@/lib/shared-calendar";

export const metadata: Metadata = { title: "기록" };

export default async function MemoriesPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;
  const today = seoulToday();
  const selectedDate = typeof date === "string" && isSupportedDate(date) ? date : today;
  const lastYear = previousYearDate(today);
  const [couple, user, profiles] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<{ id: string }>("/auth/me"),
    callApi<ProfileView>("/profiles"),
  ]);
  return (
    <>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR LITTLE MOMENTS</p>
          <h1>함께한 날들</h1>
          <p className="muted">약속으로 시작해, 기억으로 남는 날들.</p>
        </div>
      </PageHeading>
      <PhotoWorkspace
        key={selectedDate}
        today={selectedDate}
        browseHref="/memories/search"
        userId={user.data?.id || null}
        canSave={!!couple.data && !!user.data}
        names={profileNames(profiles.data)}
      />
      <section className="settings-section" aria-label="작년 오늘 돌아보기">
        <h2>작년 오늘은 어땠을까요?</h2>
        {lastYear ? (
          <>
            <p className="muted">한국 날짜 기준 {lastYear}의 기록을 직접 열어볼 수 있어요.</p>
            <div className="calendar-toolbar memory-return-actions">
              <Link className="text-button" href={`/memories?date=${lastYear}`}>
                작년 오늘의 사진 보기
              </Link>
              <Link className="text-button" href={`/?date=${lastYear}`}>
                작년 오늘의 일정·만남 보기
              </Link>
            </div>
          </>
        ) : (
          <p className="muted">
            작년에 같은 날짜가 없거나 기록 지원 범위를 벗어났어요. 월간 추억에서 다른 날짜를
            골라보세요.
          </p>
        )}
      </section>
    </>
  );
}
