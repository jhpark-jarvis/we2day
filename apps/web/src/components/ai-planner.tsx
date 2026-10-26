"use client";

import { LoaderCircle, Send, Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { changePlan } from "@/app/actions/plans";
import Link from "@/components/progress-link";
import type { PlanContent } from "@/lib/plans";

type Message = { id: string; role: "user" | "assistant"; content: string };
export function AiPlanner({ available, today }: { available: boolean; today: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [consent, setConsent] = useState(false);
  const [activityKeys, setActivityKeys] = useState<string[]>([]);
  const [proposal, setProposal] = useState<PlanContent | null>(null);
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const saveIdentity = useRef({ id: crypto.randomUUID(), request: crypto.randomUUID() });
  const busy = pending || saving;
  async function send() {
    if (busy || !text.trim() || !consent) return;
    const next: Message[] = [
      ...messages,
      { id: crypto.randomUUID(), role: "user", content: text.trim() },
    ];
    setPending(true);
    setError("");
    try {
      const response = await fetch("/api/ai/planner", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          consent: true,
          messages: next.map(({ role, content }) => ({ role, content })),
          proposal,
        }),
        signal: AbortSignal.timeout(65000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "답변을 받지 못했어요.");
      setMessages([...next, { id: crypto.randomUUID(), role: "assistant", content: result.reply }]);
      setText("");
      if (result.plan) {
        setProposal(result.plan);
        setActivityKeys(result.plan.activities.map(() => crypto.randomUUID()));
        setSaved("");
        saveIdentity.current = { id: crypto.randomUUID(), request: crypto.randomUUID() };
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "연결하지 못했어요. 다시 시도해 주세요.");
    } finally {
      setPending(false);
    }
  }
  async function save() {
    if (!proposal || busy || saved) return;
    setSaving(true);
    setError("");
    try {
      const { id, request } = saveIdentity.current;
      const result = await changePlan(id, "save", proposal, 0, 0, request);
      if (result.error) throw new Error(result.error);
      setSaved(id);
    } catch (error) {
      setError(error instanceof Error ? error.message : "저장하지 못했어요.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="ai-planner">
      <p className="muted">날짜·지역·취향을 알려주면 코스를 함께 정리해요.</p>
      {!available && (
        <p role="status">AI 연결을 준비 중이에요. 서버 설정이 완료되면 사용할 수 있어요.</p>
      )}
      <label className="ai-consent">
        <input
          type="checkbox"
          checked={consent}
          disabled={busy}
          onChange={(e) => setConsent(e.target.checked)}
        />
        입력한 대화와 현재 제안을 Cloudflare AI로 보내는 데 동의해요.
      </label>
      <p className="settings-hint">
        대화는 이 화면에만 유지돼요. 계정·사진·개인 일정은 자동으로 보내지 않아요. 남길 코스는
        초안으로 저장해 주세요.
      </p>
      <div className="ai-messages" role="log" aria-label="AI 대화" aria-busy={pending}>
        {messages.length === 0 && (
          <p className="muted">예: {today} 오후 2시부터 서울숲 근처에서 산책과 카페 코스를 짜줘.</p>
        )}
        {messages.map((message) => (
          <div className={`ai-message ai-${message.role}`} key={message.id}>
            <small>{message.role === "user" ? "내 요청" : "AI 플래너"}</small>
            <p>{message.content}</p>
          </div>
        ))}
      </div>
      <div className="ai-status" role="status">
        {pending && (
          <>
            <LoaderCircle size={18} className="ai-spinner" aria-hidden="true" /> 코스를 정리하고
            있어요.
          </>
        )}
      </div>
      <form
        className="ai-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label htmlFor="ai-message" className="sr-only">
          AI에게 보낼 내용
        </label>
        <textarea
          id="ai-message"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={2000}
          rows={3}
          disabled={busy || !available}
          placeholder="날짜와 원하는 코스를 입력해 주세요."
        />
        <button
          className="icon-button"
          type="submit"
          aria-label="메시지 전송"
          title="전송"
          disabled={busy || !available || !consent || !text.trim() || messages.length >= 12}
        >
          <Send size={21} aria-hidden="true" />
        </button>
      </form>
      <div className="calendar-toolbar ai-actions">
        <button
          type="button"
          className="text-button"
          disabled={busy || messages.length === 0}
          onClick={() => {
            setMessages([]);
            setProposal(null);
            setSaved("");
            setError("");
          }}
        >
          새 대화
        </button>
        <span className="settings-hint">하루 최대 50회 · 한국 시간 오전 9시 초기화</span>
      </div>
      {messages.length >= 12 && (
        <p role="status">
          대화 길이 제한에 도달했어요. 필요한 초안을 저장하고 새 대화를 시작해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {proposal && (
        <section className="plan-review ai-proposal" aria-label="제안한 코스">
          <h2>
            <Sparkles size={18} aria-hidden="true" /> {proposal.title}
          </h2>
          <p>
            {proposal.date} {proposal.transport}
          </p>
          <ol>
            {proposal.activities.map((activity, index) => (
              <li key={activityKeys[index]}>
                <strong>
                  {activity.time || "시간 미정"} · {activity.title}
                </strong>
                {activity.place && <p>{activity.place}</p>}
                {activity.note && <p className="settings-hint">{activity.note}</p>}
              </li>
            ))}
          </ol>
          {proposal.preparation.length > 0 && <p>준비물: {proposal.preparation.join(", ")}</p>}
          <p className="settings-hint">
            AI 제안은 실제 장소·영업정보 확인이 필요해요. 저장 후 편집 화면에서 장소를 검색하고
            확정해 주세요.
          </p>
          <div className="calendar-toolbar ai-actions">
            {saved ? (
              <Link className="primary-button" href={`/plans?item=${saved}`}>
                저장한 초안
              </Link>
            ) : (
              <button
                className="primary-button"
                type="button"
                disabled={busy}
                onClick={() => void save()}
              >
                {saving ? "저장 중…" : "초안 저장"}
              </button>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
