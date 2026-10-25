import { ChecklistWorkspace } from "@/components/checklist-workspace";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { type ChecklistRead, section } from "@/lib/page-reads";

export default async function ChecklistsPage() {
  const read = await callApi<ChecklistRead>("/bootstrap/checklists");
  const couple = section(read.data?.couple, read.status);
  const lists = section(read.data?.lists, read.status);
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
