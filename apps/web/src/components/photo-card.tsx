"use client";

import { useActionState, useEffect, useState } from "react";
import { useFormStatus } from "react-dom";
import { changePhoto } from "@/app/actions/photos";
import { koreanTimestamp, type SharedPhoto } from "@/lib/photos";

function ActionSubmit({ children, ready }: { children: string; ready: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button className="text-button" type="submit" disabled={!ready || pending} aria-busy={pending}>
      {children}
    </button>
  );
}

function PhotoActionForm({
  photo,
  action,
  label,
  onChanged,
}: {
  photo: SharedPhoto;
  action: "trash" | "restore" | "purge";
  label: string;
  onChanged: (message: string) => void;
}) {
  const [requestId, setRequestId] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [state, submit] = useActionState(changePhoto, { error: "" });
  useEffect(() => {
    setRequestId(crypto.randomUUID());
  }, []);
  useEffect(() => {
    if (state.changed) onChanged(state.changed);
  }, [state.changed, onChanged]);
  return (
    <form action={submit} className="photo-action-form">
      <input type="hidden" name="id" value={photo.id} />
      <input type="hidden" name="version" value={photo.lifecycle_version} />
      <input type="hidden" name="request_id" value={requestId} />
      <input type="hidden" name="action" value={action} />
      {action === "purge" && (
        <>
          <p className="error-message">이 사진 파일과 기록을 영구 삭제하면 복구할 수 없어요.</p>
          <div className="auth-field">
            <label htmlFor={`purge-${photo.id}`}>확인 문구 ‘영구 삭제’ 입력</label>
            <input
              id={`purge-${photo.id}`}
              name="confirmation"
              required
              pattern="영구 삭제"
              autoComplete="off"
              placeholder="영구 삭제"
              maxLength={20}
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </div>
        </>
      )}
      <ActionSubmit ready={!!requestId}>{label}</ActionSubmit>
      {state.error && (
        <p className="error-message" role="alert">
          {state.error}
        </p>
      )}
    </form>
  );
}

export function PhotoCard({
  photo,
  userId,
  trash,
  onChanged,
  selected = false,
  selectingDisabled = false,
  onSelect,
  authorName,
}: {
  photo: SharedPhoto;
  userId: string | null;
  trash: boolean;
  onChanged: (message: string) => void;
  selected?: boolean;
  selectingDisabled?: boolean;
  onSelect?: () => void;
  authorName?: string;
}) {
  const [now, setNow] = useState(0);
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const imagePath = `/api/photos/${photo.id}/image${trash ? "?trash=true" : ""}`;
  const canPurge = !!photo.purge_after && new Date(photo.purge_after).valueOf() <= now;
  return (
    <article className="shared-photo-card">
      {!trash && onSelect && (
        <label className="annual-option photo-export-choice">
          <input
            type="checkbox"
            checked={selected}
            disabled={selectingDisabled}
            onChange={onSelect}
          />
          이 사진 내보내기 선택
        </label>
      )}
      {!photo.purging_at && (
        <figure className="photo-draft-story">
          {/* biome-ignore lint/performance/noImgElement: private authenticated image, no public proxy */}
          <img
            src={imagePath}
            alt={photo.caption || `${photo.date} 함께한 날의 사진`}
            width={photo.width}
            height={photo.height}
            loading="lazy"
            onError={() => setImageError(true)}
          />
          <figcaption>
            <small>
              {photo.date} ·{" "}
              {authorName
                ? `${authorName}님의 사진`
                : `${photo.created_by === userId ? "내가" : "상대가"} 남긴 사진`}
            </small>
            <strong>{photo.caption || "함께한 하루의 한 장면"}</strong>
          </figcaption>
        </figure>
      )}
      {imageError && (
        <p className="error-message">사진을 불러오지 못했어요. 목록을 새로고침해 주세요.</p>
      )}
      {photo.purging_at && (
        <p className="photo-local-notice">
          {photo.date} · {photo.caption || "사진"}
          <br />
          영구 삭제를 진행 중이에요. 다시 시도해 파일과 기록 정리를 마무리해 주세요.
        </p>
      )}
      <details className="photo-metadata">
        <summary>휴대폰에서 원본 찾기</summary>
        <dl className="detail-list photo-details">
          <div>
            <dt>올린 사람</dt>
            <dd>{authorName || (photo.created_by === userId ? "나" : "상대방")}</dd>
          </div>
          <div>
            <dt>올린 시각</dt>
            <dd>{koreanTimestamp(photo.uploaded_at)} (한국 시간)</dd>
          </div>
          <div>
            <dt>원본 파일명</dt>
            <dd>{photo.filename}</dd>
          </div>
          <div>
            <dt>촬영 기기</dt>
            <dd>{photo.device || "기기 정보 없음"}</dd>
          </div>
          <div>
            <dt>촬영 시각</dt>
            <dd>{photo.captured_at ? `${photo.captured_at} (사진 기록값)` : "촬영 시각 없음"}</dd>
          </div>
          <div>
            <dt>파일 수정</dt>
            <dd>{photo.file_modified ? koreanTimestamp(photo.file_modified) : "수정 시각 없음"}</dd>
          </div>
        </dl>
      </details>
      {!trash ? (
        <>
          <a className="text-button" href={imagePath} download={`we2day-${photo.date}.webp`}>
            저장된 압축본 내려받기
          </a>
          <PhotoActionForm
            photo={photo}
            action="trash"
            label="사진 휴지통으로 이동"
            onChanged={onChanged}
          />
        </>
      ) : (
        <>
          {photo.trashed_at && (
            <p className="settings-hint">
              휴지통 이동: {koreanTimestamp(photo.trashed_at)} (한국 시간)
            </p>
          )}
          {photo.purge_after && (
            <p className="settings-hint">
              영구 삭제 가능: {koreanTimestamp(photo.purge_after)} (한국 시간)
            </p>
          )}
          {!photo.purging_at && (
            <PhotoActionForm
              photo={photo}
              action="restore"
              label="원래 앨범으로 복구"
              onChanged={onChanged}
            />
          )}
          {canPurge ? (
            <details className="photo-purge-confirm">
              <summary>{photo.purging_at ? "영구 삭제 다시 시도" : "영구 삭제 확인 열기"}</summary>
              <PhotoActionForm
                photo={photo}
                action="purge"
                label={photo.purging_at ? "영구 삭제 다시 시도하기" : "이 사진 영구 삭제하기"}
                onChanged={onChanged}
              />
            </details>
          ) : (
            <p className="settings-hint">
              30일 동안 보관해요. 자동으로 삭제하지 않으며, 삭제 시작 전까지 복구할 수 있어요.
            </p>
          )}
        </>
      )}
    </article>
  );
}
