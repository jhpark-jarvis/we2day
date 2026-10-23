"use client";

import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import Link from "@/components/progress-link";
import { type PlaybackRoute, projectRoutes } from "@/lib/route-playback";

export function RoutePlayback({
  items,
  active,
  hasMore,
}: {
  items: readonly PlaybackRoute[];
  active: boolean;
  hasMore: boolean;
}) {
  const frames = useMemo(() => projectRoutes(items), [items]);
  const [index, setIndex] = useState(0),
    [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2000),
    [foreground, setForeground] = useState(true);
  const current = Math.min(index, frames.length - 1);
  const running = playing && active && foreground;
  useEffect(() => {
    const pause = () => {
      setForeground(!document.hidden);
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, []);
  useEffect(() => {
    if (!running || frames.length < 2) return;
    const timer = window.setTimeout(() => {
      if (current >= frames.length - 2) setPlaying(false);
      setIndex(Math.min(current + 1, frames.length - 1));
    }, speed);
    return () => window.clearTimeout(timer);
  }, [running, current, speed, frames.length]);
  if (!frames.length) return null;
  const frame = frames[current];
  const step = (next: number) => {
    setPlaying(false);
    setIndex(next);
  };
  return (
    <section className="route-playback plan-review" aria-label="동선 재생">
      <div className="section-heading">
        <h3>동선 재생</h3>
        <span className="settings-hint">
          {current + 1} / {frames.length}일
        </span>
      </div>
      <svg
        className="route-playback-diagram"
        viewBox="0 0 360 216"
        role="img"
        aria-label={`${frame.date} ${frame.start_name}에서 ${frame.end_name}까지 두 점의 직선`}
      >
        <path
          className="route-playback-grid"
          d="M0 54H360M0 108H360M0 162H360M90 0V216M180 0V216M270 0V216"
        />
        <line
          x1={frame.start[0]}
          y1={frame.start[1]}
          x2={frame.end[0]}
          y2={frame.end[1]}
          className="route-playback-line"
        />
        <circle cx={frame.start[0]} cy={frame.start[1]} r="9" className="route-playback-start" />
        <rect
          x={frame.end[0] - 5}
          y={frame.end[1] - 5}
          width="10"
          height="10"
          className="route-playback-end"
        />
      </svg>
      <div className="route-playback-caption">
        <strong>{frame.date.replace(/^(\d{4})-(\d{2})-(\d{2})$/, "$1년 $2월 $3일")}</strong>
        <p>
          <span>○ 출발</span> {frame.start_name}
        </p>
        <p>
          <span>■ 도착</span> {frame.end_name}
        </p>
      </div>
      <fieldset className="route-playback-controls" aria-label="동선 재생 조작">
        <button
          type="button"
          className="icon-button"
          aria-label="이전 동선"
          title="이전 동선"
          disabled={!active || current <= 0}
          onClick={() => step(current - 1)}
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label={running ? "동선 재생 멈춤" : "동선 재생 시작"}
          title={running ? "멈춤" : "재생"}
          disabled={!active || frames.length < 2}
          onClick={() => {
            if (!running && current === frames.length - 1) setIndex(0);
            setPlaying(!running);
          }}
        >
          {running ? <Pause size={20} aria-hidden="true" /> : <Play size={20} aria-hidden="true" />}
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="다음 동선"
          title="다음 동선"
          disabled={!active || current >= frames.length - 1}
          onClick={() => step(current + 1)}
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
        <label className="route-playback-speed">
          속도
          <select
            aria-label="동선 재생 속도"
            value={speed}
            disabled={!active}
            onChange={(e) => setSpeed(Number(e.target.value))}
          >
            <option value={4000}>느리게</option>
            <option value={2000}>보통</option>
            <option value={1000}>빠르게</option>
          </select>
        </label>
      </fieldset>
      <label className="route-playback-scrubber">
        날짜 탐색
        <input
          type="range"
          min={0}
          max={frames.length - 1}
          value={current}
          aria-label="재생 날짜"
          aria-valuetext={frame.date}
          disabled={!active || frames.length < 2}
          onChange={(e) => step(Number(e.target.value))}
        />
      </label>
      <Link className="text-button" href={`/?date=${frame.date}`}>
        날짜 기록
      </Link>
      <p className="settings-hint">
        불러온 {frames.length}일의 두 점을 날짜순으로 보여줘요. 개략 좌표도이며 지도나 실제 이동
        경로가 아니에요.
      </p>
      {hasMore && (
        <p className="settings-hint">
          아직 불러오지 않은 기록이 있어요. 아래 ‘동선 더 보기’로 추가해 주세요.
        </p>
      )}
    </section>
  );
}
