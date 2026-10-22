"use client";
import Image from "next/image";
import Link from "next/link";
import { useState, useTransition } from "react";
import { searchPhotos } from "@/app/actions/photo-search";
import type { PhotoSearchPage, PhotoSearchQuery } from "@/lib/photo-search";
import { zonedTimestamp } from "@/lib/timezones";

export function PhotoSearch({ start, end }: { start: string; end: string }) {
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);
  const [query, setQuery] = useState("");
  const [field, setField] = useState<PhotoSearchQuery["field"]>("caption");
  const [uploader, setUploader] = useState<PhotoSearchQuery["uploader"]>("all");
  const [submitted, setSubmitted] = useState<PhotoSearchQuery | null>(null);
  const [result, setResult] = useState<PhotoSearchPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [pending, run] = useTransition();
  const input = { start_date: startDate, end_date: endDate, query: query.trim(), field, uploader };
  const changed = submitted && JSON.stringify(input) !== JSON.stringify(submitted);
  function search(next: number, conditions: PhotoSearchQuery) {
    setError("");
    run(async () => {
      try {
        const response = await searchPhotos(conditions, next);
        if (response.data) {
          setResult(response.data);
          setSubmitted(conditions);
          setOffset(next);
        } else setError(response.error);
      } catch {
        setError("사진을 찾지 못했어요. 연결을 확인한 뒤 다시 검색해 주세요.");
      }
    });
  }
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search(0, input);
        }}
      >
        <fieldset className="meeting-fields" disabled={pending}>
          <div className="plan-basics">
            <div className="auth-field">
              <label htmlFor="photo-search-start">시작 날짜</label>
              <input
                id="photo-search-start"
                type="date"
                value={startDate}
                min="2000-01-01"
                max="2100-12-31"
                required
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="auth-field">
              <label htmlFor="photo-search-end">마지막 날짜</label>
              <input
                id="photo-search-end"
                type="date"
                value={endDate}
                min="2000-01-01"
                max="2100-12-31"
                required
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          <div className="plan-basics">
            <div className="auth-field">
              <label htmlFor="photo-search-field">검색 대상</label>
              <select
                id="photo-search-field"
                value={field}
                onChange={(e) => setField(e.target.value as PhotoSearchQuery["field"])}
              >
                <option value="caption">사진 한마디</option>
                <option value="filename">원래 파일명</option>
                <option value="device">기기 정보</option>
              </select>
            </div>
            <div className="auth-field">
              <label htmlFor="photo-search-uploader">올린 사람</label>
              <select
                id="photo-search-uploader"
                value={uploader}
                onChange={(e) => setUploader(e.target.value as PhotoSearchQuery["uploader"])}
              >
                <option value="all">둘 다</option>
                <option value="mine">내가 올린 사진</option>
                <option value="partner">상대가 올린 사진</option>
              </select>
            </div>
          </div>
          <div className="auth-field">
            <label htmlFor="photo-search-text">
              {field === "caption"
                ? "사진 한마디"
                : field === "filename"
                  ? "원래 파일명"
                  : "기기 정보"}{" "}
              검색어 (선택)
            </label>
            <input
              id="photo-search-text"
              value={query}
              maxLength={100}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <p className="settings-hint">
            한 번에 최대 366일을 찾아요. 검색어를 비우면 해당 기간의 사진을 모두 찾아요.
          </p>
          <button className="primary-button" type="submit">
            사진 검색
          </button>
        </fieldset>
      </form>
      {pending && <p role="status">사진을 찾고 있어요.</p>}
      {error && (
        <p role="alert" className="error-message">
          {error} 입력한 조건은 유지돼요.
        </p>
      )}
      {result && submitted && (
        <section aria-label="사진 검색 결과" aria-busy={pending}>
          <h2>검색 결과</h2>
          <p className="settings-hint">
            {submitted.start_date} ~ {submitted.end_date} · 이번 페이지 {result.items.length}장
          </p>
          {(changed || error) && (
            <p className="settings-hint">
              아래는 이전에 검색한 결과예요. 새 조건으로 다시 검색해 주세요.
            </p>
          )}
          {result.items.length === 0 && (
            <p className="empty-state">이 조건에 맞는 사진이 없어요.</p>
          )}
          <div className="photo-search-grid">
            {result.items.map((photo) => (
              <article className="photo-search-card" key={photo.id}>
                <Image
                  src={`/api/photos/${photo.id}/image`}
                  alt={photo.caption || "함께한 날의 사진"}
                  width={400}
                  height={300}
                  unoptimized
                />
                <p className="preserve-lines">{photo.caption || "한마디 없는 사진"}</p>
                <details>
                  <summary>휴대폰에서 원본 찾기</summary>
                  <dl className="photo-reference">
                    <dt>원래 파일명</dt>
                    <dd>{photo.filename}</dd>
                    <dt>올린 사람</dt>
                    <dd>{photo.uploaded_by_me ? "나" : "상대"}</dd>
                    <dt>올린 시각 (한국)</dt>
                    <dd>{zonedTimestamp(photo.uploaded_at, "Asia/Seoul")}</dd>
                    <dt>기기 정보</dt>
                    <dd>{photo.device || "제공된 정보 없음"}</dd>
                    <dt>촬영 시각 (파일 참고)</dt>
                    <dd>{photo.captured_at || "제공된 정보 없음"}</dd>
                  </dl>
                  <p className="settings-hint">
                    파일에 담긴 참고 정보예요. 촬영 시각의 시간대는 확인할 수 없으며, 서버에는
                    압축본을 보관해요.
                  </p>
                </details>
                <Link className="text-button" href={`/memories?date=${photo.date}`}>
                  {photo.date} 앨범 보기
                </Link>
              </article>
            ))}
          </div>
          <div className="calendar-toolbar">
            {offset > 0 && (
              <button
                className="text-button"
                type="button"
                disabled={pending}
                onClick={() => search(0, submitted)}
              >
                첫 결과 보기
              </button>
            )}
            {result.next_offset !== null && (
              <button
                className="text-button"
                type="button"
                disabled={pending}
                onClick={() => search(result.next_offset as number, submitted)}
              >
                다음 사진 보기
              </button>
            )}
          </div>
        </section>
      )}
      <p className="settings-hint">
        같은 공간의 저장 완료된 사진만 찾아요. 휴지통의 사진은 휴지통에서 확인해 주세요.
      </p>
    </>
  );
}
