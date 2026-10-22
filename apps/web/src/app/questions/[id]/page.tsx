import Link from "@/components/progress-link";
import { AnswerEditor, AnswerRefresh } from "@/components/question-forms";
import { callApi } from "@/lib/api";
import type { QuestionView } from "@/lib/questions";
export default async function QuestionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const valid = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(id);
  const result = valid
    ? await callApi<QuestionView>(`/questions/${id}`)
    : { data: null, error: "질문을 확인해 주세요." };
  if (!result.data)
    return (
      <section>
        <Link className="text-button" href="/questions">
          ← 질문 목록으로
        </Link>
        <p role="alert">{result.error}</p>
      </section>
    );
  const { question, mine, partner } = result.data;
  return (
    <section className="today-workspace">
      <Link className="text-button" href={`/questions?date=${question.date}`}>
        ← 질문 목록으로
      </Link>
      <p className="eyebrow">OUR ANSWERS</p>
      <h1>함께 나누는 답변</h1>
      <p className="muted">{question.date} · 한국 기준</p>
      <h2 className="preserve-lines">{question.prompt}</h2>
      <AnswerEditor id={id} initial={mine} />
      <h2>상대가 공유한 답변</h2>
      {partner ? (
        <p className="preserve-lines">{partner.content}</p>
      ) : (
        <p className="muted">지금 볼 수 있는 공유 답변이 없어요.</p>
      )}
      <AnswerRefresh />
      <p className="settings-hint">
        미응답·건너뛰기는 상대에게 표시하지 않아요. 공유를 철회해도 이미 읽거나 복사한 내용까지
        회수하지는 못해요.
      </p>
    </section>
  );
}
