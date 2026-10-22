"use client";

import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { type PlaceResults, placeText, safePlaceLink } from "@/lib/places";

export function PlaceSearch() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <section className="place-search" aria-label="약속 장소 탐색">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "검색 닫기" : "네이버 장소 검색 열기"}
      </button>
      <div id={panelId}>{open && <SearchPanel />}</div>
    </section>
  );
}

function SearchPanel() {
  const id = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlaceResults | null>(null);
  const [searched, setSearched] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    if (!results) return;
    const clear = () => {
      pending.current?.abort();
      setResults(null);
      setSearched("");
    };
    const timer = setTimeout(clear, 10 * 60 * 1000);
    window.addEventListener("pagehide", clear);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pagehide", clear);
    };
  }, [results]);

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError("");
    setResults(null);
    setSearched("");
    try {
      const response = await fetch("/api/places/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
        cache: "no-store",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "장소를 검색하지 못했어요.");
      if (!controller.signal.aborted) {
        setResults(body);
        setSearched(query.trim());
      }
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(failure instanceof Error ? failure.message : "장소를 검색하지 못했어요.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <div className="place-search-panel">
      <h2>만날 곳 찾아보기</h2>
      <p className="muted">
        검색을 누르면 입력한 검색어를 네이버에 보내요. 지역과 장소 이름으로 찾아보세요.
      </p>
      <form className="place-search-form" onSubmit={search}>
        <div className="auth-field">
          <label htmlFor={id}>장소 검색어</label>
          <input
            id={id}
            required
            maxLength={100}
            value={query}
            autoComplete="off"
            placeholder="예: 성수 카페"
            onChange={(event) => {
              pending.current?.abort();
              setLoading(false);
              setResults(null);
              setSearched("");
              setError("");
              setQuery(event.target.value);
            }}
          />
        </div>
        <button type="submit" className="primary-button" disabled={loading || !query.trim()}>
          {loading ? "검색 중…" : "장소 검색"}
        </button>
      </form>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {loading && (
        <p role="status" className="muted">
          장소를 찾고 있어요…
        </p>
      )}
      {results && (
        <section aria-label="네이버 장소 검색 결과">
          <p className="place-source">
            <a
              href={`https://search.naver.com/search.naver?where=nexearch&query=${encodeURIComponent(searched)}`}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
            >
              NAVER 검색 결과
            </a>
          </p>
          {results.items.length === 0 ? (
            <p role="status">찾은 장소가 없어요. 지역이나 장소 이름을 바꿔 보세요.</p>
          ) : (
            <ol className="place-results">
              {results.items.map((place, index) => {
                const link = safePlaceLink(place.link);
                return (
                  // Read-only results keep provider order and are replaced together; no row state.
                  // biome-ignore lint/suspicious/noArrayIndexKey: provider does not supply unique place IDs
                  <li key={`${index}:${place.title}`}>
                    <h3>
                      <SearchText value={place.title} />
                    </h3>
                    {place.category && (
                      <p className="muted">
                        <SearchText value={place.category} />
                      </p>
                    )}
                    {place.roadAddress && (
                      <p>
                        <SearchText value={place.roadAddress} />
                      </p>
                    )}
                    {place.address && (
                      <p className="muted">
                        <SearchText value={place.address} />
                      </p>
                    )}
                    {place.description && (
                      <p>
                        <SearchText value={place.description} />
                      </p>
                    )}
                    {link && (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        referrerPolicy="no-referrer"
                      >
                        원본 링크 열기
                      </a>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
          <p className="settings-hint">
            검색 결과는 잠시 열람할 수 있어요. 닫거나 새로 검색하면 사라지며, 약속에 자동 저장되지
            않아요.
          </p>
        </section>
      )}
    </div>
  );
}

function SearchText({ value }: { value: string }) {
  return value.split(/(<b>.*?<\/b>)/gi).map((text, index) =>
    /^<b>.*<\/b>$/i.test(text) ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: repeated immutable text fragments have no identity
      <strong key={`${index}:${text}`}>{placeText(text.slice(3, -4))}</strong>
    ) : (
      placeText(text)
    ),
  );
}
