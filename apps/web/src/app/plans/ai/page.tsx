import { AiPlanner } from "@/components/ai-planner";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";

export default async function AiPlannerPage() {
  const status = await callApi<{ available: boolean }>("/ai/planner");
  return (
    <section>
      <PageHeading>
        <div>
          <p className="eyebrow">PLAN TOGETHER</p>
          <h1>AI 플래너</h1>
        </div>
      </PageHeading>
      {status.status === 401 ? (
        <Link href="/login" className="text-button">
          로그인
        </Link>
      ) : status.error ? (
        <p role="alert">{status.error}</p>
      ) : (
        <AiPlanner available={status.data?.available || false} today={seoulToday()} />
      )}
    </section>
  );
}
