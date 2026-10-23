import { redirect } from "next/navigation";
import { AnniversaryWorkspace } from "@/components/anniversary-workspace";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import type { AnniversaryList } from "@/lib/anniversaries";
import { callApi } from "@/lib/api";
import type { Couple } from "@/lib/shared-calendar";

export default async function AnniversariesPage() {
  const [couple, anniversaries] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<AnniversaryList>("/anniversaries"),
  ]);
  if (couple.status === 401) redirect("/login");
  if (!couple.data && !couple.error)
    return (
      <section className="auth-panel">
        <PageHeading>
          <h1>우리의 기념일</h1>
        </PageHeading>
        <p>먼저 둘의 공간을 연결해 주세요.</p>
        <Link className="auth-button" href="/couple">
          둘의 공간 연결하기
        </Link>
      </section>
    );
  const result = couple.data ? anniversaries : null;
  return <AnniversaryWorkspace data={result?.data || null} error={result?.error || couple.error} />;
}
