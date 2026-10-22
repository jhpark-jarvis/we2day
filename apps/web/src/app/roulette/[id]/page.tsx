import Link from "next/link";
import { RouletteEditor } from "@/components/roulette-editor";
import { callApi } from "@/lib/api";
import type { RouletteDraw, RouletteWheel } from "@/lib/roulette";
export default async function RouletteDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ offset?: string }>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const offset =
    /^\d{1,6}$/.test(query.offset || "") && Number(query.offset) <= 100000
      ? Number(query.offset)
      : 0;
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id))
    return <p role="alert">룰렛을 확인해 주세요.</p>;
  const wheel = await callApi<RouletteWheel>(`/roulette/${id}`);
  if (!wheel.data)
    return (
      <section>
        <Link className="text-button" href="/roulette">
          ← 룰렛 목록으로
        </Link>
        <p role="alert">{wheel.error}</p>
      </section>
    );
  const draws = await callApi<RouletteDraw[]>(`/roulette/${id}/draws?offset=${offset}`);
  return (
    <section className="today-workspace">
      <Link className="text-button" href="/roulette">
        ← 룰렛 목록으로
      </Link>
      <h1>{wheel.data.title}</h1>
      {draws.error && (
        <p role="alert" className="error-message">
          {draws.error}
        </p>
      )}
      <RouletteEditor
        key={`${id}:${wheel.data.version}:${offset}`}
        wheel={wheel.data}
        draws={draws.data || []}
      />
      {offset > 0 && (
        <Link className="text-button" href={`/roulette/${id}`}>
          최근 결과로
        </Link>
      )}
      {draws.data?.length === 50 && (
        <Link className="text-button" href={`/roulette/${id}?offset=${offset + 50}`}>
          이전 결과 더 보기
        </Link>
      )}
    </section>
  );
}
