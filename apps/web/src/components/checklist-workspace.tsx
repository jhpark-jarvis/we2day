"use client";

import { Pencil, Plus, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState, useTransition } from "react";
import { saveChecklist } from "@/app/actions/checklists";
import { LoadingRegion } from "@/components/loading-region";
import { PageHeading } from "@/components/page-heading";
import { TogetherBack, TogetherSheet } from "@/components/workspace-controls";
import type { Checklist, ChecklistContent, ChecklistItem } from "@/lib/checklists";
import { useItemHistory } from "@/lib/page-history";

export function ChecklistWorkspace({
  initialLists,
  initialError,
}: {
  initialLists: Checklist[];
  initialError: string;
}) {
  const [lists, setLists] = useState(initialLists);
  const [error, setError] = useState(initialError);
  const [message, setMessage] = useState("");
  const [archived, setArchived] = useState(false);
  const [more, setMore] = useState(initialLists.length === 50);
  const {
    id,
    selected,
    open,
    close,
    finish,
    error: navigationError,
  } = useItemHistory("checklists", lists, "/api/checklists");
  const [pending, startTransition] = useTransition();
  function load(next: boolean, offset = 0) {
    startTransition(async () => {
      try {
        const response = await fetch(`/api/checklists?archived=${next}&offset=${offset}`, {
          cache: "no-store",
        });
        const data: Checklist[] = await response.json();
        if (!response.ok) throw Error();
        setLists((current) =>
          offset
            ? [...current, ...data].filter(
                (item, index, array) => array.findIndex((v) => v.id === item.id) === index,
              )
            : data,
        );
        setArchived(next);
        setMore(data.length === 50);
        setError("");
        setMessage("");
      } catch {
        setError("목록을 불러오지 못했어요. 다시 시도해 주세요.");
      }
    });
  }
  const [editor, setEditor] = useState<{ id: string; saved: Checklist | null } | null>(null);
  const newId = useRef("");
  useEffect(() => {
    if (id) setEditor((current) => (current?.id === id ? current : { id, saved: selected }));
  }, [id, selected]);
  const editorPanel = editor ? (
    <ChecklistEditor
      key={editor.id}
      id={editor.id}
      visible={id === editor.id}
      saved={editor.saved}
      onClose={close}
      onSaved={(saved) => {
        setLists((current) =>
          [saved, ...current.filter((v) => v.id !== saved.id)].filter(
            (v) => v.archived === archived,
          ),
        );
        finish();
        setEditor(null);
        newId.current = "";
        setMessage("목록을 저장했어요.");
      }}
    />
  ) : null;
  return (
    <section className="together-workspace">
      {editorPanel}
      <PageHeading>
        <div>
          <p className="eyebrow">TOGETHER, READY</p>
          <h1>목록</h1>
        </div>
      </PageHeading>
      <div className="together-toolbar">
        <TogetherBack />
        <button
          className="icon-button together-add"
          aria-label="목록 만들기"
          title="목록 추가"
          type="button"
          disabled={pending}
          onClick={() => {
            setMessage("");
            newId.current ||= crypto.randomUUID();
            open(newId.current, true);
          }}
        >
          <Plus size={20} aria-hidden="true" />
        </button>
        <fieldset className="list-view-toggle" aria-label="목록 구분">
          <button
            type="button"
            aria-pressed={!archived}
            disabled={pending}
            onClick={() => load(false)}
          >
            현재
          </button>
          <button
            type="button"
            aria-pressed={archived}
            disabled={pending}
            onClick={() => load(true)}
          >
            보관함
          </button>
        </fieldset>
        <button
          className="icon-button checklist-refresh"
          type="button"
          aria-label="목록 새로고침"
          title="목록 새로고침"
          aria-busy={pending}
          disabled={pending}
          onClick={() => load(archived)}
        >
          <RefreshCw size={18} aria-hidden="true" />
        </button>
      </div>
      {(error || navigationError) && (
        <p role="alert" className="error-message">
          {error || navigationError}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <LoadingRegion busy={pending} disabled={Boolean(id)} label="목록 불러오는 중">
        <div className="plan-list together-records" aria-hidden={Boolean(id)}>
          {lists.map((list) => (
            <article className="plan-card" key={list.id}>
              <small>
                {list.items.filter((item) => item.done).length} / {list.items.length}개 준비
                {list.archived ? " · 보관됨" : ""}
              </small>
              <h2>{list.title}</h2>
              <p className="preserve-lines">{list.note}</p>
              <ul className="checklist-preview">
                {list.items.slice(0, 3).map((item) => (
                  <li key={item.id}>
                    {item.done ? "✓ " : "○ "}
                    {item.title}
                    {item.quantity ? ` · ${item.quantity}` : ""}
                  </li>
                ))}
              </ul>
              <button
                className="icon-button card-edit"
                aria-label={`목록 열기 · ${list.title}`}
                title="목록 수정"
                type="button"
                onClick={() => {
                  open(list.id);
                }}
              >
                <Pencil size={18} aria-hidden="true" />
              </button>
            </article>
          ))}
        </div>
      </LoadingRegion>
      {!lists.length && !error && (
        <p className="empty-state">
          {archived
            ? "보관된 목록이 없어요."
            : "아직 준비 목록이 없어요. 함께 챙길 일을 적어보세요."}
        </p>
      )}
      {more && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() => load(archived, lists.length)}
        >
          목록 더 보기
        </button>
      )}
    </section>
  );
}

function ChecklistEditor({
  id,
  visible,
  saved,
  onClose,
  onSaved,
}: {
  id: string;
  visible: boolean;
  saved: Checklist | null;
  onClose: () => void;
  onSaved: (saved: Checklist) => void;
}) {
  const [base, setBase] = useState(saved);
  const [content, setContent] = useState<ChecklistContent>(
    saved
      ? {
          title: saved.title,
          note: saved.note,
          items: saved.items,
          archived: saved.archived,
        }
      : { title: "", note: "", items: [], archived: false },
  );
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, startTransition] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  function changeItem(id: string, change: Partial<ChecklistItem>) {
    setContent({
      ...content,
      items: content.items.map((item) => (item.id === id ? { ...item, ...change } : item)),
    });
  }
  function save() {
    const signature = JSON.stringify([content, base?.version || 0]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    const requestId = request.current.id;
    startTransition(async () => {
      const result = await saveChecklist(id, content, base?.version || 0, requestId);
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
        const response = await fetch(`/api/checklists?id=${id}`, { cache: "no-store" });
        const data: Checklist = await response.json();
        if (!response.ok) throw Error();
        setBase(data);
        setContent({
          title: data.title,
          note: data.note,
          items: data.items,
          archived: data.archived,
        });
        setError("");
        setConflict(false);
        request.current = null;
      } catch {
        setError("최신 목록을 불러오지 못했어요. 작성 내용은 유지돼요.");
      }
    });
  }
  return (
    <TogetherSheet
      open={visible}
      title={base ? "목록 수정" : "목록 추가"}
      busy={pending}
      onClose={onClose}
    >
      <section className="together-editor">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <fieldset className="meeting-fields" disabled={pending || conflict}>
            <div className="auth-field">
              <label htmlFor="checklist-title">목록 이름</label>
              <input
                id="checklist-title"
                required
                maxLength={100}
                value={content.title}
                onChange={(e) => setContent({ ...content, title: e.target.value })}
              />
            </div>
            <div className="together-note">
              <div className="auth-field">
                <label htmlFor="checklist-note">목록 메모</label>
                <textarea
                  id="checklist-note"
                  rows={3}
                  maxLength={1000}
                  value={content.note}
                  onChange={(e) => setContent({ ...content, note: e.target.value })}
                />
              </div>
            </div>
            <h2>함께 챙길 항목</h2>
            {content.items.map((item, index) => (
              <fieldset key={item.id} className="checklist-item">
                <legend>항목 {index + 1}</legend>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={item.done}
                    onChange={(e) => changeItem(item.id, { done: e.target.checked })}
                  />
                  항목 {index + 1} 준비 완료
                </label>
                <div className="auth-field">
                  <label htmlFor={`item-${item.id}-title`}>항목 {index + 1} 이름</label>
                  <input
                    id={`item-${item.id}-title`}
                    required
                    maxLength={100}
                    value={item.title}
                    onChange={(e) => changeItem(item.id, { title: e.target.value })}
                  />
                </div>
                <div className="auth-field">
                  <label htmlFor={`item-${item.id}-quantity`}>항목 {index + 1} 수량·참고</label>
                  <input
                    id={`item-${item.id}-quantity`}
                    maxLength={100}
                    value={item.quantity}
                    onChange={(e) => changeItem(item.id, { quantity: e.target.value })}
                  />
                </div>
                {!base?.items.some((v) => v.id === item.id) && (
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`새 항목 ${index + 1} 취소`}
                    title="추가 취소"
                    onClick={() =>
                      setContent({
                        ...content,
                        items: content.items.filter((v) => v.id !== item.id),
                      })
                    }
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
                )}
              </fieldset>
            ))}
            <button
              type="button"
              className="text-button"
              disabled={content.items.length >= 50}
              onClick={() =>
                setContent({
                  ...content,
                  items: [
                    ...content.items,
                    { id: crypto.randomUUID(), title: "", quantity: "", done: false },
                  ],
                })
              }
            >
              항목 추가
            </button>
            <label className="check-field">
              <input
                type="checkbox"
                aria-label="목록 보관 (해제하면 복원)"
                checked={content.archived}
                onChange={(e) => setContent({ ...content, archived: e.target.checked })}
              />
              보관
            </label>
            <button className="primary-button" type="submit" aria-label="목록 저장">
              저장
            </button>
          </fieldset>
        </form>
        {error && (
          <p role="alert" className="error-message">
            {conflict
              ? "상대가 목록을 수정했어요. 작성 내용은 유지되며, 자동으로 덮어쓰지 않아요. 최신본을 확인해 주세요."
              : error}
          </p>
        )}
        {conflict && (
          <button
            type="button"
            className="text-button"
            disabled={pending}
            onClick={() => {
              if (window.confirm("작성 중인 내용을 버리고 최신 저장본을 불러올까요?"))
                reloadLatest();
            }}
          >
            작성 내용을 버리고 최신본 불러오기
          </button>
        )}
      </section>
    </TogetherSheet>
  );
}
