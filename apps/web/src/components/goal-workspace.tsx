"use client";
import { Pencil } from "lucide-react";

import { useRef, useState, useTransition } from "react";
import { saveGoal } from "@/app/actions/goals";
import { PageHeading } from "@/components/page-heading";
import { ArchiveToggle, RefreshButton } from "@/components/workspace-controls";
import type { Goal, GoalContent, GoalStep } from "@/lib/goals";
import { goalProgress } from "@/lib/goals";
import { useItemHistory } from "@/lib/page-history";

export function GoalWorkspace({
  initialGoals,
  initialError,
}: {
  initialGoals: Goal[];
  initialError: string;
}) {
  const [goals, setGoals] = useState(initialGoals);
  const [error, setError] = useState(initialError);
  const [message, setMessage] = useState("");
  const [archived, setArchived] = useState(false);
  const [more, setMore] = useState(initialGoals.length === 50);
  const {
    id,
    selected,
    open,
    close,
    finish,
    error: navigationError,
  } = useItemHistory("goals", goals, "/api/goals");
  const [pending, startTransition] = useTransition();
  function load(next: boolean, offset = 0) {
    startTransition(async () => {
      try {
        const response = await fetch(`/api/goals?archived=${next}&offset=${offset}`, {
          cache: "no-store",
        });
        const data: Goal[] = await response.json();
        if (!response.ok) throw Error();
        setGoals((current) =>
          offset
            ? [...current, ...data].filter(
                (step, index, array) => array.findIndex((v) => v.id === step.id) === index,
              )
            : data,
        );
        setArchived(next);
        setMore(data.length === 50);
        setError("");
        setMessage("");
      } catch {
        setError("목표를 불러오지 못했어요. 다시 시도해 주세요.");
      }
    });
  }
  if (id)
    return (
      <GoalEditor
        key={`${id}:${selected?.version || 0}`}
        id={id}
        saved={selected}
        onClose={close}
        onSaved={(saved) => {
          setGoals((current) =>
            [saved, ...current.filter((v) => v.id !== saved.id)].filter(
              (v) => v.archived === archived,
            ),
          );
          finish();
          setMessage("목표를 저장했어요.");
        }}
      />
    );
  return (
    <section>
      <PageHeading>
        <div>
          <p className="eyebrow">LITTLE STEPS, TOGETHER</p>
          <h1>목표</h1>
          <p className="muted">함께 이루고 싶은 일을 작은 단계로 나눠요.</p>
        </div>
      </PageHeading>
      <div className="calendar-toolbar">
        <button
          className="primary-button"
          type="button"
          disabled={pending}
          onClick={() => {
            setMessage("");
            open(crypto.randomUUID(), true);
          }}
        >
          목표 만들기
        </button>
        <ArchiveToggle label="목표 구분" archived={archived} pending={pending} onChange={load} />
        <RefreshButton label="목표 새로고침" pending={pending} onClick={() => load(archived)} />
      </div>
      <p className="settings-hint">
        두 사람 모두 수정할 수 있어요. 단계 진행률과 목표 달성 표시는 따로 관리해요.
      </p>
      {(error || navigationError) && (
        <p role="alert" className="error-message">
          {error || navigationError}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <div className="plan-list">
        {goals.map((goal) => (
          <article className="plan-card" key={goal.id}>
            <small>
              {goal.completed ? "달성한 목표" : "함께 진행 중"}
              {goal.archived ? " · 보관됨" : ""}
            </small>
            <h2>{goal.title}</h2>
            <p className="muted">희망 날짜 · {goal.target_date || "미정"}</p>
            <GoalProgress steps={goal.steps} />
            <ul className="checklist-preview">
              {goal.steps
                .filter((step) => !step.done)
                .slice(0, 3)
                .map((step) => (
                  <li key={step.id}>
                    {step.done ? "✓ " : "○ "}
                    {step.title}
                  </li>
                ))}
            </ul>
            {goal.steps.some((step) => step.done) && (
              <details className="compact-help">
                <summary>완료한 단계 {goal.steps.filter((step) => step.done).length}개</summary>
                <ul>
                  {goal.steps
                    .filter((step) => step.done)
                    .map((step) => (
                      <li key={step.id}>{step.title}</li>
                    ))}
                </ul>
              </details>
            )}
            <button
              className="icon-button card-edit"
              aria-label={`목표 열기 · ${goal.title}`}
              title="목표 수정"
              type="button"
              onClick={() => {
                open(goal.id);
              }}
            >
              <Pencil size={18} aria-hidden="true" />
            </button>
          </article>
        ))}
      </div>
      {!goals.length && !error && (
        <p className="empty-state">
          {archived
            ? "보관된 목표가 없어요."
            : "아직 목표가 없어요. 함께 이루고 싶은 일을 적어보세요."}
        </p>
      )}
      {more && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() => load(archived, goals.length)}
        >
          목표 더 보기
        </button>
      )}
    </section>
  );
}

function GoalEditor({
  id,
  saved,
  onClose,
  onSaved,
}: {
  id: string;
  saved: Goal | null;
  onClose: () => void;
  onSaved: (saved: Goal) => void;
}) {
  const [base, setBase] = useState(saved);
  const [content, setContent] = useState<GoalContent>(
    saved
      ? {
          title: saved.title,
          target_date: saved.target_date,
          steps: saved.steps,
          completed: saved.completed,
          archived: saved.archived,
        }
      : { title: "", target_date: null, steps: [], completed: false, archived: false },
  );
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, startTransition] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  function changeStep(id: string, change: Partial<GoalStep>) {
    setContent({
      ...content,
      steps: content.steps.map((step) => (step.id === id ? { ...step, ...change } : step)),
    });
  }
  function save() {
    const signature = JSON.stringify([content, base?.version || 0]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    const requestId = request.current.id;
    startTransition(async () => {
      const result = await saveGoal(id, content, base?.version || 0, requestId);
      if (result.data) onSaved(result.data);
      else {
        setError(result.error);
        setConflict(result.status === 409);
      }
    });
  }
  function reloadLatest() {
    startTransition(async () => {
      try {
        const response = await fetch(`/api/goals?id=${id}`, { cache: "no-store" });
        const data: Goal = await response.json();
        if (!response.ok) throw Error();
        setBase(data);
        setContent({
          title: data.title,
          target_date: data.target_date,
          steps: data.steps,
          completed: data.completed,
          archived: data.archived,
        });
        setError("");
        setConflict(false);
        request.current = null;
      } catch {
        setError("최신 목표를 불러오지 못했어요. 작성 내용은 유지돼요.");
      }
    });
  }
  return (
    <section className="plan-editor goal-editor">
      <button className="text-button" type="button" disabled={pending} onClick={onClose}>
        작성 취소
      </button>
      <PageHeading>
        <h1>{base ? "공동 목표 수정" : "새로운 공동 목표"}</h1>
      </PageHeading>
      <p className="settings-hint">
        단계는 최대 50개까지 적을 수 있어요. 모두 체크해도 목표 달성은 직접 선택해요. 저장된 단계는
        이름을 수정하거나 체크를 해제할 수 있어요.
      </p>
      <GoalProgress steps={content.steps} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <fieldset className="meeting-fields" disabled={pending || conflict}>
          <div className="auth-field">
            <label htmlFor="goal-title">목표 이름</label>
            <input
              id="goal-title"
              required
              maxLength={100}
              value={content.title}
              onChange={(e) => setContent({ ...content, title: e.target.value })}
            />
          </div>
          <div className="auth-field">
            <label htmlFor="goal-date">희망 날짜 (선택)</label>
            <input
              id="goal-date"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              value={content.target_date || ""}
              onChange={(e) => setContent({ ...content, target_date: e.target.value || null })}
            />
          </div>
          <h2>작은 단계</h2>
          {content.steps.map((step, index) => (
            <fieldset key={step.id} className="checklist-item">
              <legend>단계 {index + 1}</legend>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={step.done}
                  onChange={(e) => changeStep(step.id, { done: e.target.checked })}
                />
                단계 {index + 1} 완료
              </label>
              <div className="auth-field">
                <label htmlFor={`step-${step.id}-title`}>단계 {index + 1} 이름</label>
                <input
                  id={`step-${step.id}-title`}
                  required
                  maxLength={100}
                  value={step.title}
                  onChange={(e) => changeStep(step.id, { title: e.target.value })}
                />
              </div>
              {!base?.steps.some((v) => v.id === step.id) && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() =>
                    setContent({ ...content, steps: content.steps.filter((v) => v.id !== step.id) })
                  }
                >
                  새 단계 {index + 1} 취소
                </button>
              )}
            </fieldset>
          ))}
          <button
            type="button"
            className="text-button"
            disabled={content.steps.length >= 50}
            onClick={() =>
              setContent({
                ...content,
                steps: [...content.steps, { id: crypto.randomUUID(), title: "", done: false }],
              })
            }
          >
            단계 추가
          </button>
          <label className="check-field">
            <input
              type="checkbox"
              checked={content.completed}
              onChange={(e) => setContent({ ...content, completed: e.target.checked })}
            />
            목표 달성 (직접 선택·해제)
          </label>
          <label className="check-field">
            <input
              type="checkbox"
              checked={content.archived}
              onChange={(e) => setContent({ ...content, archived: e.target.checked })}
            />
            목표 보관 (해제하면 복원)
          </label>
          <button className="primary-button" type="submit">
            목표 저장
          </button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="error-message">
          {conflict
            ? "상대가 목표를 수정했어요. 작성 내용은 유지되며, 자동으로 덮어쓰지 않아요. 최신본을 확인해 주세요."
            : error}
        </p>
      )}
      {conflict && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() => {
            if (window.confirm("작성 중인 내용을 버리고 최신 저장본을 불러올까요?")) reloadLatest();
          }}
        >
          작성 내용을 버리고 최신본 불러오기
        </button>
      )}
    </section>
  );
}

function GoalProgress({ steps }: { steps: GoalStep[] }) {
  const { done, total, percent } = goalProgress(steps);
  return (
    <fieldset className="goal-progress" aria-label="단계 진행률">
      {percent === null ? (
        <p>단계 미정</p>
      ) : (
        <>
          <p>
            {done} / {total}단계 · {percent}%
          </p>
          <progress aria-label="완료한 단계 비율" value={done} max={total} />
        </>
      )}
    </fieldset>
  );
}
