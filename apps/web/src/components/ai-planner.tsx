"use client";

import {
  ArrowDown,
  CalendarDays,
  Info,
  LoaderCircle,
  MapPin,
  MessageSquarePlus,
  Send,
  Sparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { changePlan } from "@/app/actions/plans";
import Link from "@/components/progress-link";
import type { PlanContent } from "@/lib/plans";

type Message = { id: string; role: "user" | "assistant"; content: string };
export function AiPlanner({ available, today }: { available: boolean; today: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [pendingText, setPendingText] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const proposalRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [activityKeys, setActivityKeys] = useState<string[]>([]);
  const [proposal, setProposal] = useState<PlanContent | null>(null);
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const saveIdentity = useRef({ id: crypto.randomUUID(), request: crypto.randomUUID() });
  const busy = pending || saving;
  useEffect(() => {
    if (messages.length || pendingText) {
      const log = logRef.current;
      if (log) log.scrollTop = log.scrollHeight;
    }
  }, [messages, pendingText]);
  async function send() {
    if (busy || !text.trim()) return;
    const next: Message[] = [
      ...messages,
      { id: crypto.randomUUID(), role: "user", content: text.trim() },
    ];
    setPending(true);
    setPendingText(text.trim());
    setText("");
    setError("");
    const history = next.slice(-11).map(({ role, content }) => ({ role, content }));
    while (
      history.length > 1 &&
      new TextEncoder().encode(JSON.stringify({ messages: history, proposal })).length > 18000
    )
      history.splice(0, 2);
    try {
      const response = await fetch("/api/ai/planner", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history,
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
      setText(next[next.length - 1].content);
      setError(error instanceof Error ? error.message : "연결하지 못했어요. 다시 시도해 주세요.");
    } finally {
      setPending(false);
      setPendingText("");
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
    <div className="we2-ai">
      <section className="we2-chat" aria-label="위투 AI 대화">
        <header className="we2-chat-header">
          <div>
            <Sparkles size={18} aria-hidden="true" />
            <strong>함께 짜는 데이트</strong>
          </div>
          <div className="we2-chat-tools">
            {proposal && (
              <button
                type="button"
                className="icon-button we2-course-jump"
                title="코스 보기"
                aria-label="코스 보기"
                onClick={() =>
                  proposalRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
              >
                <ArrowDown size={19} aria-hidden="true" />
              </button>
            )}
            <button
              type="button"
              className="icon-button"
              title="새 대화"
              aria-label="새 대화"
              disabled={busy || messages.length === 0}
              onClick={() => {
                setMessages([]);
                setText("");
                setProposal(null);
                setSaved("");
                setError("");
                setActivityKeys([]);
              }}
            >
              <MessageSquarePlus size={20} aria-hidden="true" />
            </button>
          </div>
        </header>
        {!available && (
          <p role="status" className="we2-connection">
            연결을 준비 중이에요. 잠시 후 다시 확인해 주세요.
          </p>
        )}
        <div
          ref={logRef}
          className="we2-messages"
          role="log"
          aria-label="AI 대화"
          aria-busy={pending}
        >
          {messages.length === 0 && !pending && (
            <div className="we2-welcome">
              <span className="we2-welcome-icon">
                <Sparkles size={28} aria-hidden="true" />
              </span>
              <h2>우리, 어디로 갈까요?</h2>
              <p>날짜와 하고 싶은 일을 알려주세요.</p>
              <div className="we2-starters">
                {[
                  { label: "산책과 카페", prompt: `${today} 오후 산책과 카페 코스를 같이 짜줘.` },
                  {
                    label: "비 오는 날",
                    prompt: `${today} 비 오는 날 실내 데이트를 계획하고 싶어.`,
                  },
                  {
                    label: "가벼운 하루",
                    prompt: `${today} 무리하지 않는 가벼운 데이트를 계획하고 싶어.`,
                  },
                ].map(({ label, prompt }) => (
                  <button
                    type="button"
                    className="text-button"
                    key={label}
                    disabled={busy || !available}
                    onClick={() => {
                      setText(prompt);
                      inputRef.current?.focus();
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) => (
            <div className={`we2-message we2-${message.role}`} key={message.id}>
              {message.role === "assistant" && (
                <span className="we2-speaker">
                  <Sparkles size={13} aria-hidden="true" />
                  위투 AI
                </span>
              )}
              <p>{message.content}</p>
            </div>
          ))}
          {pendingText && (
            <div className="we2-message we2-user">
              <p>{pendingText}</p>
            </div>
          )}
        </div>
        <div className="we2-status" role="status">
          {pending && (
            <>
              <LoaderCircle size={15} className="ai-spinner" aria-hidden="true" />
              다음 코스를 생각하고 있어요.
            </>
          )}
        </div>
        <div className="we2-input-area">
          {error && (
            <p role="alert" className="error-message">
              {error}
            </p>
          )}
          <form
            className="we2-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <label htmlFor="ai-message" className="sr-only">
              위투 AI에게 보낼 내용
            </label>
            <textarea
              ref={inputRef}
              id="ai-message"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={2000}
              rows={2}
              disabled={busy || !available}
              placeholder="어떤 데이트를 하고 싶어요?"
              enterKeyHint="send"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button
              className="icon-button we2-send"
              type="submit"
              aria-label="메시지 전송"
              title="전송"
              disabled={busy || !available || !text.trim()}
            >
              <Send size={19} aria-hidden="true" />
            </button>
          </form>
          <div className="we2-disclosure">
            <span>Cloudflare에서 처리 · 대화는 이 화면에만 유지</span>
            <details>
              <summary aria-label="이용 안내" title="이용 안내">
                <Info size={15} aria-hidden="true" />
              </summary>
              <p>
                최근 대화와 현재 코스만 AI에 전달해요. 계정·사진·개인 일정은 자동으로 보내지 않아요.
                무료 제공량을 소진하면 요청이 중단돼요. 남길 코스는 초안으로 저장해 주세요.
              </p>
            </details>
          </div>
        </div>
      </section>
      <section
        ref={proposalRef}
        className={`we2-proposal${proposal ? " has-proposal" : ""}`}
        aria-label="코스 초안"
      >
        <header className="we2-proposal-header">
          <span>
            <MapPin size={17} aria-hidden="true" />
            코스 초안
          </span>
          {proposal && <span className="we2-draft-badge">미확정</span>}
        </header>
        {proposal ? (
          <>
            <div className="we2-proposal-body">
              <h2>{proposal.title}</h2>
              <p className="we2-proposal-date">
                <CalendarDays size={15} aria-hidden="true" />
                {proposal.date}
                {proposal.transport && ` · ${proposal.transport}`}
              </p>
              <ol className="we2-itinerary">
                {proposal.activities.map((activity, index) => (
                  <li key={activityKeys[index]}>
                    <span className="we2-stop-number">{index + 1}</span>
                    <div>
                      <small>{activity.time || "시간 미정"}</small>
                      <strong>{activity.title}</strong>
                      {activity.place && <p>{activity.place}</p>}
                      {activity.note && <p className="settings-hint">{activity.note}</p>}
                    </div>
                  </li>
                ))}
              </ol>
              {proposal.preparation.length > 0 && (
                <div className="we2-preparation">
                  <strong>준비물</strong>
                  <p>{proposal.preparation.join(", ")}</p>
                </div>
              )}
            </div>
            <footer className="we2-proposal-footer">
              <p>저장 후 장소를 확인하고 확정해 주세요.</p>
              {saved ? (
                <Link className="primary-button" href={`/plans?item=${saved}`}>
                  저장한 초안 열기
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
            </footer>
          </>
        ) : (
          <div className="we2-proposal-empty">
            <MapPin size={30} aria-hidden="true" />
            <h2>코스를 여기에 모아둘게요.</h2>
            <p>
              대화하며 정한 장소와 시간을
              <br />
              한눈에 확인할 수 있어요.
            </p>
            <span>확정 전에는 달력에 표시되지 않아요.</span>
          </div>
        )}
      </section>
    </div>
  );
}
