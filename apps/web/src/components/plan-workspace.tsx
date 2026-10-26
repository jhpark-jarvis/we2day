"use client";

import { Archive, ArchiveRestore, ArrowDown, ArrowUp, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, useTransition } from "react";
import { changePlan, deletePlanDraft } from "@/app/actions/plans";
import { NaverAppHandoff } from "@/components/naver-app-handoff";
import { PageHeading } from "@/components/page-heading";
import { PlaceSearch } from "@/components/place-search";
import { PlanChecks } from "@/components/plan-checks";
import Link from "@/components/progress-link";
import { We2AiIcon } from "@/components/we2-ai-icon";
import { ArchiveToggle, RefreshButton } from "@/components/workspace-controls";
import { useItemHistory } from "@/lib/page-history";
import {
  type Activity,
  type DatePlan,
  type PlanAction,
  type PlanContent,
  type PlanSummary,
  planStatus,
  summarizePlan,
  summaryLabels,
} from "@/lib/plans";

export function PlanWorkspace({
  initialPlans,
  initialError,
  initialListLoaded = true,
  today,
  initialContent = null,
  initialSelected = null,
  site = "",
}: {
  initialPlans: PlanSummary[];
  initialListLoaded?: boolean;
  initialError: string;
  today: string;
  initialContent?: PlanContent | null;
  initialSelected?: DatePlan | null;
  site?: string;
}) {
  const [items, setItems] = useState(initialPlans);
  const [listLoaded, setListLoaded] = useState(initialListLoaded);
  const [error, setError] = useState(initialError);
  const [archived, setArchived] = useState(false);
  const [more, setMore] = useState(initialPlans.length === 50);
  const [detailCache, setDetailCache] = useState<DatePlan | null>(initialSelected);
  const [initialNewId] = useState(() => (initialContent ? crypto.randomUUID() : ""));
  const navigation = useItemHistory(
    "plans",
    detailCache ? [detailCache] : [],
    "/api/plans",
    initialSelected?.id || "",
    initialNewId,
  );
  const selected = navigation.selected;
  const newId = !selected ? navigation.id : "";
  const [seed, setSeed] = useState(initialContent);
  const [notice, setNotice] = useState("");
  const [editorEpoch, setEditorEpoch] = useState(0);
  const [savedReview, setSavedReview] = useState("");
  const [pending, startTransition] = useTransition();
  const [sort, setSort] = useState("date_desc");
  function load(includeArchived: boolean, offset = 0, ordering = sort) {
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/plans?archived=${includeArchived}&offset=${offset}&summary=true&sort=${ordering}`,
          {
            cache: "no-store",
          },
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        setItems((current) =>
          offset
            ? [...current, ...data].filter(
                (item, index, array) => array.findIndex((other) => other.id === item.id) === index,
              )
            : data,
        );
        setArchived(includeArchived);
        setSort(ordering);
        setListLoaded(true);
        setMore(data.length === 50);
        setError("");
      } catch {
        setError("플랜을 불러오지 못했어요. 다시 시도해 주세요.");
      }
    });
  }
  function openPlan(id: string) {
    startTransition(async () => {
      try {
        const response = await fetch(`/api/plans?id=${id}`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        setDetailCache(data);
        navigation.open(data.id);
        setError("");
      } catch {
        setError("플랜을 불러오지 못했어요. 다시 선택해 주세요.");
      }
    });
  }
  function removeOrArchive(plan: PlanSummary) {
    startTransition(async () => {
      try {
        const response = await fetch(`/api/plans?id=${plan.id}`, { cache: "no-store" });
        const current: DatePlan = await response.json();
        if (!response.ok) throw new Error("최신 플랜을 불러오지 못했어요.");
        const draft = plan.status === "draft";
        if (draft && (current.published_content || current.published_revision !== 0))
          throw new Error("플랜이 확정됐어요. 목록을 새로고침해 주세요.");
        if (draft) {
          if (
            !window.confirm(
              `‘${current.content.title}’ 초안을 영구 삭제할까요? 두 사람의 목록에서 삭제되며 복구할 수 없어요.`,
            )
          )
            return;
          const result = await deletePlanDraft(current.id, current.version);
          if (result.error) throw new Error(result.error);
          setNotice("초안을 삭제했어요.");
        } else {
          const action = current.archived ? "restore" : "archive";
          const result = await changePlan(
            current.id,
            action,
            null,
            current.version,
            current.appointment?.version || 0,
            crypto.randomUUID(),
          );
          if (result.error) throw new Error(result.error);
          setNotice(
            action === "archive"
              ? "플랜을 보관했어요. 기존 달력 약속과 기록은 유지돼요."
              : "플랜을 복원했어요.",
          );
        }
        setItems((items) => items.filter((item) => item.id !== current.id));
        setError("");
        load(archived);
      } catch (error) {
        setError(error instanceof Error ? error.message : "처리하지 못했어요. 새로고침해 주세요.");
      }
    });
  }
  const orderedItems = [...items].sort((a, b) => {
    if (sort === "updated_desc" || sort === "title_asc") return 0;
    const compared = a.date.localeCompare(b.date);
    return (sort === "date_desc" ? -compared : compared) || a.id.localeCompare(b.id);
  });
  if (selected || newId)
    return (
      <PlanEditor
        key={`${selected?.id || newId}:${selected?.version || 0}:${editorEpoch}`}
        id={selected?.id || newId}
        plan={selected}
        showSavedReview={savedReview === `${selected?.id}:${selected?.version}`}
        today={today}
        seed={seed}
        site={site}
        onClone={(content) => {
          setDetailCache(null);
          setSeed({ ...content, title: `${content.title.slice(0, 94)} · 복사`, date: today });
          navigation.open(crypto.randomUUID(), true);
        }}
        onSaved={(plan, action) => {
          setSavedReview(action === "save" ? `${plan.id}:${plan.version}` : "");
          setItems((current) =>
            [summarizePlan(plan), ...current.filter((item) => item.id !== plan.id)].filter(
              (item) => item.archived === archived,
            ),
          );
          if (action === "archive" || action === "restore") {
            setDetailCache(null);
            navigation.close();
            // Direct editor entry intentionally skipped the list; load it on return.
            if (!listLoaded) load(archived);
            setNotice(
              action === "archive"
                ? "플랜을 보관했어요. 기존 달력 약속과 만남 기록은 남아 있어요."
                : "플랜을 복원했어요.",
            );
          } else {
            setDetailCache(plan);
            navigation.select(plan.id);
            setNotice("");
            load(archived);
          }
        }}
        onReload={async () => {
          const response = await fetch(`/api/plans?id=${selected?.id || newId}`, {
            cache: "no-store",
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error);
          setDetailCache(data);
          navigation.select(data.id);
          setEditorEpoch((value) => value + 1);
        }}
      />
    );
  return (
    <section className="plan-workspace">
      <PageHeading>
        <div>
          <p className="eyebrow">OUR DATE PLANS</p>
          <h1>데이트 플랜</h1>
          <p className="muted">함께 고르고, 순서대로 준비해요.</p>
        </div>
      </PageHeading>
      <div className="calendar-toolbar">
        <Link href="/plans/ai" className="text-button">
          <We2AiIcon size={24} />
          위투 AI
        </Link>
        <button
          type="button"
          className="primary-button"
          disabled={pending}
          onClick={() => {
            setSeed(null);
            navigation.open(crypto.randomUUID(), true);
          }}
        >
          플랜 만들기
        </button>
        <ArchiveToggle label="플랜 구분" archived={archived} pending={pending} onChange={load} />
        <RefreshButton label="플랜 새로고침" pending={pending} onClick={() => load(archived)} />
        <label className="plan-sort">
          <span className="sr-only">플랜 정렬</span>
          <select
            aria-label="플랜 정렬"
            value={sort}
            disabled={pending}
            onChange={(event) => load(archived, 0, event.target.value)}
          >
            <option value="date_desc">날짜 최신순</option>
            <option value="date_asc">날짜 빠른순</option>
            <option value="updated_desc">최근 수정순</option>
            <option value="title_asc">이름순</option>
          </select>
        </label>
      </div>
      <p className="settings-hint">초안은 달력에 표시되지 않아요. 확정하면 약속 하나로 연결돼요.</p>
      {(error || navigation.error) && (
        <p role="alert" className="error-message">
          {error || navigation.error}
        </p>
      )}
      {notice && (
        <p role="status" className="settings-hint">
          {notice}
        </p>
      )}
      <div className="plan-list">
        {orderedItems.map((plan) => (
          <div className="plan-card-shell" key={plan.id}>
            <button
              type="button"
              className="plan-card"
              disabled={pending}
              onClick={() => openPlan(plan.id)}
            >
              <small>
                {plan.date} · {summaryLabels[plan.status]}
              </small>
              <strong>{plan.title}</strong>
              <span>
                {plan.activity_count}개 활동 · {plan.transport || "교통수단 미정"}
              </span>
              <span className="card-action-hint" aria-hidden="true">
                플랜 열기 ↗
              </span>
            </button>
            <button
              type="button"
              className="icon-button plan-card-control"
              disabled={pending}
              aria-label={`${plan.title} ${plan.status === "draft" ? "초안 삭제" : plan.archived ? "복원" : "보관"}`}
              title={plan.status === "draft" ? "초안 삭제" : plan.archived ? "복원" : "보관"}
              onClick={() => removeOrArchive(plan)}
            >
              {plan.status === "draft" ? (
                <Trash2 size={18} aria-hidden="true" />
              ) : plan.archived ? (
                <ArchiveRestore size={18} aria-hidden="true" />
              ) : (
                <Archive size={18} aria-hidden="true" />
              )}
            </button>
          </div>
        ))}
      </div>
      {!items.length && !error && !pending && (
        <p className="empty-state">
          {archived ? "보관한 플랜이 없어요." : "첫 데이트 플랜을 함께 만들어 보세요."}
        </p>
      )}
      {more && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() => load(archived, items.length)}
        >
          플랜 더 보기
        </button>
      )}
    </section>
  );
}

function PlanEditor({
  id,
  plan,
  showSavedReview,
  today,
  seed,
  site,
  onClone,
  onSaved,
  onReload,
}: {
  id: string;
  plan: DatePlan | null;
  showSavedReview: boolean;
  today: string;
  seed: PlanContent | null;
  site: string;
  onClone: (content: PlanContent) => void;
  onSaved: (plan: DatePlan, action: PlanAction) => void;
  onReload: () => Promise<void>;
}) {
  const [content, setContent] = useState<PlanContent>(
    plan?.content ||
      seed || {
        title: "",
        date: today,
        budget: null,
        transport: "",
        activities: [],
        preparation: [],
      },
  );
  const activityKeys = useRef(
    (plan?.content.activities || seed?.activities || []).map(() => crypto.randomUUID()),
  );
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const [preparation, setPreparation] = useState(
    (plan?.content.preparation || seed?.preparation || []).join("\n"),
  );
  const [review, setReview] = useState(
    showSavedReview ||
      Boolean(plan && (!plan.published_content || planStatus(plan) === "변경안 · 다시 확정 필요")),
  );
  const reviewPanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (showSavedReview) reviewPanel.current?.scrollIntoView({ block: "start" });
  }, [showSavedReview]);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, startTransition] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  const draft = {
    ...content,
    preparation: preparation
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean),
  };
  const dirty = !plan || JSON.stringify(draft) !== JSON.stringify(plan.content);
  function mutate(action: PlanAction) {
    const body = action === "save" ? draft : null;
    const signature = JSON.stringify([
      action,
      body,
      plan?.version || 0,
      plan?.appointment?.version || 0,
    ]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    const requestId = request.current.id;
    setError("");
    startTransition(async () => {
      const result = await changePlan(
        id,
        action,
        body,
        plan?.version || 0,
        plan?.appointment?.version || 0,
        requestId,
      );
      if (result.error) {
        setConflict(result.status === 409);
        setError(
          result.status === 409
            ? "플랜 또는 연결된 약속이 바뀌었어요. 작성 내용을 확인하고 최신 내용을 불러와 주세요."
            : result.error,
        );
      } else if (result.data) onSaved(result.data, action);
    });
  }
  function activity(index: number, values: Partial<Activity>) {
    setContent((current) => ({
      ...current,
      activities: current.activities.map((item, i) =>
        i === index ? { ...item, ...values } : item,
      ),
    }));
    setReview(false);
  }
  function move(index: number, direction: number) {
    [activityKeys.current[index], activityKeys.current[index + direction]] = [
      activityKeys.current[index + direction],
      activityKeys.current[index],
    ];
    setContent((current) => {
      const activities = [...current.activities];
      [activities[index], activities[index + direction]] = [
        activities[index + direction],
        activities[index],
      ];
      return { ...current, activities };
    });
    setReview(false);
  }
  return (
    <section className="plan-editor">
      <PageHeading>
        <div>
          <p className="eyebrow">{plan ? planStatus(plan) : "NEW PLAN"}</p>
          <h1>{plan?.content.title || "새 데이트 플랜"}</h1>
        </div>
      </PageHeading>
      {plan?.published_content && (
        <div className="calendar-toolbar">
          <Link className="text-button" href={`/today?date=${plan.published_content.date}`}>
            데이트 코스
          </Link>
          <Link className="text-button" href={`/plans/${plan.id}/report`}>
            회고
          </Link>
        </div>
      )}
      {plan && (
        <button
          type="button"
          className="text-button"
          disabled={pending || dirty}
          onClick={() => onClone(plan.content)}
        >
          저장한 내용으로 새 플랜 복제
        </button>
      )}
      {plan?.archived ? (
        <>
          <p className="note-panel">
            보관한 플랜이에요. 복원하면 함께 수정할 수 있어요. 기존 달력 약속은 유지돼요.
          </p>
          <button
            type="button"
            className="primary-button"
            disabled={pending}
            onClick={() => mutate("restore")}
          >
            플랜 복원
          </button>
        </>
      ) : (
        <form
          onInvalidCapture={(event) => {
            let parent: HTMLElement | null =
              event.target instanceof HTMLElement ? event.target.parentElement : null;
            while (parent) {
              if (parent instanceof HTMLDetailsElement) parent.open = true;
              parent = parent.parentElement;
            }
          }}
          onSubmit={(event) => {
            event.preventDefault();
            mutate("save");
          }}
        >
          <fieldset className="meeting-fields" disabled={!ready || pending || conflict}>
            <div className="auth-field">
              <label htmlFor="plan-title">플랜 이름</label>
              <input
                id="plan-title"
                value={content.title}
                required
                maxLength={100}
                onChange={(event) => {
                  setContent({ ...content, title: event.target.value });
                  setReview(false);
                }}
              />
            </div>
            <div className="plan-basics">
              <div className="auth-field">
                <label htmlFor="plan-date">플랜 날짜</label>
                <input
                  id="plan-date"
                  type="date"
                  min="2000-01-01"
                  max="2100-12-31"
                  required
                  value={content.date}
                  onChange={(event) => {
                    setContent({ ...content, date: event.target.value });
                    setReview(false);
                  }}
                />
              </div>
              <details className="optional-fields">
                <summary>예산 (선택)</summary>
                <div className="auth-field">
                  <label htmlFor="plan-budget">전체 예산 (원, 선택)</label>
                  <input
                    id="plan-budget"
                    type="number"
                    min={0}
                    max={1000000000}
                    step={1}
                    value={content.budget ?? ""}
                    onChange={(event) =>
                      setContent({
                        ...content,
                        budget: event.target.value === "" ? null : Number(event.target.value),
                      })
                    }
                  />
                </div>
              </details>
            </div>
            <details className="optional-fields">
              <summary>교통수단 (선택)</summary>
              <div className="auth-field">
                <label htmlFor="plan-transport">교통수단 (선택)</label>
                <input
                  id="plan-transport"
                  maxLength={40}
                  value={content.transport}
                  placeholder="예: 자동차, 대중교통, 도보"
                  onChange={(event) => setContent({ ...content, transport: event.target.value })}
                />
              </div>
            </details>
            <p className="status-chip" role="status">
              {dirty
                ? "작성 중 · 저장 필요"
                : plan?.published_content &&
                    JSON.stringify(plan.content) !== JSON.stringify(plan.published_content)
                  ? "저장됨 · 코스 반영 필요"
                  : "저장 후 확정하면 코스에 반영돼요"}
            </p>
            <h2>활동 순서</h2>
            <p className="settings-hint">
              방문할 장소명이나 주소를 순서대로 적어 주세요. 데이트 코스에서 네이버 지도 앱으로 바로
              열 수 있어요. 첫 활동의 시간·장소가 달력 약속에 반영돼요.
            </p>
            {content.activities.map((item, index) => (
              <details
                key={activityKeys.current[index]}
                className="activity-editor-disclosure"
                open={index === 0 || !plan || index >= plan.content.activities.length}
              >
                <summary>
                  활동 {index + 1} · {item.time || "시간 미정"} · {item.title || "이름 입력"}
                  {item.place ? ` · ${item.place}` : ""}
                </summary>
                <fieldset className="plan-activity">
                  <legend>활동 {index + 1}</legend>
                  <div className="auth-field">
                    <label htmlFor={`activity-${index}-title`}>활동 {index + 1} 이름</label>
                    <input
                      id={`activity-${index}-title`}
                      value={item.title}
                      required
                      maxLength={100}
                      onChange={(event) => activity(index, { title: event.target.value })}
                    />
                  </div>
                  <div className="plan-basics">
                    <div className="auth-field">
                      <label htmlFor={`activity-${index}-time`}>활동 {index + 1} 시간</label>
                      <input
                        id={`activity-${index}-time`}
                        type="time"
                        value={item.time || ""}
                        onChange={(event) => activity(index, { time: event.target.value || null })}
                      />
                    </div>
                    <details className="optional-fields">
                      <summary>비용 (선택)</summary>
                      <div className="auth-field">
                        <label htmlFor={`activity-${index}-cost`}>
                          활동 {index + 1} 예상 비용 (원, 선택)
                        </label>
                        <input
                          id={`activity-${index}-cost`}
                          type="number"
                          min={0}
                          max={1000000000}
                          step={1}
                          value={item.cost ?? ""}
                          onChange={(event) =>
                            activity(index, {
                              cost: event.target.value === "" ? null : Number(event.target.value),
                            })
                          }
                        />
                      </div>
                    </details>
                  </div>
                  <div className="auth-field">
                    <label htmlFor={`activity-${index}-place`}>활동 {index + 1} 장소</label>
                    <input
                      id={`activity-${index}-place`}
                      value={item.place}
                      maxLength={200}
                      placeholder="장소명 또는 주소"
                      onChange={(event) => activity(index, { place: event.target.value })}
                    />
                  </div>
                  <PlaceSearch
                    initialQuery={item.place}
                    label={`활동 ${index + 1} 장소 검색`}
                    onSelect={(place) => {
                      activity(index, { place });
                      document.getElementById(`activity-${index}-place`)?.focus();
                    }}
                  />
                  <div className="map-share-input">
                    <NaverAppHandoff place={item.place} site={site} compact />
                    <div className="auth-field">
                      <label htmlFor={`activity-${index}-map-url`}>네이버 지도 공유 링크</label>
                      <input
                        id={`activity-${index}-map-url`}
                        type="url"
                        inputMode="url"
                        value={item.map_url || ""}
                        maxLength={97}
                        pattern={"https://naver[.]me/[A-Za-z0-9_\\-]{1,80}"}
                        placeholder="https://naver.me/…"
                        onChange={(event) =>
                          activity(index, { map_url: event.target.value.trim() })
                        }
                      />
                    </div>
                  </div>
                  <div className="auth-field">
                    <div className="activity-note-heading">
                      <label htmlFor={`activity-${index}-note`}>활동 {index + 1} 메모</label>
                      <fieldset
                        className="activity-actions"
                        aria-label={`활동 ${index + 1} 순서와 삭제`}
                      >
                        <button
                          type="button"
                          className="icon-button"
                          disabled={index === 0}
                          onClick={() => move(index, -1)}
                          aria-label={`활동 ${index + 1} 위로`}
                          title="위로"
                        >
                          <ArrowUp size={18} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="icon-button"
                          disabled={index === content.activities.length - 1}
                          onClick={() => move(index, 1)}
                          aria-label={`활동 ${index + 1} 아래로`}
                          title="아래로"
                        >
                          <ArrowDown size={18} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`활동 ${index + 1} 빼기`}
                          title="활동 빼기"
                          onClick={() => {
                            activityKeys.current.splice(index, 1);
                            setContent({
                              ...content,
                              activities: content.activities.filter((_, i) => i !== index),
                            });
                            setReview(false);
                          }}
                        >
                          <X size={18} aria-hidden="true" />
                        </button>
                      </fieldset>
                    </div>
                    <textarea
                      id={`activity-${index}-note`}
                      rows={2}
                      maxLength={1000}
                      value={item.note}
                      onChange={(event) => activity(index, { note: event.target.value })}
                    />
                  </div>
                </fieldset>
              </details>
            ))}
            <button
              type="button"
              className="text-button"
              disabled={content.activities.length >= 20}
              onClick={() => {
                activityKeys.current.push(crypto.randomUUID());
                setContent({
                  ...content,
                  activities: [
                    ...content.activities,
                    { title: "", time: null, place: "", cost: null, note: "" },
                  ],
                });
                setReview(false);
              }}
            >
              활동 추가
            </button>
            <PlanChecks content={content} />
            <details className="optional-fields">
              <summary>준비물 (선택)</summary>
              <div className="auth-field">
                <label htmlFor="plan-preparation">준비물 (한 줄에 하나, 최대 30개)</label>
                <textarea
                  id="plan-preparation"
                  rows={4}
                  maxLength={6030}
                  value={preparation}
                  onChange={(event) => setPreparation(event.target.value)}
                />
              </div>
            </details>
            <button type="submit" className="primary-button plan-save" aria-busy={pending}>
              {"플랜 저장"}
            </button>
            <p className="settings-hint">
              저장 후 아래 내용을 확인하고 ‘이 내용으로 확정하기’를 눌러야 코스와 달력에 반영돼요.
            </p>
            {plan && (
              <>
                <div className="calendar-toolbar">
                  <button
                    type="button"
                    className="text-button"
                    disabled={dirty}
                    onClick={() => {
                      setReview(true);
                      requestAnimationFrame(() =>
                        reviewPanel.current?.scrollIntoView({ block: "start" }),
                      );
                    }}
                  >
                    {plan.published_content ? "변경 내용 확인·재확정" : "확정 내용 확인"}
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    disabled={dirty}
                    onClick={() => mutate("archive")}
                  >
                    플랜 보관
                  </button>
                </div>
                {dirty && (
                  <p className="settings-hint">
                    작성한 내용을 먼저 저장한 뒤 확정하거나 보관해 주세요.
                  </p>
                )}
                {review && !dirty && (
                  <section
                    className="plan-review"
                    aria-label="플랜 확정 내용"
                    id="plan-publication"
                    ref={reviewPanel}
                  >
                    <h2>코스와 달력에 반영할 내용</h2>
                    <p className="settings-hint">
                      {planStatus(plan) === "확정됨"
                        ? "현재 코스와 달력에 반영된 내용이에요."
                        : "아직 코스에 반영되지 않았어요. 아래 내용을 확인하고 확정해 주세요."}
                    </p>
                    <PlanPreview content={content} />
                    <p>
                      <strong>{content.title}</strong>
                      <br />
                      {content.date} · {content.activities[0]?.time || "시간 미정"}
                      <br />
                      {content.activities[0]?.place || "장소 미정"}
                    </p>
                    {plan.appointment && (
                      <p className="settings-hint">
                        현재 달력: {plan.appointment.title} · {plan.appointment.date} ·{" "}
                        {plan.appointment.time?.slice(0, 5) || "시간 미정"} ·{" "}
                        {plan.appointment.place || "장소 미정"}
                        <br />이 약속을 위 내용으로 갱신해요. 달력에서 작성한 메모는 유지돼요.
                      </p>
                    )}
                    <p className="settings-hint">
                      실제 만남 기록은 생성되지 않아요. 보관해도 이 약속은 남아요.
                    </p>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => mutate("confirm")}
                    >
                      이 내용으로 확정하기
                    </button>
                  </section>
                )}
              </>
            )}
          </fieldset>
        </form>
      )}
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {conflict && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() =>
            startTransition(async () => {
              try {
                await onReload();
              } catch {
                setError("최신 내용을 불러오지 못했어요. 다시 시도해 주세요.");
              }
            })
          }
        >
          작성 내용을 버리고 최신 플랜 불러오기
        </button>
      )}
    </section>
  );
}

function PlanPreview({ content }: { content: PlanContent }) {
  return (
    <div className="plan-preview">
      <p>
        <strong>{content.title}</strong> · {content.date}
      </p>
      <p>
        예산 {content.budget === null ? "미정" : `${content.budget.toLocaleString("ko-KR")}원`} ·{" "}
        {content.transport || "교통수단 미정"}
      </p>
      <ol>
        {content.activities
          .map((item, index) => ({ item, ordinal: index + 1 }))
          .map(({ item, ordinal }) => (
            <li key={ordinal}>
              <strong>{item.title}</strong> · {item.time || "시간 미정"} ·{" "}
              {item.place || "장소 미정"} ·{" "}
              {item.cost === null ? "비용 미정" : `${item.cost.toLocaleString("ko-KR")}원`}
              {item.note && <p>{item.note}</p>}
            </li>
          ))}
      </ol>
      <p>준비물: {content.preparation.join(" · ") || "없음"}</p>
    </div>
  );
}
