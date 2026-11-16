import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { QuestionSearch } from "@/components/question-search";
import { TogetherBack } from "@/components/workspace-controls";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { Couple } from "@/lib/shared-calendar";

export default async function QuestionSearchPage() {
  const couple = await callApi<Couple | null>("/couple");
  const today = seoulToday();
  return (
    <section className="together-workspace together-search-page">
      <PageHeading>
        <p className="eyebrow">OUR QUESTIONS</p>
        <h1>질문 검색</h1>
      </PageHeading>
      <div className="together-toolbar">
        <TogetherBack href="/questions" label="질문 목록으로 돌아가기" />
      </div>
      {couple.data ? (
        <QuestionSearch start={`${today.slice(0, 8)}01`} end={today} />
      ) : (
        <>
          <p role="alert">{couple.error || "둘의 공간에 연결하면 질문을 찾을 수 있어요."}</p>
          <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
            공간 연결 확인하기
          </Link>
        </>
      )}
    </section>
  );
}
