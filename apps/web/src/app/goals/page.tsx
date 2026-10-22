import { GoalWorkspace } from "@/components/goal-workspace";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import type { Goal } from "@/lib/goals";
import type { Couple } from "@/lib/shared-calendar";

export default async function GoalsPage() {
  const [couple, goals] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<Goal[]>("/goals"),
  ]);
  if (!couple.data)
    return (
      <section>
        <h1>목표</h1>
        <p className="muted">둘의 공간에 연결하면 함께 목표를 만들 수 있어요.</p>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  return <GoalWorkspace initialGoals={goals.data || []} initialError={goals.error} />;
}
