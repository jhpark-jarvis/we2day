import Link from "@/components/progress-link";
import { RouteHistory } from "@/components/route-history";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { Couple } from "@/lib/shared-calendar";
export default async function RoutesPage() {
  const couple = await callApi<Couple | null>("/couple");
  if (!couple.data)
    return (
      <section>
        <h1>동선 모아보기</h1>
        <p>{couple.error || "둘의 공간을 연결해 주세요."}</p>
        <Link className="inline-link" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인
        </Link>
      </section>
    );
  const key = process.env.WE2DAY_NAVER_MAPS_CLIENT_ID || "";
  return (
    <RouteHistory today={seoulToday()} apiKey={/^[a-zA-Z0-9_-]{3,128}$/.test(key) ? key : ""} />
  );
}
