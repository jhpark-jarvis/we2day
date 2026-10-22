"use client";

import { useEffect, useRef, useState } from "react";
import { type PreparedPhoto, preparePhoto } from "@/lib/photo-preparation";
import type { SharedPhoto } from "@/lib/photos";

function size(bytes: number) {
  return `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("ko-KR")} KB`;
}

export function PhotoPreparation({
  today,
  canSave = false,
  onDateChange,
  onSaved,
}: {
  today: string;
  canSave?: boolean;
  onDateChange?: (date: string) => void;
  onSaved?: () => void;
}) {
  const [date, setDate] = useState(today);
  const validDate = !!date && date >= "2000-01-01" && date <= "2100-12-31";
  const [photo, setPhoto] = useState<(PreparedPhoto & { url: string }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [caption, setCaption] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [locked, setLocked] = useState(false);
  const uploadRequest = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const imageUrl = useRef("");
  const input = useRef<HTMLInputElement>(null);
  const release = () => {
    controller.current?.abort();
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    imageUrl.current = "";
  };
  useEffect(() => {
    setReady(true);
    return () => {
      controller.current?.abort();
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    };
  }, []);
  const clear = () => {
    release();
    setPhoto(null);
    setBusy(false);
    setError("");
    setSaved(false);
    setSaveError("");
    setLocked(false);
    setCaption("");
    uploadRequest.current = null;
    if (input.current) input.current.value = "";
  };
  const select = async (file?: File) => {
    if (!file) return;
    release();
    setPhoto(null);
    setError("");
    setSaved(false);
    setSaveError("");
    setLocked(false);
    uploadRequest.current = null;
    setBusy(true);
    const active = new AbortController();
    controller.current = active;
    try {
      const prepared = await preparePhoto(file, active.signal);
      if (active.signal.aborted) return;
      const url = URL.createObjectURL(prepared.blob);
      imageUrl.current = url;
      setPhoto({ ...prepared, url });
    } catch (failure) {
      if (!active.signal.aborted)
        setError(failure instanceof Error ? failure.message : "사진을 준비하지 못했어요.");
    } finally {
      if (!active.signal.aborted) setBusy(false);
    }
  };
  const save = async () => {
    if (!photo || !validDate || saving || saved || !canSave) return;
    setSaving(true);
    setSaveError("");
    setLocked(true);
    uploadRequest.current ||= crypto.randomUUID();
    try {
      const bytes = new Uint8Array(await photo.blob.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 8192)
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
      const response = await fetch("/api/photos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: uploadRequest.current,
          date,
          caption,
          filename: photo.filename,
          device: photo.device,
          captured_at: photo.capturedAt,
          file_modified: photo.fileModified,
          image: btoa(binary),
        }),
        signal: AbortSignal.timeout(40_000),
      });
      const result: SharedPhoto & { error?: string } = await response.json();
      if (!response.ok) {
        setSaveError(result.error || "사진을 저장하지 못했어요.");
        return;
      }
      setSaved(true);
      onSaved?.();
    } catch {
      setSaveError("저장 결과를 확인하지 못했어요. 같은 사진으로 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="photo-preparation" aria-label="사진 준비">
      <h2>사진 한 장으로 남기는 하루</h2>
      <p className="muted">날짜와 사진을 골라 압축본을 미리 확인해 보세요.</p>
      <p className="photo-local-notice" role="note">
        {canSave
          ? "미리보기는 이 기기에만 있어요. ‘둘의 사진으로 저장’을 누르면 압축본과 아래 사진 정보가 둘의 공간에 저장돼요. 원본은 전송하지 않아요."
          : "지금은 이 기기에서만 사진을 준비해요. 공유 공간에 저장되거나 상대에게 전송되지 않으며, 새로고침하면 선택이 사라져요."}
      </p>
      <div className="photo-controls">
        <div className="auth-field">
          <label htmlFor="photo-date">만난 날짜</label>
          <input
            id="photo-date"
            type="date"
            min="2000-01-01"
            max="2100-12-31"
            required
            disabled={saving || locked}
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
            disabled={!ready || saving || locked}
            accept="image/jpeg,image/png,image/webp"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              void select(file);
            }}
          />
          <p className="muted">JPEG·PNG·WebP · 한 장씩 · 최대 20MB</p>
        </div>
      </div>
      {!validDate && <p className="error-message">2000~2100년 사이의 만난 날짜를 선택해 주세요.</p>}
      {busy && <p role="status">사진을 기기에서 압축하고 있어요…</p>}
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      {(busy || photo || error) && (
        <button className="text-button" type="button" disabled={saving} onClick={clear}>
          선택 해제
        </button>
      )}
      {photo && (
        <>
          <figure className="photo-draft-story">
            {/* A local Blob URL must stay in this browser and must not use an image proxy. */}
            {/* biome-ignore lint/performance/noImgElement: local object URL, never sent to a server */}
            <img
              src={photo.url}
              alt="선택한 사진의 압축 미리보기"
              width={photo.width}
              height={photo.height}
            />
            <figcaption>
              <small>{date || "날짜를 선택해 주세요"} · 이 기기의 미리보기</small>
              <strong>함께한 하루의 한 장면</strong>
            </figcaption>
          </figure>
          <dl className="detail-list photo-details">
            <div>
              <dt>원본 파일명</dt>
              <dd>{photo.filename}</dd>
            </div>
            <div>
              <dt>촬영 기기</dt>
              <dd>{photo.device || "사진에 기기 정보가 없어요"}</dd>
            </div>
            <div>
              <dt>사진에 기록된 촬영 시각</dt>
              <dd>
                {photo.capturedAt
                  ? `${photo.capturedAt} (사진 기록값, 시간대 변환 없음)`
                  : "사진에 촬영 시각이 없어요"}
              </dd>
            </div>
            <div>
              <dt>파일 수정 시각 (한국 시간)</dt>
              <dd>
                {photo.fileModified
                  ? new Intl.DateTimeFormat("ko-KR", {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: "Asia/Seoul",
                    }).format(new Date(photo.fileModified))
                  : "알 수 없어요"}
              </dd>
            </div>
            <div>
              <dt>크기</dt>
              <dd>
                {size(photo.originalBytes)} → {size(photo.blob.size)} · {photo.width} ×{" "}
                {photo.height} · WebP
              </dd>
            </div>
          </dl>
          <p className="settings-hint">
            파일 수정 시각은 촬영 시각과 다를 수 있어요. 위치 정보는 압축본에 넣지 않아요.
            {canSave
              ? "올린 사람과 저장 시각은 저장할 때 자동으로 기록해요."
              : "업로더와 업로드 시각은 실제 저장할 때 기록해요."}
          </p>
          {canSave && (
            <div className="photo-save-panel">
              <div className="auth-field">
                <label htmlFor="photo-caption">이 사진의 한마디</label>
                <textarea
                  id="photo-caption"
                  maxLength={500}
                  rows={2}
                  value={caption}
                  disabled={locked || saving}
                  placeholder="함께한 장면을 짧게 남겨보세요."
                  onChange={(event) => setCaption(event.target.value)}
                />
              </div>
              <button
                className="primary-button"
                type="button"
                disabled={!validDate || saving || saved}
                onClick={() => void save()}
              >
                {saved
                  ? "저장 완료"
                  : saving
                    ? "사진 저장 중…"
                    : saveError
                      ? "같은 사진 다시 저장"
                      : "둘의 사진으로 저장"}
              </button>
              {saved && (
                <p role="status">
                  둘의 사진으로 저장했어요. 아래 날짜별 앨범에서 확인할 수 있어요.
                </p>
              )}
              {saveError && (
                <p className="error-message" role="alert">
                  {saveError}
                </p>
              )}
              {locked && !saved && !saving && (
                <p className="settings-hint">
                  같은 요청으로 재시도해 중복 저장을 막아요. 내용을 바꾸려면 선택을 해제하고 다시
                  골라주세요.
                </p>
              )}
            </div>
          )}
          {validDate && (
            <a
              className="auth-button photo-download"
              href={photo.url}
              download={`we2day-${date || "photo"}.webp`}
            >
              압축본 내려받기
            </a>
          )}
        </>
      )}
    </section>
  );
}
