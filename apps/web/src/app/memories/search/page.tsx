import { PhotoSearch } from "@/components/photo-search";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { Couple } from "@/lib/shared-calendar";

export default async function PhotoSearchPage() {
  const couple = await callApi<Couple | null>("/couple");
  const today = seoulToday();
  return (
    <section className="monthly-workspace">
      <Link className="text-button" href="/memories">
        ← 날짜별 사진으로
      </Link>
      <p className="eyebrow">FIND OUR MOMENTS</p>
      <h1>사진 찾아보기</h1>
      <p className="muted">날짜·한마디·파일명·기기 정보로 기억을 찾아요.</p>
      {couple.data ? (
        <PhotoSearch start={`${today.slice(0, 8)}01`} end={today} />
      ) : (
        <>
          <p role="alert">{couple.error || "둘의 공간에 연결하면 사진을 찾을 수 있어요."}</p>
          <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
            공간 연결 확인하기
          </Link>
        </>
      )}
    </section>
  );
}
