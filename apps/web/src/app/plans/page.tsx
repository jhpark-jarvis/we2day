import { PageHeading } from "@/components/page-heading";
import { PlanWorkspace } from "@/components/plan-workspace";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import type { DatePlan, PlanContent, PlanSummary } from "@/lib/plans";
import type { Couple } from "@/lib/shared-calendar";
import type { Wish } from "@/lib/wishlist";
export default async function PlansPage({
  searchParams,
}: {
  searchParams: Promise<{ wish?: string; item?: string; date?: string; new?: string }>;
}) {
  const { wish: id, item, date, new: create } = await searchParams;
  const editing = Boolean(item || id || create === "1");
  const validItem =
    typeof item === "string" && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(item);
  const [couple, plans, selected] = await Promise.all([
    callApi<Couple | null>("/couple"),
    editing ? null : callApi<PlanSummary[]>("/plans?summary=true"),
    validItem ? callApi<DatePlan>(`/plans/${item}`) : null,
  ]);
  if (!couple.data)
    return (
      <section>
        <PageHeading>
          <h1>데이트 플랜</h1>
          <p className="muted">둘의 공간에 연결하면 함께 플랜을 만들 수 있어요.</p>
        </PageHeading>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  const selectedDate = typeof date === "string" && isSupportedDate(date) ? date : seoulToday();
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
  if (!seed && create === "1" && !item)
    seed = {
      title: "",
      date: selectedDate,
      budget: null,
      transport: "자동차",
      activities: [{ title: "", time: null, place: "", cost: null, note: "" }],
      preparation: [],
    };
  return (
    <PlanWorkspace
      key={`${item || id || "list"}:${selectedDate}:${create || ""}`}
      initialPlans={plans?.data || []}
      initialListLoaded={!editing}
      initialError={
        plans?.error ||
        selected?.error ||
        seedError ||
        (item && !selected ? "플랜 주소를 확인해 주세요." : "")
      }
      initialSelected={selected?.data}
      today={selectedDate}
      site={getAuthConfig()?.site || ""}
      initialContent={seed}
    />
  );
}
