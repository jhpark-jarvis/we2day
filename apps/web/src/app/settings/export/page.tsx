import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { RecordExport } from "@/components/record-export";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { Couple } from "@/lib/shared-calendar";
export default async function ExportPage() {
  const couple = await callApi<Couple | null>("/couple");
  if (!couple.data)
    return (
      <section>
        <PageHeading>
          <h1>기록 내보내기</h1>
        </PageHeading>
        <p>{couple.error || "둘의 공간을 연결해 주세요."}</p>
        <Link className="inline-link" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인
        </Link>
      </section>
    );
  return <RecordExport today={seoulToday()} />;
}
