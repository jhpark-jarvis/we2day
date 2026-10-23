import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { QuestionSearch } from "@/components/question-search";
import { callApi } from "@/lib/api";
import { seoulToday } from "@/lib/calendar";
import type { Couple } from "@/lib/shared-calendar";

export default async function QuestionSearchPage() {
  const couple = await callApi<Couple | null>("/couple");
  const today = seoulToday();
  return (
    <section className="today-workspace">
      <PageHeading>
        <p className="eyebrow">OUR QUESTIONS</p>
        <h1>함께 나눈 질문 찾기</h1>
        <p className="muted">날짜와 질문 문구로 다시 이야기할 주제를 찾아요.</p>
      </PageHeading>
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
