"use client";
import Link from "next/link";
import { useState, useTransition } from "react";
import { searchQuestions } from "@/app/actions/question-search";
import type { QuestionSearchPage, QuestionSearchQuery } from "@/lib/question-search";

export function QuestionSearch({ start, end }: { start: string; end: string }) {
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<QuestionSearchQuery | null>(null);
  const [result, setResult] = useState<QuestionSearchPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [pending, run] = useTransition();
  const input = { start_date: startDate, end_date: endDate, query: query.trim() };
  const changed = submitted && JSON.stringify(input) !== JSON.stringify(submitted);
  function search(next: number, conditions: QuestionSearchQuery) {
    setError("");
    run(async () => {
      try {
        const response = await searchQuestions(conditions, next);
        if (response.data) {
          setResult(response.data);
          setSubmitted(conditions);
          setOffset(next);
        } else setError(response.error);
      } catch {
        setError("질문을 찾지 못했어요. 연결을 확인한 뒤 다시 검색해 주세요.");
      }
    });
  }
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search(0, input);
        }}
      >
        <fieldset className="meeting-fields" disabled={pending}>
          <div className="plan-basics">
            <div className="auth-field">
              <label htmlFor="question-search-start">시작 날짜</label>
              <input
                id="question-search-start"
                type="date"
                min="2000-01-01"
                max="2100-12-31"
                value={startDate}
                required
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="auth-field">
              <label htmlFor="question-search-end">마지막 날짜</label>
              <input
                id="question-search-end"
                type="date"
                min="2000-01-01"
                max="2100-12-31"
                value={endDate}
                required
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          <div className="auth-field">
            <label htmlFor="question-search-text">질문 문구 검색어 (선택)</label>
            <input
              id="question-search-text"
              value={query}
              maxLength={100}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <p className="settings-hint">
            최대 366일을 찾아요. 검색어를 비우면 해당 기간의 질문을 모두 찾아요.
          </p>
          <button className="primary-button" type="submit">
            질문 검색
          </button>
        </fieldset>
      </form>
      {pending && <p role="status">질문을 찾고 있어요.</p>}
      {error && (
        <p role="alert" className="error-message">
          {error} 입력한 조건은 유지돼요.
        </p>
      )}
      {result && submitted && (
        <section aria-label="질문 검색 결과" aria-busy={pending}>
          <h2>검색 결과</h2>
          <p className="settings-hint">
            {submitted.start_date} ~ {submitted.end_date} · 이번 페이지 {result.items.length}개
          </p>
          {(changed || error) && (
            <p className="settings-hint">
              아래는 이전에 검색한 결과예요. 새 조건으로 다시 검색해 주세요.
            </p>
          )}
          {result.items.length === 0 && (
            <p className="empty-state">이 조건에 맞는 질문이 없어요.</p>
          )}
          <div className="plan-list">
            {result.items.map((question) => (
              <article className="plan-card" key={question.id}>
                <p className="muted">{question.date}</p>
                <p className="preserve-lines">{question.prompt}</p>
                <Link className="text-button" href={`/questions/${question.id}`}>
                  답변 쓰기·보기
                </Link>
              </article>
            ))}
          </div>
          <div className="calendar-toolbar">
            {offset > 0 && (
              <button
                className="text-button"
                type="button"
                disabled={pending}
                onClick={() => search(0, submitted)}
              >
                첫 결과 보기
              </button>
            )}
            {result.next_offset !== null && (
              <button
                className="text-button"
                type="button"
                disabled={pending}
                onClick={() => search(result.next_offset as number, submitted)}
              >
                다음 질문 보기
              </button>
            )}
          </div>
        </section>
      )}
      <p className="settings-hint">
        둘의 공간에 추가한 질문 문구만 찾아요. 답변은 각 질문을 열어 확인할 수 있어요.
      </p>
    </>
  );
}
