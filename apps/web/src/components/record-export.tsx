"use client";

import { useState } from "react";
import { PageHeading } from "@/components/page-heading";
import Link from "@/components/progress-link";
import { downloadRecord } from "@/lib/file-download";

const kinds = {
  appointments: "약속",
  anniversaries: "기념일",
  meeting_days: "만난 날·메모",
  meeting_routes: "직선 동선",
  date_plans: "데이트 플랜",
  date_reports: "데이트 회고",
  photos: "사진 참고 정보",
  wishes: "위시",
  shared_checklists: "공동 준비 목록",
  shared_goals: "공동 목표",
  couple_questions: "질문",
  question_answers: "질문 답변",
  timezone_preferences: "시간대",
  roulette_wheels: "룰렛 후보",
  roulette_draws: "룰렛 결과",
  plan_visit_progress: "확정안별 방문 진행",
} as const;
const globalKinds = new Set([
  "anniversaries",
  "wishes",
  "shared_checklists",
  "shared_goals",
  "timezone_preferences",
  "roulette_wheels",
]);
export function RecordExport({ today }: { today: string }) {
  const [kind, setKind] = useState<keyof typeof kinds>("appointments"),
    [start, setStart] = useState(`${today.slice(0, 7)}-01`),
    [end, setEnd] = useState(today);
  const [personal, setPersonal] = useState(false),
    [confirmed, setConfirmed] = useState(false),
    [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  async function download() {
    if (!confirmed || pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await downloadRecord(
        "/api/records/export",
        { kind, start_date: start, end_date: end, include_private: personal },
        `we2day-${kind}-${start}-${end}.json`,
        "application/json",
      );
      setNotice("선택한 기록 사본의 다운로드를 요청했어요.");
    } catch (cause) {
      setError(
        cause instanceof Error && cause.name === "Error"
          ? cause.message
          : "파일을 만들지 못했어요. 조건을 유지했으니 다시 시도해 주세요.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="today-workspace">
      <Link className="text-button" href="/settings">
        ← 설정으로
      </Link>
      <PageHeading>
        <p className="eyebrow">KEEP A COPY</p>
        <h1>기록 사본 내보내기</h1>
        <p className="muted">
          지금 볼 수 있는 한 종류의 기록을 JSON 파일로 받아요. 계정 비밀번호·초대 코드·상대의 비공개
          원문은 포함하지 않아요.
        </p>
      </PageHeading>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void download();
        }}
      >
        <fieldset className="record-search-fields" disabled={pending}>
          <label>
            내보낼 기록 종류
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as keyof typeof kinds);
                setPersonal(false);
                setConfirmed(false);
                setNotice("");
              }}
            >
              {Object.entries(kinds).map(([key, value]) => (
                <option key={key} value={key}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            사본 시작일
            <input
              type="date"
              required
              min="2000-01-01"
              max="2100-12-31"
              value={start}
              onChange={(e) => {
                setStart(e.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <label>
            사본 종료일
            <input
              type="date"
              required
              min="2000-01-01"
              max="2100-12-31"
              value={end}
              onChange={(e) => {
                setEnd(e.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          {(kind === "date_reports" || kind === "question_answers") && (
            <label>
              <input
                type="checkbox"
                checked={personal}
                onChange={(e) => {
                  setPersonal(e.target.checked);
                  setConfirmed(false);
                }}
              />
              나의 비공개 초안도 포함
            </label>
          )}
          <p className="settings-hint">
            {globalKinds.has(kind)
              ? "이 종류는 날짜 범위와 관계없이 현재 보이는 전체 항목을 포함해요."
              : kind === "date_plans"
                ? "플랜은 현재 초안 날짜로 선택하고 확정 사본도 함께 포함해요."
                : kind === "date_reports" || kind === "plan_visit_progress"
                  ? "최초 회고/해당 확정안에 보존된 날짜를 기준으로 선택해요."
                  : kind === "question_answers"
                    ? "질문 날짜를 기준으로 답변을 선택해요."
                    : kind === "roulette_draws"
                      ? "한국 기준 뽑기 날짜로 선택해요."
                      : "기록에 지정된 날짜로 선택해요."}
          </p>
          <p className="settings-hint">
            한 번에 최대 500건·5MiB예요. 보관 항목은 포함하지만 휴지통 사진은 제외해요. 사진 파일은
            포함하지 않으니 날짜별 앨범에서 선택 ZIP을 따로 받아 주세요. 앱으로 가져오기·자동 복원은
            아직 제공하지 않아요.
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            파일에 메모·사진 참고 정보·선택한 기록의 좌표가 들어갈 수 있음을 확인했어요
          </label>
          <button
            className="primary-button"
            type="submit"
            disabled={!confirmed}
            aria-busy={pending}
          >
            {"기록 사본 다운로드"}
          </button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <p className="settings-hint">
        파일은 암호화되지 않은 개인 사본이에요. 공유 후에는 앱에서 공유를 철회해도 내려받은 파일을
        회수할 수 없어요. 이 기능은 DB·사진 전체 백업을 대신하지 않아요.
      </p>
    </section>
  );
}
