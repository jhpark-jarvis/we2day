import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { RecordExplorer } from "@/components/record-explorer";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import { type ContextRead, section } from "@/lib/page-reads";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string; month?: string; date?: string }>;
}) {
  const [query, context] = await Promise.all([
    searchParams,
    callApi<ContextRead>("/bootstrap/context"),
  ]);
  const couple = section(context.data?.couple, context.status);
  const profiles = context.data?.profiles.data;
  const today = seoulToday();
  const type =
    query.type === "records" || query.type === "routes" || query.type === "monthly"
      ? query.type
      : "photos";
  const month =
    typeof query.month === "string" && /^(20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(query.month)
      ? query.month
      : today.slice(0, 7);
  return (
    <section className="monthly-workspace">
      <PageHeading>
        <p className="eyebrow">FIND OUR MOMENTS</p>
        <h1>기록 검색</h1>
        <p className="muted">사진과 기록을 조건별로 찾아보세요.</p>
      </PageHeading>
      {couple.data ? (
        <RecordExplorer
          today={today}
          initialType={type}
          initialMonth={month}
          initialDate={query.date && isSupportedDate(query.date) ? query.date : today}
          site={getAuthConfig()?.site || ""}
          names={{
            mine: profiles?.mine?.display_name || "",
            partner: profiles?.partner?.display_name || "",
          }}
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
