"use client";

import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronRight,
  Circle,
  Ellipsis,
  Link2,
  MapPin,
  Pencil,
  Plus,
  Route,
  Search,
  Star,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useTransition } from "react";
import { createPortal } from "react-dom";
import { saveWish } from "@/app/actions/wishlist";
import { FavoritePlaces } from "@/components/favorite-places";
import { LoadingRegion } from "@/components/loading-region";
import { NaverAppHandoff } from "@/components/naver-app-handoff";
import { PageHeading } from "@/components/page-heading";
import { PlaceSearchPanel } from "@/components/place-search-panel";
import Link from "@/components/progress-link";
import { RefreshButton, TogetherBack } from "@/components/workspace-controls";
import { naverShareLink } from "@/lib/naver-app";
import { useItemHistory } from "@/lib/page-history";
import type { Wish, WishContent, WishOverview, WishView } from "@/lib/wishlist";

const views = [
  ["planned", "예정"],
  ["done", "완료"],
  ["archived", "보관"],
] as const;
const emptyPage: WishOverview = {
  items: [],
  counts: { planned: 0, done: 0, archived: 0 },
  has_more: false,
};
type Draft = {
  content: WishContent;
  version: number;
  source: "search" | "link" | "favorites";
  query: string;
  searching: boolean;
  error: string;
  conflict: boolean;
  request: { signature: string; id: string } | null;
};
function contentOf(wish?: Wish | null): WishContent {
  return {
    title: wish?.title || "",
    kind: wish?.kind || "place",
    note: wish?.note || "",
    place: wish?.place || "",
    map_url: wish?.map_url || "",
    done: wish?.done || false,
    archived: wish?.archived || false,
  };
}
function statusOf(wish: WishContent): WishView {
  return wish.archived ? "archived" : wish.done ? "done" : "planned";
}

export function WishWorkspace({
  initialPage,
  initialError,
  initialSelected = null,
  site,
}: {
  initialPage: WishOverview | null;
  initialError: string;
  initialSelected?: Wish | null;
  site: string;
}) {
  const router = useRouter();
  const [page, setPage] = useState(initialPage || emptyPage);
  const [counted, setCounted] = useState(Boolean(initialPage));
  const [view, setView] = useState<WishView>("planned");
  const [error, setError] = useState(initialError);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [mutating, startMutation] = useTransition();
  const currentView = useRef(view);
  currentView.current = view;
  const workspace = useRef<HTMLElement>(null);
  const active = useRef<AbortController | null>(null);
  const known = useRef(
    new Map(
      [...(initialPage?.items || []), ...(initialSelected ? [initialSelected] : [])].map((item) => [
        item.id,
        item,
      ]),
    ),
  );
  const drafts = useRef(new Map<string, Draft>());
  const newId = useRef("");
  const trigger = useRef<{ id: string; action: string } | null>(null);
  const hadEditor = useRef(false);
  const retries = useRef(new Map<string, { signature: string; id: string }>());
  const history = useItemHistory(
    "wishlist",
    [...known.current.values()],
    "/api/wishlist",
    initialSelected?.id || "",
  );
  const currentEditor = useRef(history.id);
  currentEditor.current = history.id;
  const busy = loading || mutating;

  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    if (history.id) {
      hadEditor.current = true;
      return;
    }
    if (!hadEditor.current || busy) return;
    hadEditor.current = false;
    const frame = requestAnimationFrame(() => {
      const target = [
        ...(workspace.current?.querySelectorAll<HTMLElement>("[data-wish-action]") || []),
      ].find(
        (node) =>
          node.dataset.wishId === trigger.current?.id &&
          node.dataset.wishAction === trigger.current?.action,
      );
      (
        target || workspace.current?.querySelector<HTMLElement>('[data-wish-action="add"]')
      )?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [history.id, busy]);
  useEffect(() => {
    const closeMenus = (event: PointerEvent) => {
      if (event.target instanceof Element && event.target.closest(".wish-menu")) return;
      workspace.current
        ?.querySelectorAll<HTMLDetailsElement>(".wish-menu[open]")
        .forEach((menu) => {
          menu.open = false;
        });
    };
    document.addEventListener("pointerdown", closeMenus);
    return () => document.removeEventListener("pointerdown", closeMenus);
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 3500);
    return () => clearTimeout(timer);
  }, [notice]);

  async function load(next: WishView, offset = 0) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    try {
      const response = await fetch(`/api/wishlist?view=${next}&offset=${offset}`, {
        cache: "no-store",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)]),
      });
      const data = await response.json();
      if (
        !response.ok ||
        !Array.isArray(data?.items) ||
        typeof data.has_more !== "boolean" ||
        !views.every(([key]) => Number.isSafeInteger(data.counts?.[key]) && data.counts[key] >= 0)
      )
        throw Error();
      if (controller.signal.aborted) return;
      for (const item of data.items as Wish[]) known.current.set(item.id, item);
      setPage((current) => ({
        ...data,
        items: offset
          ? [...current.items, ...data.items].filter(
              (item, index, all) => all.findIndex((other) => other.id === item.id) === index,
            )
          : data.items,
      }));
      currentView.current = next;
      setView(next);
      setCounted(true);
      setError("");
    } catch {
      if (!controller.signal.aborted)
        setError("위시 목록을 불러오지 못했어요. 다시 시도해 주세요.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  function open(wish?: Wish) {
    trigger.current = { id: wish?.id || "", action: wish ? "edit" : "add" };
    if (!wish) newId.current ||= crypto.randomUUID();
    history.open(wish?.id || newId.current, !wish);
  }
  function getDraft(id: string, wish: Wish | null) {
    let draft = drafts.current.get(id);
    if (!draft) {
      draft = {
        content: contentOf(wish),
        version: wish?.version || 0,
        source: wish?.map_url && !wish.place ? "link" : "search",
        query: "",
        searching: !wish?.place,
        error: "",
        conflict: false,
        request: null,
      };
      drafts.current.set(id, draft);
    }
    return draft;
  }
  function saved(wish: Wish) {
    const selectedView = currentView.current;
    const previous = known.current.get(wish.id);
    known.current.set(wish.id, wish);
    setPage((current) => {
      const counts = { ...current.counts };
      if (counted) {
        if (previous) counts[statusOf(previous)] = Math.max(0, counts[statusOf(previous)] - 1);
        counts[statusOf(wish)]++;
      }
      const remaining = current.items.filter((item) => item.id !== wish.id);
      return {
        ...current,
        counts,
        items: statusOf(wish) === selectedView ? [wish, ...remaining] : remaining,
      };
    });
    setError("");
    void load(selectedView);
  }
  function closeEditor(finish = false) {
    if (finish) history.finish();
    else history.close();
    if (initialSelected && new URL(window.location.href).searchParams.has("item"))
      router.replace("/wishlist", { scroll: false });
  }
  function changeStatus(wish: Wish, field: "done" | "archived") {
    if (busy) return;
    workspace.current?.querySelectorAll<HTMLDetailsElement>(".wish-menu[open]").forEach((menu) => {
      menu.open = false;
    });
    const content = { ...contentOf(wish), [field]: !wish[field] };
    const signature = JSON.stringify([content, wish.version]);
    let retry = retries.current.get(wish.id);
    if (!retry || retry.signature !== signature) {
      retry = { signature, id: crypto.randomUUID() };
      retries.current.set(wish.id, retry);
    }
    const requestId = retry.id;
    startMutation(async () => {
      try {
        const result = await saveWish(wish.id, content, wish.version, requestId);
        if (result.data) {
          retries.current.delete(wish.id);
          saved(result.data);
          setNotice(
            field === "done"
              ? content.done
                ? "완료로 이동했어요."
                : "예정으로 이동했어요."
              : content.archived
                ? "보관했어요."
                : "복원했어요.",
          );
        } else if (result.status === 409) {
          await load(view);
          setError("상대가 위시를 수정했어요. 최신 내용을 확인해 주세요.");
        } else setError(result.error);
      } catch {
        setError("연결을 확인하고 다시 시도해 주세요. 위시는 그대로 두었어요.");
      }
    });
  }

  return (
    <section className="wish-workspace" ref={workspace}>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR WISHLIST</p>
          <h1>위시</h1>
        </div>
      </PageHeading>
      <div className="wish-toolbar">
        <TogetherBack />
        <fieldset className="wish-filters" aria-label="위시 상태">
          {views.map(([key, label]) => (
            <button
              type="button"
              key={key}
              aria-pressed={view === key}
              disabled={busy}
              onClick={() => void load(key)}
            >
              {label}
              <span>{counted ? page.counts[key] : "—"}</span>
            </button>
          ))}
        </fieldset>
        <div className="wish-tools">
          <RefreshButton label="위시 새로고침" pending={busy} onClick={() => void load(view)} />
          <button
            type="button"
            className="icon-button"
            aria-label="위시 추가"
            title="위시 추가"
            data-wish-action="add"
            data-wish-id=""
            disabled={busy}
            onClick={() => open()}
          >
            <Plus size={20} aria-hidden="true" />
          </button>
        </div>
      </div>
      <LoadingRegion busy={busy} label="위시를 불러오는 중">
        <div className="wish-list">
          {page.items.map((wish, index) => (
            <article className="wish-row" key={wish.id}>
              <button
                className="wish-open"
                type="button"
                onClick={() => open(wish)}
                aria-label={`위시 수정 · ${wish.title}`}
                data-wish-action="edit"
                data-wish-id={wish.id}
              >
                <span>
                  <small>{wish.kind === "place" ? "장소" : "활동"}</small>
                  <h2>{wish.title}</h2>
                </span>
                <ChevronRight size={17} aria-hidden="true" />
              </button>
              {wish.kind === "place" && wish.place && <p className="wish-address">{wish.place}</p>}
              <div className="wish-row-actions">
                {wish.kind === "place" && (
                  <NaverAppHandoff
                    place={wish.place || wish.title}
                    mapUrl={wish.map_url}
                    site={site}
                    iconOnly
                  />
                )}
                {!wish.archived && (
                  <Link
                    className="wish-course"
                    href={`/plans?wish=${wish.id}`}
                    aria-label={`${wish.title} 코스 초안`}
                  >
                    <Route size={18} aria-hidden="true" />
                    <span>코스</span>
                  </Link>
                )}
                <details
                  className="wish-menu"
                  name="wish-actions"
                  data-align={index && index === page.items.length - 1 ? "above" : "below"}
                >
                  <summary
                    className="icon-button"
                    aria-label={`${wish.title} 더보기`}
                    title="더보기"
                  >
                    <Ellipsis size={20} aria-hidden="true" />
                  </summary>
                  <div className="wish-menu-items">
                    <button
                      type="button"
                      onClick={() => {
                        workspace.current
                          ?.querySelectorAll<HTMLDetailsElement>(".wish-menu[open]")
                          .forEach((menu) => {
                            menu.open = false;
                          });
                        open(wish);
                      }}
                    >
                      <Pencil size={17} aria-hidden="true" />
                      수정
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => changeStatus(wish, "done")}
                    >
                      {wish.done ? (
                        <Circle size={17} aria-hidden="true" />
                      ) : (
                        <Check size={17} aria-hidden="true" />
                      )}
                      {wish.done ? "예정으로" : "완료"}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => changeStatus(wish, "archived")}
                    >
                      {wish.archived ? (
                        <ArchiveRestore size={17} aria-hidden="true" />
                      ) : (
                        <Archive size={17} aria-hidden="true" />
                      )}
                      {wish.archived ? "복원" : "보관"}
                    </button>
                  </div>
                </details>
              </div>
            </article>
          ))}
        </div>
        {!page.items.length && !error && (
          <div className="wish-empty">
            <Star size={25} aria-hidden="true" />
            <p>
              {view === "archived"
                ? "보관한 위시가 없어요."
                : view === "done"
                  ? "완료한 위시가 없어요."
                  : "함께 하고 싶은 일을 담아보세요."}
            </p>
          </div>
        )}
        {!page.items.length && error && (
          <button type="button" className="text-button" onClick={() => void load(view)}>
            다시 불러오기
          </button>
        )}
        {page.has_more && (
          <button
            type="button"
            className="text-button wish-more"
            disabled={busy}
            aria-label="위시 더 보기"
            onClick={() => void load(view, page.items.length)}
          >
            더 보기
          </button>
        )}
      </LoadingRegion>
      {(error || history.error || notice) && (
        <div className="wish-feedback" role={error || history.error ? "alert" : "status"}>
          <span>{error || history.error || notice}</span>
          <button
            className="icon-button"
            type="button"
            aria-label="안내 닫기"
            onClick={() => {
              setError("");
              setNotice("");
            }}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      )}
      {history.id && (
        <WishEditor
          key={history.id}
          id={history.id}
          record={getDraft(history.id, history.selected)}
          site={site}
          onClose={() => closeEditor()}
          onSaved={(wish) => {
            drafts.current.delete(wish.id);
            if (newId.current === wish.id) newId.current = "";
            saved(wish);
            if (currentEditor.current === wish.id) closeEditor(true);
            setNotice("저장했어요.");
          }}
          onDiscard={() => {
            drafts.current.delete(history.id);
            if (newId.current === history.id) newId.current = "";
            closeEditor(true);
            void load(view);
          }}
        />
      )}
    </section>
  );
}

function WishEditor({
  id,
  record,
  site,
  onClose,
  onSaved,
  onDiscard,
}: {
  id: string;
  record: Draft;
  site: string;
  onClose: () => void;
  onSaved: (wish: Wish) => void;
  onDiscard: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const identity = useId();
  const [content, setContent] = useState(record.content);
  const [source, setSource] = useState(record.source);
  const [searching, setSearching] = useState(record.searching);
  const [error, setError] = useState(record.error);
  const [conflict, setConflict] = useState(record.conflict);
  const [pending, startTransition] = useTransition();
  const [portal, setPortal] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setPortal(document.body);
  }, []);
  useEffect(() => {
    if (!portal) return;
    const node = dialog.current;
    node?.showModal();
    return () => {
      if (node?.open) node.close();
    };
  }, [portal]);
  function change(update: Partial<WishContent>) {
    const next = { ...content, ...update };
    record.content = next;
    setContent(next);
    record.error = "";
    setError("");
  }
  function select(place: string) {
    change({
      place,
      title: content.title || place.split(" (")[0].slice(0, 100),
      map_url: content.place === place ? content.map_url : "",
    });
    record.searching = false;
    setSearching(false);
  }
  function chooseSource(next: Draft["source"]) {
    record.source = next;
    setSource(next);
    if (next === "search") {
      record.searching = true;
      setSearching(true);
    }
  }
  function fail(message: string, stale = false) {
    record.error = message;
    setError(message);
    record.conflict = stale;
    setConflict(stale);
  }
  function save() {
    if (pending || conflict) return;
    const body = {
      ...content,
      title: content.title.trim(),
      place: content.kind === "activity" ? "" : content.place || "",
      map_url: content.kind === "activity" ? "" : content.map_url || "",
    };
    if (!body.title) {
      fail("이름을 입력해 주세요.");
      return;
    }
    if (body.map_url && !naverShareLink(body.map_url)) {
      fail("네이버 지도 공유 링크를 확인해 주세요.");
      return;
    }
    const signature = JSON.stringify([body, record.version]);
    if (record.request?.signature !== signature)
      record.request = { signature, id: crypto.randomUUID() };
    const requestId = record.request.id;
    startTransition(async () => {
      try {
        const result = await saveWish(id, body, record.version, requestId);
        if (result.data) onSaved(result.data);
        else
          fail(
            result.status === 409
              ? "상대가 위시를 수정했어요. 작성 내용은 남겨뒀어요. 최신 목록으로 돌아가려면 작성 내용을 폐기해 주세요."
              : result.error,
            result.status === 409,
          );
      } catch {
        fail("연결을 확인하고 다시 저장해 주세요. 작성 내용은 유지했어요.");
      }
    });
  }
  if (!portal) return null;
  return createPortal(
    <dialog
      ref={dialog}
      className="wish-sheet"
      aria-labelledby={`${identity}-heading`}
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onClose();
      }}
      onPointerDown={(event) => {
        if (pending || event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          onClose();
      }}
    >
      <header className="wish-sheet-heading">
        <h2 id={`${identity}-heading`}>{record.version ? "위시 수정" : "위시 추가"}</h2>
        <button
          className="icon-button"
          type="button"
          disabled={pending}
          onClick={onClose}
          aria-label="작성 취소"
          title="닫기"
        >
          <X size={21} aria-hidden="true" />
        </button>
      </header>
      <form
        id={`${identity}-form`}
        className="wish-sheet-body"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <fieldset className="wish-fields" disabled={pending || conflict}>
          <fieldset className="wish-kind" aria-label="위시 종류">
            <button
              type="button"
              aria-pressed={content.kind === "place"}
              onClick={() => change({ kind: "place" })}
            >
              장소
            </button>
            <button
              type="button"
              aria-pressed={content.kind === "activity"}
              onClick={() => change({ kind: "activity" })}
            >
              활동
            </button>
          </fieldset>
          {content.kind === "place" && (
            <>
              <fieldset className="wish-sources" aria-label="장소 입력 방법">
                <button
                  type="button"
                  aria-label="장소 검색"
                  aria-pressed={source === "search"}
                  onClick={() => chooseSource("search")}
                >
                  <Search size={16} aria-hidden="true" />
                  검색
                </button>
                <button
                  type="button"
                  aria-pressed={source === "link"}
                  onClick={() => chooseSource("link")}
                >
                  <Link2 size={16} aria-hidden="true" />
                  링크
                </button>
                <button
                  type="button"
                  aria-pressed={source === "favorites"}
                  onClick={() => chooseSource("favorites")}
                >
                  <Star size={16} aria-hidden="true" />
                  자주 가는 곳
                </button>
              </fieldset>
              {source === "search" && searching && (
                <PlaceSearchPanel
                  compact
                  site={site}
                  initialQuery={record.query || content.place || content.title}
                  onQueryChange={(query) => {
                    record.query = query;
                  }}
                  onSelect={select}
                />
              )}
              {source === "favorites" && <FavoritePlaces onSelect={select} />}
              {source === "link" && (
                <div className="auth-field">
                  <label htmlFor={`${identity}-map`}>네이버 지도 공유 링크</label>
                  <input
                    id={`${identity}-map`}
                    type="url"
                    inputMode="url"
                    autoCapitalize="none"
                    autoCorrect="off"
                    maxLength={200}
                    value={content.map_url || ""}
                    placeholder="https://naver.me/…"
                    onChange={(event) => change({ map_url: event.target.value.trim() })}
                  />
                </div>
              )}
              {content.place && (
                <div className="wish-selected">
                  <MapPin size={19} aria-hidden="true" />
                  <div className="auth-field">
                    <label className="sr-only" htmlFor={`${identity}-place`}>
                      장소
                    </label>
                    <input
                      id={`${identity}-place`}
                      maxLength={200}
                      value={content.place}
                      onChange={(event) => change({ place: event.target.value, map_url: "" })}
                    />
                  </div>
                  <button
                    className="icon-button"
                    type="button"
                    aria-label="장소 선택 해제"
                    title="선택 해제"
                    onClick={() => {
                      change({ place: "", map_url: "" });
                      record.searching = true;
                      setSearching(true);
                    }}
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
                </div>
              )}
            </>
          )}
          <div className="auth-field">
            <label htmlFor={`${identity}-title`}>위시 이름</label>
            <input
              id={`${identity}-title`}
              required
              maxLength={100}
              value={content.title}
              placeholder={content.kind === "activity" ? "함께 하고 싶은 일" : "장소 이름"}
              onChange={(event) => change({ title: event.target.value })}
            />
          </div>
          <div className="wish-note-field">
            <div className="auth-field">
              <label htmlFor={`${identity}-note`}>메모</label>
              <textarea
                id={`${identity}-note`}
                aria-label="위시 메모"
                rows={3}
                maxLength={1000}
                value={content.note}
                placeholder="기억할 내용"
                onChange={(event) => change({ note: event.target.value })}
              />
            </div>
          </div>
        </fieldset>
      </form>
      <footer className="wish-sheet-footer">
        <div className="wish-sheet-message" role={error ? "alert" : undefined}>
          {error}
        </div>
        <div className="wish-save-actions">
          {conflict && (
            <button className="text-button" type="button" onClick={onDiscard}>
              작성 내용 폐기
            </button>
          )}
          <button
            className="primary-button"
            type="submit"
            form={`${identity}-form`}
            aria-label="위시 저장"
            disabled={pending || conflict || !content.title.trim()}
          >
            {pending ? "저장 중" : "저장"}
          </button>
        </div>
      </footer>
    </dialog>,
    portal,
  );
}
