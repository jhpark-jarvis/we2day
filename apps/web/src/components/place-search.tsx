"use client";

import { Search, X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { FavoritePlaces } from "@/components/favorite-places";
import { LoadingRegion } from "@/components/loading-region";
import { type PlaceResults, placeText, safePlaceLink, selectedPlaceText } from "@/lib/places";

export function PlaceSearch({
  initialQuery = "",
  label = "네이버 장소 검색",
  onSelect,
  children,
  compact = false,
  showFavorites = true,
}: {
  initialQuery?: string;
  label?: string;
  onSelect?: (place: string) => void;
  children?: ReactNode;
  compact?: boolean;
  showFavorites?: boolean;
}) {
  const [panel, setPanel] = useState<"search" | "favorites" | null>(null);
  const open = panel === "search";
  const id = useId();
  return (
    <section className={`place-search${compact ? " place-search-inline" : ""}`} aria-label={label}>
      <div className="place-search-actions">
        {children && <div className="place-search-context">{children}</div>}
        {showFavorites && onSelect && (
          <button
            type="button"
            className="text-button favorite-places-trigger"
            aria-expanded={panel === "favorites"}
            aria-controls={id}
            onClick={() => setPanel(panel === "favorites" ? null : "favorites")}
          >
            자주 가는 곳
          </button>
        )}
        <button
          type="button"
          className={compact ? "icon-button" : "text-button"}
          aria-label={open ? "검색 닫기" : "장소 검색"}
          title={open ? "검색 닫기" : "장소 검색"}
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setPanel(open ? null : "search")}
        >
          {compact ? (
            open ? (
              <X size={18} aria-hidden="true" />
            ) : (
              <Search size={18} aria-hidden="true" />
            )
          ) : open ? (
            "검색 닫기"
          ) : (
            "장소 검색"
          )}
        </button>
      </div>
      <div id={id}>
        {panel === "favorites" && onSelect && (
          <FavoritePlaces
            onSelect={(place) => {
              onSelect(place);
              setPanel(null);
            }}
          />
        )}
        {open && (
          <SearchPanel
            initialQuery={initialQuery}
            onSelect={
              onSelect &&
              ((place) => {
                onSelect(place);
                setPanel(null);
              })
            }
          />
        )}
      </div>
    </section>
  );
}

function SearchPanel({
  initialQuery,
  onSelect,
}: {
  initialQuery: string;
  onSelect?: (place: string) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState(initialQuery.slice(0, 100));
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

  async function search() {
    const value = query.trim();
    if (!value || loading) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    try {
      const response = await fetch("/api/places/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: value }),
        cache: "no-store",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]),
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(typeof body.error === "string" ? body.error : "장소를 검색하지 못했어요.");
      if (!body || !Array.isArray(body.items)) throw new Error("장소를 검색하지 못했어요.");
      if (!controller.signal.aborted) {
        setError("");
        setResults(body);
        setSearched(value);
      }
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error && failure.name !== "TimeoutError"
            ? failure.message
            : "장소 검색에 연결하지 못했어요. 다시 시도해 주세요.",
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <LoadingRegion busy={loading} label="장소를 찾는 중">
      <search className="place-search-panel" aria-label="장소 검색 입력">
        <p className="settings-hint">
          지역과 장소 이름으로 검색해 보세요. 검색어는 네이버로 전송돼요.
        </p>
        <div className="place-search-form">
          <div className="auth-field">
            <label htmlFor={id}>장소 검색어</label>
            <input
              id={id}
              type="search"
              enterKeyHint="search"
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
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                  // Search can live inside an appointment or activity form.
                  event.preventDefault();
                  event.stopPropagation();
                  void search();
                }
              }}
            />
          </div>
          <button
            type="button"
            className="primary-button"
            disabled={loading || !query.trim()}
            onClick={() => void search()}
          >
            검색
          </button>
        </div>
        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {results && (
          <section aria-label="네이버 장소 검색 결과">
            <p className="place-source">
              <a
                href={`https://map.naver.com/p/search/${encodeURIComponent(searched)}`}
                target="_blank"
                rel="noopener noreferrer"
                referrerPolicy="no-referrer"
              >
                NAVER 지역 검색
              </a>
            </p>
            {results.items.length === 0 ? (
              <p role="status">찾은 장소가 없어요. 지역이나 장소 이름을 바꿔 보세요.</p>
            ) : (
              <ol className="place-results">
                {results.items.map((place, index) => {
                  const link = safePlaceLink(place.link);
                  const destination = selectedPlaceText(place);
                  return (
                    // Provider order is preserved; no stable place IDs are supplied.
                    // biome-ignore lint/suspicious/noArrayIndexKey: transient immutable result rows
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
                          상세 보기
                        </a>
                      )}
                      {onSelect && (
                        <div className="place-result-actions">
                          <button
                            type="button"
                            className="text-button"
                            aria-label={`${placeText(place.title.replace(/<\/?b>/gi, ""))} 선택`}
                            disabled={!destination || destination.length > 200}
                            onClick={() => onSelect(destination)}
                          >
                            장소 선택
                          </button>
                          {destination.length > 200 && (
                            <span className="settings-hint">
                              장소명이 길어요. 필요한 이름이나 주소를 직접 입력해 주세요.
                            </span>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        )}
      </search>
    </LoadingRegion>
  );
}

function SearchText({ value }: { value: string }) {
  return value.split(/(<b>.*?<\/b>)/gi).map((text, index) =>
    /^<b>.*<\/b>$/i.test(text) ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: immutable text fragments have no identity
      <strong key={`${index}:${text}`}>{placeText(text.slice(3, -4))}</strong>
    ) : (
      placeText(text)
    ),
  );
}
