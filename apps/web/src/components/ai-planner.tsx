"use client";

import {
  ArrowDown,
  Bookmark,
  CalendarDays,
  ChevronDown,
  History,
  LoaderCircle,
  MapPin,
  MessageSquarePlus,
  RotateCw,
  Send,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useTransition,
} from "react";
import { changePlan } from "@/app/actions/plans";
import { AiIntake, IntakeSummary } from "@/components/ai-intake";
import Link from "@/components/progress-link";
import { We2AiIcon } from "@/components/we2-ai-icon";
import { briefMessage, type IntakeContext, type PlanningBrief } from "@/lib/ai-intake";
import type { PlanContent } from "@/lib/plans";

type Conversation = { id: string; title: string; version: number; updated_at: string };
type Turn = {
  request_id: string;
  version: number;
  user_text: string;
  result: {
    reply: string;
    plan: PlanContent | null;
    checks?: string[];
    weather?: unknown[];
    context?: IntakeContext;
  };
  prompt_version: string;
};
type Message = { id: string; role: "user" | "assistant"; content: string; weatherSource?: boolean };
type PlaceOption = { source: "favorite" | "wish"; id: string; title: string; address: string };
type Candidate = {
  ref: string;
  source: "naver" | "selected" | "user";
  title: string;
  address: string;
  destination?: string;
};
type Retry = {
  id: string;
  text: string;
  signature: string;
  brief?: PlanningBrief;
  candidate?: Candidate;
};

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
      weatherSource: Boolean(turn.result.weather?.length),
    },
  ]);
}
function reveal(element: HTMLElement | null) {
  if (!element) return;
  element.focus({ preventScroll: true });
  element.scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "start",
  });
}
function ReadFailure({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="we2-read-failure">
      <p role="alert">{message}</p>
      <button className="text-button" type="button" onClick={retry}>
        <RotateCw size={15} aria-hidden="true" />
        다시 불러오기
      </button>
    </div>
  );
}
function AiDialog({
  id,
  title,
  children,
  onClose,
  returnFocus,
}: {
  id: string;
  title: string;
  children: ReactNode;
  onClose: () => void;
  returnFocus: HTMLElement | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const trigger = returnFocus;
    const previousOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      queueMicrotask(() => {
        if (trigger?.isConnected && !trigger.matches(":disabled"))
          trigger.focus({ preventScroll: true });
        else
          document
            .querySelector<HTMLTextAreaElement>("#ai-message")
            ?.focus({ preventScroll: true });
      });
    };
  }, [returnFocus]);
  return (
    <dialog
      ref={ref}
      id={id}
      className="we2-dialog"
      aria-labelledby={`${id}-title`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="we2-dialog-header">
        <h2 id={`${id}-title`}>{title}</h2>
        <button
          className="icon-button"
          type="button"
          aria-label={`${title} 닫기`}
          title="닫기"
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      {children}
    </dialog>
  );
}
function CandidateList({
  candidates,
  busy,
  select,
}: {
  candidates: Candidate[];
  busy: boolean;
  select: (candidate: Candidate) => void;
}) {
  return (
    <div className="we2-candidate-list">
      {candidates.map((candidate) => (
        <article key={candidate.ref}>
          <div>
            <strong>{candidate.title}</strong>
            {candidate.address && <p>{candidate.address}</p>}
          </div>
          <button
            type="button"
            className="text-button"
            disabled={busy}
            aria-label={`${candidate.title} 선택`}
            onClick={() => select(candidate)}
          >
            선택
          </button>
        </article>
      ))}
    </div>
  );
}
export function AiConnectionRetry() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <button
      type="button"
      className="text-button"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      <RotateCw size={16} className={pending ? "ai-spinner" : undefined} aria-hidden="true" />
      다시 연결
    </button>
  );
}

export function AiPlanner({ available, today }: { available: boolean; today: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [intakeOpen, setIntakeOpen] = useState(true);
  const [planningContext, setPlanningContext] = useState<IntakeContext | null>(null);
  const [text, setText] = useState("");
  const textRef = useRef("");
  // Page-instance memory only. Nothing is written to browser storage or sent until submit.
  const drafts = useRef(new Map<string, string>());
  const updateText = useCallback((value: string) => {
    textRef.current = value;
    setText(value);
  }, []);
  const [pendingText, setPendingText] = useState("");
  const chatRef = useRef<HTMLElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const previousLogHeight = useRef<number | null>(null);
  const focusRequest = useRef<"start" | "input" | "log" | null>(null);
  const proposalRef = useRef<HTMLElement>(null);
  const historyRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const restoreInputAfterSend = useRef(false);
  const dialogTrigger = useRef<HTMLButtonElement | null>(null);
  const [activityKeys, setActivityKeys] = useState<string[]>([]);
  const [proposal, setProposal] = useState<PlanContent | null>(null);
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [chatError, setChatError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState("");
  const saveIdentity = useRef({ id: crypto.randomUUID(), request: crypto.randomUUID() });
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const historyRetry = useRef<{ id?: string; before?: number }>({});
  const historySequence = useRef(0),
    conversationSequence = useRef(0),
    placeSequence = useRef(0);
  const mounted = useRef(true);
  const [oldestTurn, setOldestTurn] = useState(1);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [chosenPlaces, setChosenPlaces] = useState<
    { title: string; address: string; destination?: string }[]
  >([]);
  const [checks, setChecks] = useState<string[]>([]);
  const [placeOptions, setPlaceOptions] = useState<PlaceOption[]>([]);
  const [selectedPlaces, setSelectedPlaces] = useState<PlaceOption[]>([]);
  const [loadingPlaces, setLoadingPlaces] = useState(false);
  const [placesError, setPlacesError] = useState("");
  const [dialog, setDialog] = useState<"places" | "candidates" | null>(null);
  const [placeSource, setPlaceSource] = useState<"favorite" | "wish">("favorite");
  const [placeOffset, setPlaceOffset] = useState(0);
  const placeRetry = useRef({ source: "favorite" as "favorite" | "wish", offset: 0 });
  const [hasMorePlaces, setHasMorePlaces] = useState(false);
  const conversation = useRef({ id: crypto.randomUUID(), version: 0 });
  const newDraftId = useRef(conversation.current.id);
  const retry = useRef<Retry | null>(null);
  const busy = pending || saving || loadingHistory || loadingConversation;
  const rememberDraft = useCallback(() => {
    if (textRef.current) drafts.current.set(conversation.current.id, textRef.current);
    else drafts.current.delete(conversation.current.id);
    // The server exposes at most 100 records. Keep just one additional unsent conversation.
    while (drafts.current.size > 101) {
      const oldest = drafts.current.keys().next().value;
      if (oldest === undefined) break;
      drafts.current.delete(oldest);
    }
  }, []);
  const openConversation = useCallback(
    async (id: string, before?: number, explicit = true) => {
      const sequence = ++conversationSequence.current;
      const older = Boolean(before);
      if (!older) rememberDraft();
      setLoadingConversation(true);
      setHistoryError("");
      historyRetry.current = { id, before };
      try {
        const data = await read(
          "history",
          `&conversation_id=${id}${before ? `&before=${before}` : ""}`,
        );
        if (!mounted.current || sequence !== conversationSequence.current) return;
        if (!data) throw new Error("대화 기록을 찾지 못했어요.");
        const turns: Turn[] = data.turns;
        setOldestTurn(turns[0]?.version || 1);
        if (older) {
          previousLogHeight.current = logRef.current?.scrollHeight || 0;
          if (explicit) focusRequest.current = "log";
          setMessages((previous) => [...turnMessages(turns), ...previous]);
        } else {
          conversation.current = { id, version: data.version };
          retry.current = null;
          previousLogHeight.current = null;
          focusRequest.current = explicit ? "log" : null;
          setMessages(turnMessages(turns));
          setIntakeOpen(false);
          setPlanningContext(turns[turns.length - 1]?.result.context || null);
          const plan = data.proposal || null;
          setProposal(plan);
          setActivityKeys(plan?.activities.map(() => crypto.randomUUID()) || []);
          updateText(drafts.current.get(id) || "");
          setCandidates([]);
          setChosenPlaces([]);
          setSelectedPlaces([]);
          setChecks(turns[turns.length - 1]?.result.checks || []);
          setSaved("");
          setSaveError("");
          setChatError("");
          setDialog(null);
          saveIdentity.current = { id: crypto.randomUUID(), request: crypto.randomUUID() };
        }
      } catch (error) {
        if (mounted.current && sequence === conversationSequence.current) {
          setHistoryError(error instanceof Error ? error.message : "기록을 불러오지 못했어요.");
          setHistoryOpen(true);
        }
      } finally {
        if (mounted.current && sequence === conversationSequence.current)
          setLoadingConversation(false);
      }
    },
    [rememberDraft, updateText],
  );
  const loadHistory = useCallback(
    async (restore = false) => {
      const sequence = ++historySequence.current;
      setLoadingHistory(true);
      setHistoryError("");
      historyRetry.current = {};
      try {
        const items: Conversation[] = await read("history");
        if (!mounted.current || sequence !== historySequence.current) return;
        setConversations(items);
        if (restore && items[0]) await openConversation(items[0].id, undefined, false);
      } catch {
        if (mounted.current && sequence === historySequence.current) {
          setHistoryError("대화 기록을 불러오지 못했어요.");
          setHistoryOpen(true);
        }
      } finally {
        if (mounted.current && sequence === historySequence.current) setLoadingHistory(false);
      }
    },
    [openConversation],
  );
  useEffect(() => {
    mounted.current = true;
    void loadHistory(true);
    return () => {
      mounted.current = false;
      historySequence.current++;
      conversationSequence.current++;
      placeSequence.current++;
      drafts.current.clear();
      textRef.current = "";
    };
  }, [loadHistory]);
  useLayoutEffect(() => {
    const log = logRef.current;
    if (!log) return;
    log.scrollTop =
      previousLogHeight.current !== null
        ? log.scrollHeight - previousLogHeight.current
        : messages.length || pendingText
          ? log.scrollHeight
          : 0;
    previousLogHeight.current = null;
    if (focusRequest.current) {
      if (
        chatRef.current &&
        (chatRef.current.getBoundingClientRect().top < 0 ||
          chatRef.current.getBoundingClientRect().top > innerHeight / 2)
      )
        chatRef.current.scrollIntoView({ block: "start", behavior: "auto" });
      if (focusRequest.current === "start")
        chatRef.current
          ?.querySelector<HTMLElement>(".we2-intake h2")
          ?.focus({ preventScroll: true });
      else if (focusRequest.current === "input") inputRef.current?.focus({ preventScroll: true });
      else log.focus({ preventScroll: true });
      focusRequest.current = null;
    }
  }, [messages, pendingText]);
  useEffect(() => {
    if (!pending && restoreInputAfterSend.current) {
      restoreInputAfterSend.current = false;
      if (
        document.activeElement === document.body ||
        document.activeElement?.closest(".we2-composer, .we2-status, .we2-candidate-list")
      )
        inputRef.current?.focus({ preventScroll: true });
    }
  }, [pending]);
  async function loadPlaces(source: "favorite" | "wish", offset = 0) {
    const sequence = ++placeSequence.current;
    setLoadingPlaces(true);
    setPlacesError("");
    setPlaceSource(source);
    placeRetry.current = { source, offset };
    if (!offset) {
      setPlaceOptions([]);
      setHasMorePlaces(false);
    }
    try {
      const items: PlaceOption[] = await read("places", `&source=${source}&offset=${offset}`);
      if (!mounted.current || sequence !== placeSequence.current) return;
      setPlaceOffset(offset);
      setHasMorePlaces(items.length === 50);
      setPlaceOptions(offset ? (previous) => [...previous, ...items] : items);
    } catch (error) {
      if (mounted.current && sequence === placeSequence.current)
        setPlacesError(error instanceof Error ? error.message : "장소를 불러오지 못했어요.");
    } finally {
      if (mounted.current && sequence === placeSequence.current) setLoadingPlaces(false);
    }
  }
  async function send(
    messageOverride?: string,
    candidate?: Candidate,
    submittedBrief?: PlanningBrief,
  ) {
    const content = messageOverride ?? text.trim();
    if (busy || !available || !content) return;
    restoreInputAfterSend.current = true;
    const preserveInput = Boolean(candidate);
    const chosen = candidate
      ? [
          ...chosenPlaces.filter(
            (p) => p.title !== candidate.title || p.address !== candidate.address,
          ),
          {
            title: candidate.title,
            address: candidate.address,
            destination: candidate.destination,
          },
        ].slice(-8)
      : chosenPlaces;
    const next: Message[] = [...messages, { id: crypto.randomUUID(), role: "user", content }];
    const brief =
      submittedBrief || (retry.current?.text === content ? retry.current.brief : undefined);
    setChosenPlaces(chosen);
    setPending(true);
    setPendingText(content);
    setChatError("");
    if (!preserveInput) {
      updateText("");
      drafts.current.delete(conversation.current.id);
    }
    const history = next.slice(-11).map(({ role, content }) => ({ role, content }));
    while (
      history.length > 1 &&
      new TextEncoder().encode(JSON.stringify({ messages: history, proposal })).length > 18000
    )
      history.splice(0, 2);
    const payload = {
      messages: history,
      proposal,
      conversation_id: conversation.current.id,
      version: conversation.current.version,
      selected_places: selectedPlaces.map(({ source, id }) => ({ source, id })),
      chosen_places: chosen,
      ...(brief ? { brief } : {}),
    };
    const signature = JSON.stringify(payload);
    const requestId =
      retry.current?.signature === signature ? retry.current.id : crypto.randomUUID();
    retry.current = { id: requestId, text: content, signature, brief, candidate };
    try {
      const response = await fetch("/api/ai/planner", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, request_id: requestId }),
        signal: AbortSignal.timeout(110000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "답변을 받지 못했어요.");
      conversation.current.version = result.version;
      if (newDraftId.current === conversation.current.id) newDraftId.current = crypto.randomUUID();
      retry.current = null;
      setIntakeOpen(false);
      setPlanningContext(result.context || null);
      setConversations((saved) => {
        const id = conversation.current.id,
          previous = saved.find((item) => item.id === id);
        return [
          {
            id,
            title: previous?.title || Array.from(content).slice(0, 80).join(""),
            version: result.version,
            updated_at: new Date().toISOString(),
          },
          ...saved.filter((item) => item.id !== id),
        ].slice(0, 100);
      });
      setMessages([
        ...next,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.reply,
          weatherSource: Boolean(result.weather?.length),
        },
      ]);
      if (!preserveInput) updateText("");
      setCandidates(result.candidates || []);
      setChecks(result.checks || []);
      if (result.plan) {
        setProposal(result.plan);
        setActivityKeys(result.plan.activities.map(() => crypto.randomUUID()));
        setSaved("");
        setSaveError("");
        saveIdentity.current = { id: crypto.randomUUID(), request: crypto.randomUUID() };
      }
    } catch (error) {
      if (!preserveInput) updateText(content);
      setChatError(
        error instanceof Error ? error.message : "연결하지 못했어요. 다시 시도해 주세요.",
      );
    } finally {
      setPending(false);
      setPendingText("");
    }
  }
  function selectCandidate(candidate: Candidate) {
    setDialog(null);
    void send(`선택한 장소: ${candidate.title}. 정한 조건에 맞춰 코스에 반영해줘.`, candidate);
  }
  function startConversation() {
    rememberDraft();
    const id = newDraftId.current,
      draft = drafts.current.get(id) || "";
    conversation.current = { id, version: 0 };
    retry.current = null;
    previousLogHeight.current = null;
    focusRequest.current = draft ? "input" : "start";
    setOldestTurn(1);
    setMessages([]);
    setIntakeOpen(!draft);
    setPlanningContext(null);
    updateText(draft);
    setProposal(null);
    setSaved("");
    setChatError("");
    setSaveError("");
    setActivityKeys([]);
    setCandidates([]);
    setChosenPlaces([]);
    setSelectedPlaces([]);
    setChecks([]);
    setDialog(null);
  }
  async function save() {
    if (!proposal || busy || saved) return;
    setSaving(true);
    setSaveError("");
    try {
      const { id, request } = saveIdentity.current;
      const result = await changePlan(id, "save", proposal, 0, 0, request);
      if (result.error) throw new Error(result.error);
      setSaved(id);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "저장하지 못했어요.");
    } finally {
      setSaving(false);
    }
  }
  const totalCost =
    proposal?.activities.reduce((sum, activity) => sum + Math.max(0, activity.cost || 0), 0) || 0;
  const compactChecks = checks.length > 3 || checks.join("").length > 160;
  const checksList = (
    <ul className="we2-checks" aria-label="코스 확인 사항">
      {checks.map((check) => (
        <li key={check}>{check}</li>
      ))}
    </ul>
  );
  return (
    <div className="we2-ai">
      <section ref={chatRef} className="we2-chat" aria-label="위투 AI 대화">
        <header className="we2-chat-header">
          <div>
            <We2AiIcon size={28} />
            <strong>위투 AI</strong>
          </div>
          <div className="we2-chat-tools">
            <button
              type="button"
              className="icon-button"
              title="대화 기록"
              aria-label="대화 기록"
              disabled={busy}
              onClick={() => {
                setHistoryOpen(true);
                // Scroll after the expanded list has its final height.
                requestAnimationFrame(() => reveal(historyRef.current));
              }}
            >
              <History size={20} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="icon-button"
              title="새 대화"
              aria-label="새 대화"
              disabled={busy || conversation.current.version === 0}
              onClick={startConversation}
            >
              <MessageSquarePlus size={20} aria-hidden="true" />
            </button>
          </div>
        </header>
        {!available && (
          <div className="we2-connection">
            <p role="status">연결을 준비 중이에요.</p>
            <AiConnectionRetry />
          </div>
        )}
        {planningContext && messages.length > 0 && <IntakeSummary context={planningContext} />}
        <div
          ref={logRef}
          tabIndex={-1}
          className="we2-messages"
          role="log"
          aria-label="AI 대화"
          aria-busy={pending || loadingConversation}
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
          {messages.length === 0 && !loadingHistory && !loadingConversation && (
            <div hidden={!intakeOpen}>
              <AiIntake
                key={conversation.current.id}
                disabled={busy || !available}
                selectedPlaces={selectedPlaces.length}
                onSubmit={(brief) => void send(briefMessage(brief), undefined, brief)}
                onFreeChat={() => {
                  setIntakeOpen(false);
                  queueMicrotask(() => inputRef.current?.focus({ preventScroll: true }));
                }}
              />
            </div>
          )}
          {messages.length === 0 &&
            !intakeOpen &&
            !pending &&
            !loadingHistory &&
            !loadingConversation && (
              <div className="we2-welcome">
                <span className="we2-welcome-icon">
                  <We2AiIcon size={72} />
                </span>
                <h2>우리, 어디로 갈까요?</h2>
                <p>날짜와 하고 싶은 일을 알려주세요.</p>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    setIntakeOpen(true);
                    queueMicrotask(() =>
                      chatRef.current
                        ?.querySelector<HTMLElement>(".we2-intake h2")
                        ?.focus({ preventScroll: true }),
                    );
                  }}
                >
                  조건 입력
                </button>
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
                        updateText(prompt);
                        inputRef.current?.focus({ preventScroll: true });
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
                  <We2AiIcon size={20} />
                  위투 AI
                </span>
              )}
              <p>{message.content}</p>
              {message.weatherSource && (
                <small className="we2-weather-source">
                  도시 기준 예보 ·{" "}
                  <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">
                    Open-Meteo
                  </a>
                  {" / "}
                  <a href="https://www.geonames.org/" target="_blank" rel="noopener noreferrer">
                    GeoNames
                  </a>
                </small>
              )}
            </div>
          ))}
          {pendingText && (
            <div className="we2-message we2-user">
              <p>{pendingText}</p>
            </div>
          )}
        </div>
        <div className={`we2-status${chatError ? " has-error" : ""}`}>
          {chatError ? (
            <>
              <p role="alert">{chatError}</p>
              <button
                type="button"
                className="icon-button"
                aria-label="메시지 다시 전송"
                title="다시 전송"
                disabled={busy || !available || !retry.current}
                onClick={() => {
                  const item = retry.current;
                  inputRef.current?.focus({ preventScroll: true });
                  if (item)
                    void (item.candidate || text.trim() === item.text
                      ? send(item.text, item.candidate, item.brief)
                      : send());
                }}
              >
                <RotateCw size={17} aria-hidden="true" />
              </button>
            </>
          ) : (
            <span role="status">
              {(pending || loadingHistory || loadingConversation) && (
                <>
                  <LoaderCircle size={15} className="ai-spinner" aria-hidden="true" />
                  {loadingHistory || loadingConversation
                    ? "대화 기록을 불러오고 있어요."
                    : "장소와 코스를 살펴보고 있어요."}
                </>
              )}
            </span>
          )}
        </div>
        <div className="we2-input-area">
          <div className="we2-attachments">
            <button
              type="button"
              className="text-button"
              aria-label={`저장한 장소${selectedPlaces.length ? ` · ${selectedPlaces.length}` : ""}`}
              disabled={busy}
              aria-haspopup="dialog"
              aria-expanded={dialog === "places"}
              aria-controls="we2-place-picker"
              onClick={(event) => {
                dialogTrigger.current = event.currentTarget;
                setDialog("places");
                void loadPlaces(placeSource);
              }}
            >
              <Bookmark size={16} aria-hidden="true" />
              <span>저장 장소</span>
              {selectedPlaces.length > 0 && <small>{selectedPlaces.length}</small>}
            </button>
            {candidates.length > 0 && (
              <button
                type="button"
                className="text-button"
                aria-haspopup="dialog"
                aria-label={`장소 후보 ${candidates.length}개 보기`}
                disabled={busy}
                onClick={(event) => {
                  dialogTrigger.current = event.currentTarget;
                  setDialog("candidates");
                }}
              >
                <MapPin size={16} aria-hidden="true" />
                <span>후보 {candidates.length}</span>
              </button>
            )}
            {proposal && (
              <button
                type="button"
                className="icon-button we2-course-jump"
                title="코스 보기"
                aria-label="코스 보기"
                onClick={() => reveal(proposalRef.current)}
              >
                <ArrowDown size={19} aria-hidden="true" />
              </button>
            )}
          </div>
          {(!intakeOpen || messages.length > 0) && (
            <form
              className="we2-composer"
              onSubmit={(event) => {
                event.preventDefault();
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
                onChange={(event) => updateText(event.target.value)}
                maxLength={2000}
                rows={2}
                readOnly={busy}
                disabled={!available}
                aria-busy={pending}
                placeholder="어떤 데이트를 하고 싶어요?"
                enterKeyHint="send"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
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
          )}
        </div>
      </section>
      <div className="we2-sidebar">
        {candidates.length > 0 && (
          <section className="we2-candidates we2-candidates-inline" aria-label="장소 후보">
            <header className="we2-proposal-header">
              <span>
                <MapPin size={17} aria-hidden="true" />
                장소 후보 · {candidates.length}
              </span>
            </header>
            <CandidateList candidates={candidates} busy={busy} select={selectCandidate} />
          </section>
        )}
        <section
          ref={proposalRef}
          tabIndex={-1}
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
                {((proposal.budget || 0) > 0 || totalCost > 0) && (
                  <div className="we2-costs">
                    {(proposal.budget || 0) > 0 && (
                      <span>예산 {proposal.budget?.toLocaleString("ko-KR")}원</span>
                    )}
                    {totalCost > 0 && (
                      <span>입력된 예상 비용 {totalCost.toLocaleString("ko-KR")}원</span>
                    )}
                  </div>
                )}
                <ol className="we2-itinerary">
                  {proposal.activities.map((activity, index) => (
                    <li key={activityKeys[index]}>
                      <span className="we2-stop-number">{index + 1}</span>
                      <div>
                        <small>{activity.time || "시간 미정"}</small>
                        <strong>{activity.title}</strong>
                        {activity.place && <p>{activity.place}</p>}
                        {(activity.cost || 0) > 0 && (
                          <p className="we2-activity-cost">
                            예상 {activity.cost?.toLocaleString("ko-KR")}원
                          </p>
                        )}
                        {activity.note &&
                          (activity.note.length > 80 || activity.note.includes("\n") ? (
                            <details className="we2-stop-notes">
                              <summary>메모</summary>
                              <p>{activity.note}</p>
                            </details>
                          ) : (
                            <p className="settings-hint">{activity.note}</p>
                          ))}
                      </div>
                    </li>
                  ))}
                </ol>
                {proposal.preparation.length > 0 && (
                  <div className="we2-preparation">
                    <strong>준비물</strong>
                    {proposal.preparation.join(", ").length > 160 ? (
                      <details className="we2-stop-notes">
                        <summary>준비물 보기</summary>
                        <p>{proposal.preparation.join(", ")}</p>
                      </details>
                    ) : (
                      <p>{proposal.preparation.join(", ")}</p>
                    )}
                  </div>
                )}
              </div>
              <footer className="we2-proposal-footer">
                {checks.length > 0 &&
                  (compactChecks ? (
                    <details className="we2-stop-notes">
                      <summary>확인할 내용 · {checks.length}</summary>
                      {checksList}
                    </details>
                  ) : (
                    checksList
                  ))}
                <div className="we2-save-feedback">
                  <p role={saveError ? "alert" : "status"}>
                    {saveError ||
                      (saving
                        ? "초안을 저장하고 있어요."
                        : saved
                          ? "초안을 저장했어요."
                          : "저장 후 장소를 확인하고 확정해 주세요.")}
                  </p>
                </div>
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
                    {saving ? "저장 중…" : saveError ? "다시 저장" : "초안 저장"}
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
        <section ref={historyRef} tabIndex={-1} className="we2-history" aria-label="저장한 대화">
          <header className="we2-history-header">
            <span>
              <History size={17} aria-hidden="true" />
              대화 내역
            </span>
            <button
              type="button"
              className="icon-button"
              aria-label={historyOpen ? "대화 내역 접기" : "대화 내역 펼치기"}
              aria-expanded={historyOpen}
              aria-controls="we2-history-list"
              onClick={() => setHistoryOpen(!historyOpen)}
            >
              <ChevronDown size={18} aria-hidden="true" />
            </button>
          </header>
          <div
            id="we2-history-list"
            className="we2-history-list"
            hidden={!historyOpen}
            aria-busy={loadingHistory || loadingConversation}
          >
            {historyError ? (
              <ReadFailure
                message={historyError}
                retry={() => {
                  const item = historyRetry.current;
                  if (item.id) void openConversation(item.id, item.before);
                  else void loadHistory();
                }}
              />
            ) : (
              <>
                {(loadingHistory || loadingConversation) && (
                  <p role="status" className="we2-read-status we2-history-loading">
                    <LoaderCircle size={16} className="ai-spinner" aria-hidden="true" />
                    기록을 불러오고 있어요.
                  </p>
                )}
                {conversations.length
                  ? conversations.map((item) => (
                      <button
                        type="button"
                        className="we2-history-item"
                        key={item.id}
                        disabled={busy}
                        aria-current={conversation.current.id === item.id ? "true" : undefined}
                        onClick={() => void openConversation(item.id)}
                      >
                        <span title={item.title}>{item.title}</span>
                        <small>{new Date(item.updated_at).toLocaleDateString("ko-KR")}</small>
                      </button>
                    ))
                  : !loadingHistory &&
                    !loadingConversation && (
                      <p className="we2-history-empty">저장한 대화가 없어요.</p>
                    )}
              </>
            )}
          </div>
        </section>
      </div>
      {dialog === "places" && (
        <AiDialog
          id="we2-place-picker"
          title="저장한 장소"
          onClose={() => setDialog(null)}
          returnFocus={dialogTrigger.current}
        >
          <div className="we2-dialog-body">
            <div className="we2-place-tabs">
              {(["favorite", "wish"] as const).map((source) => (
                <button
                  key={source}
                  type="button"
                  className="text-button"
                  aria-pressed={placeSource === source}
                  disabled={loadingPlaces || busy}
                  onClick={() => void loadPlaces(source)}
                >
                  {source === "favorite" ? "자주 가는 곳" : "위시"}
                </button>
              ))}
            </div>
            <p className="settings-hint">선택한 장소만 메시지와 함께 AI에 전달해요. 최대 8개.</p>
            {selectedPlaces.length > 0 && (
              <div className="we2-selected-places">
                {selectedPlaces.map((item) => (
                  <button
                    key={`${item.source}-${item.id}`}
                    type="button"
                    className="text-button"
                    disabled={busy}
                    aria-label={`${item.title} 선택 해제`}
                    onClick={() =>
                      setSelectedPlaces((previous) =>
                        previous.filter(
                          (place) => place.source !== item.source || place.id !== item.id,
                        ),
                      )
                    }
                  >
                    <span>{item.title}</span>
                    <X size={15} aria-hidden="true" />
                  </button>
                ))}
              </div>
            )}
            <div className="we2-place-options" aria-busy={loadingPlaces}>
              {placeOptions.map((item) => {
                const checked = selectedPlaces.some(
                  (place) => place.source === item.source && place.id === item.id,
                );
                return (
                  <label key={`${item.source}-${item.id}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={busy || loadingPlaces || (!checked && selectedPlaces.length >= 8)}
                      onChange={() =>
                        setSelectedPlaces((previous) =>
                          checked
                            ? previous.filter(
                                (place) => place.source !== item.source || place.id !== item.id,
                              )
                            : [...previous, item],
                        )
                      }
                    />
                    <span>
                      {item.title}
                      {item.address && <small>{item.address}</small>}
                    </span>
                  </label>
                );
              })}
              {placesError && (
                <ReadFailure
                  message={placesError}
                  retry={() =>
                    void loadPlaces(placeRetry.current.source, placeRetry.current.offset)
                  }
                />
              )}
              {loadingPlaces && (
                <p role="status" className="we2-read-status">
                  <LoaderCircle size={16} className="ai-spinner" aria-hidden="true" />
                  장소를 불러오고 있어요.
                </p>
              )}
              {!loadingPlaces && !placesError && placeOptions.length === 0 && (
                <p>저장한 장소가 없어요.</p>
              )}
              {!loadingPlaces && !placesError && hasMorePlaces && (
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => void loadPlaces(placeSource, placeOffset + 50)}
                >
                  더 보기
                </button>
              )}
            </div>
          </div>
          <footer className="we2-dialog-footer">
            <span>{selectedPlaces.length} / 8개 선택</span>
            <button type="button" className="primary-button" onClick={() => setDialog(null)}>
              완료
            </button>
          </footer>
        </AiDialog>
      )}
      {dialog === "candidates" && (
        <AiDialog
          id="we2-candidate-picker"
          title="장소 후보"
          onClose={() => setDialog(null)}
          returnFocus={dialogTrigger.current}
        >
          <div className="we2-dialog-body">
            <CandidateList candidates={candidates} busy={busy} select={selectCandidate} />
          </div>
        </AiDialog>
      )}
    </div>
  );
}
