"use client";

import { Check, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LoadingRegion } from "@/components/loading-region";
import { type PreparedPhoto, preparePhoto } from "@/lib/photo-preparation";

type Draft = {
  id: string;
  filename: string;
  caption: string;
  photo?: PreparedPhoto & { url: string };
  state: "preparing" | "ready" | "invalid" | "uploading" | "saved" | "failed";
  error: string;
};
function size(bytes: number) {
  return `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("ko-KR")} KB`;
}
export function PhotoPreparation({
  today,
  selectedDate,
  canSave = false,
  onDateChange,
  onSaved,
}: {
  today: string;
  selectedDate?: string;
  canSave?: boolean;
  onDateChange?: (date: string) => void;
  onSaved?: (date: string) => void;
}) {
  const [date, setDate] = useState(selectedDate ?? today);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [locked, setLocked] = useState(false);
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const urls = useRef(new Set<string>());
  const input = useRef<HTMLInputElement>(null);
  const running = useRef(false);
  const lockedDate = useRef("");
  const validDate = !!date && date >= "2000-01-01" && date <= "2100-12-31";
  useEffect(() => {
    if (selectedDate !== undefined && !locked) setDate(selectedDate);
  }, [selectedDate, locked]);
  useEffect(() => {
    setReady(true);
    const ownedUrls = urls.current;
    return () => {
      controller.current?.abort();
      for (const url of ownedUrls) URL.revokeObjectURL(url);
      ownedUrls.clear();
    };
  }, []);
  const release = () => {
    controller.current?.abort();
    for (const url of urls.current) URL.revokeObjectURL(url);
    urls.current.clear();
  };
  const clear = () => {
    if (running.current) return;
    release();
    setDrafts([]);
    setBusy(false);
    setLocked(false);
    setNotice("");
    lockedDate.current = "";
    if (input.current) input.current.value = "";
  };
  const patch = (id: string, change: Partial<Draft>) =>
    setDrafts((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, ...change } : draft)),
    );
  const select = async (files: File[]) => {
    if (!files.length || running.current) return;
    clear();
    if (files.length > 20) {
      setNotice("한 번에 20장까지 선택할 수 있어요. 사진을 나눠서 골라주세요.");
      return;
    }
    const active = new AbortController();
    controller.current = active;
    const chosen: Draft[] = files.map((file) => ({
      id: crypto.randomUUID(),
      filename: file.name,
      caption: "",
      state: "preparing",
      error: "",
    }));
    setDrafts(chosen);
    setBusy(true);
    // Decode one original at a time to keep mobile memory bounded.
    for (let index = 0; index < files.length; index++) {
      if (active.signal.aborted) return;
      try {
        const photo = await preparePhoto(files[index], active.signal);
        if (active.signal.aborted) return;
        const url = URL.createObjectURL(photo.blob);
        urls.current.add(url);
        patch(chosen[index].id, { photo: { ...photo, url }, state: "ready" });
      } catch (failure) {
        if (active.signal.aborted) return;
        patch(chosen[index].id, {
          state: "invalid",
          error: failure instanceof Error ? failure.message : "사진을 준비하지 못했어요.",
        });
      }
    }
    if (!active.signal.aborted) setBusy(false);
  };
  const remove = (draft: Draft) => {
    if (locked || busy || running.current) return;
    if (draft.photo) {
      URL.revokeObjectURL(draft.photo.url);
      urls.current.delete(draft.photo.url);
    }
    setDrafts((current) => current.filter((item) => item.id !== draft.id));
  };
  const save = async () => {
    if (!validDate || busy || running.current || !canSave) return;
    const pending = drafts.filter(
      (draft) => draft.photo && ["ready", "failed"].includes(draft.state),
    );
    if (!pending.length) return;
    running.current = true;
    setSaving(true);
    setLocked(true);
    lockedDate.current ||= date;
    const active = new AbortController();
    controller.current = active;
    let successes = 0;
    try {
      for (const draft of pending) {
        if (active.signal.aborted) break;
        const photo = draft.photo;
        if (!photo) continue;
        patch(draft.id, { state: "uploading", error: "" });
        try {
          const bytes = new Uint8Array(await photo.blob.arrayBuffer());
          let binary = "";
          for (let offset = 0; offset < bytes.length; offset += 8192)
            binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
          const response = await fetch("/api/photos", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              request_id: draft.id,
              date: lockedDate.current,
              caption: draft.caption,
              filename: photo.filename,
              device: photo.device,
              captured_at: photo.capturedAt,
              file_modified: photo.fileModified,
              image: btoa(binary),
            }),
            signal: AbortSignal.any([active.signal, AbortSignal.timeout(40_000)]),
          });
          const result: { error?: string } = await response.json();
          if (!response.ok) throw new Error(result.error || "사진을 저장하지 못했어요.");
          if (active.signal.aborted) break;
          patch(draft.id, { state: "saved", error: "" });
          successes++;
        } catch (failure) {
          if (active.signal.aborted) break;
          patch(draft.id, {
            state: "failed",
            error:
              failure instanceof Error && failure.name === "Error"
                ? failure.message
                : "저장 결과를 확인하지 못했어요. 다시 시도해 주세요.",
          });
        }
      }
    } finally {
      running.current = false;
      if (!active.signal.aborted) {
        setSaving(false);
        if (successes) onSaved?.(lockedDate.current);
      }
    }
  };
  const successful = drafts.filter((draft) => draft.state === "saved").length;
  const prepared = drafts.filter((draft) => draft.photo).length;
  const failed = drafts.some((draft) => draft.state === "failed");
  const pending = drafts.some((draft) => ["ready", "failed"].includes(draft.state));
  const complete = prepared > 0 && successful === prepared;
  return (
    <section className="photo-preparation" aria-label="사진 준비">
      <p className="photo-local-notice" role="note">
        {canSave
          ? "여러 장을 골라 한 번에 저장할 수 있어요. 원본은 전송하지 않고 사진마다 압축해서 저장해요."
          : "사진은 이 기기에서만 준비해요. 공유 공간에 저장되지 않으며, 새로고침하면 선택이 사라져요."}
      </p>
      <LoadingRegion busy={busy} label="사진을 한 장씩 압축하고 있어요">
        <div className="photo-controls">
          <div className="auth-field">
            <label htmlFor="photo-date">만난 날짜</label>
            <input
              id="photo-date"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              required
              disabled={!ready || saving || locked}
              value={date}
              onChange={(event) => {
                setDate(event.target.value);
                onDateChange?.(event.target.value);
              }}
            />
          </div>
          <div className="auth-field">
            <label htmlFor="photo-file">사진 선택</label>
            <input
              ref={input}
              id="photo-file"
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={!ready || saving || locked}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                event.target.value = "";
                void select(files);
              }}
            />
            <p className="muted">JPEG·PNG·WebP · 최대 20장 · 한 장당 20MB</p>
          </div>
        </div>
      </LoadingRegion>
      {!validDate && <p className="error-message">2000~2100년 사이의 만난 날짜를 선택해 주세요.</p>}
      {notice && (
        <p className="error-message" role="alert">
          {notice}
        </p>
      )}
      <div className="photo-batch-toolbar">
        <span className="muted" aria-live="polite">
          {drafts.length
            ? `${drafts.length}장 선택 · ${successful}장 저장`
            : "사진을 선택해 주세요"}
        </span>
        <button
          className="text-button"
          type="button"
          disabled={saving || (!drafts.length && !notice)}
          onClick={clear}
        >
          선택 해제
        </button>
      </div>
      <ul className="photo-batch-list" aria-label="선택한 사진">
        {drafts.map((draft, index) => (
          <li key={draft.id} className="photo-batch-item" aria-label={`${index + 1}번째 사진`}>
            <div className="section-heading">
              <strong>{draft.filename}</strong>
              {!locked && (
                <button
                  className="icon-button"
                  type="button"
                  aria-label={`${draft.filename} 선택 해제`}
                  title="선택 해제"
                  disabled={busy}
                  onClick={() => remove(draft)}
                >
                  <X size={18} aria-hidden="true" />
                </button>
              )}
              {draft.state === "saved" && <Check size={20} aria-label="저장 완료" />}
            </div>
            {draft.photo && (
              <>
                <figure className="photo-draft-story">
                  {/* biome-ignore lint/performance/noImgElement: local object URL, never sent to a server */}
                  <img
                    src={draft.photo.url}
                    loading="lazy"
                    decoding="async"
                    alt="선택한 사진의 압축 미리보기"
                    width={draft.photo.width}
                    height={draft.photo.height}
                  />
                  <figcaption>
                    <small>{date || "날짜를 선택해 주세요"} · 이 기기의 미리보기</small>
                  </figcaption>
                </figure>
                <p className="muted">
                  {size(draft.photo.originalBytes)} → {size(draft.photo.blob.size)} ·{" "}
                  {draft.photo.width} × {draft.photo.height} ·{" "}
                  {draft.photo.blob.type === "image/jpeg" ? "JPEG" : "WebP"}
                </p>
                <details className="photo-batch-details">
                  <summary>사진 정보</summary>
                  <dl className="detail-list photo-details">
                    <div>
                      <dt>촬영 기기</dt>
                      <dd>{draft.photo.device || "사진에 기기 정보가 없어요"}</dd>
                    </div>
                    <div>
                      <dt>사진에 기록된 촬영 시각</dt>
                      <dd>{draft.photo.capturedAt || "사진에 촬영 시각이 없어요"}</dd>
                    </div>
                    <div>
                      <dt>파일 수정 시각 (한국 시간)</dt>
                      <dd>
                        {draft.photo.fileModified
                          ? new Intl.DateTimeFormat("ko-KR", {
                              dateStyle: "medium",
                              timeStyle: "short",
                              timeZone: "Asia/Seoul",
                            }).format(new Date(draft.photo.fileModified))
                          : "알 수 없어요"}
                      </dd>
                    </div>
                  </dl>
                  <p className="settings-hint">
                    파일 수정 시각은 촬영 시각과 다를 수 있어요. 위치 정보는 압축본에 넣지 않아요.
                    올린 사람과 저장 시각은 저장할 때 기록해요.
                  </p>
                  {validDate && (
                    <a
                      className="auth-button photo-download"
                      href={draft.photo.url}
                      download={`we2day-${date}${drafts.length > 1 ? `-${index + 1}` : ""}.${draft.photo.blob.type === "image/jpeg" ? "jpg" : "webp"}`}
                    >
                      압축본 내려받기
                    </a>
                  )}
                </details>
                {canSave && (
                  <div className="auth-field">
                    <label htmlFor={`caption-${draft.id}`}>
                      {drafts.length === 1 ? "이 사진의 한마디" : `${index + 1}번째 사진의 한마디`}
                    </label>
                    <textarea
                      id={`caption-${draft.id}`}
                      maxLength={500}
                      rows={2}
                      value={draft.caption}
                      disabled={locked || saving}
                      placeholder="함께한 장면을 짧게 남겨보세요."
                      onChange={(event) => patch(draft.id, { caption: event.target.value })}
                    />
                  </div>
                )}
              </>
            )}
            <div className="photo-batch-status" aria-live="polite">
              {draft.error ? (
                <p className="error-message" role="alert">
                  {draft.error}
                </p>
              ) : (
                <p>
                  {draft.state === "preparing"
                    ? "사진 준비 중"
                    : draft.state === "uploading"
                      ? "저장 중…"
                      : draft.state === "saved"
                        ? "저장 완료"
                        : "업로드 준비 완료"}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
      {canSave && prepared > 0 && (
        <div className="photo-save-panel">
          <LoadingRegion busy={saving} label="선택한 사진을 순서대로 저장하고 있어요">
            <button
              className="primary-button"
              type="button"
              disabled={!validDate || busy || saving || !pending}
              onClick={() => void save()}
            >
              {complete
                ? "저장 완료"
                : failed
                  ? prepared === 1
                    ? "같은 사진 다시 저장"
                    : "실패한 사진 다시 저장"
                  : drafts.length === 1
                    ? "둘의 사진으로 저장"
                    : `${prepared}장 함께 저장`}
            </button>
          </LoadingRegion>
          <div className="photo-batch-summary" role="status">
            {complete
              ? prepared === 1
                ? "둘의 사진으로 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요."
                : `${successful}장을 저장했어요. 창을 닫으면 앨범에서 확인할 수 있어요.`
              : failed && !saving
                ? "저장된 사진은 유지돼요. 실패한 사진만 다시 시도해 주세요."
                : saving
                  ? `${successful} / ${prepared}장 저장`
                  : "날짜는 모든 사진에 동일하게 적용해요."}
          </div>
          {locked && !complete && !saving && (
            <p className="settings-hint">
              중복 저장을 막기 위해 같은 요청으로 재시도해요. 저장 결과가 확인될 때까지 선택을
              유지해 주세요.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
