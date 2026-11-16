import { CalendarDays, MessagesSquare, Search } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { QuestionForm } from "@/components/question-forms";
import { ServerRefresh, TogetherBack, TogetherCreate } from "@/components/workspace-controls";
import { callApi } from "@/lib/api";
import { isSupportedDate, seoulToday } from "@/lib/calendar";
import type { CoupleQuestion } from "@/lib/questions";
import type { Couple } from "@/lib/shared-calendar";
export default async function QuestionsPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; offset?: string }>;
}) {
  const query = await searchParams;
  const date = query.date && isSupportedDate(query.date) ? query.date : seoulToday();
  const offset =
    /^\d{1,6}$/.test(query.offset || "") && Number(query.offset) <= 100000
      ? Number(query.offset)
      : 0;
  const [couple, result] = await Promise.all([
    callApi<Couple | null>("/couple"),
    callApi<CoupleQuestion[]>(`/questions?date=${date}&offset=${offset}`),
  ]);
  if (!couple.data)
    return (
      <section>
        <PageHeading>
          <h1>질문</h1>
        </PageHeading>
        <p>둘의 공간에 연결하면 질문을 나눌 수 있어요.</p>
        <Link className="text-button" href={couple.status === 401 ? "/login" : "/couple"}>
          공간 연결 확인하기
        </Link>
      </section>
    );

  return (
    <section className="together-workspace">
      <PageHeading>
        <p className="eyebrow">A QUESTION FOR US</p>
        <h1>질문</h1>
      </PageHeading>
      <div className="together-toolbar question-toolbar">
        <TogetherBack />
        <form className="together-date-filter">
          <div className="auth-field">
            <label className="sr-only" htmlFor="question-date">
              질문 날짜 (한국 기준)
            </label>
            <input
              id="question-date"
              name="date"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              defaultValue={date}
            />
          </div>
          <button type="submit" className="icon-button" aria-label="이 날짜 보기" title="날짜 조회">
            <CalendarDays size={19} aria-hidden="true" />
          </button>
        </form>
        <div className="together-tools">
          <Link
            className="icon-button"
            href="/questions/search"
            aria-label="날짜·문구로 질문 찾기"
            title="질문 검색"
          >
            <Search size={19} aria-hidden="true" />
          </Link>
          <ServerRefresh label="질문 새로고침" />
          <TogetherCreate title="질문 추가">
            <QuestionForm key={date} date={date} />
          </TogetherCreate>
        </div>
      </div>
      {result.error && (
        <p role="alert" className="error-message">
          {result.error}
        </p>
      )}
      <div className="plan-list together-records question-records">
        {result.data?.map((q) => (
          <article className="plan-card" key={q.id}>
            <p className="preserve-lines">{q.prompt}</p>
            <Link
              className="icon-button"
              href={`/questions/${q.id}`}
              aria-label="답변 쓰기·보기"
              title="답변"
            >
              <MessagesSquare size={20} aria-hidden="true" />
            </Link>
          </article>
        ))}
      </div>
      {result.data?.length === 0 && <p className="empty-state">이 날짜에는 아직 질문이 없어요.</p>}
      {offset > 0 && (
        <Link className="text-button" href={`/questions?date=${date}`}>
          처음 질문으로
        </Link>
      )}
      {result.data?.length === 50 && (
        <Link className="text-button" href={`/questions?date=${date}&offset=${offset + 50}`}>
          다음 질문 보기
        </Link>
      )}
    </section>
  );
}
