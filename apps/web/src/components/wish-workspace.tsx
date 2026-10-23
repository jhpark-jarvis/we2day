"use client";

import { useRef, useState, useTransition } from "react";
import { saveWish } from "@/app/actions/wishlist";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { ArchiveToggle, RefreshButton } from "@/components/workspace-controls";
import type { Wish, WishContent } from "@/lib/wishlist";
export function WishWorkspace({
  initialItems,
  initialError,
  initialSelected = null,
}: {
  initialItems: Wish[];
  initialError: string;
  initialSelected?: Wish | null;
}) {
  const [items, setItems] = useState(initialItems);
  const [error, setError] = useState(initialError);
  const [archived, setArchived] = useState(false);
  const [more, setMore] = useState(initialItems.length === 50);
  const [selected, setSelected] = useState<Wish | null>(initialSelected);
  const [id, setId] = useState(initialSelected?.id || "");
  const [pending, startTransition] = useTransition();
  function load(next: boolean, offset = 0) {
    startTransition(async () => {
      try {
        const response = await fetch(`/api/wishlist?archived=${next}&offset=${offset}`, {
          cache: "no-store",
        });
        const data = await response.json();
        if (!response.ok) throw Error();
        setItems((current) =>
          offset
            ? [...current, ...data].filter(
                (item, index, array) => array.findIndex((v) => v.id === item.id) === index,
              )
            : data,
        );
        setArchived(next);
        setMore(data.length === 50);
        setError("");
      } catch {
        setError("위시 목록을 불러오지 못했어요. 다시 시도해 주세요.");
      }
    });
  }
  if (id)
    return (
      <WishEditor
        key={`${id}:${selected?.version || 0}`}
        id={id}
        wish={selected}
        onClose={() => {
          setId("");
          setSelected(null);
        }}
        onSaved={(wish) => {
          setItems((current) =>
            [wish, ...current.filter((v) => v.id !== wish.id)].filter(
              (v) => v.archived === archived,
            ),
          );
          setSelected(null);
          setId("");
        }}
      />
    );
  return (
    <section>
      <Link className="text-button" href="/plans">
        ← 플랜
      </Link>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR WISHLIST</p>
          <h1>위시리스트</h1>
          <p className="muted">함께 가고 싶은 곳, 해보고 싶은 일을 모아요.</p>
        </div>
      </PageHeading>
      <div className="calendar-toolbar">
        <button className="primary-button" type="button" onClick={() => setId(crypto.randomUUID())}>
          위시 추가
        </button>
        <ArchiveToggle label="위시 구분" archived={archived} pending={pending} onChange={load} />
        <RefreshButton label="위시 새로고침" pending={pending} onClick={() => load(archived)} />
      </div>
      <p className="settings-hint">
        직접 작성한 내용만 저장해요. 완료 표시는 만난 날이나 실제 방문 기록을 만들지 않아요.
      </p>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      <div className="plan-list">
        {items.map((wish) => (
          <article className="plan-card" key={wish.id}>
            <small>
              {wish.kind === "place" ? "가고 싶은 곳" : "해보고 싶은 일"} ·{" "}
              {wish.done ? "완료" : "하고 싶어요"}
              {wish.archived ? " · 보관됨" : ""}
            </small>
            <h2>{wish.title}</h2>
            <p className="preserve-lines">{wish.note}</p>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setSelected(wish);
                setId(wish.id);
              }}
            >
              위시 수정 · {wish.title}
            </button>
            {!wish.archived && (
              <Link className="text-button" href={`/plans?wish=${wish.id}`}>
                이 위시로 플랜 초안 만들기
              </Link>
            )}
          </article>
        ))}
      </div>
      {!items.length && !error && (
        <p className="empty-state">
          {archived ? "보관된 위시가 없어요." : "아직 모아둔 위시가 없어요."}
        </p>
      )}
      {more && (
        <button
          type="button"
          className="text-button"
          disabled={pending}
          onClick={() => load(archived, items.length)}
        >
          위시 더 보기
        </button>
      )}
    </section>
  );
}
function WishEditor({
  id,
  wish,
  onClose,
  onSaved,
}: {
  id: string;
  wish: Wish | null;
  onClose: () => void;
  onSaved: (wish: Wish) => void;
}) {
  const [content, setContent] = useState<WishContent>(
    wish
      ? {
          title: wish.title,
          kind: wish.kind,
          note: wish.note,
          done: wish.done,
          archived: wish.archived,
        }
      : { title: "", kind: "place", note: "", done: false, archived: false },
  );
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, startTransition] = useTransition();
  const request = useRef<{ signature: string; id: string } | null>(null);
  function save() {
    const signature = JSON.stringify([content, wish?.version || 0]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    const requestId = request.current.id;
    startTransition(async () => {
      const result = await saveWish(id, content, wish?.version || 0, requestId);
      if (result.data) onSaved(result.data);
      else {
        setError(
          result.status === 409
            ? "상대가 위시를 수정했어요. 작성 내용을 확인하고 최신 목록을 불러와 주세요."
            : result.error,
        );
        setConflict(result.status === 409);
      }
    });
  }
  return (
    <section className="plan-editor">
      <button className="text-button" type="button" disabled={pending} onClick={onClose}>
        ← 위시 목록으로
      </button>
      <PageHeading>
        <h1>{wish ? "위시 수정" : "새로운 위시"}</h1>
      </PageHeading>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <fieldset className="meeting-fields" disabled={pending || conflict}>
          <div className="auth-field">
            <label htmlFor="wish-title">위시 이름</label>
            <input
              id="wish-title"
              required
              maxLength={100}
              value={content.title}
              onChange={(e) => setContent({ ...content, title: e.target.value })}
            />
          </div>
          <div className="auth-field">
            <label htmlFor="wish-kind">위시 종류</label>
            <select
              id="wish-kind"
              value={content.kind}
              onChange={(e) =>
                setContent({ ...content, kind: e.target.value as WishContent["kind"] })
              }
            >
              <option value="place">가고 싶은 곳</option>
              <option value="activity">해보고 싶은 일</option>
            </select>
          </div>
          <div className="auth-field">
            <label htmlFor="wish-note">위시 메모</label>
            <textarea
              id="wish-note"
              maxLength={1000}
              rows={4}
              value={content.note}
              onChange={(e) => setContent({ ...content, note: e.target.value })}
            />
          </div>
          <label className="check-field">
            <input
              type="checkbox"
              checked={content.done}
              onChange={(e) => setContent({ ...content, done: e.target.checked })}
            />
            함께 해봤어요
          </label>
          <label className="check-field">
            <input
              type="checkbox"
              checked={content.archived}
              onChange={(e) => setContent({ ...content, archived: e.target.checked })}
            />
            위시 보관 (해제하면 목록으로 복원)
          </label>
          <button className="primary-button" type="submit">
            위시 저장
          </button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {conflict && (
        <button className="text-button" type="button" onClick={onClose}>
          작성 내용을 버리고 목록으로
        </button>
      )}
    </section>
  );
}
