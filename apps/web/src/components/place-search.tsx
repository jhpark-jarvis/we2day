"use client";

import { Search, X } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { FavoritePlaces } from "@/components/favorite-places";
import { PlaceSearchPanel } from "@/components/place-search-panel";

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
          <PlaceSearchPanel
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
