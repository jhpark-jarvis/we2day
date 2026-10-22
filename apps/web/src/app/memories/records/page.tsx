import Link from "next/link";
import { RecordSearch } from "@/components/record-search";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { Couple } from "@/lib/shared-calendar";
export default async function RecordsPage() {
  const couple = await callApi<Couple | null>("/couple");
  if (!couple.data)
    return (
      <section>
        <h1>기록 찾기</h1>
        <p>{couple.error || "둘의 공간을 먼저 연결해 주세요."}</p>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인
        </Link>
      </section>
    );
  return <RecordSearch today={seoulToday()} />;
}
