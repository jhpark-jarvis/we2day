"use client";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { createQuestion, saveAnswer } from "@/app/actions/together";
import type { Answer } from "@/lib/questions";
export function AnswerRefresh() {
  return (
    <button type="button" className="text-button" onClick={() => window.location.reload()}>
      작성 내용을 버리고 공유 답변 새로고침
    </button>
  );
}

export function QuestionForm({ date }: { date: string }) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [pending, start] = useTransition();
  const request = useRef<{ id: string; signature: string; requestId: string } | null>(null);
  return (
    <form
      className="meeting-fields"
      onSubmit={(e) => {
        e.preventDefault();
        const signature = JSON.stringify([date, prompt]);
        if (!request.current)
          request.current = { id: crypto.randomUUID(), signature, requestId: crypto.randomUUID() };
        else if (request.current.signature !== signature)
          request.current = { ...request.current, signature, requestId: crypto.randomUUID() };
        const saved = request.current;
        start(async () => {
          const result = await createQuestion(saved.id, date, prompt, saved.requestId);
          if (result.data) router.push(`/questions/${result.data.id}`);
          else setError(result.error);
        });
      }}
    >
      <fieldset disabled={pending} className="meeting-fields">
        <div className="auth-field">
          <label htmlFor="new-question">함께 나눌 질문</label>
          <textarea
            id="new-question"
            required
            maxLength={500}
            rows={3}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>
        <p className="settings-hint">
          질문은 저장 후 그대로 유지돼요. 다른 질문은 새로 추가해 주세요.
        </p>
        <button className="primary-button" type="submit">
          질문 추가
        </button>
      </fieldset>
      {error && (
        <>
          <p role="alert" className="error-message">
            {error}
          </p>
          <button className="text-button" type="button" onClick={() => window.location.reload()}>
            작성 내용을 버리고 질문 목록 새로고침
          </button>
        </>
      )}
    </form>
  );
}

export function AnswerEditor({ id, initial }: { id: string; initial: Answer | null }) {
  const [mine, setMine] = useState(initial);
  const [content, setContent] = useState(initial?.content || "");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, start] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  function save(shared: boolean, skipped: boolean) {
    const signature = JSON.stringify([content, shared, skipped, mine?.version || 0]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    const requestId = request.current.id;
    setMessage("");
    start(async () => {
      const result = await saveAnswer(id, content, shared, skipped, mine?.version || 0, requestId);
      if (result.data) {
        setMine(result.data);
        setError("");
        setMessage(
          skipped
            ? "질문을 건너뛰었어요. 작성한 초안은 나만 볼 수 있어요."
            : shared
              ? "답변을 공유했어요."
              : "개인 답변으로 저장했어요.",
        );
      } else {
        setError(result.error);
        setConflict(result.status === 409);
      }
    });
  }
  return (
    <section className="report-workspace">
      <h2>나의 답변</h2>
      <p className="settings-hint">본인만 수정할 수 있어요. 직접 공유한 답변만 상대에게 보여요.</p>
      {mine?.skipped && <p>건너뛴 질문이에요. 저장하면 답변을 이어갈 수 있어요.</p>}
      <fieldset className="meeting-fields" disabled={pending || conflict}>
        <div className="auth-field">
          <label htmlFor="question-answer">답변 내용</label>
          <textarea
            id="question-answer"
            maxLength={2000}
            rows={6}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </div>
        <button type="button" className="primary-button" onClick={() => save(false, false)}>
          {mine?.shared ? "공유 철회하고 개인 저장" : "개인 답변 저장"}
        </button>
        <button
          type="button"
          className="text-button"
          disabled={!content.trim()}
          onClick={() => save(true, false)}
        >
          {mine?.shared ? "수정한 답변 공유" : "이 답변을 상대와 공유"}
        </button>
        <button type="button" className="text-button" onClick={() => save(false, true)}>
          이 질문 건너뛰기·공유 철회
        </button>
      </fieldset>
      {message && <p role="status">{message}</p>}
      {error && (
        <p role="alert" className="error-message">
          {conflict ? "다른 화면에서 답변이 바뀌었어요. 작성 내용은 유지돼요." : error}
        </p>
      )}
      {conflict && (
        <button type="button" className="text-button" onClick={() => window.location.reload()}>
          작성 내용을 버리고 최신 답변 불러오기
        </button>
      )}
    </section>
  );
}
