"use client";
import { ArchiveRestore, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, useTransition } from "react";
import { saveFavoritePlace } from "@/app/actions/favorite-places";
import { LoadingRegion } from "@/components/loading-region";
import { PlaceSearchPanel } from "@/components/place-search-panel";
import { ArchiveToggle, RefreshButton } from "@/components/workspace-controls";
import type { FavoritePage, FavoritePlace } from "@/lib/favorite-places";

export function FavoritePlaces({
  onSelect,
  manage = false,
}: {
  onSelect?: (place: string) => void;
  manage?: boolean;
}) {
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState<(FavoritePage & { archived: boolean }) | null>(null);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [pending, startTransition] = useTransition();
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<{ id: string; place?: FavoritePlace } | null>(null);
  const active = useRef<AbortController | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const retry = useRef<{ id: string; version: number; archived: boolean; request: string } | null>(
    null,
  );
  const load = useCallback(
    async (offset = 0) => {
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      setLoading(true);
      try {
        const response = await fetch(`/api/favorite-places?archived=${archived}&offset=${offset}`, {
          cache: "no-store",
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "장소를 불러오지 못했어요.");
        if (controller.signal.aborted) return;
        setPage((previous) => ({
          ...body,
          archived,
          items:
            offset && previous?.archived === archived
              ? [...previous.items, ...body.items].filter(
                  (item, index, all) => all.findIndex((value) => value.id === item.id) === index,
                )
              : body.items,
        }));
        setError("");
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error && cause.name === "Error"
              ? cause.message
              : "목록과 입력은 유지했어요. 다시 불러와 주세요.",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [archived],
  );
  useEffect(() => {
    void load();
    return () => active.current?.abort();
  }, [load]);
  function archive(place: FavoritePlace) {
    if (pending) return;
    const previous = retry.current;
    const request =
      previous?.id === place.id &&
      previous.version === place.version &&
      previous.archived === !place.archived
        ? previous.request
        : crypto.randomUUID();
    retry.current = { id: place.id, version: place.version, archived: !place.archived, request };
    startTransition(async () => {
      try {
        const result = await saveFavoritePlace(
          place.id,
          { label: place.label, destination: place.destination, archived: !place.archived },
          place.version,
          request,
        );
        if (result.error) {
          setError(result.error);
          return;
        }
        retry.current = null;
        setNotice(
          place.archived ? "장소를 복원했어요." : "장소를 삭제했어요. 휴지통에서 복원할 수 있어요.",
        );
        void load();
      } catch {
        setError("연결을 확인하고 다시 시도해 주세요. 목록은 유지했어요.");
      }
    });
  }
  return (
    <section
      className="favorite-places"
      aria-label={manage ? "자주 가는 곳 관리" : "자주 가는 곳 목록"}
    >
      <div className="favorite-places-toolbar">
        {manage ? (
          <ArchiveToggle
            label="장소 목록 범위"
            currentLabel="장소"
            archivedLabel="휴지통"
            archived={archived}
            pending={pending}
            onChange={(value) => {
              setArchived(value);
              setNotice("");
            }}
          />
        ) : (
          <h3>자주 가는 곳</h3>
        )}
        <div className="favorite-places-actions">
          {manage && (
            <button
              type="button"
              className="icon-button"
              aria-label="장소 추가"
              title="장소 추가"
              disabled={pending}
              onClick={(event) => {
                trigger.current = event.currentTarget;
                setEditor({ id: crypto.randomUUID() });
              }}
            >
              <Plus size={20} aria-hidden="true" />
            </button>
          )}
          <RefreshButton
            label="자주 가는 곳 새로고침"
            pending={loading || pending}
            onClick={() => void load()}
          />
        </div>
      </div>
      {manage && (
        <p className="settings-hint">
          삭제한 장소는 휴지통에서 복원할 수 있어요. 이미 저장한 약속·코스는 바뀌지 않아요.
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      <LoadingRegion
        busy={loading || pending}
        disabled={!!page && page.archived !== archived}
        label="자주 가는 곳을 불러오는 중"
        className="loading-results"
      >
        <div style={{ visibility: page && page.archived !== archived ? "hidden" : undefined }}>
          {page && page.items.length === 0 && (
            <p className="muted">
              {archived
                ? "휴지통이 비어 있어요."
                : manage
                  ? "자주 쓰는 장소명이나 주소를 추가해 보세요."
                  : "설정의 ‘자주 가는 곳’에서 장소를 추가해 주세요."}
            </p>
          )}
          <ul className="favorite-place-list">
            {page?.items.map((place) => (
              <li key={place.id}>
                <div>
                  <strong>{place.label}</strong>
                  <p>{place.destination}</p>
                </div>
                <div className="favorite-places-actions">
                  {onSelect && (
                    <button
                      type="button"
                      className="text-button"
                      aria-label={`${place.label} 선택`}
                      onClick={() => onSelect(place.destination)}
                    >
                      선택
                    </button>
                  )}
                  {manage && (
                    <>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`${place.label} 수정`}
                        title="수정"
                        onClick={(event) => {
                          trigger.current = event.currentTarget;
                          setEditor({ id: place.id, place });
                        }}
                      >
                        <Pencil size={18} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`${place.label} ${archived ? "복원" : "삭제"}`}
                        title={archived ? "복원" : "삭제"}
                        onClick={() => archive(place)}
                      >
                        {archived ? (
                          <ArchiveRestore size={18} aria-hidden="true" />
                        ) : (
                          <Trash2 size={18} aria-hidden="true" />
                        )}
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {page?.next_offset != null && (
            <button
              type="button"
              className="text-button"
              onClick={() => void load(page.next_offset || 0)}
            >
              장소 더 보기
            </button>
          )}
        </div>
      </LoadingRegion>
      {editor && (
        <FavoritePlaceEditor
          key={editor.id}
          id={editor.id}
          place={editor.place}
          onClose={() => {
            setEditor(null);
            if (trigger.current?.isConnected) trigger.current.focus();
          }}
          onSaved={() => {
            setEditor(null);
            setNotice("장소를 저장했어요.");
            void load();
            if (trigger.current?.isConnected) trigger.current.focus();
          }}
        />
      )}
    </section>
  );
}

function FavoritePlaceEditor({
  id,
  place,
  onClose,
  onSaved,
}: {
  id: string;
  place?: FavoritePlace;
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const identity = useId();
  const [label, setLabel] = useState(place?.label || ""),
    [destination, setDestination] = useState(place?.destination || "");
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState(""),
    [conflict, setConflict] = useState(false);
  const request = useRef("");
  const destinationInput = useRef<HTMLInputElement>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  function change(update: () => void) {
    request.current = "";
    update();
  }
  return (
    <dialog
      ref={dialog}
      className="favorite-place-dialog"
      aria-labelledby={`${identity}-title`}
      onClose={onClose}
      onCancel={(event) => {
        if (pending) event.preventDefault();
      }}
    >
      <div className="section-heading">
        <h2 id={`${identity}-title`}>{place ? "장소 수정" : "장소 추가"}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="장소 편집 닫기"
          title="닫기"
          disabled={pending}
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (pending || conflict) return;
          request.current ||= crypto.randomUUID();
          startTransition(async () => {
            try {
              const result = await saveFavoritePlace(
                id,
                { label, destination, archived: place?.archived || false },
                place?.version || 0,
                request.current,
              );
              if (result.error) {
                setError(result.error);
                setConflict(result.status === 409);
              } else onSaved();
            } catch {
              setError("연결을 확인하고 다시 저장해 주세요. 작성 내용은 유지했어요.");
            }
          });
        }}
      >
        <fieldset className="favorite-place-fields" disabled={pending || conflict}>
          <div className="auth-field">
            <label htmlFor={`${identity}-label`}>장소 별칭</label>
            <input
              id={`${identity}-label`}
              maxLength={100}
              value={label}
              required
              onChange={(event) => change(() => setLabel(event.target.value))}
              placeholder="예: 자주 가는 카페"
            />
          </div>
          <div className="auth-field">
            <div className="favorite-place-destination-heading">
              <label htmlFor={`${identity}-destination`}>장소명·주소</label>
              <button
                type="button"
                className="icon-button"
                aria-label={searchOpen ? "검색 닫기" : "장소 검색"}
                title={searchOpen ? "검색 닫기" : "장소 검색"}
                aria-expanded={searchOpen}
                aria-controls={`${identity}-search`}
                onClick={() => setSearchOpen(!searchOpen)}
              >
                {searchOpen ? (
                  <X size={18} aria-hidden="true" />
                ) : (
                  <Search size={18} aria-hidden="true" />
                )}
              </button>
            </div>
            <input
              id={`${identity}-destination`}
              ref={destinationInput}
              maxLength={200}
              value={destination}
              required
              onChange={(event) => change(() => setDestination(event.target.value))}
              placeholder="지도에서 찾을 장소명이나 주소"
            />
          </div>
          <div id={`${identity}-search`}>
            {searchOpen && (
              <PlaceSearchPanel
                initialQuery={destination}
                onSelect={(value) => {
                  change(() => setDestination(value));
                  setSearchOpen(false);
                  destinationInput.current?.focus();
                }}
              />
            )}
          </div>
          <p className="settings-hint">
            둘이 함께 쓰는 목록이에요. 저장한 장소를 골라도 코스 저장·확정은 별도로 진행해요.
          </p>
          <div className="editor-actions">
            <button
              type="submit"
              className="primary-button"
              disabled={!label.trim() || !destination.trim()}
            >
              저장
            </button>
          </div>
        </fieldset>
        {error && (
          <p role="alert" className="error-message">
            {error}
            {conflict && " 작성 내용은 남아 있어요. 닫은 뒤 목록을 새로고침하고 다시 열어 주세요."}
          </p>
        )}
      </form>
    </dialog>
  );
}
