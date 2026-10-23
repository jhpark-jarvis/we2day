"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  Children,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { LoadingRegion } from "@/components/loading-region";
import { PhotoCard } from "@/components/photo-card";
import { PhotoPreparation } from "@/components/photo-preparation";
import Link from "@/components/progress-link";
import { RefreshButton } from "@/components/workspace-controls";
import { isSupportedDate } from "@/lib/calendar";
import type { PhotoPage, SharedPhoto } from "@/lib/photos";

export function PhotoWorkspace({
  today,
  userId,
  canSave,
  names = {},
  trash = false,
}: {
  today: string;
  userId: string | null;
  canSave: boolean;
  names?: Record<string, string>;
  trash?: boolean;
}) {
  const [date, setDate] = useState(trash ? "" : today);
  const [recordId, setRecordId] = useState("");
  const [items, setItems] = useState<SharedPhoto[]>([]);
  const [loadedAlbum, setLoadedAlbum] = useState("");
  const [after, setAfter] = useState<string | null>(null);
  const [loading, setLoading] = useState(canSave);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const album = trash ? `trash:${date}` : date;
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const exportRequest = useRef<AbortController | null>(null);
  const downloadUrl = useRef("");
  useEffect(
    () => () => {
      exportRequest.current?.abort();
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    },
    [],
  );
  const exportSelected = async () => {
    if (!selected.length || exporting) return;
    const controller = new AbortController();
    exportRequest.current = controller;
    setExporting(true);
    setExportError("");
    setNotice("");
    try {
      const response = await fetch("/api/photos/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: selected }),
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(70_000)]),
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.error || "내보내지 못했어요.");
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
      const url = URL.createObjectURL(blob);
      downloadUrl.current = url;
      const link = document.createElement("a");
      link.href = url;
      link.download = `we2day-photos-${date}.zip`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => {
        URL.revokeObjectURL(url);
        if (downloadUrl.current === url) downloadUrl.current = "";
      }, 30_000);
      setNotice("선택한 압축본과 참고 정보의 ZIP 다운로드를 시작했어요.");
    } catch (failure) {
      if (!controller.signal.aborted)
        setExportError(failure instanceof Error ? failure.message : "사진을 내보내지 못했어요.");
    } finally {
      if (!controller.signal.aborted) setExporting(false);
    }
  };
  const changed = useCallback((message: string) => {
    setNotice(message);
    setRecordId("");
    setRefresh((value) => value + 1);
  }, []);
  const active = useRef<AbortController | null>(null);
  const load = async (day: string, cursor: string | null = null) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    if (!cursor) {
      exportRequest.current?.abort();
      setExporting(false);
    }
    try {
      const response = await fetch(
        `/api/photos?${trash ? `trash=true${day ? `&date=${day}` : ""}` : `date=${day}`}${cursor ? `&after=${cursor}` : ""}`,
        {
          cache: "no-store",
          signal: controller.signal,
        },
      );
      const body: PhotoPage & { error?: string } = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) {
        setError(body.error || "사진을 불러오지 못했어요.");
        return;
      }
      setError("");
      setExportError("");
      if (!cursor) {
        setSelected([]);
        setRecordId((current) => (body.items.some((photo) => photo.id === current) ? current : ""));
      }
      setLoadedAlbum(trash ? `trash:${day}` : day);
      setItems((previous) => (cursor ? [...previous, ...body.items] : body.items));
      setAfter(body.next_after);
    } catch {
      if (!controller.signal.aborted) setError("사진을 불러오지 못했어요. 다시 시도해 주세요.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };
  // The request is owned by the selected date; abort old responses on date changes/unmount.
  // biome-ignore lint/correctness/useExhaustiveDependencies: load is scoped to each selection
  useEffect(() => {
    if (canSave && (trash || isSupportedDate(date))) void load(date);
    else {
      setItems([]);
      setAfter(null);
      setLoading(false);
      setError("");
    }
    return () => active.current?.abort();
  }, [date, refresh, canSave, trash]);
  return (
    <>
      {!canSave && (
        <p className="photo-local-notice">
          {trash ? "사진 휴지통을 보려면 " : "사진 준비는 바로 할 수 있어요. 함께 저장하려면 "}
          <Link className="inline-link" href={userId ? "/couple" : "/login"}>
            {userId ? "둘의 공간을 연결해 주세요" : "로그인해 주세요"}
          </Link>
          .
        </p>
      )}
      {!trash && (
        <div>
          <PhotoPreparation
            today={today}
            canSave={canSave}
            onDateChange={(day) => {
              setLoading(canSave);
              setDate(day);
            }}
            onSaved={() => setRefresh((value) => value + 1)}
          />
        </div>
      )}
      {canSave && (
        <section
          className="shared-photo-section"
          aria-label={trash ? "둘의 사진 휴지통" : "날짜별 사진 앨범"}
        >
          <div className="calendar-toolbar">
            <h2>
              {trash
                ? "둘의 사진 휴지통"
                : isSupportedDate(date)
                  ? `${date.slice(0, 4)}년 ${date.slice(5, 7)}월 ${date.slice(8, 10)}일`
                  : "사진을 볼 날짜를 선택해 주세요"}
            </h2>
            <RefreshButton
              label="사진 새로고침"
              pending={loading}
              disabled={!trash && !isSupportedDate(date)}
              onClick={() => {
                setRefresh((value) => value + 1);
              }}
            />
          </div>
          {trash && (
            <div className="trash-filters">
              <div className="auth-field">
                <label htmlFor="trash-date">기록 날짜 (선택)</label>
                <input
                  id="trash-date"
                  type="date"
                  min="2000-01-01"
                  max="2100-12-31"
                  value={date}
                  onChange={(e) => {
                    active.current?.abort();
                    setLoading(true);
                    setDate(e.target.value);
                    setRecordId("");
                    setNotice("");
                  }}
                />
              </div>
              <button
                className="text-button"
                type="button"
                onClick={() => {
                  setDate("");
                  setRecordId("");
                }}
              >
                전체 날짜
              </button>
              <div className="auth-field">
                <label htmlFor="trash-record">사진 기록</label>
                <select
                  id="trash-record"
                  value={recordId}
                  disabled={loading}
                  onChange={(e) => setRecordId(e.target.value)}
                >
                  <option value="">불러온 기록 전체</option>
                  {items.map((photo) => (
                    <option key={photo.id} value={photo.id}>
                      {photo.date} · {photo.caption || photo.filename}
                    </option>
                  ))}
                </select>
              </div>
              <p className="settings-hint">
                사진에 지정한 기록 날짜로 찾아요. 추가 기록이 있으면 ‘사진 더 보기’로 불러올 수
                있어요.
              </p>
            </div>
          )}
          {notice && <p role="status">{notice}</p>}
          {trash && (
            <p className="settings-hint">
              둘 다 사진을 복구할 수 있어요. 최소30일 보관 후 별도 확인으로 영구 삭제하며 자동
              삭제는 하지 않아요.
            </p>
          )}
          <LoadingRegion busy={loading} label="사진을 불러오는 중" className="loading-results">
            {error && (
              <p className="error-message" role="alert">
                {error}
              </p>
            )}
            <div
              inert={loadedAlbum !== album}
              style={{ visibility: loadedAlbum && loadedAlbum !== album ? "hidden" : undefined }}
            >
              {!trash && items.length > 0 && (
                <div className="photo-export-toolbar">
                  <button
                    aria-busy={exporting}
                    className="auth-button"
                    type="button"
                    disabled={exporting || selected.length === 0}
                    onClick={() => void exportSelected()}
                  >
                    {`선택한 사진 ${selected.length}장 ZIP 내보내기`}
                  </button>
                  <p className="settings-hint">
                    한 번에 최대20장 · 압축본과 원본 찾기 정보가 포함돼요. 원본 파일과 앱 복원
                    기능은 포함하지 않아요.
                  </p>
                  {exportError && (
                    <p className="error-message" role="alert">
                      {exportError}
                    </p>
                  )}
                </div>
              )}
              {!error && items.length === 0 && (
                <p className="muted">
                  {trash
                    ? "휴지통이 비어 있어요."
                    : "아직 이 날의 사진이 없어요. 첫 장면을 남겨보세요."}
                </p>
              )}
              <PhotoCollection carousel={!trash} count={items.length}>
                {items
                  .filter((photo) => !recordId || photo.id === recordId)
                  .map((photo) => (
                    <PhotoCard
                      authorName={names[photo.created_by]}
                      key={`${photo.id}:${photo.lifecycle_version}`}
                      photo={photo}
                      userId={userId}
                      trash={trash}
                      onChanged={changed}
                      selected={selected.includes(photo.id)}
                      selectingDisabled={exporting}
                      onSelect={() => {
                        if (!selected.includes(photo.id) && selected.length >= 20) {
                          setExportError("한 번에 최대20장까지 선택해 주세요.");
                          return;
                        }
                        setExportError("");
                        setSelected((current) =>
                          current.includes(photo.id)
                            ? current.filter((id) => id !== photo.id)
                            : [...current, photo.id],
                        );
                      }}
                    />
                  ))}
              </PhotoCollection>
              {after && (
                <button
                  className="auth-button"
                  type="button"
                  disabled={loading}
                  onClick={() => void load(date, after)}
                >
                  사진 더 보기
                </button>
              )}
            </div>
          </LoadingRegion>
        </section>
      )}
    </>
  );
}

function PhotoCollection({
  children,
  carousel,
  count,
}: {
  children: ReactNode;
  carousel: boolean;
  count: number;
}) {
  const id = useId();
  const strip = useRef<HTMLElement>(null);
  const [index, setIndex] = useState(0);
  useEffect(() => {
    setIndex((current) => Math.max(0, Math.min(current, count - 1)));
  }, [count]);
  function move(next: number) {
    const element = strip.current;
    if (!element) return;
    const target = element.children[Math.max(0, Math.min(count - 1, next))] as
      | HTMLElement
      | undefined;
    if (target)
      element.scrollTo({
        left:
          target.getBoundingClientRect().left -
          element.getBoundingClientRect().left +
          element.scrollLeft,
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      });
  }
  function keydown(event: KeyboardEvent<HTMLElement>) {
    if (event.target !== event.currentTarget || !["ArrowLeft", "ArrowRight"].includes(event.key))
      return;
    event.preventDefault();
    move(index + (event.key === "ArrowRight" ? 1 : -1));
  }
  if (!carousel) return <div className="shared-photo-grid">{children}</div>;
  return (
    <>
      {count > 0 && (
        <nav className="photo-slide-navigation" aria-label="사진 이동">
          <span aria-live="polite">
            {index + 1} / {count}
          </span>
          <button
            className="icon-button"
            type="button"
            aria-label="이전 사진"
            title="이전 사진"
            aria-controls={id}
            disabled={index === 0}
            onClick={() => move(index - 1)}
          >
            <ChevronLeft size={20} aria-hidden="true" />
          </button>
          <button
            className="icon-button"
            type="button"
            aria-label="다음 사진"
            title="다음 사진"
            aria-controls={id}
            disabled={index >= count - 1}
            onClick={() => move(index + 1)}
          >
            <ChevronRight size={20} aria-hidden="true" />
          </button>
        </nav>
      )}
      <section
        id={id}
        ref={strip}
        className="shared-photo-carousel"
        aria-label="사진 슬라이드"
        tabIndex={count ? 0 : -1}
        onKeyDown={keydown}
        onScroll={() => {
          const el = strip.current;
          if (el?.clientWidth)
            setIndex(
              Math.max(0, Math.min(count - 1, Math.round(el.scrollLeft / (el.clientWidth + 16)))),
            );
        }}
      >
        {Children.map(children, (child, position) => (
          <div className="photo-slide" inert={position !== index} aria-hidden={position !== index}>
            {child}
          </div>
        ))}
      </section>
    </>
  );
}
