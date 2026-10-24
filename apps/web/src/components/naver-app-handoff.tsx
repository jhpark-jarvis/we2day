"use client";
import { Settings2 } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { naverAppLinks, naverShareLink, type RouteMode } from "@/lib/naver-app";

export function NaverAppHandoff({
  place,
  site,
  compact = false,
  extraAction,
  mapUrl = "",
}: {
  place: string;
  mapUrl?: string;
  site: string;
  compact?: boolean;
  extraAction?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const optionsId = useId();
  const [platform, setPlatform] = useState<"ios" | "android">("ios");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [mode, setMode] = useState<RouteMode>("car");
  useEffect(() => {
    if (/Android/i.test(navigator.userAgent)) setPlatform("android");
  }, []);
  const shared = naverShareLink(mapUrl);
  const search = naverAppLinks(site, place);
  const route = naverAppLinks(site, place, { lat, lng, mode });
  if (compact)
    return search ? (
      <a
        className="text-button"
        href={shared || search?.[platform]}
        rel="noreferrer"
        referrerPolicy="no-referrer"
      >
        지도 검색
      </a>
    ) : null;
  if (!place.trim() && !shared)
    return (
      <p className="settings-hint">이 활동에는 장소가 없어요. 플랜에서 장소를 직접 적어 주세요.</p>
    );
  return (
    <section className="naver-handoff" aria-label="네이버 지도 앱 이동">
      <div className="handoff-actions">
        {(shared || search) && (
          <a
            className="primary-button"
            href={shared || search?.[platform]}
            rel="noreferrer"
            referrerPolicy="no-referrer"
          >
            네이버 지도
          </a>
        )}
        {extraAction}
        <button
          type="button"
          className="icon-button"
          aria-label="앱 연결 옵션"
          title="앱 연결 옵션"
          aria-expanded={open}
          aria-controls={optionsId}
          onClick={() => setOpen(!open)}
        >
          <Settings2 size={19} aria-hidden="true" />
        </button>
      </div>
      <p className="settings-hint">
        {shared
          ? "저장한 공유 링크를 열어요. 네이버 지도에서 목적지나 경로를 확인해 주세요."
          : "저장한 장소명·주소로 지도 앱을 열어요. 목적지를 확인하고 운전 길찾기를 선택해 주세요."}
      </p>
      {open && (
        <div className="plan-review" id={optionsId}>
          <h3>선택한 장소 · {place}</h3>
          <p className="settings-hint">
            앱 열기를 누르면 장소 이름과 직접 입력한 목적지 좌표가 네이버 지도 앱으로 전달돼요. 이
            화면에서는 현재 위치를 수집하거나 좌표를 저장하지 않아요.
          </p>
          <div className="auth-field">
            <label htmlFor="naver-app-platform">이동할 휴대폰</label>
            <select
              id="naver-app-platform"
              value={platform}
              onChange={(e) => setPlatform(e.target.value as "ios" | "android")}
            >
              <option value="ios">iPhone · 네이버 지도 앱</option>
              <option value="android">Android · 네이버 지도 앱</option>
            </select>
          </div>

          <details>
            <summary>목적지 좌표로 바로 길찾기</summary>
            <p className="settings-hint">
              직접 확인한 목적지의 위도·경도를 입력하세요. 활동을 바꾸면 입력을 지워요.
            </p>
            <div className="plan-basics">
              <div className="auth-field">
                <label htmlFor="handoff-lat">길찾기 목적지 위도</label>
                <input
                  id="handoff-lat"
                  inputMode="decimal"
                  value={lat}
                  maxLength={20}
                  onChange={(e) => setLat(e.target.value)}
                />
              </div>
              <div className="auth-field">
                <label htmlFor="handoff-lng">길찾기 목적지 경도</label>
                <input
                  id="handoff-lng"
                  inputMode="decimal"
                  value={lng}
                  maxLength={20}
                  onChange={(e) => setLng(e.target.value)}
                />
              </div>
            </div>
            <div className="auth-field">
              <label htmlFor="handoff-mode">네이버 지도 길찾기 방식</label>
              <select
                id="handoff-mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as RouteMode)}
              >
                <option value="car">자동차 길찾기</option>
                <option value="public">대중교통 길찾기</option>
                <option value="walk">도보 길찾기</option>
                <option value="bicycle">자전거 길찾기</option>
                <option value="navigation">내비게이션</option>
              </select>
            </div>
            {route ? (
              <a
                className="primary-button"
                href={route[platform]}
                rel="noreferrer"
                referrerPolicy="no-referrer"
              >
                네이버 지도 앱으로 길찾기 요청
              </a>
            ) : (
              <p className="settings-hint">
                위도31.43~44.35·경도122.37~132.00 범위의 좌표 두 값을 입력하면 길찾기 버튼이 나와요.
              </p>
            )}
          </details>
          <p className="settings-hint">
            앱 실행·도착 여부는 이 화면에서 확인할 수 없어요. 돌아온 뒤 방문 진행은 직접 표시하고,
            바뀐 플랜은 새로고침해 주세요.
          </p>
          <div className="calendar-toolbar">
            <a
              className="text-button"
              href="https://apps.apple.com/app/id311867728"
              target="_blank"
              rel="noreferrer"
              referrerPolicy="no-referrer"
            >
              iPhone 설치 안내
            </a>
            <a
              className="text-button"
              href="https://play.google.com/store/apps/details?id=com.nhn.android.nmap"
              target="_blank"
              rel="noreferrer"
              referrerPolicy="no-referrer"
            >
              Android 설치 안내
            </a>
          </div>
          <p className="settings-hint">
            앱이 열리지 않으면 브라우저의 외부 앱 차단 여부를 확인하거나 장소 이름을 복사해 지도
            앱에서 검색하세요. 자동으로 스토어로 이동시키지 않아요.
          </p>
        </div>
      )}
    </section>
  );
}
