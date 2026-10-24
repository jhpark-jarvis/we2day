"use client";

import {
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Images,
  MapPin,
  Pencil,
  RefreshCw,
} from "lucide-react";
import Image from "next/image";
import { type KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { AppointmentForm } from "@/components/appointment-form";
import { LoadingRegion } from "@/components/loading-region";
import { LocalAppointmentTime } from "@/components/local-appointment-time";
import { MeetingDayEditor } from "@/components/meeting-day";
import { PageHeading } from "@/components/page-heading";
import { PhotoStory } from "@/components/photo-story";
import { PlaceSearch } from "@/components/place-search";
import Link from "@/components/progress-link";
import { calendarDate, daysInMonth, parseDate } from "@/lib/calendar";
import type { MeetingDay } from "@/lib/meetings";
import type { Appointment } from "@/lib/shared-calendar";
import type { TimezoneView } from "@/lib/timezones";

const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
const examples = [
  {
    id: "walk",
    date: "2026-10-10",
    time: "15:00",
    title: "가을 산책",
    note: "걷다가 잠깐 쉬고, 서로의 한 주 이야기하기.",
    photo: true,
  },
  {
    id: "coffee",
    date: "2026-10-10",
    time: "18:30",
    title: "카페에서 쉬어가기",
    note: "따뜻한 커피 한 잔과 긴 수다.",
    photo: false,
  },
  {
    id: "weekend",
    date: "2026-10-24",
    time: "14:00",
    title: "느긋한 오후 데이트",
    note: "시간만 정했어요. 장소는 함께 골라요.",
    photo: false,
  },
  {
    id: "dinner",
    date: "2026-10-24",
    time: "18:30",
    title: "저녁 약속",
    note: "먹고 싶은 메뉴 같이 고르기.",
    photo: false,
  },
];
type CalendarEvent = (typeof examples)[number] & { place?: string };

export function CalendarWorkspace({
  today,
  preview = false,
  status = "guest",
  memberCount,
  initialEvents = [],
  initialError = "",
  initialDate,
  zones = null,
  participantNames = [],
}: {
  today: string;
  preview?: boolean;
  status?: "ready" | "guest" | "unlinked" | "unavailable";
  memberCount?: number;
  initialEvents?: Appointment[];
  initialError?: string;
  initialDate?: string;
  zones?: TimezoneView | null;
  participantNames?: string[];
}) {
  const [selected, setSelected] = useState(preview ? "2026-10-24" : initialDate || today);
  const [detail, setDetail] = useState<CalendarEvent | null>(null);
  const [savedEvents, setSavedEvents] = useState(initialEvents);
  const [error, setError] = useState(initialError);
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [meetings, setMeetings] = useState<MeetingDay[]>([]);
  const [meetingError, setMeetingError] = useState("");
  const [meetingLoading, setMeetingLoading] = useState(true);
  const [meetingNotice, setMeetingNotice] = useState("");
  const firstLoad = useRef(true);
  const calendarElement = useRef<HTMLDivElement>(null);
  const keyboardFocus = useRef(false);
  const keyboardHelpId = useId();
  const [editing, setEditing] = useState<{ appointment?: Appointment; requestId: string } | null>(
    null,
  );
  useEffect(() => {
    const reset = () => {
      setDetail(null);
      setEditing(null);
    };
    window.addEventListener("we2day:calendar-home", reset);
    return () => window.removeEventListener("we2day:calendar-home", reset);
  }, []);
  const [year, month, day] = parseDate(selected);
  const events: CalendarEvent[] = preview
    ? examples
    : savedEvents.map((event) => ({
        ...event,
        time: event.time?.slice(0, 5) || "시간 미정",
        photo: false,
      }));
  const monthKey = selected.slice(0, 7);
  const dayEvents = events.filter((event) => event.date === selected);
  const leading = new Date(Date.UTC(year, month, 1)).getUTCDay();
  const weekday = weekdays[new Date(Date.UTC(year, month, day)).getUTCDay()];

  useEffect(() => {
    if (!keyboardFocus.current) return;
    calendarElement.current?.querySelector<HTMLButtonElement>(`[data-date="${selected}"]`)?.focus();
    keyboardFocus.current = false;
  }, [selected]);

  function moveDate(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next = new Date(Date.UTC(year, month, day));
    const offsets: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    const offset = offsets[event.key];
    if (offset !== undefined) next.setUTCDate(day + offset);
    else if (event.key === "Home") next.setUTCDate(day - next.getUTCDay());
    else if (event.key === "End") next.setUTCDate(day + 6 - next.getUTCDay());
    else if (event.key === "PageUp" || event.key === "PageDown") {
      const direction = event.key === "PageUp" ? -1 : 1;
      next.setUTCDate(1);
      next.setUTCMonth(month + direction * (event.shiftKey ? 12 : 1));
      next.setUTCDate(Math.min(day, daysInMonth(next.getUTCFullYear(), next.getUTCMonth())));
    } else return;
    event.preventDefault();
    const nextYear = next.getUTCFullYear();
    if (nextYear < 2000 || nextYear > 2100) return;
    const nextSelected = calendarDate(nextYear, next.getUTCMonth(), next.getUTCDate());
    if (nextSelected === selected) return;
    keyboardFocus.current = true;
    setSelected(nextSelected);
    setMeetingNotice("");
  }

  useEffect(() => {
    void refresh;
    if (preview || status !== "ready") return;
    const controller = new AbortController();
    setMeetingLoading(true);
    setMeetingNotice("");
    fetch(`/api/meetings?month=${monthKey}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "만난 날을 불러오지 못했어요.");
        if (!controller.signal.aborted) {
          setMeetingError("");
          setMeetings(body);
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setMeetingError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setMeetingLoading(false);
      });
    return () => controller.abort();
  }, [monthKey, preview, status, refresh]);

  const onMeetingSaved = useCallback((meeting: MeetingDay) => {
    setMeetings((current) => [...current.filter((item) => item.date !== meeting.date), meeting]);
    setMeetingNotice("만남 기록을 저장했어요.");
  }, []);

  useEffect(() => {
    // A manual refresh reruns this request even when the selected month is unchanged.
    void refresh;
    if (preview || status !== "ready") return;
    if (firstLoad.current) {
      firstLoad.current = false;
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    fetch(`/api/appointments?month=${monthKey}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "일정을 불러오지 못했어요.");
        if (!controller.signal.aborted) {
          setError("");
          setSavedEvents(body);
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : "연결하지 못했어요.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [monthKey, preview, status, refresh]);

  const onSaved = useCallback((appointment: Appointment) => {
    setSavedEvents((current) =>
      [...current.filter((event) => event.id !== appointment.id), appointment].sort((a, b) =>
        `${a.date}${a.time || "99"}`.localeCompare(`${b.date}${b.time || "99"}`),
      ),
    );
    setSelected(appointment.date);
    setEditing(null);
    setDetail(null);
    setError("");
  }, []);

  if (editing)
    return (
      <AppointmentForm
        date={selected}
        {...editing}
        onSaved={onSaved}
        onCancel={() => setEditing(null)}
        onReload={() => {
          setEditing(null);
          setDetail(null);
          setRefresh((value) => value + 1);
        }}
      />
    );

  function changeMonth(direction: number) {
    const date = new Date(Date.UTC(year, month + direction, 1));
    const nextYear = date.getUTCFullYear(),
      nextMonth = date.getUTCMonth();
    if (nextYear < 2000 || nextYear > 2100) return;
    setSelected(calendarDate(nextYear, nextMonth, Math.min(day, daysInMonth(nextYear, nextMonth))));
  }

  if (detail)
    return (
      <section className="appointment-detail">
        <PageHeading>
          <p className="eyebrow">{detail.photo ? "OUR LITTLE MEMORY" : "OUR NEXT PLAN"}</p>
          <h1>{detail.title}</h1>
          <p className="muted">
            {detail.date.replaceAll("-", ".")} · {detail.time}
          </p>
        </PageHeading>
        {!preview && <LocalAppointmentTime date={detail.date} time={detail.time} zones={zones} />}
        {detail.photo && (
          <Image
            className="detail-photo"
            src="/demo/autumn.jpg"
            alt="생성된 가을 산책 예시 사진"
            width={960}
            height={640}
          />
        )}
        <section className="appointment-information" aria-label="약속 정보">
          <header className="section-heading">
            <h2>약속 정보</h2>
            {!preview && (
              <button
                type="button"
                className="icon-button"
                aria-label="약속 수정하기"
                title="약속 수정하기"
                onClick={() =>
                  setEditing({
                    appointment: savedEvents.find((event) => event.id === detail.id),
                    requestId: crypto.randomUUID(),
                  })
                }
              >
                <Pencil size={18} aria-hidden="true" />
              </button>
            )}
          </header>
          <dl className="detail-list">
            <div>
              <dt>함께</dt>
              <dd>
                {preview
                  ? "가상 사용자 1 · 가상 사용자 2"
                  : participantNames.join(" · ") || "이름을 불러오지 못했어요"}
              </dd>
            </div>
            <div>
              <dt>장소</dt>
              <dd>
                {preview ? (
                  <span className="appointment-place">
                    <MapPin size={14} aria-hidden="true" />
                    <span>
                      {detail.photo ? "강변 산책길 (예시)" : detail.place || "아직 정하지 않았어요"}
                    </span>
                  </span>
                ) : (
                  <PlaceSearch initialQuery={detail.place || ""} compact>
                    <span className="appointment-place">
                      <MapPin size={14} aria-hidden="true" />
                      <span>{detail.place || "아직 정하지 않았어요"}</span>
                    </span>
                  </PlaceSearch>
                )}
              </dd>
            </div>
          </dl>
          {detail.note && <p className="note-panel">{detail.note}</p>}
        </section>
        {detail.photo && (
          <details className="photo-metadata">
            <summary>사진 정보</summary>
            <dl className="detail-list">
              <div>
                <dt>올린 사람</dt>
                <dd>가상 사용자 1 (예시)</dd>
              </div>
              <div>
                <dt>업로드</dt>
                <dd>2026.10.10 21:12</dd>
              </div>
              <div>
                <dt>촬영 정보</dt>
                <dd>iPhone 15 · 15:42 (예시)</dd>
              </div>
            </dl>
          </details>
        )}
        {preview && <p className="preview-label">화면 미리보기 · 저장되지 않는 예시 데이터</p>}
      </section>
    );

  return (
    <>
      <PageHeading>
        <div>
          <p className="eyebrow">OUR LITTLE PLANS</p>
          <h1>함께할 날들</h1>
          <p className="muted">사소한 약속도 놓치지 않도록.</p>
        </div>
        {preview && <span className="preview-badge">미리보기</span>}
      </PageHeading>
      {!preview && (
        <div className="calendar-toolbar">
          {status === "ready" ? (
            <>
              <button
                type="button"
                className="primary-button"
                onClick={() => setEditing({ requestId: crypto.randomUUID() })}
              >
                약속 추가하기
              </button>
              <details className="schedule-tools">
                <summary>
                  일정 도구
                  <ChevronDown className="schedule-tools-chevron" size={16} aria-hidden="true" />
                </summary>
                <nav aria-label="일정 도구">
                  <Link href={`/plans?date=${selected}`}>플랜</Link>
                  <Link href={`/today?date=${selected}`}>데이트 코스</Link>
                  <Link href="/reminders">다가오는 일정</Link>
                  <Link href="/calendar/export">캘린더 내보내기</Link>
                </nav>
              </details>
              {memberCount === 1 && (
                <Link className="text-button" href="/couple">
                  초대
                </Link>
              )}
            </>
          ) : (
            <Link className="text-button" href={status === "guest" ? "/login" : "/couple"}>
              {status === "guest"
                ? "로그인하고 약속 함께 보기"
                : status === "unlinked"
                  ? "둘의 공간 연결하기"
                  : "공간 연결 확인하기"}
            </Link>
          )}
        </div>
      )}
      {!preview && error && status !== "guest" && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      <LoadingRegion busy={loading} label="일정을 불러오는 중">
        <div className="calendar-workspace">
          <section className="month-calendar" aria-label="월 달력">
            <div className="month-heading">
              <h2 aria-live="polite" aria-atomic="true">
                {year}년 {month + 1}월
              </h2>
              <div className="month-actions">
                <button className="today-button" type="button" onClick={() => setSelected(today)}>
                  오늘
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => changeMonth(-1)}
                  aria-label="이전 달"
                >
                  <ChevronLeft size={18} />
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => changeMonth(1)}
                  aria-label="다음 달"
                >
                  <ChevronRight size={18} />
                </button>
                {!preview && status === "ready" && (
                  <button
                    className="icon-button calendar-refresh"
                    type="button"
                    aria-label="일정 새로고침"
                    title="일정 새로고침"
                    aria-busy={loading}
                    disabled={loading}
                    onClick={() => setRefresh((value) => value + 1)}
                  >
                    <RefreshCw size={18} aria-hidden="true" />
                  </button>
                )}
              </div>
            </div>
            <div className="weekdays" aria-hidden="true">
              {weekdays.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </div>
            <p id={keyboardHelpId} className="sr-only">
              방향키로 날짜와 주를 이동하고, Home·End로 주의 처음과 끝, Page Up·Down으로 월을
              이동해요. Shift와 Page Up·Down은 연도를 이동해요.
            </p>
            <div className="calendar-days" ref={calendarElement}>
              {weekdays.slice(0, leading).map((weekday) => (
                <span key={`blank-${weekday}`} aria-hidden="true" />
              ))}
              {Array.from({ length: daysInMonth(year, month) }, (_, i) => {
                const value = i + 1,
                  key = calendarDate(year, month, value),
                  hasEvent = events.some((event) => event.date === key),
                  hasMet =
                    !preview && meetings.some((meeting) => meeting.date === key && meeting.met);
                return (
                  <button
                    className={`calendar-day${(leading + i) % 7 === 0 ? " sunday" : ""}${hasMet ? " has-meeting" : ""}`}
                    key={key}
                    type="button"
                    aria-label={`${month + 1}월 ${value}일${hasEvent ? ", 약속 있음" : ""}${hasMet ? ", 만난 날" : ""}`}
                    aria-pressed={key === selected}
                    aria-current={key === today ? "date" : undefined}
                    aria-describedby={key === selected ? keyboardHelpId : undefined}
                    data-date={key}
                    tabIndex={key === selected ? 0 : -1}
                    onKeyDown={moveDate}
                    onClick={() => {
                      setSelected(key);
                      setMeetingNotice("");
                    }}
                  >
                    <span className="day-number">
                      <span className="day-label">{value}</span>
                      <span
                        className={`day-dot${hasEvent ? " has-event" : ""}`}
                        aria-hidden="true"
                      />
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="calendar-caption">
              {preview || status !== "ready" ? "함께할 날들" : "작은 점은 약속 · 밑줄은 만난 날"}
            </p>
          </section>
          <div className="day-workspace">
            <section className="agenda" aria-label="선택한 날짜의 약속">
              <header className="agenda-heading">
                <h2 aria-live="polite">
                  {month + 1}월 {day}일 <small>{weekday}요일</small>
                </h2>
                <span className="muted">약속 {dayEvents.length}</span>
              </header>
              {!preview && status === "ready" && (
                <div className="calendar-toolbar agenda-actions">
                  <Link className="text-button" href={`/today?date=${selected}`}>
                    {selected === today ? "오늘의 데이트 코스" : "데이트 코스"}
                  </Link>
                </div>
              )}
              {dayEvents.length ? (
                dayEvents.map((event) => (
                  <button
                    className="appointment-row"
                    type="button"
                    key={event.id}
                    onClick={() => setDetail(event)}
                  >
                    <time>{event.time}</time>
                    <span>
                      <strong>{event.title}</strong>
                      <small>{event.note}</small>
                    </span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </button>
                ))
              ) : (
                <div className="empty-state">
                  <CalendarDays size={24} aria-hidden="true" />
                  <h3>아직 약속이 없어요</h3>
                  <p>함께할 시간을 담아갈 공간이에요.</p>
                </div>
              )}
            </section>
            {!preview && status === "ready" && (
              <>
                {meetingError && (
                  <p className="error-message" role="alert">
                    만남 기록을 불러오지 못했어요. 일정 새로고침으로 다시 시도해 주세요.
                  </p>
                )}
                <LoadingRegion
                  busy={meetingLoading}
                  disabled={Boolean(meetingError)}
                  label="만남 기록을 불러오는 중"
                >
                  <MeetingDayEditor
                    key={`${selected}:${meetings.find((item) => item.date === selected)?.version || 0}`}
                    date={selected}
                    today={today}
                    record={meetings.find((item) => item.date === selected)}
                    onSaved={onMeetingSaved}
                    onReload={() => setRefresh((value) => value + 1)}
                  />
                </LoadingRegion>
                {meetingNotice && (
                  <p className="settings-hint" role="status">
                    {meetingNotice}
                  </p>
                )}
              </>
            )}
            {!preview && status === "ready" && (
              <section className="memory-section" aria-label="하루 동선">
                <h2>하루 동선</h2>
                <Link
                  className="text-button"
                  href={`/memories/search?type=routes&date=${selected}`}
                >
                  동선 보기
                </Link>
              </section>
            )}
            {preview ? (
              <section className="memory-section" aria-label="지난 기록">
                <h2>지난 기록</h2>
                <PhotoStory onOpen={() => setDetail(examples[0])} />
                <p className="preview-label">생성된 예시 사진 · 실제 사진이 아닙니다</p>
              </section>
            ) : (
              <section className="memory-section">
                <header>
                  <Images size={17} aria-hidden="true" />
                  <h2>함께한 날의 사진</h2>
                </header>
                <p className="muted">이 날의 사진을 함께 모아보세요.</p>
                <Link className="text-button" href={`/memories?date=${selected}`}>
                  {month + 1}월 {day}일 사진 보기·남기기
                </Link>
              </section>
            )}
          </div>
        </div>
      </LoadingRegion>
      {preview && <p className="preview-label">화면 미리보기 · 저장되지 않는 예시 일정</p>}
    </>
  );
}
