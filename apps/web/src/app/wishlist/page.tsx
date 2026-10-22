import Link from "@/components/progress-link";
import { WishWorkspace } from "@/components/wish-workspace";
import { callApi } from "@/lib/api";
import type { Couple } from "@/lib/shared-calendar";
import type { Wish } from "@/lib/wishlist";
export default async function WishlistPage({
  searchParams,
}: {
  searchParams: Promise<{ item?: string }>;
}) {
  const [couple, wishes] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<Wish[]>("/wishlist"),
  ]);
  if (!couple.data)
    return (
      <section>
        <h1>우리의 위시리스트</h1>
        <p className="muted">둘의 공간에 연결하면 함께 만들 수 있어요.</p>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  const { item } = await searchParams;
  const selected =
    item && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(item)
      ? await callApi<Wish>(`/wishlist/${item}`)
      : null;
  return (
    <WishWorkspace
      initialItems={wishes.data || []}
      initialSelected={selected?.data}
      initialError={
        wishes.error || selected?.error || (item && !selected ? "위시 주소를 확인해 주세요." : "")
      }
    />
  );
}
