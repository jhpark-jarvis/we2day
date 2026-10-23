import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { RecordExplorer } from "@/components/record-explorer";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { ProfileView } from "@/lib/profiles";
import type { Couple } from "@/lib/shared-calendar";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string; month?: string }>;
}) {
  const [query, couple, profiles] = await Promise.all([
    searchParams,
    callApi<Couple | null>("/couple"),
    callApi<ProfileView>("/profiles"),
  ]);
  const today = seoulToday();
  const type =
    query.type === "records" || query.type === "routes" || query.type === "monthly"
      ? query.type
      : "photos";
  const month =
    typeof query.month === "string" && /^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(query.month)
      ? query.month
      : today.slice(0, 7);
  const mapsKey = process.env.WE2DAY_NAVER_MAPS_CLIENT_ID || "";
  return (
    <section className="monthly-workspace">
      <PageHeading>
        <p className="eyebrow">FIND OUR MOMENTS</p>
        <h1>기록 검색</h1>
        <p className="muted">사진부터 동선까지, 조건을 골라 찾아보세요.</p>
      </PageHeading>
      {couple.data ? (
        <RecordExplorer
          today={today}
          initialType={type}
          initialMonth={month}
          names={{
            mine: profiles.data?.mine?.display_name || "",
            partner: profiles.data?.partner?.display_name || "",
          }}
          mapsKey={/^[a-zA-Z0-9_-]{3,128}$/.test(mapsKey) ? mapsKey : ""}
        />
      ) : (
        <>
          <p role="alert">{couple.error || "둘의 공간을 연결하면 기록을 찾을 수 있어요."}</p>
          <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
            공간 연결 확인하기
          </Link>
        </>
      )}
    </section>
  );
}
