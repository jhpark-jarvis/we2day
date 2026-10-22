import Link from "next/link";
import { PlanWorkspace } from "@/components/plan-workspace";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { DatePlan, PlanContent } from "@/lib/plans";
import type { Couple } from "@/lib/shared-calendar";
import type { Wish } from "@/lib/wishlist";
export default async function PlansPage({
  searchParams,
}: {
  searchParams: Promise<{ wish?: string; item?: string }>;
}) {
  const [couple, plans] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<DatePlan[]>("/plans"),
  ]);
  if (!couple.data)
    return (
      <section>
        <h1>데이트 플랜</h1>
        <p className="muted">둘의 공간에 연결하면 함께 플랜을 만들 수 있어요.</p>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  const { wish: id, item } = await searchParams;
  const selected =
    item && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(item)
      ? await callApi<DatePlan>(`/plans/${item}`)
      : null;
  let seed: PlanContent | null = null;
  let seedError = "";
  if (id) {
    const valid = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id);
    const wish = valid ? await callApi<Wish>(`/wishlist/${id}`) : null;
    if (wish?.data && !wish.data.archived) {
      const item = wish.data;
      seed = {
        title: item.title,
        date: seoulToday(),
        budget: null,
        transport: "",
        activities: [
          {
            title: item.title,
            time: null,
            place: item.kind === "place" ? item.title : "",
            cost: null,
            note: item.note,
          },
        ],
        preparation: [],
      };
    } else
      seedError = wish?.error || "위시를 확인해 주세요. 보관한 위시는 복원한 뒤 사용할 수 있어요.";
  }
  return (
    <PlanWorkspace
      initialPlans={plans.data || []}
      initialError={
        plans.error ||
        selected?.error ||
        seedError ||
        (item && !selected ? "플랜 주소를 확인해 주세요." : "")
      }
      initialSelected={selected?.data}
      today={seoulToday()}
      initialContent={seed}
    />
  );
}
