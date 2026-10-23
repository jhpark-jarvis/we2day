import { ChecklistWorkspace } from "@/components/checklist-workspace";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import type { Checklist } from "@/lib/checklists";
import type { Couple } from "@/lib/shared-calendar";

export default async function ChecklistsPage() {
  const [couple, lists] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<Checklist[]>("/checklists"),
  ]);
  if (!couple.data)
    return (
      <section>
        <PageHeading>
          <h1>목록</h1>
          <p className="muted">둘의 공간에 연결하면 함께 준비할 수 있어요.</p>
        </PageHeading>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  return <ChecklistWorkspace initialLists={lists.data || []} initialError={lists.error} />;
}
