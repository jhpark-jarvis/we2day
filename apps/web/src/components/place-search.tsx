"use client";
import { useEffect, useId, useState } from "react";
import { NaverAppHandoff } from "@/components/naver-app-handoff";
import { normalizePlaceQuery, PLACE_QUERY_MAX_LENGTH } from "@/lib/places";

export function PlaceSearch({ initialQuery = "" }: { initialQuery?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section className="place-search" aria-label="네이버 지도 장소 검색">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        {open ? "검색 닫기" : "네이버 지도 검색"}
      </button>
      <div id={id}>{open && <MapSearchPanel initialQuery={initialQuery} />}</div>
    </section>
  );
}

function MapSearchPanel({ initialQuery }: { initialQuery: string }) {
  const id = useId();
  const [query, setQuery] = useState(initialQuery.slice(0, PLACE_QUERY_MAX_LENGTH));
  const [site, setSite] = useState("");
  useEffect(() => setSite(window.location.origin), []);
  const value = normalizePlaceQuery(query);
  return (
    <search className="plan-review" aria-label="네이버 지도 검색어">
      <div className="auth-field">
        <label htmlFor={id}>장소명 또는 주소</label>
        <input
          id={id}
          type="search"
          value={query}
          maxLength={PLACE_QUERY_MAX_LENGTH}
          placeholder="예: 강남역, 방문할 가게 이름이나 주소"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <NaverAppHandoff place={value} site={site} compact />
      <p className="settings-hint">
        네이버 지도 앱에서 검색해요. 검색어를 바꿔도 작성 중인 약속이나 저장한 장소는 바뀌지 않아요.
      </p>
      {!value && (
        <p className="settings-hint">장소명이나 주소를 입력하면 지도 검색 버튼이 나타나요.</p>
      )}
      <p className="settings-hint">네이버 지도 앱이 설치된 휴대폰에서 이용해 주세요.</p>
    </search>
  );
}
