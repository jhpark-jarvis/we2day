import { notFound } from "next/navigation";
import Link from "@/components/progress-link";
import { ReportWorkspace } from "@/components/report-workspace";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { DatePlan } from "@/lib/plans";
import type { DateReport } from "@/lib/reports";
export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id)) notFound();
  const [plan, user, reports] = await Promise.all([
    callApi<DatePlan>(`/plans/${id}`),
    callApi<{ id: string }>("/auth/me"),
    callApi<DateReport[]>(`/reports/${id}`),
  ]);
  if (!plan.data || !user.data)
    return (
      <section>
        <h1>데이트 리포트</h1>
        <p role="alert">{plan.error || user.error}</p>
        <Link href="/plans" className="text-button">
          플랜으로 돌아가기
        </Link>
      </section>
    );
  return (
    <ReportWorkspace
      plan={plan.data}
      userId={user.data.id}
      initialReports={reports.data || []}
      initialError={reports.error}
      today={seoulToday()}
    />
  );
}
