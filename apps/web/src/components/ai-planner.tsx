"use client";

import {
  ArrowDown,
  CalendarDays,
  FileText,
  History,
  Info,
  LoaderCircle,
  MapPin,
  MessageSquarePlus,
  Send,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { changePlan } from "@/app/actions/plans";
import Link from "@/components/progress-link";
import type { PlanContent } from "@/lib/plans";

type Conversation = { id: string; title: string; version: number; updated_at: string };
type Turn = {
  request_id: string;
  version: number;
  user_text: string;
  result: { reply: string; plan: PlanContent | null };
  prompt_version: string;
};
type PromptInfo = {
  system: string;
  today: string;
  version: string;
  model: string;
  temperature: number;
  max_tokens: number;
  recent_messages: number;
  input_bytes: number;
};
type Message = { id: string; role: "user" | "assistant"; content: string };
async function read(view: string, query = "") {
  const response = await fetch(`/api/ai/planner?view=${view}${query}`, { cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "기록을 불러오지 못했어요.");
  return result;
}
function turnMessages(turns: Turn[]): Message[] {
  return turns.flatMap((turn) => [
    { id: `${turn.request_id}-user`, role: "user" as const, content: turn.user_text },
    {
      id: `${turn.request_id}-assistant`,
      role: "assistant" as const,
      content: turn.result.reply,
    },
  ]);
}
export function AiPlanner({ available, today }: { available: boolean; today: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [pendingText, setPendingText] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const previousLogHeight = useRef<number | null>(null);
  const proposalRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [activityKeys, setActivityKeys] = useState<string[]>([]);
  const [proposal, setProposal] = useState<PlanContent | null>(null);
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const saveIdentity = useRef({ id: crypto.randomUUID(), request: crypto.randomUUID() });
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [promptInfo, setPromptInfo] = useState<PromptInfo | null>(null);
  const [promptOpen, setPromptOpen] = useState(false);
  const [oldestTurn, setOldestTurn] = useState(1);
  const conversation = useRef({ id: crypto.randomUUID(), version: 0 });
  const retry = useRef<{ id: string; text: string } | null>(null);
  const busy = pending || saving || loadingHistory;
  const openConversation = useCallback(async (id: string, before?: number) => {
    const older = Boolean(before);
    setLoadingHistory(true);
    setError("");
    try {
      const data = await read(
        "history",
        `&conversation_id=${id}${before ? `&before=${before}` : ""}`,
      );
      if (!data) throw new Error("대화 기록을 찾지 못했어요.");
      const turns: Turn[] = data.turns;
      setOldestTurn(turns[0]?.version || 1);
      if (older) {
        previousLogHeight.current = logRef.current?.scrollHeight || 0;
        setMessages((previous) => [...turnMessages(turns), ...previous]);
      } else {
        conversation.current = { id, version: data.version };
        retry.current = null;
        setMessages(turnMessages(turns));
        const plan = data.proposal || null;
        setProposal(plan);
        setActivityKeys(plan?.activities.map(() => crypto.randomUUID()) || []);
        setText("");
        setSaved("");
        setHistoryOpen(false);
        saveIdentity.current = { id: crypto.randomUUID(), request: crypto.randomUUID() };
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "기록을 불러오지 못했어요.");
    } finally {
      setLoadingHistory(false);
    }
  }, []);
  useEffect(() => {
    let active = true;
    void read("history")
      .then(async (items: Conversation[]) => {
        if (!active) return;
        setConversations(items);
        if (items[0]) await openConversation(items[0].id);
      })
      .catch(() => {
        if (active) setError("대화 기록을 불러오지 못했어요. 새로고침해 주세요.");
      })
      .finally(() => {
        if (active) setLoadingHistory(false);
      });
    return () => {
      active = false;
    };
    // Initial history is restored once; selecting another record is explicit.
  }, [openConversation]);
  useEffect(() => {
    if (messages.length || pendingText) {
      const log = logRef.current;
      if (log) {
        log.scrollTop =
          previousLogHeight.current === null
            ? log.scrollHeight
            : log.scrollHeight - previousLogHeight.current;
        previousLogHeight.current = null;
      }
    }
  }, [messages, pendingText]);
  async function send() {
    if (busy || !text.trim()) return;
    const next: Message[] = [
      ...messages,
      { id: crypto.randomUUID(), role: "user", content: text.trim() },
    ];
    const requestId = retry.current?.text === text.trim() ? retry.current.id : crypto.randomUUID();
    retry.current = { id: requestId, text: text.trim() };
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
          conversation_id: conversation.current.id,
          version: conversation.current.version,
          request_id: requestId,
        }),
        signal: AbortSignal.timeout(65000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "답변을 받지 못했어요.");
      conversation.current.version = result.version;
      retry.current = null;
      void read("history")
        .then(setConversations)
        .catch(() => {});
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
            <button
              type="button"
              className="icon-button"
              title="대화 기록"
              aria-label="대화 기록"
              aria-expanded={historyOpen}
              disabled={busy}
              onClick={() => setHistoryOpen(!historyOpen)}
            >
              <History size={20} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="icon-button"
              title="AI 지침"
              aria-label="AI 지침"
              aria-expanded={promptOpen}
              disabled={busy}
              onClick={async () => {
                if (promptOpen) {
                  setPromptOpen(false);
                  return;
                }
                try {
                  setPromptInfo(await read("prompt"));
                  setPromptOpen(true);
                } catch {
                  setError("AI 지침을 불러오지 못했어요.");
                }
              }}
            >
              <FileText size={20} aria-hidden="true" />
            </button>
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
                conversation.current = { id: crypto.randomUUID(), version: 0 };
                retry.current = null;
                setOldestTurn(1);
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
        {historyOpen && (
          <section className="we2-history" aria-label="저장한 대화">
            <strong>내 대화</strong>
            <p className="settings-hint">최근 100개 · 본인만 조회</p>
            {conversations.length ? (
              conversations.map((item) => (
                <button
                  type="button"
                  className="we2-history-item"
                  key={item.id}
                  disabled={busy}
                  onClick={() => void openConversation(item.id)}
                >
                  <span>{item.title}</span>
                  <small>{new Date(item.updated_at).toLocaleDateString("ko-KR")}</small>
                </button>
              ))
            ) : (
              <p>저장한 대화가 없어요.</p>
            )}
          </section>
        )}
        {promptOpen && promptInfo && (
          <section className="we2-prompt" aria-label="현재 AI 지침">
            <strong>현재 시스템 지침</strong>
            <p className="settings-hint">
              {promptInfo.version} · {promptInfo.model}
              <br />
              temperature {promptInfo.temperature} · 최대 출력 {promptInfo.max_tokens} 토큰 · 최근{" "}
              {promptInfo.recent_messages}개 메시지 · 입력 {promptInfo.input_bytes}바이트
            </p>
            <pre>
              {promptInfo.system}
              {"\n오늘 한국 날짜: "}
              {promptInfo.today}
            </pre>
            <p className="settings-hint">
              현재 코스와 최근 대화를 함께 전달해요. 이전 기록에 남은 지침 버전은 당시 버전이며,
              이어 대화에는 위 지침을 사용해요.
            </p>
          </section>
        )}
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
          {oldestTurn > 1 && (
            <button
              type="button"
              className="text-button"
              disabled={busy}
              onClick={() => void openConversation(conversation.current.id, oldestTurn)}
            >
              이전 대화
            </button>
          )}
          {messages.length === 0 && !pending && !loadingHistory && (
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
          {(pending || loadingHistory) && (
            <>
              <LoaderCircle size={15} className="ai-spinner" aria-hidden="true" />
              {loadingHistory ? "대화 기록을 불러오고 있어요." : "다음 코스를 생각하고 있어요."}
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
            <span>Cloudflare에서 처리 · 대화는 본인만 조회</span>
            <details>
              <summary aria-label="이용 안내" title="이용 안내">
                <Info size={15} aria-hidden="true" />
              </summary>
              <p>
                대화와 제안은 내 기록에 저장돼요. 최근 대화와 현재 코스만 AI에 전달해요.
                계정·사진·개인 일정은 자동으로 보내지 않아요. 무료 제공량을 소진하면 요청이
                중단돼요. 남길 코스는 초안으로 저장해 주세요.
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
