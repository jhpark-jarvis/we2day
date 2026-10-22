import Link from "@/components/progress-link";
import { RouletteEditor } from "@/components/roulette-editor";
import { callApi } from "@/lib/api";
import type { RouletteWheel } from "@/lib/roulette";
import type { Couple } from "@/lib/shared-calendar";
export default async function RoulettePage({
  searchParams,
}: {
  searchParams: Promise<{ archived?: string; offset?: string }>;
}) {
  const query = await searchParams;
  const archived = query.archived === "true";
  const offset =
    /^\d{1,6}$/.test(query.offset || "") && Number(query.offset) <= 100000
      ? Number(query.offset)
      : 0;
  const [couple, result] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<RouletteWheel[]>(`/roulette?archived=${archived}&offset=${offset}`),
  ]);
  if (!couple.data)
    return (
      <section>
        <h1>룰렛</h1>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  return (
    <section className="today-workspace">
      <p className="eyebrow">PICK ONE, TOGETHER</p>
      <h1>룰렛</h1>
      <p className="muted">직접 적은 후보 중 하나를 함께 골라요.</p>
      <nav className="archive-links" aria-label="룰렛 구분">
        <Link href="/roulette" aria-current={!archived ? "page" : undefined}>
          현재
        </Link>
        <Link href="/roulette?archived=true" aria-current={archived ? "page" : undefined}>
          보관함
        </Link>
      </nav>
      {result.error && (
        <p role="alert" className="error-message">
          {result.error}
        </p>
      )}
      <div className="plan-list">
        {result.data?.map((wheel) => (
          <article className="plan-card" key={wheel.id}>
            <h2>{wheel.title}</h2>
            <p>
              {wheel.candidates.length}개 후보{wheel.archived ? " · 보관됨" : ""}
            </p>
            <Link className="text-button" href={`/roulette/${wheel.id}`}>
              룰렛 열기 · {wheel.title}
            </Link>
          </article>
        ))}
      </div>
      {result.data?.length === 0 && <p className="empty-state">아직 룰렛이 없어요.</p>}
      {offset > 0 && (
        <Link className="text-button" href={`/roulette?archived=${archived}`}>
          처음 룰렛으로
        </Link>
      )}
      {result.data?.length === 50 && (
        <Link className="text-button" href={`/roulette?archived=${archived}&offset=${offset + 50}`}>
          다음 룰렛 보기
        </Link>
      )}
      <h2>새 룰렛 만들기</h2>
      <RouletteEditor wheel={null} draws={[]} />
      <p className="settings-hint">
        뽑기는 후보 선택만 도와요. 약속·방문·결제나 보상을 자동으로 만들지 않아요.
      </p>
    </section>
  );
}
