import { AiConnectionRetry, AiPlanner } from "@/components/ai-planner";
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
          <h1>위투 AI</h1>
          <p className="muted">대화로 함께 짜는 데이트 코스.</p>
        </div>
      </PageHeading>
      {status.status === 401 ? (
        <Link href="/login" className="text-button">
          로그인
        </Link>
      ) : status.error ? (
        <div className="we2-connection-error">
          <p role="alert">{status.error}</p>
          <AiConnectionRetry />
        </div>
      ) : (
        <AiPlanner available={status.data?.available || false} today={seoulToday()} />
      )}
    </section>
  );
}
