import { FavoritePlaces } from "@/components/favorite-places";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import type { Couple } from "@/lib/shared-calendar";
export default async function FavoritePlacesPage() {
  const couple = await callApi<Couple | null>("/couple");
  return (
    <>
      <PageHeading>
        <p className="eyebrow">OUR GO-TO PLACES</p>
        <h1>자주 가는 곳</h1>
        <p className="muted">둘이 함께 쓰는 장소를 관리해요.</p>
      </PageHeading>
      {couple.data ? (
        <FavoritePlaces manage />
      ) : (
        <>
          <p role="alert">{couple.error || "둘의 공간을 연결해 주세요."}</p>
          <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
            공간 연결 확인
          </Link>
        </>
      )}
    </>
  );
}
