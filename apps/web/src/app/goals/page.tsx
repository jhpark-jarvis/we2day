import { GoalWorkspace } from "@/components/goal-workspace";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { type GoalRead, section } from "@/lib/page-reads";

export default async function GoalsPage() {
  const read = await callApi<GoalRead>("/bootstrap/goals");
  const couple = section(read.data?.couple, read.status);
  const goals = section(read.data?.goals, read.status);
  if (!couple.data)
    return (
      <section>
        <PageHeading>
          <h1>목표</h1>
          <p className="muted">둘의 공간에 연결하면 함께 목표를 만들 수 있어요.</p>
        </PageHeading>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  return <GoalWorkspace initialGoals={goals.data || []} initialError={goals.error} />;
}
